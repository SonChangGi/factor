"""Integrated fixed-factor research and genuinely traded monthly selection."""

from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
import numpy as np
import pandas as pd
from .backtest import run_factor_backtest, _rebalance_dates
from .config import RunConfig, FIXED_WEIGHTING_POLICY
from .portfolio import TargetAllocation, construct_target_allocation
from .metrics import (
    cagr,
    sortino_ratio,
    sharpe_ratio,
    calmar_ratio,
    max_drawdown,
    subperiod_stability,
    _winsorized_percentile,
)
from .integrated_research import (
    monthly_signal_diagnostics,
    synchronized_bootstrap,
    regime_analysis,
    conditional_exposures,
)
from .integrated_repairs import backtest_inputs
from .integrated_history import fixed_factor_history


@dataclass
class IntegratedConfig:
    start_date: str = "2016-01-01"
    end_date: str | None = None
    evaluation_window_days: int = 756
    top_n: int = 20
    max_weight: float = 0.10
    transaction_cost_bps: float = 5.0
    slippage_bps: float = 5.0
    bootstrap_repetitions: int = 2000
    execution_delay_sessions: int = 1
    weighting: str = "score_liquidity_rank"
    comparison_factors: tuple = ()
    common_universe: bool = False
    run_stress: bool = False

    def __post_init__(self):
        if self.weighting not in ("score_liquidity_rank", "equal"):
            raise ValueError("unsupported weighting")
        if not isinstance(self.evaluation_window_days, int) or self.evaluation_window_days < 3:
            raise ValueError("evaluation window must have at least three sessions")
        if not isinstance(self.bootstrap_repetitions, int) or self.bootstrap_repetitions < 0:
            raise ValueError("invalid bootstrap repetitions")
        if not isinstance(self.top_n, int) or not 1 <= self.top_n <= 50:
            raise ValueError("top_n must be 1..50")
        if not 0 < self.max_weight <= 1 or min(self.transaction_cost_bps, self.slippage_bps) < 0:
            raise ValueError("invalid weights or costs")
        if not isinstance(self.execution_delay_sessions, int) or self.execution_delay_sessions < 1:
            raise ValueError("invalid execution delay")


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _return_intervals(returns, interval_sessions=None):
    """Retain the calendar and distinguish daily returns from gap recovery.

    Explicit accounting intervals are authoritative, including when the first
    row of a sliced evaluation window recovers an earlier quote gap. Without
    them, infer catch-up intervals conservatively after the first observation.
    Direct one-session price differences should pass their own interval mask.
    """
    if interval_sessions is not None:
        intervals = pd.to_numeric(interval_sessions.reindex(returns.index), errors="coerce")
        observed = returns.notna()
        invalid = intervals.isna() | intervals.lt(1) | intervals.mod(1).ne(0)
        if (observed & invalid).any():
            raise ValueError("Observed returns require positive integer accounting intervals")
        return intervals.where(observed, 0).fillna(0).astype(int)
    intervals = pd.Series(0, index=returns.index, dtype=int)
    started, gap = False, 0
    for position, value in enumerate(returns):
        if pd.isna(value):
            gap += int(started)
        else:
            intervals.iloc[position] = gap + 1
            started, gap = True, 0
    return intervals


def metrics(returns, interval_sessions=None):
    intervals = _return_intervals(returns, interval_sessions)
    first = returns.first_valid_index()
    active = returns.loc[first:] if first is not None else returns.iloc[:0]
    active_intervals = intervals.reindex(active.index)
    daily = active.where(active_intervals.eq(1)).dropna()
    observations = int(active.notna().sum())
    multi = int((active.notna() & active_intervals.gt(1)).sum())
    ending = bool(len(active) and pd.notna(active.iloc[-1]))
    complete = ending and len(daily) >= 2
    result = dict(
        cagr=cagr(active) if observations else float("nan"),
        sortino=sortino_ratio(daily) if len(daily) >= 2 else float("nan"),
        calmar=calmar_ratio(active) if observations else float("nan"),
        mdd=max_drawdown(active) if observations else float("nan"),
        sharpe=sharpe_ratio(daily) if len(daily) >= 2 else float("nan"),
        stability=subperiod_stability(active)[0],
    )
    result.update(
        calendarObservations=len(active),
        observedReturnCount=observations,
        dailyRiskObservations=len(daily),
        multiSessionReturnObservations=multi,
        valuationCoverageRatio=observations / len(active) if len(active) else float("nan"),
        dailyRiskCoverageRatio=len(daily) / len(active) if len(active) else float("nan"),
        endingNavAvailable=ending,
        riskMetricsComplete=complete,
        riskMetricsExact=complete and observations == len(active) and multi == 0,
    )
    return result


