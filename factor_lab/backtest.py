from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import RunConfig
from .portfolio import TargetAllocation, construct_target_allocation


ATTRIBUTION_METHOD = "frozen_realized_share_sleeve_contribution"
ATTRIBUTION_VERSION = "1"
ATTRIBUTION_RESIDUAL_TOLERANCE = 1e-10


@dataclass(frozen=True, slots=True)
class ContributionEvent:
    symbol: str
    interval_start: pd.Timestamp | None
    date: pd.Timestamp
    return_interval_sessions: int
    contribution: float
    start_weight: float
    security_return: float
    portfolio_return: float

    @property
    def absolute_contribution(self) -> float:
        return abs(self.contribution)

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "intervalStart": (
                self.interval_start.date().isoformat() if self.interval_start is not None else None
            ),
            "date": self.date.date().isoformat(),
            "returnIntervalSessions": self.return_interval_sessions,
            "contribution": self.contribution,
            "absoluteContribution": self.absolute_contribution,
            "startWeight": self.start_weight,
            "securityReturn": self.security_return,
            "portfolioReturn": self.portfolio_return,
        }


@dataclass(frozen=True, slots=True)
class SecurityContributionSummary:
    symbol: str
    signed_contribution: float
    absolute_contribution: float
    absolute_contribution_share: float

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "signedContribution": self.signed_contribution,
            "absoluteContribution": self.absolute_contribution,
            "absoluteContributionShare": self.absolute_contribution_share,
        }


@dataclass(frozen=True, slots=True)
class LeaveOneSecuritySensitivity:
    symbol: str
    base_cagr: float
    leave_one_cagr: float
    cagr_delta: float
    absolute_cagr_delta: float

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "method": "frozen_realized_contribution_deletion",
            "baseCagr": self.base_cagr,
            "leaveOneCagr": self.leave_one_cagr,
            "cagrDelta": self.cagr_delta,
            "absoluteCagrDelta": self.absolute_cagr_delta,
            "reoptimized": False,
        }


@dataclass(frozen=True, slots=True)
class ContributionDiagnostics:
    attribution_method: str
    attribution_version: str
    complete: bool
    reason: str | None
    evaluation_start: pd.Timestamp | None
    evaluation_end: pd.Timestamp | None
    active_calendar_observations: int
    observed_return_count: int
    max_exact_single_session_security_contribution: ContributionEvent | None
    max_observed_interval_security_contribution: ContributionEvent | None
    largest_absolute_contribution_security: SecurityContributionSummary | None
    total_absolute_security_contribution: float
    absolute_contribution_hhi: float
    max_leave_one_security: LeaveOneSecuritySensitivity | None
    top_leave_one_security: tuple[LeaveOneSecuritySensitivity, ...]
    attribution_max_residual: float

    @property
    def max_abs_security_day_contribution(self) -> float:
        event = self.max_exact_single_session_security_contribution
        return event.absolute_contribution if event is not None else 0.0

    @property
    def max_security_absolute_contribution_share(self) -> float:
        summary = self.largest_absolute_contribution_security
        return summary.absolute_contribution_share if summary is not None else 0.0

    @property
    def max_leave_one_security_cagr_delta(self) -> float:
        sensitivity = self.max_leave_one_security
        return sensitivity.absolute_cagr_delta if sensitivity is not None else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "attributionMethod": self.attribution_method,
            "attributionVersion": self.attribution_version,
            "complete": self.complete,
            "reason": self.reason,
            "evaluationStart": (
                self.evaluation_start.date().isoformat()
                if self.evaluation_start is not None
                else None
            ),
            "evaluationEnd": (
                self.evaluation_end.date().isoformat() if self.evaluation_end is not None else None
            ),
            "activeCalendarObservations": self.active_calendar_observations,
            "observedReturnCount": self.observed_return_count,
            "maxAbsSecurityDayContribution": self.max_abs_security_day_contribution,
            "maxExactSingleSessionSecurityContribution": (
                self.max_exact_single_session_security_contribution.to_dict()
                if self.max_exact_single_session_security_contribution is not None
                else None
            ),
            "maxObservedIntervalSecurityContribution": (
                self.max_observed_interval_security_contribution.to_dict()
                if self.max_observed_interval_security_contribution is not None
                else None
            ),
            "largestAbsoluteContributionSecurity": (
                self.largest_absolute_contribution_security.to_dict()
                if self.largest_absolute_contribution_security is not None
                else None
            ),
            "maxSecurityAbsoluteContributionShare": (self.max_security_absolute_contribution_share),
            "totalAbsoluteSecurityContribution": self.total_absolute_security_contribution,
            "absoluteContributionHhi": self.absolute_contribution_hhi,
            "maxLeaveOneSecurityCagrDelta": self.max_leave_one_security_cagr_delta,
            "maxLeaveOneSecurity": (
                self.max_leave_one_security.to_dict()
                if self.max_leave_one_security is not None
                else None
            ),
            "topLeaveOneSecurity": [row.to_dict() for row in self.top_leave_one_security],
            "attributionMaxResidual": self.attribution_max_residual,
            "observedReturnsPreserved": True,
            "reoptimized": False,
        }


def _event_order_key(event: ContributionEvent) -> tuple[float, int, str]:
    """Prefer larger absolute events, then the earlier date and symbol."""

    return (-event.absolute_contribution, int(event.date.value), event.symbol)


