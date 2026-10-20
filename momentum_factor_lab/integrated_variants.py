"""Executable legacy formula experiments on the integrated accounting engine.

Legacy score formulas are versioned separately from the 32-definition registry.
They cannot join the monthly selector merely by being run as an experiment.
"""

from __future__ import annotations
from pathlib import Path
from dataclasses import asdict
import hashlib
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from . import integrated_legacy_best as legacy
from .backtest import run_factor_backtest
from .config import RunConfig, FIXED_WEIGHTING_POLICY
from .integrated_engine import (
    IntegratedConfig,
    completed_monthends,
    _allocation,
    _holding_rows,
    metrics,
    performance,
    clean,
    annotate_metric_states,
    symbol_diagnostics,
    next_execution,
)
from .integrated_research import monthly_signal_diagnostics
from .integrated_repairs import backtest_inputs

MAP = Path(__file__).parent / "resources" / "integrated_legacy_map.json"


def experiment_catalog():
    return json.loads(MAP.read_text())["rows"]


def resolve_experiment(experiment_definition):
    if not isinstance(experiment_definition, dict) or set(experiment_definition) != {
        "project",
        "id",
    }:
        raise ValueError("experimentDefinition requires project and id")
    row = next(
        (
            r
            for r in experiment_catalog()
            if r["project"] == experiment_definition["project"]
            and r["legacyId"] == experiment_definition["id"]
        ),
        None,
    )
    if row is None:
        raise ValueError("Unknown legacy definition")
    if row["status"] in ("deferred_fundamental", "invalid_definition"):
        raise ValueError(f"Legacy definition is not executable: {row['status']}")
    if row["project"] == "best":
        dependencies = legacy.expand_factor_dependencies([row["legacyId"]])
        if any(legacy.FACTOR_REGISTRY[name].requires_fundamentals for name in dependencies):
            raise ValueError("Fundamental dependencies are deferred")
    return row


def _project_market_columns(market):
    requested = market.metadata.get("requestedSymbols")
    return [c for c in market.prices if requested is None or c in requested]


