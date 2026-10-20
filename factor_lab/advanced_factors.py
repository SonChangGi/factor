from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from .metrics import mark_to_last_observed_returns


VOLUME_FACTOR_NAMES: Final[tuple[str, ...]] = (
    "volume_confirmed_mom_6m",
    "signed_volume_pressure_3m",
)
ADVANCED_FACTOR_NAMES: Final[tuple[str, ...]] = VOLUME_FACTOR_NAMES


@dataclass(slots=True)
class AdvancedFactorResult:
    scores: dict[str, pd.DataFrame]
    status: pd.DataFrame

    @property
    def available_scores(self) -> dict[str, pd.DataFrame]:
        if self.status.empty:
            return {}
        names = set(self.status.loc[self.status["available"].astype(bool), "factor"])
        return {name: panel for name, panel in self.scores.items() if name in names}


def advanced_factor_definitions_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "factor": "volume_confirmed_mom_6m",
                "category": "volume",
                "formula": "6m(skip10) * (1 + clip(log(mean_dollar_volume_21 / prior_mean_dollar_volume_105), -0.5, 0.5))",
                "description": "Six-month price momentum scaled by recent, non-overlapping dollar-volume confirmation.",
                "validation_notes": "Uses only adjusted price and dollar-volume observations available through the signal date.",
                "method_class": "literature_inspired_proxy",
                "canonical_replication": False,
                "canonical_name": "volume_confirmed_mom_6m",
                "formula_version": 1,
                "formation_end_lag_days": 10,
                "component_units": "price_return_times_log_volume_confirmation",
                "limitations": (
                    "Volume confirmation proxy, not a canonical portfolio replication.",
                ),
                "references": ("https://doi.org/10.1111/0022-1082.00280",),
                "compatibility_alias_of": None,
                "selection_eligible": True,
                "minimum_history_sessions": 136,
            },
            {
                "factor": "signed_volume_pressure_3m",
                "category": "volume",
                "formula": "sum_63(sign(return) * price * volume) / sum_63(price * volume)",
                "description": "Three-month signed dollar-volume pressure, bounded between -1 and 1.",
                "validation_notes": "Uses contemporaneous price and supplied share volume without filling missing observations.",
                "method_class": "research_proxy",
                "canonical_replication": False,
                "canonical_name": "signed_volume_pressure_3m",
                "formula_version": 1,
                "formation_end_lag_days": 0,
                "component_units": "signed_dollar_volume_share",
                "limitations": ("Signed-volume pressure is a transparent research proxy.",),
                "references": (),
                "compatibility_alias_of": None,
                "selection_eligible": True,
                "minimum_history_sessions": 64,
            },
        ]
    )


def _empty_scores(prices: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        name: pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
        for name in VOLUME_FACTOR_NAMES
    }


def compute_advanced_factor_scores(
    prices: pd.DataFrame,
    *,
    volumes: pd.DataFrame | None = None,
    dollar_volumes: pd.DataFrame | None = None,
    eligibility_mask: pd.DataFrame | None = None,
) -> AdvancedFactorResult:
    """Compute optional volume factors from supplied local observations."""

    if volumes is None or volumes.empty:
        return AdvancedFactorResult(
            scores=_empty_scores(prices),
            status=pd.DataFrame(
                [
                    {
                        "factor": name,
                        "available": False,
                        "reasonCode": "no_volume_input",
                        "detail": "no volume input",
                    }
                    for name in VOLUME_FACTOR_NAMES
                ]
            ),
        )
    numeric_prices = prices.apply(pd.to_numeric, errors="coerce")
    numeric_volumes = volumes.reindex(index=prices.index, columns=prices.columns).apply(
        pd.to_numeric, errors="coerce"
    )
    numeric_volumes = numeric_volumes.where(numeric_volumes.ge(0.0))
    eligible = (
        eligibility_mask.reindex(index=prices.index, columns=prices.columns).fillna(False)
        if eligibility_mask is not None
        else pd.DataFrame(True, index=prices.index, columns=prices.columns)
    )

    momentum = numeric_prices.shift(10).divide(numeric_prices.shift(136)) - 1.0
    observed_dollar_volume = (
        dollar_volumes.reindex(index=prices.index, columns=prices.columns).apply(
            pd.to_numeric, errors="coerce"
        )
        if dollar_volumes is not None and not dollar_volumes.empty
        else numeric_prices.mul(numeric_volumes)
    )
    recent_volume = observed_dollar_volume.shift(10).rolling(21, min_periods=21).mean()
    prior_volume = observed_dollar_volume.shift(31).rolling(105, min_periods=105).mean()
    volume_ratio = recent_volume.divide(prior_volume)
    confirmation = np.log(volume_ratio.where(volume_ratio.gt(0.0))).clip(-0.5, 0.5)
    volume_confirmed = momentum.mul(1.0 + confirmation)

    returns = mark_to_last_observed_returns(numeric_prices)
    valid_dollar_volume = observed_dollar_volume.where(observed_dollar_volume.gt(0.0))
    signed = np.sign(returns).mul(valid_dollar_volume)
    pressure = (
        signed.rolling(63, min_periods=63)
        .sum()
        .divide(valid_dollar_volume.rolling(63, min_periods=63).sum())
    )
    outputs = {
        "volume_confirmed_mom_6m": volume_confirmed.where(eligible).replace(
            [np.inf, -np.inf], np.nan
        ),
        "signed_volume_pressure_3m": pressure.where(eligible).replace([np.inf, -np.inf], np.nan),
    }
    rows: list[dict[str, object]] = []
    for name, panel in outputs.items():
        latest_count = int(panel.iloc[-1].notna().sum()) if not panel.empty else 0
        rows.append(
            {
                "factor": name,
                "available": latest_count > 0,
                "reasonCode": None if latest_count > 0 else "no_finite_latest_factor_score",
                "latestFiniteCount": latest_count,
                "detail": (
                    "computed from supplied price and volume input"
                    if latest_count > 0
                    else "no finite latest score from supplied volume input"
                ),
            }
        )
    status = pd.DataFrame(rows)
    return AdvancedFactorResult(scores=outputs, status=status)