def series_rows(series):
    return [dict(date=str(d.date()), value=v) for d, v in series.items()]


def performance(returns):
    first = returns.first_valid_index()
    active = returns.loc[first:] if first is not None else returns.iloc[:0]
    nav = (1 + active).cumprod()
    peak = nav.cummax().clip(lower=1)
    return series_rows(nav), series_rows(nav / peak - 1)


def completed_monthends(index):
    from exchange_calendars import get_calendar

    if len(index) == 0:
        return pd.DatetimeIndex([])
    calendar = get_calendar(
        "XNYS", start=str(index[0].date()), end=str((index[-1] + pd.Timedelta(days=35)).date())
    )
    dates = _rebalance_dates(index, "ME")
    return pd.DatetimeIndex(
        [d for d in dates if calendar.is_session(d) and calendar.next_session(d).month != d.month]
    )


def next_execution(date, delay):
    from exchange_calendars import get_calendar

    calendar = get_calendar(
        "XNYS", start=str(date.date()), end=str((date + pd.Timedelta(days=60)).date())
    )
    return calendar.session_offset(date, delay)


def _allocation(date, scores, market, adv, config, run_config):
    allocation = construct_target_allocation(
        FIXED_WEIGHTING_POLICY,
        date,
        scores.loc[date],
        market.prices.loc[date],
        market.eligibility.loc[date],
        run_config,
        trailing_dollar_volume=adv.loc[date],
    )
    if config.weighting == "equal" and len(allocation.rows):
        allocation.rows = allocation.rows.copy()
        allocation.rows["weight"] = min(config.max_weight, 1 / len(allocation.rows))
        allocation.cash_weight = 1 - allocation.rows.weight.sum()
    return allocation


def _holding_rows(weights):
    return [dict(symbol=str(s), weight=float(w)) for s, w in weights.items() if w > 1e-12]


def _candidate_data_issue(result, returns, observed_prices=None):
    missing = returns.index[~np.isfinite(returns)]
    symbols = []
    if observed_prices is not None and len(missing):
        quoted = observed_prices.reindex(missing)
        held = result.weights.reindex(index=missing, columns=quoted.columns).gt(1e-15)
        affected = (held & quoted.isna()).any()
        symbols = sorted(str(symbol) for symbol in affected.index[affected])
    return dict(
        evaluationStart=str(returns.index[0].date()) if len(returns) else None,
        evaluationEnd=str(returns.index[-1].date()) if len(returns) else None,
        missingNavSessions=len(missing),
        firstMissingDate=str(missing[0].date()) if len(missing) else None,
        lastMissingDate=str(missing[-1].date()) if len(missing) else None,
        symbols=symbols,
    )