@dataclass(slots=True)
class _ContributionAccumulator:
    columns: pd.Index
    evaluation_start: pd.Timestamp | None
    evaluation_end: pd.Timestamp | None
    signed_by_security: np.ndarray
    absolute_by_security: np.ndarray
    leave_one_log_ratio: np.ndarray
    leave_one_valid: np.ndarray
    observed_return_count: int = 0
    total_absolute_security_contribution: float = 0.0
    attribution_max_residual: float = 0.0
    max_exact_single_session_event: ContributionEvent | None = None
    max_observed_interval_event: ContributionEvent | None = None

    @classmethod
    def create(
        cls,
        columns: pd.Index,
        evaluation_start: pd.Timestamp | None,
        evaluation_end: pd.Timestamp | None,
    ) -> _ContributionAccumulator:
        size = len(columns)
        return cls(
            columns=columns,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
            signed_by_security=np.zeros(size, dtype=float),
            absolute_by_security=np.zeros(size, dtype=float),
            leave_one_log_ratio=np.zeros(size, dtype=float),
            leave_one_valid=np.ones(size, dtype=bool),
        )

    def observe(
        self,
        *,
        date: pd.Timestamp,
        interval_start: pd.Timestamp | None,
        return_interval_sessions: int,
        portfolio_return: float,
        held_positions: np.ndarray,
        security_contributions: np.ndarray,
        start_weights: np.ndarray,
        security_returns: np.ndarray,
        cash_contribution: float,
        cost_contribution: float,
    ) -> None:
        contribution_sum = float(security_contributions.sum())
        residual = float(
            portfolio_return - contribution_sum - cash_contribution - cost_contribution
        )
        self.attribution_max_residual = max(self.attribution_max_residual, abs(residual))
        self.observed_return_count += 1

        if held_positions.size == 0:
            return
        absolute = np.abs(security_contributions)
        self.signed_by_security[held_positions] += security_contributions
        self.absolute_by_security[held_positions] += absolute
        self.total_absolute_security_contribution += float(absolute.sum())

        base_growth_factor = 1.0 + portfolio_return
        without_growth_factors = base_growth_factor - security_contributions
        valid = (
            np.isfinite(without_growth_factors)
            & np.isfinite(base_growth_factor)
            & (without_growth_factors > 0.0)
            & (base_growth_factor > 0.0)
        )
        invalid_positions = held_positions[~valid]
        if invalid_positions.size:
            self.leave_one_valid[invalid_positions] = False
        if bool(valid.any()):
            valid_positions = held_positions[valid]
            self.leave_one_log_ratio[valid_positions] += np.log(
                without_growth_factors[valid] / base_growth_factor
            )

        for local_position in np.flatnonzero(absolute > 0.0):
            security_position = int(held_positions[local_position])
            event = ContributionEvent(
                symbol=str(self.columns[security_position]),
                interval_start=interval_start,
                date=date,
                return_interval_sessions=return_interval_sessions,
                contribution=float(security_contributions[local_position]),
                start_weight=float(start_weights[local_position]),
                security_return=float(security_returns[local_position]),
                portfolio_return=portfolio_return,
            )
            if self.max_observed_interval_event is None or _event_order_key(
                event
            ) < _event_order_key(self.max_observed_interval_event):
                self.max_observed_interval_event = event
            if return_interval_sessions == 1 and (
                self.max_exact_single_session_event is None
                or _event_order_key(event) < _event_order_key(self.max_exact_single_session_event)
            ):
                self.max_exact_single_session_event = event

    def finalize(
        self,
        returns: pd.Series,
        strategy_active: pd.Series,
    ) -> ContributionDiagnostics:
        window_returns = (
            returns.loc[self.evaluation_start : self.evaluation_end]
            if self.evaluation_start is not None and self.evaluation_end is not None
            else returns.iloc[0:0]
        )
        window_active = strategy_active.reindex(window_returns.index).fillna(False).astype(bool)
        active_positions = np.flatnonzero(window_active.to_numpy())
        active = (
            window_returns.iloc[int(active_positions[0]) :]
            if active_positions.size
            else window_returns.iloc[0:0]
        )
        active_calendar_observations = len(active)
        observed = pd.to_numeric(active, errors="coerce").dropna()
        reasons: list[str] = []
        if active.empty:
            reasons.append("no_active_strategy_in_evaluation_window")
        elif pd.isna(active.iloc[-1]):
            reasons.append("ending_nav_unavailable")
        if len(observed) != self.observed_return_count:
            reasons.append("attribution_observation_count_mismatch")
        if self.attribution_max_residual > ATTRIBUTION_RESIDUAL_TOLERANCE:
            reasons.append("attribution_residual_exceeds_tolerance")

        contributing_positions = np.flatnonzero(self.absolute_by_security > 0.0)
        invalid_leave_one = contributing_positions[~self.leave_one_valid[contributing_positions]]
        if invalid_leave_one.size:
            reasons.append("non_positive_leave_one_growth_factor")

        largest_summary: SecurityContributionSummary | None = None
        absolute_contribution_hhi = 0.0
        total_absolute = self.total_absolute_security_contribution
        if total_absolute > 0.0 and contributing_positions.size:
            shares = self.absolute_by_security[contributing_positions] / total_absolute
            absolute_contribution_hhi = float(np.square(shares).sum())
            ordered_positions = sorted(
                contributing_positions.tolist(),
                key=lambda position: (
                    -float(self.absolute_by_security[position]),
                    str(self.columns[position]),
                ),
            )
            largest_position = int(ordered_positions[0])
            largest_summary = SecurityContributionSummary(
                symbol=str(self.columns[largest_position]),
                signed_contribution=float(self.signed_by_security[largest_position]),
                absolute_contribution=float(self.absolute_by_security[largest_position]),
                absolute_contribution_share=float(
                    self.absolute_by_security[largest_position] / total_absolute
                ),
            )

        sensitivities: list[LeaveOneSecuritySensitivity] = []
        ending_available = bool(not active.empty and pd.notna(active.iloc[-1]))
        if ending_available and not invalid_leave_one.size and not observed.empty:
            growth_factors = 1.0 + observed.to_numpy(dtype=float)
            if bool(np.isfinite(growth_factors).all()) and bool((growth_factors > 0.0).all()):
                base_log_growth = float(np.log(growth_factors).sum())
                years = max(active_calendar_observations / 252.0, 1e-9)
                with np.errstate(over="ignore", invalid="ignore"):
                    base_cagr = float(np.exp(base_log_growth / years) - 1.0)
                if not np.isfinite(base_cagr):
                    reasons.append("non_finite_base_cagr")
                else:
                    for position in contributing_positions:
                        leave_one_log_growth = base_log_growth + float(
                            self.leave_one_log_ratio[position]
                        )
                        with np.errstate(over="ignore", invalid="ignore"):
                            leave_one_cagr = float(np.exp(leave_one_log_growth / years) - 1.0)
                        if not np.isfinite(leave_one_cagr):
                            reasons.append("non_finite_leave_one_cagr")
                            sensitivities = []
                            break
                        cagr_delta = base_cagr - leave_one_cagr
                        sensitivities.append(
                            LeaveOneSecuritySensitivity(
                                symbol=str(self.columns[position]),
                                base_cagr=base_cagr,
                                leave_one_cagr=leave_one_cagr,
                                cagr_delta=cagr_delta,
                                absolute_cagr_delta=abs(cagr_delta),
                            )
                        )
            else:
                reasons.append("non_positive_base_growth_factor")
        sensitivities.sort(key=lambda row: (-row.absolute_cagr_delta, row.symbol))
        top_leave_one = tuple(sensitivities[:10])
        max_leave_one = top_leave_one[0] if top_leave_one else None
        complete = not reasons
        return ContributionDiagnostics(
            attribution_method=ATTRIBUTION_METHOD,
            attribution_version=ATTRIBUTION_VERSION,
            complete=complete,
            reason=None if complete else ";".join(dict.fromkeys(reasons)),
            evaluation_start=self.evaluation_start,
            evaluation_end=self.evaluation_end,
            active_calendar_observations=active_calendar_observations,
            observed_return_count=self.observed_return_count,
            max_exact_single_session_security_contribution=self.max_exact_single_session_event,
            max_observed_interval_security_contribution=self.max_observed_interval_event,
            largest_absolute_contribution_security=largest_summary,
            total_absolute_security_contribution=total_absolute,
            absolute_contribution_hhi=absolute_contribution_hhi,
            max_leave_one_security=max_leave_one,
            top_leave_one_security=top_leave_one,
            attribution_max_residual=self.attribution_max_residual,
        )


