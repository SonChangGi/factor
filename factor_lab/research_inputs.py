from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Mapping

from .config import (
    MAX_EVALUATION_WINDOW_DAYS,
    MAX_TOP_N,
    MIN_EVALUATION_WINDOW_DAYS,
    RunConfig,
    minimum_evaluation_observations,
)
from .identity import canonical_sha256


RESEARCH_INPUTS_VERSION = "research-inputs-v2"
LEGACY_RESEARCH_INPUTS_VERSION = "research-inputs-v1"
TRADING_SESSIONS_PER_YEAR = 252


class ResearchInputError(ValueError):
    """Raised when a public research-input object is unknown or invalid."""


@dataclass(frozen=True, slots=True)
class ResearchInputs:
    rebalance_frequency: str = "ME"
    evaluation_window_days: int = 756
    top_n: int = 20
    max_weight: float = 0.10
    transaction_cost_bps: float = 5.0
    slippage_bps: float = 5.0
    min_history_days: int = 252
    min_price: float = 5.0
    min_avg_dollar_volume: float = 0.0
    min_avg_volume: float = 0.0
    liquidity_lookback_days: int = 63
    min_liquidity_observations: int = 42
    max_price_missing_ratio: float = 0.05
    max_volume_missing_ratio: float = 0.10
    max_extreme_daily_return: float = 0.80
    selection_min_sharpe: float = 0.0
    selection_max_drawdown: float = 0.60
    selection_max_annualized_cost_drag: float = 0.02
    selection_min_effective_names: float = 10.0
    selection_max_target_hhi: float = 0.15
    selection_max_target_weight: float = 0.15
    selection_max_abs_security_day_contribution: float = 0.10
    selection_max_security_absolute_contribution_share: float = 0.35
    selection_max_leave_one_security_cagr_delta: float = 0.25
    selection_extreme_event_action: str = "exclude"
    selection_extreme_event_penalty_points: float = 20.0

    @property
    def minimum_evaluation_observations(self) -> int:
        return minimum_evaluation_observations(self.evaluation_window_days)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": RESEARCH_INPUTS_VERSION,
            "rebalanceFrequency": self.rebalance_frequency,
            "evaluationWindowDays": self.evaluation_window_days,
            "topN": self.top_n,
            "maxWeight": self.max_weight,
            "transactionCostBps": self.transaction_cost_bps,
            "slippageBps": self.slippage_bps,
            "minHistoryDays": self.min_history_days,
            "minPrice": self.min_price,
            "minAvgDollarVolume": self.min_avg_dollar_volume,
            "minAvgVolume": self.min_avg_volume,
            "liquidityLookbackDays": self.liquidity_lookback_days,
            "minLiquidityObservations": self.min_liquidity_observations,
            "maxPriceMissingRatio": self.max_price_missing_ratio,
            "maxVolumeMissingRatio": self.max_volume_missing_ratio,
            "maxExtremeDailyReturn": self.max_extreme_daily_return,
            "selectionMinSharpe": self.selection_min_sharpe,
            "selectionMaxDrawdown": self.selection_max_drawdown,
            "selectionMaxAnnualizedCostDrag": self.selection_max_annualized_cost_drag,
            "selectionMinEffectiveNames": self.selection_min_effective_names,
            "selectionMaxTargetHhi": self.selection_max_target_hhi,
            "selectionMaxTargetWeight": self.selection_max_target_weight,
            "selectionMaxAbsSecurityDayContribution": (
                self.selection_max_abs_security_day_contribution
            ),
            "selectionMaxSecurityAbsoluteContributionShare": (
                self.selection_max_security_absolute_contribution_share
            ),
            "selectionMaxLeaveOneSecurityCagrDelta": (
                self.selection_max_leave_one_security_cagr_delta
            ),
            "selectionExtremeEventAction": self.selection_extreme_event_action,
            "selectionExtremeEventPenaltyPoints": self.selection_extreme_event_penalty_points,
        }

    @property
    def state_key(self) -> str:
        return canonical_sha256(self.to_dict())

    def apply(self, base: RunConfig) -> RunConfig:
        configured = replace(
            base,
            rebalance_frequency=self.rebalance_frequency,
            evaluation_window_days=self.evaluation_window_days,
            min_evaluation_observations=self.minimum_evaluation_observations,
            min_daily_risk_observations=self.minimum_evaluation_observations,
            top_n=self.top_n,
            max_weight=self.max_weight,
            transaction_cost_bps=self.transaction_cost_bps,
            slippage_bps=self.slippage_bps,
            min_history_days=self.min_history_days,
            min_price=self.min_price,
            min_avg_dollar_volume=self.min_avg_dollar_volume,
            min_avg_volume=self.min_avg_volume,
            liquidity_lookback_days=self.liquidity_lookback_days,
            min_liquidity_observations=self.min_liquidity_observations,
            max_price_missing_ratio=self.max_price_missing_ratio,
            max_volume_missing_ratio=self.max_volume_missing_ratio,
            max_extreme_daily_return=self.max_extreme_daily_return,
            selection_min_sharpe=self.selection_min_sharpe,
            selection_max_drawdown=self.selection_max_drawdown,
            selection_max_annualized_cost_drag=self.selection_max_annualized_cost_drag,
            selection_min_effective_names=self.selection_min_effective_names,
            selection_max_target_hhi=self.selection_max_target_hhi,
            selection_max_target_weight=self.selection_max_target_weight,
            selection_max_abs_security_day_contribution=(
                self.selection_max_abs_security_day_contribution
            ),
            selection_max_security_absolute_contribution_share=(
                self.selection_max_security_absolute_contribution_share
            ),
            selection_max_leave_one_security_cagr_delta=(
                self.selection_max_leave_one_security_cagr_delta
            ),
            selection_extreme_event_action=self.selection_extreme_event_action,
            selection_extreme_event_penalty_points=self.selection_extreme_event_penalty_points,
        )
        configured.validate()
        return configured

    @classmethod
    def from_config(cls, config: RunConfig) -> ResearchInputs:
        return cls(
            rebalance_frequency=config.rebalance_frequency,
            evaluation_window_days=config.evaluation_window_days,
            top_n=config.top_n,
            max_weight=config.max_weight,
            transaction_cost_bps=config.transaction_cost_bps,
            slippage_bps=config.slippage_bps,
            min_history_days=config.min_history_days,
            min_price=config.min_price,
            min_avg_dollar_volume=config.min_avg_dollar_volume,
            min_avg_volume=config.min_avg_volume,
            liquidity_lookback_days=config.liquidity_lookback_days,
            min_liquidity_observations=config.min_liquidity_observations,
            max_price_missing_ratio=config.max_price_missing_ratio,
            max_volume_missing_ratio=config.max_volume_missing_ratio,
            max_extreme_daily_return=config.max_extreme_daily_return,
            selection_min_sharpe=config.selection_min_sharpe,
            selection_max_drawdown=config.selection_max_drawdown,
            selection_max_annualized_cost_drag=config.selection_max_annualized_cost_drag,
            selection_min_effective_names=config.selection_min_effective_names,
            selection_max_target_hhi=config.selection_max_target_hhi,
            selection_max_target_weight=config.selection_max_target_weight,
            selection_max_abs_security_day_contribution=(
                config.selection_max_abs_security_day_contribution
            ),
            selection_max_security_absolute_contribution_share=(
                config.selection_max_security_absolute_contribution_share
            ),
            selection_max_leave_one_security_cagr_delta=(
                config.selection_max_leave_one_security_cagr_delta
            ),
            selection_extreme_event_action=config.selection_extreme_event_action,
            selection_extreme_event_penalty_points=config.selection_extreme_event_penalty_points,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ResearchInputs:
        if not isinstance(value, Mapping):
            raise ResearchInputError("research inputs must be an object")
        version = value.get("version", RESEARCH_INPUTS_VERSION)
        if version not in {RESEARCH_INPUTS_VERSION, LEGACY_RESEARCH_INPUTS_VERSION}:
            raise ResearchInputError("unsupported research-input version")
        aliases = {
            "version": None,
            "rebalanceFrequency": "rebalance_frequency",
            "evaluationWindowDays": "evaluation_window_days",
            "topN": "top_n",
            "maxWeight": "max_weight",
            "transactionCostBps": "transaction_cost_bps",
            "slippageBps": "slippage_bps",
            "minHistoryDays": "min_history_days",
            "minPrice": "min_price",
            "minAvgDollarVolume": "min_avg_dollar_volume",
            "minAvgVolume": "min_avg_volume",
            "liquidityLookbackDays": "liquidity_lookback_days",
            "minLiquidityObservations": "min_liquidity_observations",
            "maxPriceMissingRatio": "max_price_missing_ratio",
            "maxVolumeMissingRatio": "max_volume_missing_ratio",
            "maxExtremeDailyReturn": "max_extreme_daily_return",
            "selectionMinSharpe": "selection_min_sharpe",
            "selectionMaxDrawdown": "selection_max_drawdown",
            "selectionMaxAnnualizedCostDrag": "selection_max_annualized_cost_drag",
            "selectionMinEffectiveNames": "selection_min_effective_names",
            "selectionMaxTargetHhi": "selection_max_target_hhi",
            "selectionMaxTargetWeight": "selection_max_target_weight",
            "selectionMaxAbsSecurityDayContribution": (
                "selection_max_abs_security_day_contribution"
            ),
            "selectionMaxSecurityAbsoluteContributionShare": (
                "selection_max_security_absolute_contribution_share"
            ),
            "selectionMaxLeaveOneSecurityCagrDelta": (
                "selection_max_leave_one_security_cagr_delta"
            ),
            "selectionExtremeEventAction": "selection_extreme_event_action",
            "selectionExtremeEventPenaltyPoints": "selection_extreme_event_penalty_points",
        }
        if version == LEGACY_RESEARCH_INPUTS_VERSION:
            aliases["evaluationYears"] = None
        unknown = sorted(set(value).difference(aliases))
        if unknown:
            raise ResearchInputError("unknown research inputs: " + ", ".join(unknown))
        kwargs = {
            target: value[source]
            for source, target in aliases.items()
            if target is not None and source in value
        }
        if version == LEGACY_RESEARCH_INPUTS_VERSION:
            evaluation_years = value.get("evaluationYears", 3)
            if not isinstance(evaluation_years, int) or isinstance(evaluation_years, bool):
                raise ResearchInputError("evaluationYears must be an integer")
            if not 1 <= evaluation_years <= 10:
                raise ResearchInputError("evaluationYears must be between 1 and 10")
            legacy_window_days = evaluation_years * TRADING_SESSIONS_PER_YEAR
            declared_window_days = value.get("evaluationWindowDays", legacy_window_days)
            if declared_window_days != legacy_window_days:
                raise ResearchInputError(
                    "legacy evaluationWindowDays must equal evaluationYears times 252"
                )
            kwargs["evaluation_window_days"] = legacy_window_days
        try:
            inputs = cls(**kwargs)
        except TypeError as exc:
            raise ResearchInputError(str(exc)) from exc
        inputs._validate()
        return inputs

    def _validate(self) -> None:
        numeric_fields = {
            "evaluationWindowDays": self.evaluation_window_days,
            "topN": self.top_n,
            "maxWeight": self.max_weight,
            "transactionCostBps": self.transaction_cost_bps,
            "slippageBps": self.slippage_bps,
            "minHistoryDays": self.min_history_days,
            "minPrice": self.min_price,
            "minAvgDollarVolume": self.min_avg_dollar_volume,
            "minAvgVolume": self.min_avg_volume,
            "liquidityLookbackDays": self.liquidity_lookback_days,
            "minLiquidityObservations": self.min_liquidity_observations,
            "maxPriceMissingRatio": self.max_price_missing_ratio,
            "maxVolumeMissingRatio": self.max_volume_missing_ratio,
            "maxExtremeDailyReturn": self.max_extreme_daily_return,
            "selectionMinSharpe": self.selection_min_sharpe,
            "selectionMaxDrawdown": self.selection_max_drawdown,
            "selectionMaxAnnualizedCostDrag": self.selection_max_annualized_cost_drag,
            "selectionMinEffectiveNames": self.selection_min_effective_names,
            "selectionMaxTargetHhi": self.selection_max_target_hhi,
            "selectionMaxTargetWeight": self.selection_max_target_weight,
            "selectionMaxAbsSecurityDayContribution": (
                self.selection_max_abs_security_day_contribution
            ),
            "selectionMaxSecurityAbsoluteContributionShare": (
                self.selection_max_security_absolute_contribution_share
            ),
            "selectionMaxLeaveOneSecurityCagrDelta": (
                self.selection_max_leave_one_security_cagr_delta
            ),
            "selectionExtremeEventPenaltyPoints": self.selection_extreme_event_penalty_points,
        }
        for field, number in numeric_fields.items():
            if (
                isinstance(number, bool)
                or not isinstance(number, int | float)
                or not isfinite(number)
            ):
                raise ResearchInputError(f"{field} must be a finite number")
        if self.rebalance_frequency not in {"W", "ME", "QE"}:
            raise ResearchInputError("rebalanceFrequency must be W, ME, or QE")
        if (
            not isinstance(self.evaluation_window_days, int)
            or isinstance(self.evaluation_window_days, bool)
        ):
            raise ResearchInputError("evaluationWindowDays must be an integer")
        if not (
            MIN_EVALUATION_WINDOW_DAYS <= self.evaluation_window_days <= MAX_EVALUATION_WINDOW_DAYS
        ):
            raise ResearchInputError("evaluationWindowDays must be between 21 and 2520")
        if (
            not isinstance(self.top_n, int)
            or isinstance(self.top_n, bool)
            or not 1 <= self.top_n <= MAX_TOP_N
        ):
            raise ResearchInputError(f"topN must be an integer between 1 and {MAX_TOP_N}")
        for field, number in {
            "minHistoryDays": self.min_history_days,
            "liquidityLookbackDays": self.liquidity_lookback_days,
            "minLiquidityObservations": self.min_liquidity_observations,
        }.items():
            if not isinstance(number, int) or isinstance(number, bool):
                raise ResearchInputError(f"{field} must be an integer")
        if not 0.0 < float(self.max_weight) <= 1.0:
            raise ResearchInputError("maxWeight must be in (0, 1]")
        nonnegative = {
            "transactionCostBps": self.transaction_cost_bps,
            "slippageBps": self.slippage_bps,
            "minPrice": self.min_price,
            "minAvgDollarVolume": self.min_avg_dollar_volume,
            "minAvgVolume": self.min_avg_volume,
        }
        if any(float(number) < 0.0 for number in nonnegative.values()):
            raise ResearchInputError("cost, price, and liquidity inputs must be non-negative")
        if self.min_history_days < 21:
            raise ResearchInputError("minHistoryDays must be at least 21")
        if self.liquidity_lookback_days < 1:
            raise ResearchInputError("liquidityLookbackDays must be positive")
        if not 1 <= self.min_liquidity_observations <= self.liquidity_lookback_days:
            raise ResearchInputError("minLiquidityObservations must fit liquidityLookbackDays")
        for field, number in {
            "maxPriceMissingRatio": self.max_price_missing_ratio,
            "maxVolumeMissingRatio": self.max_volume_missing_ratio,
        }.items():
            if not 0.0 <= float(number) < 1.0:
                raise ResearchInputError(f"{field} must be in [0, 1)")
        if not 0.0 < float(self.max_extreme_daily_return):
            raise ResearchInputError("maxExtremeDailyReturn must be positive")
        if float(self.selection_min_sharpe) < -10.0:
            raise ResearchInputError("selectionMinSharpe must be at least -10")
        if not 0.0 < float(self.selection_max_drawdown) <= 1.0:
            raise ResearchInputError("selectionMaxDrawdown must be in (0, 1]")
        if float(self.selection_max_annualized_cost_drag) < 0.0:
            raise ResearchInputError("selectionMaxAnnualizedCostDrag must be non-negative")
        if not 0.0 < float(self.selection_min_effective_names) <= self.top_n:
            raise ResearchInputError("selectionMinEffectiveNames must be in (0, topN]")
        for field, number in {
            "selectionMaxTargetHhi": self.selection_max_target_hhi,
            "selectionMaxTargetWeight": self.selection_max_target_weight,
        }.items():
            if not 0.0 < float(number) <= 1.0:
                raise ResearchInputError(f"{field} must be in (0, 1]")
        for field, number in {
            "selectionMaxAbsSecurityDayContribution": (
                self.selection_max_abs_security_day_contribution
            ),
            "selectionMaxLeaveOneSecurityCagrDelta": (
                self.selection_max_leave_one_security_cagr_delta
            ),
            "selectionExtremeEventPenaltyPoints": self.selection_extreme_event_penalty_points,
        }.items():
            if float(number) < 0.0:
                raise ResearchInputError(f"{field} must be non-negative")
        if not 0.0 <= float(self.selection_max_security_absolute_contribution_share) <= 1.0:
            raise ResearchInputError(
                "selectionMaxSecurityAbsoluteContributionShare must be in [0, 1]"
            )
        if self.selection_extreme_event_action not in {"warn", "penalize", "exclude"}:
            raise ResearchInputError(
                "selectionExtremeEventAction must be warn, penalize, or exclude"
            )