def _monthly_candidate(result, date, allocation, price_changes, window, observed_prices=None):
    returns = result.returns.loc[:date].tail(window)
    first = result.returns.first_valid_index()
    if (
        len(returns) == window
        and first is not None
        and first <= returns.index[0]
        and not np.isfinite(returns).all()
    ):
        return dict(
            status="data_error", reason="incomplete_nav", metrics={},
            dataIssue=_candidate_data_issue(result, returns, observed_prices),
        )
    if allocation.status != "available":
        target_reasons = list(allocation.reasons)
        # No eligible signal can be a normal history/coverage shortage.
        # Calculation/invariant failures and lost policy inputs must not be
        # mistaken for risk rejection and trigger a new cash allocation.
        normal_shortage = (
            allocation.status == "unavailable"
            and target_reasons == ["no_complete_signal_inputs"]
        )
        return dict(
            status="insufficient_data" if normal_shortage else "data_error",
            reason="incomplete_nav_or_target" if normal_shortage else "target_allocation_failed",
            metrics={},
            allocationIssue=dict(
                status=allocation.status,
                reasons=target_reasons,
                componentStatus=dict(allocation.component_status),
            ),
        )
    if (
        len(returns) != window
        or not np.isfinite(returns).all()
        or allocation.rows.empty
    ):
        return dict(status="insufficient_data", reason="incomplete_nav_or_target", metrics={})
    intervals = _return_intervals(returns, result.return_interval_sessions)
    if not intervals.eq(1).all():
        issue = _candidate_data_issue(result, returns, observed_prices)
        issue["multiSessionReturnDates"] = [
            str(d.date()) for d in intervals.index[intervals.gt(1)]
        ]
        return dict(
            status="data_error", reason="multi_session_return_in_window", metrics={},
            dataIssue=issue,
        )
    m = metrics(returns, intervals)
    reasons = []
    costs = result.costs.reindex(returns.index)
    m["annualizedCostDrag"] = costs.sum() * 252 / window
    weights = allocation.weights()
    norm = weights / weights.sum()
    hhi = float((norm**2).sum())
    m.update(effectiveNames=1 / hhi, hhi=hhi, maxWeight=weights.max())
    # Every contribution and leave-one calculation ends at this signal date.
    held = result.weights.reindex(returns.index)
    active_columns = held.columns[held.ne(0).any()]
    held = held[active_columns]
    changes = price_changes.reindex(returns.index)[active_columns]
    recorded = getattr(result, "security_contributions", None)
    contributions = (
        recorded.reindex(index=returns.index, columns=active_columns)
        if recorded is not None and not recorded.empty
        else (held * changes).where(held > 1e-15, 0.0)
    )
    if contributions.isna().any().any():
        return dict(status="data_error", reason="incomplete_contributions", metrics=m)
    absolute = contributions.abs().sum()
    total = absolute.sum()
    m["maxSecurityContributionShare"] = float(absolute.max() / total) if total > 0 else 0.0
    m["maxSecurityDayContribution"] = float(contributions.abs().max().max())
    relevant = contributions.columns[(absolute > 0).to_numpy()]
    without = returns.to_numpy()[:, None] - contributions[relevant].to_numpy()
    leave_cagr = np.prod(1 + without, axis=0) ** (252 / window) - 1
    m["maxLeaveOneCagrDelta"] = (
        float(np.max(np.abs(m["cagr"] - leave_cagr))) if len(relevant) else 0.0
    )
    checks = [
        (m["sharpe"] < 0, "sharpe"),
        (m["mdd"] < -0.60, "drawdown"),
        (m["annualizedCostDrag"] > 0.02, "cost"),
        (m["effectiveNames"] < 10 - 1e-9, "effective_names"),
        (hhi > 0.15, "hhi"),
        (m["maxWeight"] > 0.15, "weight"),
        (m["maxSecurityDayContribution"] > 0.10, "security_day"),
        (m["maxSecurityContributionShare"] > 0.35, "security_dependence"),
        (m["maxLeaveOneCagrDelta"] > 0.25, "leave_one"),
    ]
    reasons = [reason for fail, reason in checks if fail]
    return dict(
        status="risk_rejected" if reasons else "eligible",
        reason=",".join(reasons),
        metrics=m,
        turnover=float(result.turnover.reindex(returns.index).sum()),
    )


def rank_candidates(candidates):
    comparable = {
        k: v for k, v in candidates.items() if v["status"] in ("eligible", "risk_rejected")
    }
    weights = dict(cagr=0.25, sortino=0.25, calmar=0.20, mdd=0.20, stability=0.10)
    for row in comparable.values():
        row.update(score=0.0, components={})
    for metric, weight in weights.items():
        ranks = _winsorized_percentile(
            pd.Series({k: v["metrics"][metric] for k, v in comparable.items()}, dtype=float),
            0.05,
            0.95,
        )
        for key, value in ranks.items():
            comparable[key]["components"][metric] = float(value * weight)
            comparable[key]["score"] += float(value * weight)
    eligible = [
        k for k, v in comparable.items() if v["status"] == "eligible" and np.isfinite(v["score"])
    ]

    def order(k):
        row = comparable[k]
        m = row["metrics"]
        return tuple(
            -row["score"] if f == "score" else -m[f]
            for f in ["score", "sortino", "calmar", "mdd", "cagr", "sharpe", "stability"]
        ) + (row["turnover"], k)

    return sorted(eligible, key=order)