@dataclass(slots=True)
class BacktestResult:
    factor_name: str
    policy_id: str
    returns: pd.Series
    equity: pd.Series
    weights: pd.DataFrame
    cash_weights: pd.Series
    turnover: pd.Series
    costs: pd.Series
    signal_dates: pd.Series
    contribution_diagnostics: ContributionDiagnostics
    pre_trade_weights: pd.DataFrame = field(default_factory=pd.DataFrame)
    eligible_security_counts: pd.Series = field(default_factory=pd.Series)
    selected_security_counts: pd.Series = field(default_factory=pd.Series)
    selection_fractions: pd.Series = field(default_factory=pd.Series)
    gross_exposure: pd.Series = field(default_factory=pd.Series)
    strategy_active: pd.Series = field(default_factory=pd.Series)
    valuation_available: pd.Series = field(default_factory=pd.Series)
    stale_holding_counts: pd.Series = field(default_factory=pd.Series)
    stale_holding_weights: pd.Series = field(default_factory=pd.Series)
    execution_statuses: pd.Series = field(default_factory=pd.Series)
    unpriceable_target_counts: pd.Series = field(default_factory=pd.Series)
    return_interval_sessions: pd.Series = field(default_factory=pd.Series)
    target_cash_weights: pd.Series = field(default_factory=pd.Series)
    target_hhi: pd.Series = field(default_factory=pd.Series)
    target_effective_names: pd.Series = field(default_factory=pd.Series)
    target_top1_weights: pd.Series = field(default_factory=pd.Series)
    target_top5_weights: pd.Series = field(default_factory=pd.Series)
    target_max_weights: pd.Series = field(default_factory=pd.Series)
    policy_input_statuses: pd.Series = field(default_factory=pd.Series)
    policy_input_reasons: pd.Series = field(default_factory=pd.Series)
    security_contributions: pd.DataFrame = field(default_factory=pd.DataFrame)
    ending_weights: pd.Series = field(default_factory=pd.Series)
    # cash_weights includes liquid cash plus corporate cash receivables;
    # receivable_weights exposes the non-spendable subset separately.
    receivable_weights: pd.Series = field(default_factory=pd.Series)
    ending_cash_weight: float = 1.0
    ending_receivable_weight: float = 0.0
    last_execution_date: pd.Timestamp | None = None
    last_signal_date: pd.Timestamp | None = None
    first_nonempty_execution_date: pd.Timestamp | None = None
    first_market_exposure_return_date: pd.Timestamp | None = None


def _rebalance_dates(index: pd.DatetimeIndex, frequency: str) -> pd.DatetimeIndex:
    if index.empty:
        return index
    if frequency == "W":
        groups = index.to_period("W-FRI")
    elif frequency == "ME":
        groups = index.to_period("M")
    elif frequency == "QE":
        groups = index.to_period("Q")
    else:
        raise ValueError("rebalance frequency must be W, ME, or QE")
    marker = pd.Series(index, index=index)
    return pd.DatetimeIndex(marker.groupby(groups).last().to_numpy())


def _cash_daily_return(annual_return: float) -> float:
    if annual_return <= -1.0:
        raise ValueError("annual_cash_return must be greater than -1")
    return float((1.0 + annual_return) ** (1.0 / 252.0) - 1.0)


