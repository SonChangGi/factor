import warnings

import numpy as np
import pandas as pd

from factor_lab.advanced_factors import (
    ADVANCED_FACTOR_NAMES,
    advanced_factor_definitions_frame,
    compute_advanced_factor_scores,
)


def test_volume_factors_are_available_from_supplied_observations() -> None:
    dates = pd.bdate_range("2023-01-02", periods=220)
    prices = pd.DataFrame(
        {
            "AAA": 100.0 * np.cumprod(np.repeat(1.001, len(dates))),
            "BBB": 100.0 * np.cumprod(np.repeat(0.999, len(dates))),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "AAA": np.linspace(1_000_000, 3_000_000, len(dates)),
            "BBB": np.linspace(3_000_000, 1_000_000, len(dates)),
        },
        index=dates,
    )
    result = compute_advanced_factor_scores(
        prices,
        volumes=volumes,
        eligibility_mask=pd.DataFrame(True, index=dates, columns=prices.columns),
    )
    assert set(result.available_scores) == set(ADVANCED_FACTOR_NAMES)
    assert result.status["available"].all()
    assert result.scores["signed_volume_pressure_3m"].iloc[-1, 0] > 0
    assert result.scores["signed_volume_pressure_3m"].iloc[-1, 1] < 0


def test_missing_volume_does_not_create_synthetic_factor_values() -> None:
    dates = pd.bdate_range("2023-01-02", periods=220)
    prices = pd.DataFrame({"AAA": np.linspace(100, 150, len(dates))}, index=dates)
    result = compute_advanced_factor_scores(prices)
    assert result.available_scores == {}
    assert not result.status["available"].any()
    assert result.status["reasonCode"].eq("no_volume_input").all()
    assert all(panel.isna().all().all() for panel in result.scores.values())


def test_historical_volume_without_latest_scores_is_not_a_current_factor() -> None:
    dates = pd.bdate_range("2023-01-02", periods=220)
    prices = pd.DataFrame({"AAA": np.linspace(100, 150, len(dates))}, index=dates)
    volumes = pd.DataFrame({"AAA": 1_000_000.0}, index=dates)
    volumes.loc[dates[-140] :, "AAA"] = np.nan
    result = compute_advanced_factor_scores(
        prices,
        volumes=volumes,
        eligibility_mask=pd.DataFrame(True, index=dates, columns=prices.columns),
    )
    assert result.available_scores == {}
    assert not result.status["available"].any()
    assert result.status["reasonCode"].eq("no_finite_latest_factor_score").all()
    assert result.status["detail"].str.contains("no finite latest score").all()


def test_zero_dollar_volume_is_missing_for_log_confirmation_without_warning() -> None:
    dates = pd.bdate_range("2023-01-02", periods=220)
    prices = pd.DataFrame({"AAA": np.linspace(100, 150, len(dates))}, index=dates)
    volumes = pd.DataFrame({"AAA": 1_000_000.0}, index=dates)
    volumes.loc[dates[130:170], "AAA"] = 0.0

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = compute_advanced_factor_scores(
            prices,
            volumes=volumes,
            eligibility_mask=pd.DataFrame(True, index=dates, columns=prices.columns),
        )

    assert not any("divide by zero encountered in log" in str(item.message) for item in caught)
    assert not np.isinf(result.scores["volume_confirmed_mom_6m"].to_numpy()).any()


def test_advanced_factor_catalog_is_complete() -> None:
    definitions = advanced_factor_definitions_frame()
    assert definitions["factor"].tolist() == list(ADVANCED_FACTOR_NAMES)
    assert definitions["formula"].str.len().gt(10).all()
