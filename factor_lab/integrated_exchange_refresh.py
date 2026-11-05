"""Freeze and replay exchange eligibility alongside the guarded daily price vintage."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .integrated_data import RESOURCE, integrated_universe
from .integrated_listing import listing_context, provider_symbols
from .investable_universe import LISTING_EXCLUSIONS, build_universe_screen

POLICY = RESOURCE.with_name("integrated_exchange_policy.json")
FILENAMES = ("nasdaqlisted.txt", "otherlisted.txt")


def reviewed_policy(data, target=None):
    raw = POLICY.read_bytes()
    policy = json.loads(raw)
    accepted = data.get("exchangeUniverse")
    if target is not None and not accepted and (
        target < policy["earliestSession"] or target <= data["asOf"]
    ):
        return None, None
    expected_hash = policy["review"]["universeSourceHash"]
    if expected_hash != sha256(RESOURCE.read_bytes()).hexdigest() or (
        data.get("universeSourceHash") != expected_hash
    ):
        raise ValueError("Exchange refresh requires a reviewed baseline for the requested universe")
    digest = sha256(raw).hexdigest()
    if accepted and accepted["policySha256"] != digest:
        raise ValueError("Exchange eligibility policy changed; a reviewed baseline is required")
    return policy, digest


def exchange_plan(data, target):
    """Locate any missed month-end evidence without inventing past eligibility."""
    import pandas as pd
    from exchange_calendars import get_calendar
    from .integrated_engine import completed_monthends

    policy, _ = reviewed_policy(data, target)
    prior = data.get("exchangeUniverse")
    if not policy or not (prior or data.get("historicalUniverse")) or target <= data["asOf"]:
        return policy is not None, None
    start, end = pd.Timestamp(data["asOf"]), pd.Timestamp(target)
    calendar = get_calendar("XNYS", start=start - pd.Timedelta(days=7), end=end + pd.Timedelta(days=45))
    days = calendar.sessions_in_range(start, end)
    monthends = completed_monthends(days)
    missed = monthends[(monthends > start) & (monthends < end)]
    if len(missed) > 1:
        raise ValueError("Exchange eligibility recovery spans multiple month-ends; review the baseline")
    return True, str(missed[0].date()) if len(missed) else None


def exchange_observation(baseline_data, target, directory):
    """Validate dated evidence before any full-market download or calculation."""
    import pandas as pd
    from exchange_calendars import get_calendar

    policy, digest = reviewed_policy(baseline_data, target)
    accepted = baseline_data.get("exchangeUniverse")
    if policy is None:
        return None

    universe = integrated_universe()["symbols"]
    keys = [row["symbol"] for row in universe]
    context = listing_context(keys, target)
    providers = provider_symbols(keys, context)
    newly_reviewed = {row["symbol"] for row in context["transitions"]
                      if accepted and row["effectiveDate"] > accepted["latest"]["session"]}
    rows = [dict(row, providerTicker=providers[row["symbol"]], status="excluded") for row in universe]
    inputs = {
        "resultIdentity": {"resultId": "listing-observation"},
        "data": {"asOf": target, "symbols": rows, "requestedSymbols": baseline_data["requestedSymbols"]},
    }
    if directory is None:
        raise ValueError(f"Exchange directory evidence is required for {target}")
    screen = build_universe_screen(inputs, *(Path(directory) / name for name in FILENAMES))
    if screen["listingAsOfEastern"] != target:
        raise ValueError(f"Exchange directories must match completed session {target}")
    day = pd.Timestamp(target)
    calendar = get_calendar("XNYS", start=day - pd.Timedelta(days=7), end=day + pd.Timedelta(days=7))
    close = calendar.session_close(day)
    for source in screen["sources"]:
        created = datetime.fromisoformat(source["createdAtEastern"]).replace(tzinfo=ZoneInfo("America/New_York"))
        if created < close:
            raise ValueError(f"Exchange directory was created before the {target} close")

    excluded = {}
    listed_stocks = 0
    for row in screen["rows"]:
        if row["symbol"] not in providers:
            continue
        prior_reason = accepted["latest"]["excluded"].get(row["symbol"]) if accepted else None
        if row["category"] in {"equity", "adr"}:
            listed_stocks += 1
            if prior_reason in {"listing_unconfirmed", "otc_legacy", "ticker_reused",
                                "listing_identity_review"} and row["symbol"] not in newly_reviewed:
                excluded[row["symbol"]] = "listing_identity_review"
        elif row["decision"] in LISTING_EXCLUSIONS:
            excluded[row["symbol"]] = row["decision"]
        else:
            excluded[row["symbol"]] = "separate_etf_pool"
    reference = max(policy["review"]["listedStocks"],
                    accepted["latest"]["listedStocks"] if accepted else 0)
    if listed_stocks < reference * policy["minimumReviewedCoverage"]:
        raise ValueError(f"Exchange directory coverage fell below the reviewed threshold ({listed_stocks}/{reference})")
    observation = {
        "session": target, "sources": screen["sources"], "listedStocks": listed_stocks,
        "excluded": excluded, "listedEtfCandidates": screen["listedEtfCandidates"],
        "listedStockAdditions": [row["symbol"] for row in screen["rows"]
                                 if row["decision"] == "provider_data_required"
                                 and row["category"] in {"equity", "adr"}],
    }
    if accepted and target == baseline_data["asOf"] and observation != accepted["latest"]:
        raise ValueError("Same-session exchange refresh requires the original accepted directory bytes")
    return {"policyVersion": policy["version"], "policySha256": digest, "latest": observation}


def apply_exchange_observation(market, baseline_data, observation, recovery=None):
    """Replay accepted month-end masks; add new evidence only for the target date."""
    historical = baseline_data.get("historicalUniverse")
    if historical:
        from .integrated_universe_migration import apply_historical_universe
        market = apply_historical_universe(market, historical)
    if observation is None:
        return market
    from dataclasses import replace
    import pandas as pd
    from .integrated_engine import completed_monthends

    latest = observation["latest"]
    target = pd.Timestamp(latest["session"])
    if market.prices.index[-1] != target:
        raise ValueError("Exchange evidence does not match the final market session")
    prior = baseline_data.get("exchangeUniverse")
    signals = dict(prior["signalObservations"]) if prior else {}
    monthends = completed_monthends(market.prices.index)
    if prior or historical:
        missed = monthends[(monthends > pd.Timestamp(baseline_data["asOf"])) & (monthends < target)]
        needed = [str(day.date()) for day in missed]
        if needed != ([recovery["latest"]["session"]] if recovery else []):
            raise ValueError(f"Exchange evidence is missing for month-end {', '.join(needed)}")
        if recovery:
            signals[needed[0]] = recovery["latest"]
    if target in monthends:
        signals[latest["session"]] = latest

    eligibility = market.eligibility.copy()
    for day, evidence in {**signals, latest["session"]: latest}.items():
        stamp = pd.Timestamp(day)
        if stamp not in eligibility.index:
            raise ValueError(f"Exchange evidence date missing from market calendar: {day}")
        eligibility.loc[stamp, list(evidence["excluded"])] = False
    metadata = dict(market.metadata, exchangeUniverse={**observation, "signalObservations": signals})
    return replace(market, eligibility=eligibility, metadata=metadata)