def run_integrated_analysis(market, config=None, factors=None, *, progress_callback=None):
    from .integrated_factors import (
        factor_registry,
        compute_integrated_factors,
        iter_integrated_factors,
    )

    if config is None:
        config = IntegratedConfig()
    if isinstance(config, dict):
        config = IntegratedConfig(**config)
    definitions = factor_registry()
    panels = (
        compute_integrated_factors(market)
        if factors is None and config.common_universe
        else factors
    )
    if panels is not None:
        definitions = [d for d in definitions if d["id"] in panels]
    if not definitions:
        raise ValueError("no integrated factor definitions")
    rc = RunConfig(
        start_date=config.start_date,
        end_date=config.end_date,
        top_n=config.top_n,
        max_weight=config.max_weight,
        transaction_cost_bps=config.transaction_cost_bps,
        slippage_bps=config.slippage_bps,
        evaluation_window_days=config.evaluation_window_days,
        score_cagr_weight=0.25,
        score_sharpe_weight=0.0,
    )
    index = market.prices.index
    run_index = index[
        (index >= pd.Timestamp(config.start_date))
        & (index <= pd.Timestamp(config.end_date) if config.end_date else True)
    ]
    if len(run_index) < 2:
        raise ValueError("insufficient evaluation dates")
    prices = market.prices.loc[run_index]
    dates = completed_monthends(run_index)
    adv = (market.raw_close * market.volumes).rolling(63, min_periods=42).mean()
    eligibility = market.eligibility.loc[run_index].copy()
    if config.common_universe:
        selected = config.comparison_factors or tuple(panels)
        for key in selected:
            eligibility &= panels[key].loc[run_index].notna()
    price_changes = prices.pct_change(fill_method=None)
    monthly = {date: {} for date in dates}
    targets = {}
    factor_rows = []
    returns_by_id = {}
    intervals_by_id = {}
    weights_by_id = {}
    signals_by_id = {}
    lookup = {d["id"]: d for d in definitions}
    panel_iterator = panels.items() if panels is not None else iter_integrated_factors(market)
    for key, raw_panel in panel_iterator:
        definition = lookup[key]
        panel = raw_panel.where(market.eligibility)
        if config.common_universe:
            panel = panel.copy()
            panel.loc[run_index] = panel.loc[run_index].where(eligibility)
        allocations = {d: _allocation(d, panel, market, adv, config, rc) for d in dates}
        ic, quintiles = monthly_signal_diagnostics(
            panel, market.prices, dates, definition["direction"], config.execution_delay_sessions,
            valuation_prices=market.valuation_prices,
            corporate_actions=market.metadata.get("corporateActions", ()),
        )
        row = dict(
            id=key,
            label=definition["name"],
            family=definition["family"],
            direction=definition["direction"],
            definition=definition,
            ic=ic,
            quintiles=quintiles,
            status="research_only",
            metrics={},
            nav=[],
            drawdown=[],
            holdings=[],
        )
        signals_by_id[key] = panel.reindex(dates).rank(axis=1, pct=True)
        if definition["selectionEligible"]:
            result = run_factor_backtest(
                key,
                FIXED_WEIGHTING_POLICY,
                prices,
                panel.loc[run_index],
                rc,
                eligibility_mask=eligibility,
                trailing_dollar_volume=adv.loc[run_index],
                signal_targets=allocations,
                execution_delay_sessions=config.execution_delay_sessions,
                **backtest_inputs(market, run_index),
            )
            row.update(fixed_factor_history(result, allocations, run_index,
                                            config.execution_delay_sessions,
                                            next_execution=next_execution))
            returns_by_id[key] = result.returns
            intervals_by_id[key] = result.return_interval_sessions
            for date in dates:
                monthly[date][key] = _monthly_candidate(
                    result, date, allocations[date], price_changes, config.evaluation_window_days,
                    observed_prices=prices,
                )
            targets[key] = allocations
            nav, drawdown = performance(result.returns)
            first_valid = result.returns.first_valid_index()
            active_returns = (
                result.returns.loc[first_valid:]
                if first_valid is not None
                else result.returns.iloc[:0]
            )
            row.update(
                status=(
                    "insufficient_data"
                    if active_returns.empty
                    else "available"
                    if active_returns.notna().all()
                    else "partial_data"
                ),
                valuationCoverage=float(active_returns.notna().mean())
                if len(active_returns)
                else None,
                lastValuedDate=str(result.equity.last_valid_index().date())
                if result.equity.last_valid_index() is not None
                else None,
                metrics=metrics(result.returns, result.return_interval_sessions),
                nav=nav,
                drawdown=drawdown,
                holdings=_holding_rows(result.ending_weights),
                cashWeight=result.ending_cash_weight,
                receivableWeight=result.ending_receivable_weight,
                liquidCashWeight=result.ending_cash_weight - result.ending_receivable_weight,
            )
            weights_by_id[key] = actual_holding_snapshots(result, dates, run_index)
            del result
        factor_rows.append(row)
        if progress_callback is not None:
            progress_callback(
                dict(stage="factor", id=key, completed=len(factor_rows), total=len(definitions))
            )
    selected_targets = {}
    history = []
    for date, candidates in monthly.items():
        order = rank_candidates(candidates)
        key = order[0] if order else None
        comparable = [
            v for v in candidates.values() if v["status"] in ("eligible", "risk_rejected")
        ]
        errors = any(v["status"] == "data_error" for v in candidates.values())
        if key:
            status = "selected"
            selected_targets[date] = targets[key][date]
        elif comparable and not errors:
            status = "cash"
            selected_targets[date] = TargetAllocation(
                FIXED_WEIGHTING_POLICY, date, status="available"
            )
        else:
            status = "deferred"
        pos = run_index.get_loc(date) + config.execution_delay_sessions
        history.append(
            dict(
                date=str(date.date()),
                signalDate=str(date.date()),
                executionDate=str(run_index[pos].date())
                if pos < len(run_index)
                else str(next_execution(date, config.execution_delay_sessions).date()),
                factorId=key,
                label=next(
                    (d["name"] for d in definitions if d["id"] == key),
                    "현금" if status == "cash" else "선택 보류",
                ),
                status=status,
                score=candidates[key]["score"] if key else None,
                candidates=[dict(id=k, **v) for k, v in candidates.items()],
                holdings=_holding_rows(selected_targets[date].weights())
                if date in selected_targets
                else [],
            )
        )
    dummy = pd.DataFrame(0.0, index=run_index, columns=prices.columns)
    selected = run_factor_backtest(
        "MONTHLY_SELECTION",
        FIXED_WEIGHTING_POLICY,
        prices,
        dummy,
        rc,
        signal_targets=selected_targets,
        execution_delay_sessions=config.execution_delay_sessions,
        **backtest_inputs(market, run_index),
    )
    for h in history:
        d = pd.Timestamp(h["executionDate"]) if h["executionDate"] else None
        h["executionStatus"] = selected.execution_statuses.get(d, "pending")
        h["cost"] = selected.costs.get(d, None)
        h["turnover"] = selected.turnover.get(d, None)
        h["targetHoldings"] = h["holdings"]
        if d is not None and d in run_index:
            position = run_index.get_loc(d)
            actual = (
                selected.weights.iloc[position + 1]
                if position + 1 < len(run_index)
                else selected.ending_weights
            )
            h["holdings"] = _holding_rows(actual)
            h["holdingsAsOf"] = str(d.date())
            h["cashWeight"] = float(selected.cash_weights.iloc[position + 1]) if position + 1 < len(run_index) else selected.ending_cash_weight
            h["receivableWeight"] = float(selected.receivable_weights.iloc[position + 1]) if position + 1 < len(run_index) else selected.ending_receivable_weight
            h["liquidCashWeight"] = h["cashWeight"] - h["receivableWeight"]
        elif d is not None:
            h["holdings"] = _holding_rows(selected.ending_weights)
            h["holdingsAsOf"] = str(run_index[-1].date())
            h["cashWeight"] = selected.ending_cash_weight
            h["receivableWeight"] = selected.ending_receivable_weight
            h["liquidCashWeight"] = selected.ending_cash_weight - selected.ending_receivable_weight
    nav, drawdown = performance(selected.returns)
    selection = dict(
        current=history[-1] if history else None,
        history=history,
        nav=nav,
        drawdown=drawdown,
        holdings=_holding_rows(selected.ending_weights),
        cashWeight=selected.ending_cash_weight,
        receivableWeight=selected.ending_receivable_weight,
        liquidCashWeight=selected.ending_cash_weight - selected.ending_receivable_weight,
        metrics=metrics(selected.returns, selected.return_interval_sessions),
        pending=history[-1]
        if history and pd.Timestamp(history[-1]["executionDate"]) > run_index[-1]
        else None,
        holdingsAsOf=str(run_index[-1].date()),
    )
    comparisons = []
    comparison_start = selected.returns.first_valid_index()
    for key in ("SPY", "QQQ", "^IXIC"):
        if key in prices:
            r = prices[key].pct_change(fill_method=None)
            returns_by_id[key] = r
            intervals_by_id[key] = r.notna().astype(int)
            aligned = r.loc[comparison_start:] if comparison_start is not None else r.iloc[:0]
            n, d = performance(aligned)
            comparisons.append(dict(
                id=key, label=key, nav=n, drawdown=d,
                metrics=metrics(aligned, intervals_by_id[key]),
            ))
    fixed = next((r for r in factor_rows if r["id"] == "MOM12_1"), None)
    if fixed:
        aligned = (
            returns_by_id["MOM12_1"].loc[comparison_start:]
            if comparison_start is not None
            else returns_by_id["MOM12_1"].iloc[:0]
        )
        n, d = performance(aligned)
        comparisons.append(
            dict(id="MOM12_1", label=fixed["label"], nav=n, drawdown=d,
                 metrics=metrics(aligned, intervals_by_id["MOM12_1"]))
        )
    returns_by_id["MONTHLY_SELECTION"] = selected.returns
    intervals_by_id["MONTHLY_SELECTION"] = selected.return_interval_sessions
    research = build_research(
        returns_by_id, signals_by_id, weights_by_id, factor_rows, config, intervals_by_id
    )
    settings = asdict(config)
    identity = dict(
        snapshotId=market.metadata.get("snapshotId"), settings=settings, definitions=definitions,
        engineVersion="integrated-accounting-v5",
    )
    digest = hashlib.sha256(json.dumps(clean(identity), sort_keys=True).encode()).hexdigest()
    output = dict(
        schemaVersion="integrated-factor/v1",
        registry=definitions,
        selection=selection,
        factors=factor_rows,
        comparisons=comparisons,
        research=research,
        data={
            **market.metadata,
            "asOf": str(run_index[-1].date()),
            "requestedCount": len(market.metadata.get("requestedSymbols", prices.columns)),
            "pricedCount": int(prices.notna().any().sum()),
            "eligibleCount": int(eligibility.iloc[-1].sum()),
            "symbols": symbol_diagnostics(market, prices, eligibility),
        },
        settings=settings,
        resultIdentity=dict(
            resultId=digest[:20],
            inputHash=market.metadata.get("snapshotId"),
            registryVersion="integrated-32-v1",
            engineVersion="integrated-accounting-v5",
        ),
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )
    if config.run_stress:
        output["research"]["stress"] = run_stress_suite(
            market, config, panels, frozen_targets=selected_targets,
            source_result_id=output["resultIdentity"]["resultId"],
        )
    annotate_metric_states(output)
    return clean(output)


