from pathlib import Path

import pytest

from factor_lab.config import MAX_TOP_N, RunConfig
from factor_lab.research_inputs import (
    RESEARCH_INPUTS_VERSION,
    ResearchInputError,
    ResearchInputs,
)


def test_public_inputs_round_trip_and_apply_to_run_config(tmp_path: Path) -> None:
    inputs = ResearchInputs.from_mapping(
        {
            "version": RESEARCH_INPUTS_VERSION,
            "rebalanceFrequency": "W",
            "evaluationWindowDays": 1_000,
            "topN": 30,
            "maxWeight": 0.08,
            "transactionCostBps": 7.0,
            "slippageBps": 9.0,
            "minPrice": 10.0,
            "minAvgDollarVolume": 5_000_000.0,
        }
    )
    config = inputs.apply(
        RunConfig(
            demo=True,
            output_dir=tmp_path / "output",
            site_dir=tmp_path / "site",
            cache_dir=tmp_path / "cache",
        )
    )
    assert config.rebalance_frequency == "W"
    assert config.evaluation_window_days == 1_000
    assert config.min_evaluation_observations == 748
    assert config.min_daily_risk_observations == 748
    assert config.top_n == 30
    assert config.selection_extreme_event_action == "exclude"
    assert config.selection_max_abs_security_day_contribution == pytest.approx(0.10)
    assert ResearchInputs.from_config(config) == inputs
    assert inputs.to_dict()["evaluationWindowDays"] == 1_000
    assert "evaluationYears" not in inputs.to_dict()
    assert len(inputs.state_key) == 64


@pytest.mark.parametrize(
    "value",
    [
        {"nearestPreset": True},
        {"version": "research-inputs-v0"},
        {"evaluationYears": 3},
        {"evaluationWindowDays": 20},
        {"evaluationWindowDays": 2_521},
        {"evaluationWindowDays": 2.5},
        {"evaluationWindowDays": True},
        {"topN": 0},
        {"topN": MAX_TOP_N + 1},
        {"maxWeight": 0.0},
        {"minLiquidityObservations": 64, "liquidityLookbackDays": 63},
        {"selectionMinEffectiveNames": 21, "topN": 20},
        {"selectionMaxTargetHhi": 0.0},
        {"selectionMaxSecurityAbsoluteContributionShare": 1.01},
        {"selectionExtremeEventAction": "delete_observation"},
    ],
)
def test_invalid_or_unknown_public_inputs_fail_closed(value: dict[str, object]) -> None:
    with pytest.raises(ResearchInputError):
        ResearchInputs.from_mapping(value)


def test_different_public_inputs_have_different_state_keys() -> None:
    baseline = ResearchInputs()
    changed = ResearchInputs(evaluation_window_days=757)
    assert baseline.state_key != changed.state_key


@pytest.mark.parametrize(
    ("evaluation_window_days", "minimum_observations"),
    [
        (21, 21),
        (126, 126),
        (251, 251),
        (252, 252),
        (504, 252),
        (505, 253),
        (756, 504),
        (2_520, 2_268),
    ],
)
def test_short_and_long_evaluation_windows_derive_bounded_coverage(
    evaluation_window_days: int,
    minimum_observations: int,
) -> None:
    inputs = ResearchInputs.from_mapping({"evaluationWindowDays": evaluation_window_days})

    assert inputs.minimum_evaluation_observations == minimum_observations
    config = inputs.apply(RunConfig(demo=True))
    assert config.evaluation_window_days == evaluation_window_days
    assert config.min_evaluation_observations == minimum_observations
    assert config.min_daily_risk_observations == minimum_observations


def test_explicit_legacy_v1_inputs_can_be_read_but_normalize_to_v2() -> None:
    legacy = ResearchInputs.from_mapping(
        {
            "version": "research-inputs-v1",
            "evaluationYears": 5,
            "evaluationWindowDays": 1_260,
            "topN": 25,
        }
    )

    assert legacy.evaluation_window_days == 1_260
    assert legacy.top_n == 25
    assert legacy.to_dict()["version"] == RESEARCH_INPUTS_VERSION
    assert "evaluationYears" not in legacy.to_dict()


def test_legacy_v1_rejects_conflicting_year_and_day_values() -> None:
    with pytest.raises(ResearchInputError, match="must equal"):
        ResearchInputs.from_mapping(
            {
                "version": "research-inputs-v1",
                "evaluationYears": 3,
                "evaluationWindowDays": 1_000,
            }
        )


_NUMERIC_PUBLIC_INPUTS = (
    "evaluationWindowDays",
    "topN",
    "maxWeight",
    "transactionCostBps",
    "slippageBps",
    "minHistoryDays",
    "minPrice",
    "minAvgDollarVolume",
    "minAvgVolume",
    "liquidityLookbackDays",
    "minLiquidityObservations",
    "maxPriceMissingRatio",
    "maxVolumeMissingRatio",
    "maxExtremeDailyReturn",
    "selectionMinSharpe",
    "selectionMaxDrawdown",
    "selectionMaxAnnualizedCostDrag",
    "selectionMinEffectiveNames",
    "selectionMaxTargetHhi",
    "selectionMaxTargetWeight",
    "selectionMaxAbsSecurityDayContribution",
    "selectionMaxSecurityAbsoluteContributionShare",
    "selectionMaxLeaveOneSecurityCagrDelta",
    "selectionExtremeEventPenaltyPoints",
)


@pytest.mark.parametrize("field", _NUMERIC_PUBLIC_INPUTS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_every_numeric_public_input_rejects_nonfinite_values(
    field: str,
    value: float,
) -> None:
    with pytest.raises(ResearchInputError, match="finite number"):
        ResearchInputs.from_mapping({field: value})