def variant_scores(market, experiment_definition, dates=None):
    row = resolve_experiment(experiment_definition)
    symbols = _project_market_columns(market)
    p = market.prices[symbols]
    eligibility = market.eligibility[symbols]
    name = row["legacyId"]
    if row["project"] == "momentum":
        from .factors import FACTOR_SPECS, ELIGIBILITY_AWARE_FACTOR_FNS

        spec = FACTOR_SPECS.get(name)
        if spec is None:
            from .advanced_factors import compute_advanced_factor_scores, VOLUME_FACTOR_NAMES

            if name not in VOLUME_FACTOR_NAMES:
                raise ValueError("Legacy Momentum definition implementation unavailable")
            return compute_advanced_factor_scores(
                p,
                volumes=market.volumes[symbols],
                dollar_volumes=market.raw_close[symbols] * market.volumes[symbols],
                eligibility_mask=eligibility,
            ).scores[name]
        aware = ELIGIBILITY_AWARE_FACTOR_FNS.get(name)
        values = aware(p, eligibility) if aware else spec.fn(p)
        return values.replace([np.inf, -np.inf], np.nan).where(eligibility)
    dates = completed_monthends(p.index) if dates is None else dates
    selected = legacy.expand_factor_dependencies([name])
    definitions = [legacy.FACTOR_REGISTRY[id] for id in selected]
    # Preserve formula offsets but expose one coherent OHLC price basis.
    # Paired raw/as-traded close×volume supplies dollar-volume formulas.
    scale = market.prices / market.split_close
    inputs = {
        "adj_close": p.to_numpy(),
        "close": p.to_numpy(),
        "open": (market.split_open * scale)[symbols].to_numpy(),
        "high": (market.split_high * scale)[symbols].to_numpy(),
        "low": (market.split_low * scale)[symbols].to_numpy(),
        "raw_close": market.raw_close[symbols].to_numpy(),
        "volume": market.volumes[symbols].to_numpy(),
    }
    lookback = (
        max([int(v) for d in definitions for _, v in d.params if isinstance(v, (int, float))] + [1])
        + 2
    )
    output = pd.DataFrame(np.nan, index=p.index, columns=symbols)
    for date in dates:
        position = p.index.get_loc(date)
        begin = max(0, position - lookback)
        raw = {d.name: pd.Series(np.nan, index=symbols) for d in definitions}
        for j, symbol in enumerate(symbols):
            if not eligibility.at[date, symbol]:
                continue
            price_values = inputs["adj_close"][begin : position + 1, j]
            # Missing sessions are kept in their original positions, never
            # collapsed into shorter trading-day lookbacks.
            rows = tuple(
                {key: float(values[k, j]) for key, values in inputs.items() if key != "raw_close"}
                | {"date": p.index[k]}
                for k in range(begin, position + 1)
            )
            closes = tuple(
                (p.index[k], float(inputs["adj_close"][k, j])) for k in range(begin, position + 1)
            )
            volumes = tuple(
                (p.index[k], float(inputs["volume"][k, j]), float(inputs["raw_close"][k, j]))
                for k in range(begin, position + 1)
            )
            history = legacy._History(rows=rows, closes=closes, volumes=volumes)
            for definition in definitions:
                if definition.kind == "composite":
                    continue
                required = _required_history(definition)
                if len(price_values) < required or not np.isfinite(price_values[-required:]).all():
                    continue
                shape_fields = _required_shape_fields(definition)
                if any(
                    not np.isfinite(inputs[field][position - required + 1 : position + 1, j]).all()
                    for field in shape_fields
                ):
                    continue
                value, reason = legacy._score_factor(definition, history, None)
                if not reason and np.isfinite(value):
                    raw[definition.name].at[symbol] = value
        for definition in definitions:
            if definition.kind != "composite":
                continue
            components = []
            for dependency in definition.dependencies:
                values = raw[dependency].where(eligibility.loc[date])
                span = values.max() - values.min()
                components.append(
                    (values - values.min()) / span if span > 0 else values.where(values.isna(), 0.5)
                )
            frame = pd.concat(components, axis=1)
            raw[definition.name] = frame.mean(axis=1).where(frame.notna().all(axis=1))
        output.loc[date] = raw[name]
    return output


def _definition(row):
    original = row["original"]
    project = row["project"]
    name = row["legacyId"]
    if project == "best":
        formula = (
            original["kind"] + ": " + ", ".join(f"{k}={v}" for k, v in original.get("params", []))
        )
        source_hash = legacy.LEGACY_SOURCE_SHA256
    else:
        formula = original["formula"]
        source_file = (
            "advanced_factors.py"
            if name in ("volume_confirmed_mom_6m", "signed_volume_pressure_3m")
            else "factors.py"
        )
        source_hash = hashlib.sha256((Path(__file__).parent / source_file).read_bytes()).hexdigest()
    return dict(
        id=f"legacy:{project}:{name}",
        name=name,
        label=name,
        family=original.get("category", "experiment"),
        direction="higher",
        selectionEligible=False,
        formula=formula,
        parameters=dict(original.get("params", [])),
        version="legacy-formula-integrated-inputs-v1",
        sourceProject=project,
        sourceId=name,
        legacySourceHash=source_hash,
        inputContractVersion="total-return-OHLC-paired-as-traded-DV-v1",
        missingPolicy="complete required sessions; missing rows retain original trading-day positions",
        priceBasis="total-return OHLC; raw paired close×volume for dollar volume",
        hypothesis=original.get("description", ""),
        falsification="Forward net performance does not retain the proposed direction.",
        original=original,
    )