def _target_for_signal(
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
    return construct_target_allocation(
        policy_id,
        signal_date,
        scores,
        prices,
        eligibility,
        config,
        trailing_dollar_volume=trailing_dollar_volume,
        trailing_market_cap=trailing_market_cap,
    )


def run_factor_backtest(
    factor_name: str,
    policy_id: str,
    prices: pd.DataFrame,
    scores: pd.DataFrame,
    config: RunConfig,
    *,
    eligibility_mask: pd.DataFrame | None = None,
    trailing_dollar_volume: pd.DataFrame | None = None,
    trailing_market_cap: pd.DataFrame | None = None,
    retain_weight_history: bool = True,
    weight_history_tail_sessions: int | None = None,
    signal_targets: dict[pd.Timestamp, TargetAllocation] | None = None,
    execution_delay_sessions: int = 1,
    valuation_prices: pd.DataFrame | None = None,
    corporate_actions: tuple[dict, ...] | list[dict] = (),
    retain_contribution_history: bool = False,
) -> BacktestResult:
    """Backtest a date-t close signal with next-session-close execution.

    The implementation compares model portfolios rather than simulating an
    order-management system.  Each holding is carried as a persistent share
    sleeve plus a cash notional.  An internal quote gap therefore makes only
    that close's total NAV unavailable: no missing asset return is filled with
    zero, normally quoted sleeves continue to retain their economic value, and
    the next complete close catches up exactly from the last complete NAV.

    With close-only inputs, a signal formed at close t is traded at close t+1
    and first earns the close-t+1 to close-t+2 return.  A rebalance is cancelled
    when an existing holding cannot be valued; an unpriceable new target is
    omitted while the remaining target can still be implemented.  The
    unavailable intraday execution return is never approximated.

    Optional valuation marks may fill a verified no-trade close but never
    become executable quotes. Corporate actions exchange total-return price
    units at the start of their effective session, without a discretionary
    trade or cost. Each action supplies ``date``, ``symbol``, ``targetSymbol``,
    ``unitRatio`` and optional ``cashPerUnit``; these are normalized price-unit
    quantities, not raw share ratios. The input layer must derive them from
    source/target price bases available at the event. Event-session economic
    gains remain attributed to the predecessor sleeve, while pre-trade and
    ending holdings reflect the received security. A cash-only action has
    ``targetSymbol=None``, ``unitRatio=0`` and positive ``cashPerUnit``. Its
    consideration is a non-interest-bearing cash receivable until an explicit
    ``settlementDate``; unknown settlement never becomes spendable cash. A
    stock-plus-cash action preserves immediate paid cash when settlementDate
    is omitted, while an explicit None or future date creates a receivable.
    Cash weights include both liquid cash and receivables; the separately
    exposed receivable weights identify the unavailable part. Rebalances wait
    while any corporate cash receivable remains unsettled.
    """

    if not isinstance(execution_delay_sessions, int) or execution_delay_sessions < 1:
        raise ValueError("execution_delay_sessions must be a positive integer")
    if weight_history_tail_sessions is not None:
        if (
            not retain_weight_history
            or not isinstance(weight_history_tail_sessions, int)
            or isinstance(weight_history_tail_sessions, bool)
            or weight_history_tail_sessions < 1
        ):
            raise ValueError(
                "weight_history_tail_sessions requires retained history and a positive integer"
            )
    if not prices.index.equals(scores.index):
        raise ValueError("prices and scores must share the exact same date index")
    if (
        prices.index.has_duplicates
        or not prices.index.is_monotonic_increasing
        or scores.index.has_duplicates
        or not scores.index.is_monotonic_increasing
    ):
        raise ValueError("price and score dates must be unique and increasing")
    if eligibility_mask is not None and not eligibility_mask.index.equals(prices.index):
        raise ValueError("eligibility_mask must share the exact price date index")
    common_columns = [column for column in prices.columns if column in scores.columns]
    if not common_columns:
        raise ValueError("prices and scores have no common symbols")
    prices = prices.reindex(columns=common_columns).sort_index()
    scores = scores.reindex(columns=common_columns)
    eligibility = (
        eligibility_mask.reindex(index=prices.index, columns=common_columns).fillna(False)
        if eligibility_mask is not None
        else prices.notna()
    )
    for name, panel in (
        ("trailing_dollar_volume", trailing_dollar_volume),
        ("trailing_market_cap", trailing_market_cap),
    ):
        if panel is not None and not panel.index.equals(prices.index):
            raise ValueError(f"{name} must share the price date index")
    dates = pd.DatetimeIndex(prices.index)
    columns = pd.Index(common_columns)
    price_values = prices.to_numpy(dtype=float, copy=False)
    if valuation_prices is not None:
        if not valuation_prices.index.equals(dates) or not columns.isin(valuation_prices.columns).all():
            raise ValueError("valuation_prices must share the exact dates and cover price columns")
        mark_values = valuation_prices.reindex(columns=columns).to_numpy(dtype=float, copy=False)
        observed = np.isfinite(price_values) & (price_values > 0.0)
        if not np.allclose(mark_values[observed], price_values[observed], rtol=1e-12, atol=0):
            raise ValueError("valuation_prices must preserve all observed execution quotes")
        if np.isinf(mark_values).any() or (mark_values[np.isfinite(mark_values)] < 0).any():
            raise ValueError("valuation_prices contains invalid marks")
    else:
        mark_values = price_values
    actions_by_date: dict[
        pd.Timestamp, list[tuple[int, int | None, float, float, pd.Timestamp | None, bool]]
    ] = {}
    action_keys = set()
    for action in corporate_actions:
        date = pd.Timestamp(action["date"])
        source = str(action["symbol"])
        target = action["targetSymbol"]
        target = str(target) if target is not None else None
        ratio = float(action["unitRatio"])
        cash_per_unit = float(action.get("cashPerUnit", 0.0))
        if source not in columns or (target is not None and (target not in columns or source == target)):
            raise ValueError("corporate action requires source and distinct target price columns")
        if not np.isfinite(ratio) or not np.isfinite(cash_per_unit) or cash_per_unit < 0:
            raise ValueError("corporate action has invalid unit ratio or cash consideration")
        if (target is None and (ratio != 0 or cash_per_unit <= 0)) or (target is not None and ratio <= 0):
            raise ValueError("cash-only action requires zero ratio and positive cash consideration")
        settlement = action.get("settlementDate")
        settlement = pd.Timestamp(settlement) if settlement is not None else None
        if settlement is not None and (pd.isna(settlement) or settlement < date):
            raise ValueError("corporate cash settlement cannot precede the effective date")
        defer_cash = target is None or "settlementDate" in action
        key = (date, source)
        if key in action_keys:
            raise ValueError("duplicate corporate action for source and date")
        action_keys.add(key)
        if date < dates[0] or date > dates[-1]:
            continue
        if date not in dates:
            raise ValueError("corporate action effective date must be an observed session")
        actions_by_date.setdefault(date, []).append(
            (columns.get_loc(source), columns.get_loc(target) if target is not None else None,
             ratio, cash_per_unit, settlement, defer_cash)
        )

    target_by_date: dict[pd.Timestamp, np.ndarray] = {}
    allocation_by_date: dict[pd.Timestamp, TargetAllocation] = {}
    signal_by_date: dict[pd.Timestamp, pd.Timestamp] = {}
    policy_status_by_date: dict[pd.Timestamp, str] = {}
    policy_reasons_by_date: dict[pd.Timestamp, tuple[str, ...]] = {}
    eligible_by_date: dict[pd.Timestamp, int] = {}
    selected_by_date: dict[pd.Timestamp, int] = {}
    position_by_date = {date: position for position, date in enumerate(dates)}
    signal_schedule = sorted(signal_targets) if signal_targets is not None else _rebalance_dates(dates, config.rebalance_frequency)
    for signal_date in signal_schedule:
        position = position_by_date[pd.Timestamp(signal_date)]
        if position + execution_delay_sessions >= len(dates):
            continue
        execution_date = pd.Timestamp(dates[position + execution_delay_sessions])
        allocation = signal_targets[signal_date] if signal_targets is not None else _target_for_signal(
            policy_id,
            pd.Timestamp(signal_date),
            scores.loc[signal_date],
            prices.loc[signal_date],
            eligibility.loc[signal_date],
            config,
            trailing_dollar_volume=(
                trailing_dollar_volume.loc[signal_date]
                if trailing_dollar_volume is not None
                else None
            ),
            trailing_market_cap=(
                trailing_market_cap.loc[signal_date] if trailing_market_cap is not None else None
            ),
        )
        # A formation date without any finite eligible score is not a strategy
        # signal.  Recording it would make the preceding cash warm-up look like
        # factor evidence and can falsely satisfy the minimum-history gate.
        policy_status_by_date[execution_date] = allocation.status
        policy_reasons_by_date[execution_date] = tuple(allocation.reasons)
        if allocation.status == "available" and (allocation.selected_security_count > 0 or signal_targets is not None):
            target_weights = allocation.weights(columns).to_numpy(dtype=float)
            if not np.isfinite(target_weights).all() or (target_weights < 0).any() or target_weights.sum() > 1.0 + 1e-10:
                raise ValueError("invalid explicit target weights")
            target_by_date[execution_date] = target_weights
            allocation_by_date[execution_date] = allocation
            signal_by_date[execution_date] = pd.Timestamp(signal_date)
            eligible_by_date[execution_date] = allocation.eligible_security_count
            selected_by_date[execution_date] = allocation.selected_security_count

    # Canonical accounting state.  Shares are never inferred from a missing
    # quote, and are not changed by valuation gaps.  The absolute NAV scale is
    # arbitrary (one research currency unit at inception) but internally exact.
    shares = np.zeros(len(columns), dtype=float)
    cash_value = 1.0
    cash_receivables: list[tuple[pd.Timestamp | None, float]] = []
    # Sparse ancestry survives incomplete closes, so an exchange during a quote
    # gap still reconciles to the last complete predecessor-sleeve NAV.
    attribution_transfers: dict[tuple[int, int], float] = {}
    attribution_cash: dict[int, float] = {}
    last_complete_nav = 1.0
    last_complete_weights = np.zeros(len(columns), dtype=float)
    last_complete_cash_weight = 1.0
    last_complete_receivable_weight = 0.0
    last_complete_date: pd.Timestamp | None = None
    strategy_started = False
    first_nonempty_execution_date: pd.Timestamp | None = None
    first_market_exposure_return_date: pd.Timestamp | None = None
    last_execution_date: pd.Timestamp | None = None
    last_signal_date: pd.Timestamp | None = None
    daily_cash_return = _cash_daily_return(config.annual_cash_return)
    cost_rate = config.total_cost_bps / 10_000.0
    weight_rows: list[np.ndarray] | deque[np.ndarray] = (
        deque(maxlen=weight_history_tail_sessions)
        if weight_history_tail_sessions is not None
        else []
    )
    pretrade_rows: list[np.ndarray] | deque[np.ndarray] = (
        deque(maxlen=weight_history_tail_sessions)
        if weight_history_tail_sessions is not None
        else []
    )
    cash_values: list[float] | deque[float] = (
        deque(maxlen=weight_history_tail_sessions)
        if weight_history_tail_sessions is not None
        else []
    )
    receivable_values: list[float] | deque[float] = (
        deque(maxlen=weight_history_tail_sessions)
        if weight_history_tail_sessions is not None
        else []
    )
    security_contribution_rows: list[np.ndarray] = []
    return_values: list[float] = []
    turnover_values: list[float] = []
    cost_values: list[float] = []
    exposure_values: list[float] = []
    active_values: list[bool] = []
    valuation_values: list[bool] = []
    stale_count_values: list[int] = []
    stale_weight_values: list[float] = []
    execution_status_values: list[str] = []
    unpriceable_count_values: list[int] = []
    interval_session_values: list[int] = []
    target_cash_values: list[float] = []
    target_hhi_values: list[float] = []
    target_effective_name_values: list[float] = []
    target_top1_values: list[float] = []
    target_top5_values: list[float] = []
    target_max_values: list[float] = []
    policy_status_values: list[str] = []
    policy_reason_values: list[tuple[str, ...]] = []
    sessions_since_complete_return = 0
    evaluation_start_position = max(0, len(dates) - config.evaluation_window_days)
    contribution_accumulator = _ContributionAccumulator.create(
        columns,
        (
            pd.Timestamp(dates[evaluation_start_position])
            if len(dates) > evaluation_start_position
            else None
        ),
        pd.Timestamp(dates[-1]) if len(dates) else None,
    )

    for position, date in enumerate(dates):
        start_weights = last_complete_weights.copy()
        start_cash_weight = float(last_complete_cash_weight)
        interval_start = last_complete_date
        if retain_weight_history:
            weight_rows.append(start_weights)
            cash_values.append(start_cash_weight)
            receivable_values.append(float(last_complete_receivable_weight))
        start_exposure = float(start_weights.sum())
        exposure_values.append(start_exposure)
        if (
            strategy_started
            and first_market_exposure_return_date is None
            and start_exposure > 1e-15
        ):
            first_market_exposure_return_date = pd.Timestamp(date)

        # Cash accrues close-to-close.  There is no preceding interval for the
        # first supplied close.
        if position > 0:
            cash_value *= 1.0 + daily_cash_return
        # Settlement changes liquidity, never NAV. Only liquid cash earns
        # the close-to-close cash return above; a legal claim earns none.
        remaining_receivables = []
        for settlement, amount in cash_receivables:
            if settlement is not None and settlement <= date:
                cash_value += amount
            else:
                remaining_receivables.append((settlement, amount))
        cash_receivables = remaining_receivables
        for source, target, ratio, cash_per_unit, settlement, defer_cash in actions_by_date.get(date, ()):
            source_units = float(shares[source])
            if source_units <= 1e-15:
                continue
            inherited_units = 0.0
            for (origin, destination), units in list(attribution_transfers.items()):
                if destination != source:
                    continue
                inherited_units += units
                del attribution_transfers[origin, destination]
                if target is not None:
                    target_key = (origin, target)
                    attribution_transfers[target_key] = attribution_transfers.get(target_key, 0.0) + units * ratio
                attribution_cash[origin] = attribution_cash.get(origin, 0.0) + units * cash_per_unit
            native_units = max(0.0, source_units - inherited_units)
            if native_units > 0:
                if target is not None:
                    target_key = (source, target)
                    attribution_transfers[target_key] = attribution_transfers.get(target_key, 0.0) + native_units * ratio
                attribution_cash[source] = attribution_cash.get(source, 0.0) + native_units * cash_per_unit
            shares[source] = 0.0
            if target is not None:
                shares[target] += source_units * ratio
            consideration = source_units * cash_per_unit
            if consideration > 0:
                if defer_cash and (settlement is None or settlement > date):
                    cash_receivables.append((settlement, consideration))
                else:
                    cash_value += consideration
        receivable_value = float(sum(amount for _, amount in cash_receivables))
        pretrade_cash_value = float(cash_value + receivable_value)

        execution_prices = price_values[position]
        valuation_marks = mark_values[position]
        held = shares > 1e-15
        stale_held = held & (~np.isfinite(execution_prices) | (execution_prices <= 0.0))
        unvalued_held = held & (~np.isfinite(valuation_marks) | (valuation_marks <= 0.0))
        valuation_complete = not bool(unvalued_held.any())
        valuation_values.append(valuation_complete)
        stale_count_values.append(int(stale_held.sum()))
        stale_weight_values.append(float(start_weights[stale_held].sum()))

        if valuation_complete:
            sleeve_values = shares * np.where(np.isfinite(valuation_marks), valuation_marks, 0.0)
            pretrade_nav = float(sleeve_values.sum() + pretrade_cash_value)
            if not np.isfinite(pretrade_nav) or pretrade_nav <= 0.0:
                raise ValueError(f"portfolio NAV is non-positive or non-finite on {date.date()}")
            pretrade = sleeve_values / pretrade_nav
            pretrade_cash = float(pretrade_cash_value / pretrade_nav)
        else:
            pretrade_nav = float("nan")
            pretrade = last_complete_weights.copy()
            pretrade_cash = float(last_complete_cash_weight)
        if retain_weight_history:
            pretrade_rows.append(pretrade.copy())

        turnover = 0.0
        cost = 0.0
        execution_status = "none"
        unpriceable_target_count = 0
        target_cash_diagnostic = float("nan")
        target_hhi_diagnostic = float("nan")
        target_effective_names_diagnostic = float("nan")
        target_top1_diagnostic = float("nan")
        target_top5_diagnostic = float("nan")
        target_max_diagnostic = float("nan")
        successful_entry = False
        anchor_nav = float(last_complete_nav)
        if date in target_by_date:
            target = target_by_date[date]
            allocation = allocation_by_date[date]
            unpriceable = (target > 0.0) & (
                ~np.isfinite(execution_prices) | (execution_prices <= 0.0)
            )
            unpriceable_target_count = int(unpriceable.sum())
            executable_target = np.where(unpriceable, 0.0, target)
            selected_by_date[date] = int((executable_target > 0.0).sum())
            target_cash = max(0.0, 1.0 - float(executable_target.sum()))
            positive_target = executable_target[executable_target > 0.0]
            invested_target = float(positive_target.sum())
            normalized_target = (
                positive_target / invested_target
                if invested_target > 0.0
                else np.asarray([], dtype=float)
            )
            target_hhi_diagnostic = (
                float(np.square(normalized_target).sum()) if invested_target > 0.0 else 0.0
            )
            target_effective_names_diagnostic = (
                float(1.0 / target_hhi_diagnostic) if target_hhi_diagnostic > 0.0 else 0.0
            )
            sorted_target = np.sort(positive_target)[::-1]
            target_cash_diagnostic = target_cash
            target_top1_diagnostic = float(sorted_target[:1].sum())
            target_top5_diagnostic = float(sorted_target[:5].sum())
            target_max_diagnostic = float(sorted_target.max()) if sorted_target.size else 0.0
            if not valuation_complete or bool(stale_held.any()):
                # A valuation mark is not an executable sale quote. Preserve
                # both turnover and share sleeves until actual quotes return.
                execution_status = "blocked_missing_held_quote"
                selected_by_date[date] = int(held.sum())
            elif receivable_value > 0.0:
                # A compulsory cash entitlement is valued at its legal amount,
                # but cannot fund a rebalance before confirmed settlement.
                execution_status = "blocked_unsettled_corporate_cash"
                selected_by_date[date] = int(held.sum())
            elif not bool((executable_target > 0.0).any()) and bool((target > 0.0).any()):
                # Do not liquidate a valid research portfolio merely because
                # every proposed new close is absent.
                execution_status = "blocked_all_targets_unpriceable"
                selected_by_date[date] = int(held.sum())
            else:
                turnover = 0.5 * (
                    float(np.abs(executable_target - pretrade).sum())
                    + abs(target_cash - pretrade_cash)
                )
                cost_notional = pretrade_nav * turnover * cost_rate
                post_cost_nav = pretrade_nav - cost_notional
                if post_cost_nav <= 0.0:
                    raise ValueError(f"transaction costs exhaust portfolio NAV on {date.date()}")
                shares = np.divide(
                    executable_target * post_cost_nav,
                    execution_prices,
                    out=np.zeros_like(executable_target),
                    where=(executable_target > 0.0)
                    & np.isfinite(execution_prices)
                    & (execution_prices > 0.0),
                )
                cash_value = target_cash * post_cost_nav
                last_complete_nav = float(post_cost_nav)
                last_complete_weights = executable_target.copy()
                last_complete_cash_weight = float(target_cash)
                last_complete_receivable_weight = 0.0
                cost = (
                    float(cost_notional / anchor_nav)
                    if strategy_started
                    else float(cost_notional / pretrade_nav)
                )
                execution_status = (
                    "executed_partial_unpriceable_targets"
                    if unpriceable_target_count
                    else "executed"
                )
                if not strategy_started:
                    strategy_started = True
                    successful_entry = True
                if first_nonempty_execution_date is None and bool((executable_target > 0).any()):
                    first_nonempty_execution_date = pd.Timestamp(date)
                last_execution_date = pd.Timestamp(date)
                last_signal_date = allocation.signal_date

        if valuation_complete and not execution_status.startswith("executed"):
            # Normal mark-to-market close, or a cancelled rebalance.  The
            # canonical share sleeves are unchanged.
            last_complete_nav = float(pretrade_nav)
            last_complete_weights = pretrade.copy()
            last_complete_cash_weight = float(pretrade_cash)
            last_complete_receivable_weight = float(receivable_value / pretrade_nav)

        if successful_entry:
            # The entry close is the first strategy observation.  It contains
            # the execution cost exactly once but excludes the preceding
            # cash-only warm-up return.
            portfolio_return = -float(cost)
            return_interval_sessions = 1
            sessions_since_complete_return = 0
        elif not strategy_started:
            portfolio_return = float("nan")
            return_interval_sessions = 0
        elif not valuation_complete:
            portfolio_return = float("nan")
            sessions_since_complete_return += 1
            return_interval_sessions = 0
        else:
            portfolio_return = float(last_complete_nav / anchor_nav - 1.0)
            return_interval_sessions = sessions_since_complete_return + 1
            sessions_since_complete_return = 0

        contribution_row = np.zeros(len(columns), dtype=float) if retain_contribution_history else None
        if strategy_started and not np.isfinite(portfolio_return) and contribution_row is not None:
            contribution_row[start_weights > 1e-15] = np.nan
        if (
            (position >= evaluation_start_position or retain_contribution_history)
            and strategy_started
            and np.isfinite(portfolio_return)
        ):
            if successful_entry:
                held_positions = np.asarray([], dtype=int)
                security_contributions = np.asarray([], dtype=float)
                contribution_start_weights = np.asarray([], dtype=float)
                security_returns = np.asarray([], dtype=float)
                cash_contribution = 0.0
            else:
                held_positions = np.flatnonzero(start_weights > 1e-15)
                contribution_start_weights = start_weights[held_positions]
                starting_sleeve_values = contribution_start_weights * anchor_nav
                attributed_values = sleeve_values.copy()
                for (origin, destination), units in attribution_transfers.items():
                    received_value = units * valuation_marks[destination]
                    attributed_values[destination] -= received_value
                    attributed_values[origin] += received_value
                for origin, cash_received in attribution_cash.items():
                    attributed_values[origin] += cash_received
                security_contributions = (
                    attributed_values[held_positions] / anchor_nav - contribution_start_weights
                )
                security_returns = (
                    np.divide(
                        attributed_values[held_positions],
                        starting_sleeve_values,
                        out=np.zeros_like(security_contributions),
                        where=starting_sleeve_values > 0.0,
                    )
                    - 1.0
                )
                cash_contribution = float(
                    (pretrade_cash_value - sum(attribution_cash.values())) / anchor_nav - start_cash_weight
                )
            if contribution_row is not None:
                contribution_row[held_positions] = security_contributions
            if position >= evaluation_start_position:
                contribution_accumulator.observe(
                    date=pd.Timestamp(date),
                    interval_start=interval_start,
                    return_interval_sessions=return_interval_sessions,
                    portfolio_return=portfolio_return,
                    held_positions=held_positions,
                    security_contributions=security_contributions,
                    start_weights=contribution_start_weights,
                    security_returns=security_returns,
                    cash_contribution=cash_contribution,
                    cost_contribution=-float(cost),
                )
        if contribution_row is not None:
            security_contribution_rows.append(contribution_row)
        if valuation_complete:
            last_complete_date = pd.Timestamp(date)
            attribution_transfers.clear()
            attribution_cash.clear()
        return_values.append(portfolio_return)
        turnover_values.append(turnover)
        cost_values.append(cost)
        active_values.append(strategy_started)
        execution_status_values.append(execution_status)
        unpriceable_count_values.append(unpriceable_target_count)
        interval_session_values.append(return_interval_sessions)
        target_cash_values.append(target_cash_diagnostic)
        target_hhi_values.append(target_hhi_diagnostic)
        target_effective_name_values.append(target_effective_names_diagnostic)
        target_top1_values.append(target_top1_diagnostic)
        target_top5_values.append(target_top5_diagnostic)
        target_max_values.append(target_max_diagnostic)
        policy_status_values.append(policy_status_by_date.get(pd.Timestamp(date), "not_scheduled"))
        policy_reason_values.append(policy_reasons_by_date.get(pd.Timestamp(date), ()))

    returns = pd.Series(return_values, index=dates, name=factor_name, dtype=float)
    equity = (1.0 + returns).cumprod(skipna=True).rename(factor_name)
    retained_dates = (
        dates[-len(weight_rows) :] if retain_weight_history and len(weight_rows) else dates[:0]
    )
    weights = (
        pd.DataFrame(weight_rows, index=retained_dates, columns=columns)
        if retain_weight_history
        else pd.DataFrame(columns=columns, dtype=float)
    )
    pretrade = (
        pd.DataFrame(pretrade_rows, index=retained_dates, columns=columns)
        if retain_weight_history
        else pd.DataFrame(columns=columns, dtype=float)
    )
    turnover = pd.Series(turnover_values, index=dates, name="turnover", dtype=float)
    costs = pd.Series(cost_values, index=dates, name="cost", dtype=float)
    cash_weights = (
        pd.Series(cash_values, index=retained_dates, name="cash_weight", dtype=float)
        if retain_weight_history
        else pd.Series(name="cash_weight", dtype=float)
    )
    signal_dates = pd.Series(signal_by_date, name="signal_date", dtype="datetime64[ns]")
    eligible_counts = pd.Series(eligible_by_date, name="eligible_security_count", dtype=float)
    selected_counts = pd.Series(selected_by_date, name="selected_security_count", dtype=float)
    selection_fractions = selected_counts.divide(eligible_counts.replace(0.0, np.nan)).rename(
        "selection_fraction"
    )
    gross_exposure = pd.Series(exposure_values, index=dates, name="gross_exposure", dtype=float)
    strategy_active = pd.Series(active_values, index=dates, name="strategy_active", dtype=bool)
    valuation_available = pd.Series(
        valuation_values, index=dates, name="valuation_available", dtype=bool
    )
    stale_holding_counts = pd.Series(
        stale_count_values, index=dates, name="stale_holding_count", dtype=int
    )
    stale_holding_weights = pd.Series(
        stale_weight_values, index=dates, name="stale_holding_weight", dtype=float
    )
    execution_statuses = pd.Series(
        execution_status_values, index=dates, name="execution_status", dtype=object
    )
    unpriceable_target_counts = pd.Series(
        unpriceable_count_values,
        index=dates,
        name="unpriceable_target_count",
        dtype=int,
    )
    return_interval_sessions = pd.Series(
        interval_session_values,
        index=dates,
        name="return_interval_sessions",
        dtype=int,
    )
    target_cash_weights = pd.Series(
        target_cash_values, index=dates, name="target_cash_weight", dtype=float
    )
    target_hhi = pd.Series(target_hhi_values, index=dates, name="target_hhi", dtype=float)
    target_effective_names = pd.Series(
        target_effective_name_values,
        index=dates,
        name="target_effective_names",
        dtype=float,
    )
    target_top1_weights = pd.Series(
        target_top1_values, index=dates, name="target_top1_weight", dtype=float
    )
    target_top5_weights = pd.Series(
        target_top5_values, index=dates, name="target_top5_weight", dtype=float
    )
    target_max_weights = pd.Series(
        target_max_values, index=dates, name="target_max_weight", dtype=float
    )
    policy_input_statuses = pd.Series(
        policy_status_values, index=dates, name="policy_input_status", dtype=object
    )
    policy_input_reasons = pd.Series(
        policy_reason_values, index=dates, name="policy_input_reasons", dtype=object
    )
    contribution_diagnostics = contribution_accumulator.finalize(returns, strategy_active)
    return BacktestResult(
        factor_name=factor_name,
        policy_id=policy_id,
        returns=returns,
        equity=equity,
        weights=weights,
        cash_weights=cash_weights,
        turnover=turnover,
        costs=costs,
        signal_dates=signal_dates,
        contribution_diagnostics=contribution_diagnostics,
        pre_trade_weights=pretrade,
        eligible_security_counts=eligible_counts,
        selected_security_counts=selected_counts,
        selection_fractions=selection_fractions,
        gross_exposure=gross_exposure,
        strategy_active=strategy_active,
        valuation_available=valuation_available,
        stale_holding_counts=stale_holding_counts,
        stale_holding_weights=stale_holding_weights,
        execution_statuses=execution_statuses,
        unpriceable_target_counts=unpriceable_target_counts,
        return_interval_sessions=return_interval_sessions,
        target_cash_weights=target_cash_weights,
        target_hhi=target_hhi,
        target_effective_names=target_effective_names,
        target_top1_weights=target_top1_weights,
        target_top5_weights=target_top5_weights,
        target_max_weights=target_max_weights,
        policy_input_statuses=policy_input_statuses,
        policy_input_reasons=policy_input_reasons,
        security_contributions=(
            pd.DataFrame(security_contribution_rows, index=dates, columns=columns)
            if retain_contribution_history else pd.DataFrame(columns=columns, dtype=float)
        ),
        ending_weights=pd.Series(last_complete_weights, index=columns, dtype=float),
        receivable_weights=(
            pd.Series(receivable_values, index=retained_dates, name="receivable_weight", dtype=float)
            if retain_weight_history else pd.Series(name="receivable_weight", dtype=float)
        ),
        ending_cash_weight=float(last_complete_cash_weight),
        ending_receivable_weight=float(last_complete_receivable_weight),
        last_execution_date=last_execution_date,
        last_signal_date=last_signal_date,
        first_nonempty_execution_date=first_nonempty_execution_date,
        first_market_exposure_return_date=first_market_exposure_return_date,
    )
