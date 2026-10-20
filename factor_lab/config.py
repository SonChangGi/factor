from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from .universe import DEFAULT_UNIVERSE, is_supported_symbol, normalize_symbol


FIXED_WEIGHTING_POLICY = "score_liquidity_rank"
WEIGHTING_POLICIES = (FIXED_WEIGHTING_POLICY,)
MAX_TOP_N = 50
MIN_EVALUATION_WINDOW_DAYS = 21
MAX_EVALUATION_WINDOW_DAYS = 2_520


def minimum_evaluation_observations(evaluation_window_days: int) -> int:
    """Return the comparison-coverage floor for an evaluation window."""

    return min(
        evaluation_window_days,
        max(252, evaluation_window_days - 252),
    )


POLICY_REGISTRY_VERSION = "weighting-policy-registry-v3"
POLICY_REGISTRY = {
    FIXED_WEIGHTING_POLICY: {
        "version": "1",
        "implementationId": "score_liquidity_rank_v1",
        "label": "팩터·유동성 고정 혼합",
        "description": (
            "팩터 점수 70%와 후행 거래대금 30%의 백분위 순위를 결합하고 종목별 최대 비중을 적용"
        ),
        "formula": ("floor+0.70*factor_score_pct+0.30*lagged_raw_dollar_volume_pct"),
        "requiredSignalDateInputs": [
            "factor_score",
            "eligible_adjusted_close",
            "trailing_raw_close_times_raw_volume",
        ],
        "selectionRole": "fixed_methodology_not_optimized",
    },
}

POLICY_VERSIONS = {
    policy: str(definition["version"]) for policy, definition in POLICY_REGISTRY.items()
}

FACTOR_SELECTION_VERSION = "fixed-policy-factor-selection-v1"
ABSOLUTE_GUARDRAIL_VERSION = "absolute-factor-v2"
ANALYSIS_CACHE_VERSION = "analysis-cache-v2"