def build_research(returns, signals, holdings, factors, config, interval_sessions=None):
    frame = pd.DataFrame(returns)
    # Daily cross-series diagnostics require the same one-session horizon.
    # Preserve missing dates: never convert a multi-session catch-up to a daily
    # sample or stitch the sessions surrounding it into a bootstrap block.
    coverage = []
    for key in frame:
        intervals = _return_intervals(
            frame[key], interval_sessions.get(key) if interval_sessions is not None else None
        )
        observed = frame[key].notna()
        coverage.append(dict(
            id=key,
            observedReturnCount=int(observed.sum()),
            dailyObservations=int((observed & intervals.eq(1)).sum()),
            excludedMultiSessionObservations=int((observed & intervals.gt(1)).sum()),
        ))
        frame[key] = frame[key].where(intervals.eq(1))
    correlations = []
    overlaps = []
    keys = list(signals)
    for i, left in enumerate(keys):
        for right in keys[i + 1 :]:
            corr = signals[left].corrwith(signals[right], axis=1).mean()
            ret = frame[left].corr(frame[right]) if left in frame and right in frame else np.nan
            correlations.append(dict(left=left, right=right, signal=corr, returns=ret))
            if left in holdings and right in holdings:
                values, cash_values = [], []
                unavailable = 0
                for d in holdings[left]:
                    a_snapshot, b_snapshot = holdings[left][d], holdings[right].get(d)
                    if (
                        not b_snapshot
                        or a_snapshot["status"] != "available"
                        or b_snapshot["status"] != "available"
                    ):
                        unavailable += 1
                        continue
                    a, b = a_snapshot["weights"].align(b_snapshot["weights"], fill_value=0)
                    values.append(float(np.minimum(a, b).sum()))
                    cash_values.append(min(a_snapshot.get("liquidCashWeight", a_snapshot["cashWeight"]), b_snapshot.get("liquidCashWeight", b_snapshot["cashWeight"])))
                overlaps.append(
                    dict(
                        left=left,
                        right=right,
                        value=np.mean(values) if values else np.nan,
                        cashOverlap=np.mean(cash_values) if cash_values else np.nan,
                        observations=len(values),
                        unavailableObservations=unavailable,
                        basis="actual_month_end_holdings",
                        status="available" if values else "insufficient_data",
                    )
                )
    # Restrict synchronized inference to the longest common complete history.
    available = frame.loc[:, frame.notna().any()]
    bootstrap = [
        synchronized_bootstrap(available, config.bootstrap_repetitions, b) for b in (10, 20, 40)
    ]
    monthly = pd.DataFrame(
        {r["id"]: pd.Series({x["date"]: x["buy"] for x in r["ic"]}) for r in factors}
    )
    ic_bootstrap = []
    if len(monthly):
        monthly["ZERO"] = 0.0
        ic_bootstrap = [
            synchronized_bootstrap(monthly, config.bootstrap_repetitions, b, benchmark="ZERO")
            for b in (2, 3, 6)
        ]
    return dict(
        returnBasis="observed_single_session_returns_calendar_preserved",
        returnCoverage=coverage,
        conditionalExposures=conditional_exposures(available),
        correlations=correlations,
        overlap=overlaps,
        bootstrap=bootstrap,
        icBootstrap=ic_bootstrap,
        holm={
            "family": "all reported candidate mean excess-return tests",
            "method": "Holm",
            "results": bootstrap[1].get("results", []),
        },
        dsr=dict(status="unavailable", reason="historical_search_count_unknown"),
        regimes=regime_analysis(available, available["SPY"]) if "SPY" in available else {},
        stress=[],
        searchHistory=[
            dict(id=d["id"], status=d["status"], definitionVersion=d["definition"].get("version"))
            for d in factors
        ],
    )


