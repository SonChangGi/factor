from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import (
    FIXED_WEIGHTING_POLICY,
    POLICY_VERSIONS,
    RunConfig,
    WEIGHTING_POLICIES,
)


TIE_BREAK_POLICY = "factor_score_desc_then_boundary_trailing_dollar_volume_desc_then_symbol_asc"
POLICY_LABELS = {
    FIXED_WEIGHTING_POLICY: "Fixed factor, liquidity, and point-in-time market-cap rank",
}


@dataclass(slots=True)
class TargetAllocation:
    policy_id: str
    signal_date: pd.Timestamp
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    cash_weight: float = 1.0
    eligible_security_count: int = 0
    status: str = "unavailable"
    reasons: list[str] = field(default_factory=list)
    component_status: dict[str, str] = field(default_factory=dict)
    concentration: dict[str, float] = field(default_factory=dict)
    policy_version: str = ""
    tie_break_policy: str = TIE_BREAK_POLICY

    @property
    def selected_security_count(self) -> int:
        return int(len(self.rows))

    def weights(self, index: pd.Index | None = None) -> pd.Series:
        values = (
            self.rows.set_index("symbol")["weight"].astype(float)
            if not self.rows.empty
            else pd.Series(dtype=float)
        )
        return values.reindex(index, fill_value=0.0) if index is not None else values

    def to_dict(self) -> dict[str, object]:
        return {
            "weightingPolicyId": self.policy_id,
            "weightingPolicyVersion": self.policy_version,
            "signalDate": self.signal_date.date().isoformat(),
            "status": self.status,
            "eligibleSecurityCount": self.eligible_security_count,
            "selectedSecurityCount": self.selected_security_count,
            "cashWeight": self.cash_weight,
            "reasons": list(self.reasons),
            "componentStatus": dict(self.component_status),
            "concentration": dict(self.concentration),
            "tieBreakPolicy": self.tie_break_policy,
            "weights": self.rows.to_dict(orient="records"),
        }


@dataclass(slots=True)
class ModelPortfolio:
    factor: str
    as_of: pd.Timestamp
    allocation: TargetAllocation
    target_type: str = "factor_portfolio"
    execution_timing: str = "next_available_session_close_after_signal"

    @property
    def rows(self) -> pd.DataFrame:
        return self.allocation.rows

    @property
    def cash_weight(self) -> float:
        return self.allocation.cash_weight

    @property
    def eligible_security_count(self) -> int:
        return self.allocation.eligible_security_count

    @property
    def status(self) -> str:
        return self.allocation.status

    @property
    def reasons(self) -> list[str]:
        return self.allocation.reasons

    def to_dict(self) -> dict[str, object]:
        payload = self.allocation.to_dict()
        payload.update(
            {
                "factor": self.factor,
                "asOf": self.as_of.date().isoformat(),
                "targetType": self.target_type,
                "executionTiming": self.execution_timing,
                "selectionFraction": (
                    self.allocation.selected_security_count / self.eligible_security_count
                    if self.eligible_security_count
                    else 0.0
                ),
            }
        )
        return payload


def _rank_scores(scores: pd.Series) -> pd.Series:
    if not scores.index.is_unique:
        raise ValueError("scores must have unique symbols")
    clean = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    ranking = pd.DataFrame(
        {"factorScore": clean.to_numpy(dtype=float), "symbol": clean.index.astype(str)},
        index=clean.index,
    ).sort_values(
        ["factorScore", "symbol"],
        ascending=[False, True],
        kind="stable",
    )
    return pd.Series(ranking["factorScore"].to_numpy(), index=ranking.index, dtype=float)