@dataclass(slots=True)
class RunConfig:
    """Configuration for one reproducible factor-and-policy research run.

    Exactly one data source is selected: live public market data, a reviewed
    local adjusted-price file, or the deterministic synthetic demo.  The
    market-data as-of date always comes from the last observed price row.
    """

    start_date: str = "2016-01-01"
    end_date: str | None = None
    live: bool = False
    prices_path: Path | None = None
    volumes_path: Path | None = None
    market_caps_path: Path | None = None
    volume_basis: str | None = None
    demo: bool = False
    demo_symbol_count: int = 200
    demo_seed: int = 42
    demo_missing_ratio: float = 0.0

    benchmark: str = "SPY"
    chart_benchmark: str = "^IXIC"
    additional_comparison_benchmarks: tuple[str, ...] = ("QQQ",)
    rebalance_frequency: str = "ME"
    top_n: int = 20
    max_weight: float = 0.10
    transaction_cost_bps: float = 5.0
    slippage_bps: float = 5.0
    annual_cash_return: float = 0.0

    min_history_days: int = 252
    min_price: float = 5.0
    min_avg_dollar_volume: float = 0.0
    min_avg_volume: float = 0.0
    liquidity_lookback_days: int = 63
    min_liquidity_observations: int = 42
    max_price_missing_ratio: float = 0.05
    stale_after_days: int = 7
    data_quality_lookback_days: int = 252
    max_volume_missing_ratio: float = 0.10
    max_extreme_daily_return: float = 0.80

    evaluation_window_days: int = 756
    min_evaluation_observations: int = 504
    min_valuation_coverage: float = 0.98
    min_daily_risk_observations: int = 504
    stability_periods: int = 3
    score_sortino_weight: float = 0.25
    score_calmar_weight: float = 0.20
    score_max_drawdown_weight: float = 0.20
    score_cagr_weight: float = 0.15
    score_sharpe_weight: float = 0.10
    score_stability_weight: float = 0.10
    score_winsor_lower: float = 0.05
    score_winsor_upper: float = 0.95

    weighting_policies: tuple[str, ...] = WEIGHTING_POLICIES
    allocation_score_weight: float = 0.70
    allocation_liquidity_weight: float = 0.30
    allocation_market_cap_weight: float = 0.0
    allocation_rank_floor: float = 0.05
    market_cap_max_age_days: int = 550
    market_cap_min_universe_coverage: float = 0.75

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

    output_dir: Path = Path("outputs/sample")
    site_dir: Path = Path("docs")
    cache_dir: Path = Path(".cache/factor_lab")
    export_input_snapshot: bool = False
    market_cache_max_age_hours: float = 24.0
    refresh_market_data: bool = False
    require_current_session: bool = False

    max_price_symbols: int | None = None
    price_chunk_size: int = 25
    yahoo_chart_fallback_limit: int | None = 250
    nasdaq_fallback_limit: int | None = 250
    stooq_fallback_limit: int | None = 0
    finance_datareader_fallback_limit: int | None = 0
    retry_count: int = 2
    retry_backoff_seconds: float = 0.5
    sec_user_agent: str | None = None
    universe_source_mode: str = "packaged"
    universe_profile: str = "large_liquid"
    universe: list[str] = field(default_factory=lambda: list(DEFAULT_UNIVERSE))
    # Keep one request date across collection, analysis, and preset copies.
    # This is an init field so dataclasses.replace preserves the same run date.
    _resolved_end_date: str = field(
        default_factory=lambda: datetime.now(UTC).date().isoformat(),
        repr=False,
        compare=False,
        kw_only=True,
    )

    def __post_init__(self) -> None:
        self.benchmark = normalize_symbol(self.benchmark)
        self.chart_benchmark = normalize_symbol(self.chart_benchmark)
        raw_additional = self.additional_comparison_benchmarks
        if isinstance(raw_additional, str):
            raw_additional = tuple(raw_additional.replace("\n", ",").split(","))
        seen = {self.benchmark, self.chart_benchmark}
        normalized: list[str] = []
        for value in raw_additional:
            symbol = normalize_symbol(value)
            if symbol and symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        self.additional_comparison_benchmarks = tuple(normalized)

    @property
    def total_cost_bps(self) -> float:
        return self.transaction_cost_bps + self.slippage_bps

    @property
    def comparison_benchmarks(self) -> tuple[str, ...]:
        """Ordered adjusted-price comparators, distinct from stock candidates."""

        return tuple(
            dict.fromkeys(
                (
                    self.benchmark,
                    self.chart_benchmark,
                    *self.additional_comparison_benchmarks,
                )
            )
        )

    @property
    def total_cost_rate(self) -> float:
        return self.total_cost_bps / 10_000.0

    @property
    def score_weights(self) -> dict[str, float]:
        return {
            "sortino": self.score_sortino_weight,
            "calmar": self.score_calmar_weight,
            "max_drawdown": self.score_max_drawdown_weight,
            "cagr": self.score_cagr_weight,
            "sharpe": self.score_sharpe_weight,
            "stability": self.score_stability_weight,
        }

    @property
    def policy_versions(self) -> dict[str, str]:
        return {policy: POLICY_VERSIONS[policy] for policy in self.weighting_policies}

    @property
    def factor_selection_version(self) -> str:
        """Version of the fixed-policy factor-selection procedure."""

        return FACTOR_SELECTION_VERSION

    @property
    def absolute_guardrail_version(self) -> str:
        return ABSOLUTE_GUARDRAIL_VERSION

    @property
    def analysis_cache_version(self) -> str:
        return ANALYSIS_CACHE_VERSION

    @property
    def data_mode(self) -> str:
        if self.live:
            return "live_market"
        return "demo" if self.demo else "local_file"

    @property
    def effective_end_date(self) -> str:
        return self.end_date or self._resolved_end_date

    def for_new_run(self) -> RunConfig:
        """Resolve a fresh request date without changing an ongoing run's config."""

        return replace(self, _resolved_end_date=datetime.now(UTC).date().isoformat())

    @property
    def discovery_min_avg_dollar_volume(self) -> float:
        if self.universe_profile == "aggressive_stock_only":
            return min(self.min_avg_dollar_volume, 1_000_000.0)
        return self.min_avg_dollar_volume

    def validate(self) -> None:
        sources = int(self.live) + int(self.demo) + int(self.prices_path is not None)
        if sources != 1:
            raise ValueError("choose exactly one data source: --live, --demo, or --prices")
        if not is_supported_symbol(self.benchmark):
            raise ValueError("benchmark must be a supported security symbol")
        if not _is_supported_comparison_symbol(self.chart_benchmark):
            raise ValueError("chart_benchmark must be a supported security or index symbol")
        if any(
            not _is_supported_comparison_symbol(symbol)
            for symbol in self.additional_comparison_benchmarks
        ):
            raise ValueError(
                "additional_comparison_benchmarks must contain supported security or index symbols"
            )
        if self.volumes_path is not None and self.prices_path is None:
            raise ValueError("--volumes requires --prices")
        if self.market_caps_path is not None and self.prices_path is None:
            raise ValueError("--market-caps requires --prices")
        if self.volumes_path is not None and self.volume_basis != "split_adjusted":
            raise ValueError("--volumes requires --volume-basis split_adjusted")
        if self.volumes_path is None and self.volume_basis is not None:
            raise ValueError("volume_basis requires a volume file")
        if self.live and (
            self.volumes_path is not None
            or self.market_caps_path is not None
            or self.volume_basis is not None
        ):
            raise ValueError("live acquisition owns its price, volume, and market-cap inputs")

        numeric_values = {
            "demo_symbol_count": self.demo_symbol_count,
            "demo_seed": self.demo_seed,
            "demo_missing_ratio": self.demo_missing_ratio,
            "top_n": self.top_n,
            "max_weight": self.max_weight,
            "transaction_cost_bps": self.transaction_cost_bps,
            "slippage_bps": self.slippage_bps,
            "annual_cash_return": self.annual_cash_return,
            "min_history_days": self.min_history_days,
            "min_price": self.min_price,
            "min_avg_dollar_volume": self.min_avg_dollar_volume,
            "min_avg_volume": self.min_avg_volume,
            "liquidity_lookback_days": self.liquidity_lookback_days,
            "min_liquidity_observations": self.min_liquidity_observations,
            "max_price_missing_ratio": self.max_price_missing_ratio,
            "stale_after_days": self.stale_after_days,
            "data_quality_lookback_days": self.data_quality_lookback_days,
            "max_volume_missing_ratio": self.max_volume_missing_ratio,
            "max_extreme_daily_return": self.max_extreme_daily_return,
            "evaluation_window_days": self.evaluation_window_days,
            "min_evaluation_observations": self.min_evaluation_observations,
            "min_valuation_coverage": self.min_valuation_coverage,
            "min_daily_risk_observations": self.min_daily_risk_observations,
            "stability_periods": self.stability_periods,
            "score_winsor_lower": self.score_winsor_lower,
            "score_winsor_upper": self.score_winsor_upper,
            "allocation_score_weight": self.allocation_score_weight,
            "allocation_liquidity_weight": self.allocation_liquidity_weight,
            "allocation_market_cap_weight": self.allocation_market_cap_weight,
            "allocation_rank_floor": self.allocation_rank_floor,
            "market_cap_max_age_days": self.market_cap_max_age_days,
            "market_cap_min_universe_coverage": self.market_cap_min_universe_coverage,
            "selection_min_sharpe": self.selection_min_sharpe,
            "selection_max_drawdown": self.selection_max_drawdown,
            "selection_max_annualized_cost_drag": self.selection_max_annualized_cost_drag,
            "selection_min_effective_names": self.selection_min_effective_names,
            "selection_max_target_hhi": self.selection_max_target_hhi,
            "selection_max_target_weight": self.selection_max_target_weight,
            "selection_max_abs_security_day_contribution": (
                self.selection_max_abs_security_day_contribution
            ),
            "selection_max_security_absolute_contribution_share": (
                self.selection_max_security_absolute_contribution_share
            ),
            "selection_max_leave_one_security_cagr_delta": (
                self.selection_max_leave_one_security_cagr_delta
            ),
            "selection_extreme_event_penalty_points": (self.selection_extreme_event_penalty_points),
            "market_cache_max_age_hours": self.market_cache_max_age_hours,
            **{f"score_{name}_weight": value for name, value in self.score_weights.items()},
        }
        invalid = [name for name, value in numeric_values.items() if not isfinite(float(value))]
        if invalid:
            raise ValueError("configuration values must be finite: " + ", ".join(sorted(invalid)))
        if self.demo_symbol_count < 50:
            raise ValueError("demo_symbol_count must be at least 50")
        if self.demo_seed < 0:
            raise ValueError("demo_seed must be non-negative")
        if not 0.0 <= self.demo_missing_ratio < 1.0:
            raise ValueError("demo_missing_ratio must be in [0, 1)")
        if 0.0 < self.demo_missing_ratio < 0.001:
            raise ValueError("positive demo_missing_ratio must be at least 0.001")
        if not self.demo and self.demo_missing_ratio != 0.0:
            raise ValueError("demo_missing_ratio requires --demo")
        if (
            not isinstance(self.top_n, int)
            or isinstance(self.top_n, bool)
            or not 1 <= self.top_n <= MAX_TOP_N
        ):
            raise ValueError(f"top_n must be between 1 and {MAX_TOP_N}")
        if not 0.0 < self.max_weight <= 1.0:
            raise ValueError("max_weight must be in (0, 1]")
        if self.transaction_cost_bps < 0 or self.slippage_bps < 0:
            raise ValueError("transaction and slippage costs must be non-negative")
        if self.annual_cash_return <= -1.0:
            raise ValueError("annual_cash_return must be greater than -1")
        if self.min_history_days < 21:
            raise ValueError("min_history_days must be at least 21")
        if self.min_price < 0 or self.min_avg_dollar_volume < 0 or self.min_avg_volume < 0:
            raise ValueError("price and liquidity thresholds must be non-negative")
        if self.liquidity_lookback_days < 1:
            raise ValueError("liquidity_lookback_days must be at least 1")
        if not 1 <= self.min_liquidity_observations <= self.liquidity_lookback_days:
            raise ValueError("min_liquidity_observations must fit the liquidity lookback")
        if not 0.0 <= self.max_price_missing_ratio < 1.0:
            raise ValueError("max_price_missing_ratio must be in [0, 1)")
        if self.rebalance_frequency not in {"W", "ME", "QE"}:
            raise ValueError("rebalance_frequency must be W, ME, or QE")
        if not (
            MIN_EVALUATION_WINDOW_DAYS <= self.evaluation_window_days <= MAX_EVALUATION_WINDOW_DAYS
        ):
            raise ValueError(
                "evaluation_window_days must be between "
                f"{MIN_EVALUATION_WINDOW_DAYS} and {MAX_EVALUATION_WINDOW_DAYS}"
            )
        minimum_required_observations = min(252, self.evaluation_window_days)
        if not (
            minimum_required_observations
            <= self.min_evaluation_observations
            <= self.evaluation_window_days
        ):
            raise ValueError("min_evaluation_observations must fit the evaluation window")
        if not 0.0 < self.min_valuation_coverage <= 1.0:
            raise ValueError("min_valuation_coverage must be in (0, 1]")
        if not 2 <= self.min_daily_risk_observations <= self.evaluation_window_days:
            raise ValueError("min_daily_risk_observations must fit the evaluation window")
        if self.stability_periods < 2:
            raise ValueError("stability_periods must be at least 2")
        if not 0.0 <= self.score_winsor_lower < self.score_winsor_upper <= 1.0:
            raise ValueError("score winsor bounds must satisfy 0 <= lower < upper <= 1")
        if any(weight < 0.0 for weight in self.score_weights.values()):
            raise ValueError("composite score weights must be non-negative")
        if not isclose(sum(self.score_weights.values()), 1.0, abs_tol=1e-12):
            raise ValueError("composite score weights must sum to 1")
        if tuple(self.weighting_policies) != WEIGHTING_POLICIES:
            raise ValueError("the fixed weighting policy must run exactly once")
        component_weights = (
            self.allocation_score_weight,
            self.allocation_liquidity_weight,
            self.allocation_market_cap_weight,
        )
        if any(value < 0.0 for value in component_weights) or not isclose(
            sum(component_weights), 1.0, abs_tol=1e-12
        ):
            raise ValueError("allocation component weights must be non-negative and sum to 1")
        if component_weights != (0.70, 0.30, 0.0):
            raise ValueError("allocation component weights are fixed at 0.70/0.30/0.00")
        if self.allocation_rank_floor != 0.05:
            raise ValueError("allocation_rank_floor is fixed at 0.05")
        if self.market_cap_max_age_days != 550:
            raise ValueError("market_cap_max_age_days is fixed at 550")
        if not 0.0 < self.market_cap_min_universe_coverage <= 1.0:
            raise ValueError("market_cap_min_universe_coverage must be in (0, 1]")
        if self.selection_min_effective_names <= 0.0:
            raise ValueError("selection_min_effective_names must be positive")
        if self.selection_min_effective_names > self.top_n:
            raise ValueError("selection_min_effective_names cannot exceed top_n")
        if self.selection_min_sharpe < -10.0:
            raise ValueError("selection_min_sharpe must be at least -10")
        for name, value in {
            "selection_max_drawdown": self.selection_max_drawdown,
            "selection_max_annualized_cost_drag": self.selection_max_annualized_cost_drag,
            "selection_max_target_hhi": self.selection_max_target_hhi,
            "selection_max_target_weight": self.selection_max_target_weight,
            "selection_max_abs_security_day_contribution": (
                self.selection_max_abs_security_day_contribution
            ),
            "selection_max_security_absolute_contribution_share": (
                self.selection_max_security_absolute_contribution_share
            ),
            "selection_max_leave_one_security_cagr_delta": (
                self.selection_max_leave_one_security_cagr_delta
            ),
            "selection_extreme_event_penalty_points": (self.selection_extreme_event_penalty_points),
        }.items():
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if not 0.0 < self.selection_max_drawdown <= 1.0:
            raise ValueError("selection_max_drawdown must be in (0, 1]")
        if not 0.0 < self.selection_max_target_hhi <= 1.0:
            raise ValueError("selection_max_target_hhi must be in (0, 1]")
        if not 0.0 < self.selection_max_target_weight <= 1.0:
            raise ValueError("selection_max_target_weight must be in (0, 1]")
        if not 0.0 <= self.selection_max_security_absolute_contribution_share <= 1.0:
            raise ValueError("selection_max_security_absolute_contribution_share must be in [0, 1]")
        if self.selection_extreme_event_action not in {"warn", "penalize", "exclude"}:
            raise ValueError("selection_extreme_event_action must be warn, penalize, or exclude")
        if self.market_cache_max_age_hours <= 0.0:
            raise ValueError("market_cache_max_age_hours must be positive")
        if self.max_price_symbols is not None and self.max_price_symbols < 1:
            raise ValueError("max_price_symbols must be at least 1")
        if self.price_chunk_size < 1:
            raise ValueError("price_chunk_size must be at least 1")
        for name, value in {
            "yahoo_chart_fallback_limit": self.yahoo_chart_fallback_limit,
            "nasdaq_fallback_limit": self.nasdaq_fallback_limit,
            "stooq_fallback_limit": self.stooq_fallback_limit,
            "finance_datareader_fallback_limit": self.finance_datareader_fallback_limit,
        }.items():
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.retry_count < 0 or self.retry_backoff_seconds < 0:
            raise ValueError("retry settings must be non-negative")
        if self.universe_source_mode not in {"packaged", "refresh"}:
            raise ValueError("universe_source_mode must be packaged or refresh")
        if self.universe_profile not in {
            "large_liquid",
            "extended_current",
            "aggressive_stock_only",
        }:
            raise ValueError("unsupported universe_profile")
        try:
            start = datetime.fromisoformat(self.start_date).date()
            end = datetime.fromisoformat(self.effective_end_date).date()
        except ValueError as exc:
            raise ValueError("start_date and end_date must be ISO dates") from exc
        if start > end:
            raise ValueError("start_date must be on or before end_date")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("_resolved_end_date")
        for key in (
            "prices_path",
            "volumes_path",
            "market_caps_path",
            "output_dir",
            "site_dir",
            "cache_dir",
        ):
            value = data.get(key)
            data[key] = str(value) if value is not None else None
        data["data_mode"] = self.data_mode
        data["total_cost_bps"] = self.total_cost_bps
        data["effective_end_date"] = self.effective_end_date
        data["candidate_universe_size"] = len(self.universe)
        data["comparison_benchmarks"] = list(self.comparison_benchmarks)
        data["policy_versions"] = self.policy_versions
        data["factor_selection_version"] = self.factor_selection_version
        data["absolute_guardrail_version"] = self.absolute_guardrail_version
        data["analysis_cache_version"] = self.analysis_cache_version
        return data


def _is_supported_comparison_symbol(symbol: str) -> bool:
    normalized = normalize_symbol(symbol)
    return is_supported_symbol(normalized) or (
        normalized.startswith("^") and is_supported_symbol(normalized[1:])
    )
