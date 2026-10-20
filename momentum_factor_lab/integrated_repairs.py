"""Evidence-backed amendments to immutable market snapshots.

Trades, non-trading valuation marks, security identity and mandatory exchanges
are different contracts. No generic forward filling or return clipping occurs.
The parent snapshot and every amendment's source remain inspectable.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import numpy as np
import pandas as pd

from .integrated_data import compute_eligibility, apply_market_quality


def amend_market(market, amendments):
    """Create a derived input without mutating any parent matrix.

    Quote amendments are whole-source bars in the same price/currency basis.
    Close-only sources never supply fabricated open/high/low fields. Known
    zero-volume marks value holdings but remain absent from executable prices.
    """
    expected = amendments.get("inputSnapshotId")
    if expected and expected != market.metadata.get("snapshotId"):
        raise ValueError("Amendments belong to a different immutable input snapshot")
    names = ("prices", "raw_close", "raw_open", "raw_high", "raw_low", "volumes",
             "dividends", "splits", "eligibility", "provider_close", "provider_open",
             "provider_high", "provider_low", "provider_volumes", "shape_valid")
    result = replace(market, **{n: getattr(market, n).copy() if getattr(market, n) is not None
                                else None for n in names},
                     metadata=dict(market.metadata), valuation_prices=None)
    ledger = []
    calendar = result.prices.index
    for row in amendments.get("splitCorrections", []):
        symbol, date, ratio = row["symbol"], pd.Timestamp(row["date"]), row["ratio"]
        if (date not in calendar or not row.get("sourceUrl") or ratio <= 0
                or not np.isfinite(ratio) or result.provider_close is None):
            raise ValueError("Missing split correction requires source, event and provider basis")
        if pd.notna(result.splits.at[date, symbol]) and result.splits.at[date, symbol] != 0:
            raise ValueError("Refusing to apply an already recorded split a second time")
        before = calendar < date
        result.prices.loc[before, symbol] /= ratio
        for name in ("close", "open", "high", "low"):
            getattr(result, "provider_" + name).loc[before, symbol] /= ratio
        result.provider_volumes.loc[before, symbol] *= ratio
        result.dividends.loc[before, symbol] /= ratio
        result.splits.at[date, symbol] = ratio
        ledger.append({"kind": "verified_missing_split_normalization", **row,
                       "rawBasis": "As-traded OHLC and volume preserved; provider OHLC/TR and paired volume normalized only before effective session"})
    for row in amendments.get("quotes", []):
        symbol, date = row["symbol"], pd.Timestamp(row["date"])
        if date not in calendar or symbol not in result.prices:
            raise ValueError("Amendment is outside snapshot axes")
        if not row.get("sourceUrl") or not row.get("retrievedAt"):
            raise ValueError("Quote amendment requires source and retrieval time")
        if pd.notna(result.prices.at[date, symbol]):
            # Source comparisons can include existing observations. Never
            # overwrite a valid primary-provider bar with rounded feed values.
            if not np.isclose(result.prices.at[date, symbol], row["adjustedClose"], atol=.011):
                raise ValueError(f"Conflicting observed close: {symbol} {date.date()}")
            continue
        if min(row["close"], row["adjustedClose"], row["volume"]) <= 0:
            raise ValueError("Trade amendment requires positive prices and volume")
        result.prices.at[date, symbol] = row["adjustedClose"]
        result.raw_close.at[date, symbol] = row["close"]
        result.volumes.at[date, symbol] = row["volume"]
        result.splits.at[date, symbol] = row.get("split", 0.)
        result.dividends.at[date, symbol] = row.get("dividend", 0.)
        if result.provider_close is not None:
            result.provider_close.at[date, symbol] = row["close"]
            result.provider_volumes.at[date, symbol] = row["volume"]
        for name in ("open", "high", "low"):
            getattr(result, "raw_" + name).at[date, symbol] = row.get(name, np.nan)
            provider = getattr(result, "provider_" + name)
            if provider is not None:
                provider.at[date, symbol] = row.get(name, np.nan)
        ledger.append({"kind": "observed_quote", **row})

    for row in amendments.get("identityStarts", []):
        symbol, date = row["symbol"], pd.Timestamp(row["date"])
        before = calendar < date
        # The provider's old security/listing bars remain in the immutable
        # parent, but cannot form this security's history or eligibility.
        for name in names:
            frame = getattr(result, name)
            if frame is not None:
                frame.loc[before, symbol] = False if name in ("eligibility", "shape_valid") else np.nan
        ledger.append({"kind": "security_identity_start", **row})

    for row in amendments.get("quarantines", []):
        symbol = row["symbol"]
        start = pd.Timestamp(row.get("start", str(calendar[0].date())))
        end = pd.Timestamp(row.get("end", str(calendar[-1].date())))
        mask = (calendar >= start) & (calendar <= end)
        for name in names:
            frame = getattr(result, name)
            if frame is not None:
                frame.loc[mask, symbol] = False if name in ("eligibility", "shape_valid") else np.nan
        ledger.append({"kind": "unverified_input_quarantine", **row})

    result.valuation_prices = result.prices.copy()
    if market.valuation_prices is not None:
        result.valuation_prices = result.valuation_prices.combine_first(market.valuation_prices)
        for row in amendments.get("identityStarts", []):
            result.valuation_prices.loc[calendar < pd.Timestamp(row["date"]), row["symbol"]] = np.nan
        for row in amendments.get("quarantines", []):
            start = pd.Timestamp(row.get("start", str(calendar[0].date())))
            end = pd.Timestamp(row.get("end", str(calendar[-1].date())))
            result.valuation_prices.loc[(calendar >= start) & (calendar <= end), row["symbol"]] = np.nan
    for row in amendments.get("valuationMarks", []):
        symbol, date = row["symbol"], pd.Timestamp(row["date"])
        if date not in calendar or symbol not in result.prices:
            raise ValueError("Valuation mark is outside snapshot axes")
        if row["volume"] != 0 or row["adjustedClose"] <= 0 or not row.get("sourceUrl"):
            raise ValueError("Non-trading valuation mark requires sourced zero-volume bar")
        if pd.notna(result.prices.at[date, symbol]):
            raise ValueError("Valuation-only mark cannot override an executable quote")
        result.valuation_prices.at[date, symbol] = row["adjustedClose"]
        ledger.append({"kind": "non_trading_valuation_mark", **row})

    actions = []
    for row in amendments.get("exchanges", []):
        date, symbol, target = pd.Timestamp(row["date"]), row["symbol"], row.get("targetSymbol")
        if date not in calendar or not row.get("sourceUrl"):
            raise ValueError("Exchange requires an observed session and source")
        earlier = result.prices.loc[result.prices.index < date, symbol].dropna()
        if earlier.empty:
            raise ValueError("Exchange has no predecessor unit anchor")
        anchor = earlier.index[-1]
        if target is None:
            cash = row.get("cashPerShare", 0.)
            source_tr, source_raw = result.prices.at[anchor, symbol], result.raw_close.at[anchor, symbol]
            if cash <= 0 or not np.isfinite([cash, source_tr, source_raw]).all() or source_raw <= 0:
                raise ValueError("Cash merger requires sourced positive entitlement and unit anchor")
            action = {**row, "targetSymbol": None, "unitRatio": 0.,
                      "cashPerUnit": source_tr / source_raw * cash,
                      "settlementDate": row.get("settlementDate"),
                      "sourceUnitAnchorDate": str(anchor.date()),
                      "unitBasis": "source TR/raw anchor × legal cash entitlement; not an executable quote"}
            actions.append(action)
            result.eligibility.loc[calendar >= date, symbol] = False
            ledger.append({"kind": "mandatory_cash_entitlement", **action})
            continue
        values = [result.prices.at[anchor, symbol], result.raw_close.at[anchor, symbol],
                  result.raw_close.at[date, target], result.prices.at[date, target]]
        if not np.isfinite(values).all() or min(values) <= 0 or row["shareRatio"] <= 0:
            raise ValueError("Exchange unit conversion requires finite same-day target prices")
        unit_ratio = values[0] / values[1] * row["shareRatio"] * values[2] / values[3]
        action = {**row, "unitRatio": unit_ratio, "cashPerUnit": 0.,
                  "sourceUnitAnchorDate": str(anchor.date()),
                  "unitBasis": "source TR/raw anchor × legal share ratio × target raw/TR at exchange"}
        actions.append(action)
        result.eligibility.loc[calendar >= date, symbol] = False
        ledger.append({"kind": "mandatory_share_exchange", **action})

    result.eligibility = compute_eligibility(result.prices, result.raw_close, result.volumes,
                                           result.metadata.get("requestedSymbols"))
    for action in actions:
        result.eligibility.loc[calendar >= pd.Timestamp(action["date"]), action["symbol"]] = False
    result = apply_market_quality(result)
    # Missing fields in a close-only amendment are unavailable shape inputs,
    # rather than synthetic flat candles.
    if result.shape_valid is not None:
        result.shape_valid &= (result.split_open.notna() & result.split_high.notna()
                               & result.split_low.notna())
    result.metadata.update(
        amendmentVersion="evidence-amendments-v1",
        amendments=ledger,
        corporateActions=actions,
        amendmentHash=hashlib.sha256(json.dumps(amendments, sort_keys=True).encode()).hexdigest(),
        valuationBasis="Observed total-return close; separately sourced zero-volume marks for disclosed non-trading sessions. No generic forward fill.",
        fractionalSharePolicy="Continuous research units retain fractional successor shares at market value; no rounding gain or fabricated cash-in-lieu.",
        cashEntitlementPolicy="Legally fixed cash consideration is a non-interest-bearing receivable. Unknown payment date remains unsettled and cannot fund a rebalance.",
    )
    return result


def backtest_inputs(market, index, columns=None):
    columns = market.prices.columns if columns is None else columns
    marks = getattr(market, "valuation_prices", None)
    actions = [row for row in market.metadata.get("corporateActions", [])
               if pd.Timestamp(row["date"]) in index]
    for row in actions:
        if row["symbol"] in columns and row.get("targetSymbol") is not None and row["targetSymbol"] not in columns:
            raise ValueError("Backtest projection omits a mandatory successor asset")
    return dict(
        valuation_prices=marks.reindex(index=index, columns=columns) if marks is not None else None,
        corporate_actions=[row for row in actions if row["symbol"] in columns],
        retain_contribution_history=marks is not None or bool(actions),
    )