def frozen_choice_delay_stress(market, config, targets, source_result_id=None):
    """Delay the original orders without re-ranking factors or changing targets."""
    from dataclasses import replace
    delayed = replace(config, execution_delay_sessions=2, run_stress=False,
                      bootstrap_repetitions=0)
    index = market.prices.index
    index = index[(index >= pd.Timestamp(config.start_date)) &
                  (index <= pd.Timestamp(config.end_date) if config.end_date else True)]
    prices = market.prices.loc[index]
    rc = RunConfig(start_date=config.start_date, end_date=config.end_date,
                   top_n=config.top_n, max_weight=config.max_weight,
                   transaction_cost_bps=config.transaction_cost_bps,
                   slippage_bps=config.slippage_bps,
                   evaluation_window_days=config.evaluation_window_days)
    book = run_factor_backtest(
        "MONTHLY_SELECTION", FIXED_WEIGHTING_POLICY, prices,
        pd.DataFrame(0., index=index, columns=prices.columns), rc,
        signal_targets=targets, execution_delay_sessions=2,
        **backtest_inputs(market, index),
    )
    nav, drawdown = performance(book.returns)
    return dict(id="fixed_choice_delay2", settings=dict(execution_delay_sessions=2),
                effectiveSettings=asdict(delayed), metrics=metrics(book.returns, book.return_interval_sessions),
                nav=nav, drawdown=drawdown, status="available",
                sourceResultId=source_result_id,
                selectionPolicy="frozen_original_monthly_targets")