def _positive_finite(series: pd.Series, index: pd.Index) -> pd.Series:
    values = pd.to_numeric(series.reindex(index), errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    return values.where(values.gt(0.0))


def _percentile_component(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if values.dropna().empty:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return values.rank(method="average", pct=True, ascending=True).astype(float)


def _select_with_boundary_tie_break(
    ranked: pd.Series,
    top_n: int,
    trailing_dollar_volume: pd.Series,
) -> tuple[pd.Series, bool]:
    """Resolve a Top-N boundary tie with signal-date liquidity evidence."""

    if len(ranked) <= top_n:
        return ranked, False
    cutoff = float(ranked.iloc[top_n - 1])
    above = ranked.loc[ranked.gt(cutoff)]
    tied = ranked.loc[ranked.eq(cutoff)]
    if len(above) + len(tied) <= top_n:
        return ranked.head(top_n), False
    remaining = top_n - len(above)
    tie_liquidity = _positive_finite(trailing_dollar_volume, tied.index)
    if int(tie_liquidity.notna().sum()) < remaining:
        return pd.Series(dtype=float), True
    tie_order = pd.DataFrame(
        {
            "score": tied,
            "liquidity": tie_liquidity,
            "symbol": tied.index.astype(str),
        },
        index=tied.index,
    ).dropna(subset=["liquidity"])
    tie_order = tie_order.sort_values(
        ["liquidity", "symbol"],
        ascending=[False, True],
        kind="stable",
    )
    chosen = tied.reindex(tie_order.head(remaining).index)
    return pd.concat([above, chosen]), True


def _water_fill_cap(raw: pd.Series, max_weight: float) -> pd.Series:
    """Normalize positive raw scores and redistribute above-cap excess deterministically."""

    values = pd.to_numeric(raw, errors="coerce").replace([np.inf, -np.inf], np.nan)
    values = values.fillna(0.0).clip(lower=0.0).astype(float)
    result = pd.Series(0.0, index=values.index, dtype=float)
    active = values[values.gt(0.0)].copy()
    budget = 1.0
    while not active.empty and budget > 1e-15:
        capacity = max_weight - result.reindex(active.index)
        active = active.loc[capacity.gt(1e-15)]
        if active.empty:
            break
        raw_total = float(active.sum())
        proposal = (
            pd.Series(budget / len(active), index=active.index)
            if raw_total <= 0.0
            else active / raw_total * budget
        )
        capacity = max_weight - result.loc[active.index]
        binding = proposal.ge(capacity - 1e-15)
        if not bool(binding.any()):
            result.loc[active.index] += proposal
            budget = 0.0
            break
        bound_index = proposal.index[binding]
        allocation = capacity.loc[bound_index].clip(lower=0.0)
        result.loc[bound_index] += allocation
        budget -= float(allocation.sum())
        active = active.drop(index=bound_index)
    return result.clip(lower=0.0, upper=max_weight)


def capped_weight_values(raw_values: list[float], max_weight: float) -> list[float]:
    """Expose the canonical cap redistribution for serialized-payload validation."""

    raw = pd.Series(raw_values, index=range(len(raw_values)), dtype=float)
    return _water_fill_cap(raw, max_weight).to_list()


def _concentration(weights: pd.Series, cash_weight: float) -> dict[str, float]:
    positive = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0)
    invested = float(positive.sum())
    if invested <= 0.0:
        return {
            "investedWeight": 0.0,
            "cashWeight": float(cash_weight),
            "riskySleeveHhi": 0.0,
            "effectiveNames": 0.0,
            "top1Weight": 0.0,
            "top5Weight": 0.0,
            "maxWeight": 0.0,
        }
    normalized = positive / invested
    hhi = float(normalized.pow(2).sum())
    sorted_weights = positive.sort_values(ascending=False)
    return {
        "investedWeight": invested,
        "cashWeight": float(cash_weight),
        "riskySleeveHhi": hhi,
        "effectiveNames": float(1.0 / hhi) if hhi > 0.0 else 0.0,
        "top1Weight": float(sorted_weights.head(1).sum()),
        "top5Weight": float(sorted_weights.head(5).sum()),
        "maxWeight": float(sorted_weights.max()),
    }


def _unavailable(
    policy_id: str,
    signal_date: pd.Timestamp,
    reason: str,
    *,
    eligible_count: int = 0,
    component_status: dict[str, str] | None = None,
) -> TargetAllocation:
    return TargetAllocation(
        policy_id=policy_id,
        signal_date=signal_date,
        eligible_security_count=eligible_count,
        status="unavailable",
        reasons=[reason],
        component_status=component_status or {},
        concentration=_concentration(pd.Series(dtype=float), 1.0),
        policy_version=POLICY_VERSIONS[policy_id],
    )


def construct_target_allocation(
    policy_id: str,
    signal_date: pd.Timestamp,
    scores: pd.Series,
    prices: pd.Series,
    eligibility: pd.Series,
    config: RunConfig,
    *,
    trailing_dollar_volume: pd.Series | None = None,
    trailing_market_cap: pd.Series | None = None,
) -> TargetAllocation:
    """Build one target from signal-date-only inputs for history and current use."""

    if policy_id not in WEIGHTING_POLICIES:
        raise ValueError(f"unknown weighting policy: {policy_id}")
    for name, series in (("scores", scores), ("prices", prices), ("eligibility", eligibility)):
        if not series.index.is_unique:
            return _unavailable(policy_id, signal_date, f"duplicate_{name}_symbol")
    numeric_scores = pd.to_numeric(scores, errors="coerce").replace([np.inf, -np.inf], np.nan)
    numeric_prices = pd.to_numeric(prices.reindex(scores.index), errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    eligible = eligibility.reindex(scores.index).fillna(False).astype(bool)
    base_complete = eligible & numeric_scores.notna() & numeric_prices.gt(0.0)
    ranked = _rank_scores(numeric_scores.where(base_complete).dropna())
    eligible_count = int(len(ranked))
    if ranked.empty:
        return _unavailable(policy_id, signal_date, "no_complete_signal_inputs")

    liquidity = (
        _positive_finite(trailing_dollar_volume, ranked.index)
        if trailing_dollar_volume is not None
        else pd.Series(np.nan, index=ranked.index, dtype=float)
    )
    ranked = ranked.loc[liquidity.notna()]
    if ranked.empty:
        return _unavailable(
            policy_id,
            signal_date,
            "no_finite_trailing_dollar_volume",
            eligible_count=eligible_count,
            component_status={
                "liquidity": "unavailable" if liquidity.dropna().empty else "partial",
                "marketCap": "not_used",
            },
        )

    selected, boundary_tie_resolved = _select_with_boundary_tie_break(
        ranked,
        config.top_n,
        liquidity,
    )
    if selected.empty:
        return _unavailable(
            policy_id,
            signal_date,
            "top_n_boundary_tie_has_no_finite_liquidity_tie_break",
            eligible_count=eligible_count,
        )
    symbols = selected.index
    rank_strength = selected.rank(method="average", ascending=True).astype(float)
    component_status: dict[str, str] = {"score": "available"}
    diagnostics = pd.DataFrame(index=symbols)
    diagnostics["rankComponent"] = rank_strength
    diagnostics["trailingDollarVolume"] = liquidity.reindex(symbols)
    diagnostics["trailingMarketCap"] = np.nan
    diagnostics["scoreComponent"] = np.nan
    diagnostics["liquidityComponent"] = np.nan
    diagnostics["marketCapComponent"] = 0.0
    score_values = selected.clip(lower=0.0)
    if not bool(score_values.gt(0.0).any()):
        score_values = selected
    score_component = _percentile_component(score_values)
    liquidity_component = _percentile_component(np.log1p(liquidity.reindex(symbols)))
    raw = (
        config.allocation_rank_floor
        + config.allocation_score_weight * score_component
        + config.allocation_liquidity_weight * liquidity_component
    )
    diagnostics["scoreComponent"] = score_component
    diagnostics["liquidityComponent"] = liquidity_component
    component_status.update(
        {
            "methodology": "fixed_not_optimized",
            "liquidity": "trailing_raw_dollar_volume",
            "marketCap": "not_used",
        }
    )

    weights = _water_fill_cap(raw, config.max_weight)
    total = float(weights.sum())
    cash_weight = max(0.0, 1.0 - total)
    rows = pd.DataFrame(
        {
            "rank": np.arange(1, len(symbols) + 1, dtype=int),
            "symbol": symbols.astype(str),
            "factorScore": selected.to_numpy(dtype=float),
            "rawPolicyScore": raw.reindex(symbols).to_numpy(dtype=float),
            "preCapWeight": (
                raw.reindex(symbols) / float(raw.sum())
                if float(raw.sum()) > 0.0
                else pd.Series(0.0, index=symbols)
            ).to_numpy(dtype=float),
            "weight": weights.reindex(symbols).to_numpy(dtype=float),
            "maxWeight": float(config.max_weight),
            "capBinding": weights.reindex(symbols).ge(config.max_weight - 1e-12).to_numpy(),
            "rankComponent": diagnostics["rankComponent"].to_numpy(dtype=float),
            "trailingDollarVolume": diagnostics["trailingDollarVolume"].to_numpy(dtype=float),
            "trailingMarketCap": diagnostics["trailingMarketCap"].to_numpy(dtype=float),
            "scoreComponent": diagnostics["scoreComponent"].to_numpy(dtype=float),
            "liquidityComponent": diagnostics["liquidityComponent"].to_numpy(dtype=float),
            "marketCapComponent": diagnostics["marketCapComponent"].to_numpy(dtype=float),
        }
    )
    reasons: list[str] = []
    if boundary_tie_resolved:
        reasons.append("top_n_boundary_tie_resolved_by_trailing_dollar_volume")
        component_status["selectionTieBreak"] = "trailing_dollar_volume_desc_then_symbol_asc"
    if len(rows) < config.top_n:
        reasons.append("fewer_complete_policy_inputs_than_top_n")
    if cash_weight > 1e-12:
        reasons.append("max_weight_capacity_or_missing_policy_inputs")
    values = rows["weight"].to_numpy(dtype=float)
    if (
        not np.isfinite(values).all()
        or bool((values < 0.0).any())
        or bool((values > config.max_weight + 1e-12).any())
        or not np.isclose(total + cash_weight, 1.0, atol=1e-10)
    ):
        return _unavailable(
            policy_id,
            signal_date,
            "weight_invariant_failed",
            eligible_count=eligible_count,
            component_status=component_status,
        )
    return TargetAllocation(
        policy_id=policy_id,
        signal_date=signal_date,
        rows=rows,
        cash_weight=cash_weight,
        eligible_security_count=eligible_count,
        status="available",
        reasons=reasons,
        component_status=component_status,
        concentration=_concentration(rows.set_index("symbol")["weight"], cash_weight),
        policy_version=POLICY_VERSIONS[policy_id],
    )


def balanced_weights(
    scores: pd.Series,
    top_n: int = 20,
    max_weight: float = 0.10,
    require_positive: bool = False,
) -> pd.Series:
    """Small equal-weight primitive retained as the explicit baseline policy helper."""

    ranked = _rank_scores(scores)
    if require_positive:
        ranked = ranked.loc[ranked.gt(0.0)]
    selected = ranked.head(top_n)
    raw = pd.Series(1.0, index=selected.index)
    weights = _water_fill_cap(raw, max_weight)
    return weights.reindex(scores.index, fill_value=0.0)


def construct_model_portfolio(
    factor: str,
    as_of: pd.Timestamp,
    scores: pd.Series,
    prices: pd.Series,
    eligibility: pd.Series,
    config: RunConfig,
    *,
    policy_id: str,
    trailing_dollar_volume: pd.Series | None = None,
    trailing_market_cap: pd.Series | None = None,
    names: pd.Series | None = None,
) -> ModelPortfolio:
    allocation = construct_target_allocation(
        policy_id,
        as_of,
        scores,
        prices,
        eligibility,
        config,
        trailing_dollar_volume=trailing_dollar_volume,
        trailing_market_cap=trailing_market_cap,
    )
    if not allocation.rows.empty:
        rows = allocation.rows.copy()
        symbols = pd.Index(rows["symbol"].astype(str))
        rows.insert(
            2,
            "name",
            (
                names.reindex(symbols)
                .fillna(pd.Series(symbols, index=symbols))
                .astype(str)
                .to_numpy()
                if names is not None
                else symbols.to_numpy()
            ),
        )
        rows.insert(
            4,
            "latestPrice",
            pd.to_numeric(prices.reindex(symbols), errors="coerce").to_numpy(dtype=float),
        )
        rows.insert(5, "eligibilityStatus", "eligible")
        allocation.rows = rows
    return ModelPortfolio(factor=factor, as_of=as_of, allocation=allocation)