def run_legacy_experiment(market, config, experiment_definition):
    row = resolve_experiment(experiment_definition)
    if config is None:
        config = IntegratedConfig()
    if isinstance(config, dict):
        config = IntegratedConfig(**config)
    if config.common_universe:
        from dataclasses import replace
        from .integrated_factors import iter_integrated_factors

        wanted = set(config.comparison_factors)
        if not wanted:
            raise ValueError("Common-universe experiment requires comparison factors")
        mask = market.eligibility.copy()
        for factor_id, panel in iter_integrated_factors(market):
            if factor_id in wanted:
                mask &= panel.notna()
                wanted.remove(factor_id)
            if not wanted:
                break
        if wanted:
            raise ValueError("Unknown common-universe factor definitions")
        market = replace(market, eligibility=mask)
    definition = _definition(row)
    key = definition["id"]
    full_index = market.prices.index
    index = full_index[
        (full_index >= pd.Timestamp(config.start_date))
        & (full_index <= pd.Timestamp(config.end_date) if config.end_date else True)
    ]
    if len(index) < 2:
        raise ValueError("Insufficient experiment dates")
    dates = completed_monthends(index)
    scores = variant_scores(market, experiment_definition, dates)
    prices = market.prices.loc[index, scores.columns]
    rc = RunConfig(
        start_date=config.start_date,
        end_date=config.end_date,
        top_n=config.top_n,
        max_weight=config.max_weight,
        transaction_cost_bps=config.transaction_cost_bps,
        slippage_bps=config.slippage_bps,
    )
    adv = (market.raw_close * market.volumes).rolling(63, min_periods=42).mean()
    allocations = {d: _allocation(d, scores, market, adv, config, rc) for d in dates}
    result = run_factor_backtest(
        key,
        FIXED_WEIGHTING_POLICY,
        prices,
        scores.loc[index],
        rc,
        signal_targets=allocations,
        execution_delay_sessions=config.execution_delay_sessions,
        **backtest_inputs(market, index, prices.columns),
    )
    ic, quintiles = monthly_signal_diagnostics(
        scores, market.prices[scores.columns], dates, "higher", config.execution_delay_sessions,
        valuation_prices=market.valuation_prices,
        corporate_actions=market.metadata.get("corporateActions", ()),
    )
    nav, drawdown = performance(result.returns)
    measured = metrics(result.returns, result.return_interval_sessions)
    first = result.returns.first_valid_index()
    active = result.returns.loc[first:] if first is not None else result.returns.iloc[:0]
    status = (
        "insufficient_data"
        if active.empty
        else "available"
        if active.notna().all()
        else "partial_data"
    )
    history = []
    for date, allocation in allocations.items():
        pos = index.get_loc(date) + config.execution_delay_sessions
        execution = (
            index[pos]
            if pos < len(index)
            else next_execution(date, config.execution_delay_sessions)
        )
        actual = result.weights.iloc[pos + 1] if pos + 1 < len(index) else result.ending_weights
        history.append(
            dict(
                date=str(date.date()),
                signalDate=str(date.date()),
                executionDate=str(execution.date()),
                factorId=key,
                label=definition["name"],
                status="fixed",
                score=None,
                candidates=[],
                targetHoldings=_holding_rows(allocation.weights()),
                holdings=_holding_rows(actual),
                holdingsAsOf=str(min(execution, index[-1]).date()),
                executionStatus=result.execution_statuses.get(execution, "pending"),
                cost=result.costs.get(execution),
                turnover=result.turnover.get(execution),
                cashWeight=float(result.cash_weights.iloc[pos + 1]) if pos + 1 < len(index) else result.ending_cash_weight,
                receivableWeight=float(result.receivable_weights.iloc[pos + 1]) if pos + 1 < len(index) else result.ending_receivable_weight,
            )
        )
    factor = dict(
        id=key,
        label=definition["name"],
        family=definition["family"],
        direction="higher",
        status=status,
        metrics=measured,
        nav=nav,
        drawdown=drawdown,
        holdings=_holding_rows(result.ending_weights),
        cashWeight=result.ending_cash_weight,
        receivableWeight=result.ending_receivable_weight,
        liquidCashWeight=result.ending_cash_weight - result.ending_receivable_weight,
        ic=ic,
        quintiles=quintiles,
        definition=definition,
        valuationCoverage=float(active.notna().mean()) if len(active) else None,
        lastValuedDate=str(result.equity.last_valid_index().date())
        if result.equity.last_valid_index() is not None
        else None,
    )
    selection = dict(
        current=history[-1] if history else None,
        history=history,
        nav=nav,
        drawdown=drawdown,
        holdings=factor["holdings"],
        cashWeight=result.ending_cash_weight,
        receivableWeight=result.ending_receivable_weight,
        liquidCashWeight=result.ending_cash_weight - result.ending_receivable_weight,
        metrics=measured,
        pending=history[-1]
        if history and pd.Timestamp(history[-1]["executionDate"]) > index[-1]
        else None,
        holdingsAsOf=str(index[-1].date()),
    )
    comparisons = []
    for symbol in ("SPY", "QQQ", "^IXIC"):
        if symbol not in market.prices:
            continue
        returns = market.prices.loc[index, symbol].pct_change(fill_method=None)
        returns = returns.loc[first:] if first is not None else returns.iloc[:0]
        n, d = performance(returns)
        comparisons.append(
            dict(id=symbol, label=symbol, nav=n, drawdown=d,
                 metrics=metrics(returns, returns.notna().astype(int)))
        )
    source_hash = hashlib.sha256(
        Path(__file__).read_bytes()
        + (Path(__file__).parent / "integrated_legacy_best.py").read_bytes()
    ).hexdigest()
    identity = dict(
        strategyType="fixed_factor_experiment",
        experimentDefinition=experiment_definition,
        inputHash=market.metadata.get("snapshotId"),
        definitionVersion=definition["version"],
        legacySourceHash=definition["legacySourceHash"],
        variantCodeHash=source_hash,
    )
    identity["resultId"] = hashlib.sha256(
        json.dumps({"identity": identity, "settings": asdict(config)}, sort_keys=True).encode()
    ).hexdigest()[:24]
    output = dict(
        schemaVersion="integrated-factor/v1",
        registry=[definition],
        factors=[factor],
        selection=selection,
        comparisons=comparisons,
        research=dict(
            correlations=[],
            overlap=[],
            bootstrap=[],
            stress=[],
            dsr=dict(status="unavailable", reason="historical_search_count_unknown"),
            searchHistory=[dict(project=row["project"], id=row["legacyId"], status=status)],
        ),
        data={
            **market.metadata,
            "asOf": str(index[-1].date()),
            "requestedCount": len(_project_market_columns(market)),
            "pricedCount": int(market.prices.loc[index].notna().any().sum()),
            "eligibleCount": int(market.eligibility.loc[index].iloc[-1].sum()),
            "symbols": symbol_diagnostics(
                market, market.prices.loc[index], market.eligibility.loc[index]
            ),
        },
        settings=asdict(config),
        experimentDefinition=experiment_definition,
        resultIdentity=identity,
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )
    annotate_metric_states(output)
    return clean(output)


def _required_history(definition):
    params = dict(definition.params)
    periods = max([int(v) for v in params.values() if isinstance(v, (int, float))] + [1])
    close_level = {
        "liquidity",
        "volume_trend",
        "volume_shock",
        "moving_average_gap",
        "moving_average_cross",
        "range_position",
        "drawdown_high",
        "range_contraction",
        "intraday_return",
    }
    if definition.kind in close_level or (
        definition.kind == "volatility" and params.get("measure") == "range"
    ):
        return periods
    return periods + 1


def _required_shape_fields(definition):
    if definition.kind == "overnight_return":
        return ("open",)
    if definition.kind == "intraday_return":
        return ("open",)
    if definition.kind in ("range_position", "breakout_strength", "range_contraction") or (
        definition.kind == "volatility" and dict(definition.params).get("measure") == "range"
    ):
        return ("high", "low")
    return ()