def run_stress_suite(market, config, factors=None, *, frozen_targets=None, source_result_id=None):
    from dataclasses import replace

    scenarios = [
        ("cost20", dict(transaction_cost_bps=10.0, slippage_bps=10.0)),
        ("cost40", dict(transaction_cost_bps=20.0, slippage_bps=20.0)),
        ("delay2", dict(execution_delay_sessions=2)),
        ("top10", dict(top_n=10)),
        ("top30", dict(top_n=30)),
        ("equal", dict(weighting="equal")),
    ]
    # Standalone callers can request stresses without an in-memory base run.
    # The normal integrated path passes its original TargetAllocation objects,
    # so it neither reconstructs actual holdings as targets nor recomputes the
    # monthly choices for the frozen experiment.
    if frozen_targets is None:
        base = run_integrated_analysis(
            market, replace(config, run_stress=False, bootstrap_repetitions=0), factors)
        source_result_id = source_result_id or base["resultIdentity"]["resultId"]
        frozen_targets = {
            pd.Timestamp(row["signalDate"]): TargetAllocation(
                FIXED_WEIGHTING_POLICY, pd.Timestamp(row["signalDate"]),
                rows=pd.DataFrame(row["targetHoldings"]), status="available")
            for row in base["selection"]["history"] if row["status"] in ("selected", "cash")
        }
    results = []
    for name, change in scenarios:
        effective = replace(config, **change, run_stress=False, bootstrap_repetitions=0)
        run = run_integrated_analysis(market, effective, factors)
        results.append(dict(
            id=name, settings=change, effectiveSettings=asdict(effective),
            metrics=run["selection"]["metrics"], nav=run["selection"]["nav"],
            drawdown=run["selection"]["drawdown"], status="available",
            sourceResultId=source_result_id,
            sourceRunResultId=run["resultIdentity"]["resultId"],
            selectionPolicy="reevaluated_monthly_candidates",
        ))
    results.insert(2, frozen_choice_delay_stress(market, config, frozen_targets, source_result_id))
    return results


def symbol_diagnostics(market, prices, eligibility):
    receipts = {s: r for r in market.metadata.get("receipts", []) for s in r.get("symbols", [])}
    symbols = market.metadata.get("requestedSymbols", list(prices.columns))
    prices = market.prices.loc[: prices.index[-1]]
    observations = prices.notna().sum()
    raw = market.raw_close.reindex(prices.index)
    volume = market.volumes.reindex(prices.index)
    dv = (raw * volume.where(volume > 0)).tail(63)
    source = (
        "Yahoo"
        if "Yahoo" in market.metadata.get("priceBasis", "")
        else market.metadata.get("provider")
    )
    rows = []
    for symbol in symbols:
        if symbol not in prices:
            continue
        series = prices[symbol]
        last = series.last_valid_index()
        reasons = []
        if pd.isna(series.iloc[-1]):
            reasons.append("missing_latest_price")
        if observations[symbol] < 252:
            reasons.append("history_below_252")
        if pd.notna(raw[symbol].iloc[-1]) and raw[symbol].iloc[-1] < 5:
            reasons.append("price_below_5")
        if dv[symbol].count() < 42:
            reasons.append("liquidity_observations_below_42")
        elif dv[symbol].mean() < 5e6:
            reasons.append("dollar_volume_below_5m")
        allowed = bool(eligibility[symbol].iloc[-1])
        if not allowed and not reasons:
            reasons.append("price_volume_quality_or_common_input_filter")
        receipt = receipts.get(symbol, {})
        rows.append(
            dict(
                symbol=symbol,
                status="eligible" if allowed else "missing" if last is None else "ineligible",
                source=source,
                reason=reasons,
                lastObservation=str(last.date()) if last is not None else None,
                retrievedAt=receipt.get("retrievedAt"),
                inputHash=receipt.get("sha256"),
                observations=int(observations[symbol]),
            )
        )
    return rows


def annotate_metric_states(value):
    if isinstance(value, dict):
        if isinstance(value.get("metrics"), dict):
            value["metricStates"] = {
                key: (
                    "positive_infinity"
                    if number == float("inf")
                    else "negative_infinity"
                    if number == float("-inf")
                    else "insufficient_data"
                    if not np.isfinite(number)
                    else "available"
                )
                for key, number in value["metrics"].items()
                if isinstance(number, (int, float, np.number))
            }
        for child in list(value.values()):
            annotate_metric_states(child)
    elif isinstance(value, list):
        for child in value:
            annotate_metric_states(child)


def actual_holding_snapshots(result, dates, index):
    snapshots = {}
    claims = getattr(result, "receivable_weights", pd.Series(0., index=index))
    for date in dates:
        position = index.get_loc(date)
        if not result.strategy_active.loc[date]:
            snapshots[date] = dict(status="not_started")
        elif not result.valuation_available.loc[date]:
            snapshots[date] = dict(status="unavailable_valuation")
        else:
            weights = (
                result.weights.iloc[position + 1]
                if position + 1 < len(index)
                else result.ending_weights
            )
            cash = (
                result.cash_weights.iloc[position + 1]
                if position + 1 < len(index)
                else result.ending_cash_weight
            )
            snapshots[date] = dict(
                status="available", weights=weights[weights > 1e-15], cashWeight=float(cash)
            )
            claim = float(claims.iloc[position + 1]) if position + 1 < len(index) else getattr(result, "ending_receivable_weight", 0.)
            snapshots[date].update(receivableWeight=claim, liquidCashWeight=float(cash) - claim)
    return snapshots
