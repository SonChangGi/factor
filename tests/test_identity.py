from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from factor_lab.config import RunConfig
from factor_lab.data import MarketData
from factor_lab.identity import (
    CANONICAL_JSON_VERSION,
    analysis_cache_path,
    build_result_identity,
    canonical_json_bytes,
    load_analysis_cache,
    normalized_research_inputs,
    write_analysis_cache,
)


def test_engine_digest_covers_all_factor_implementation_modules() -> None:
    import factor_lab.identity as identity_module

    assert {"advanced_factors.py", "factors.py"} <= set(identity_module._ENGINE_SOURCE_FILES)


def test_canonical_json_uses_cross_language_rfc8785_number_encoding() -> None:
    payload = {
        "zero": 0.0,
        "negativeZero": -0.0,
        "one": 1.0,
        "tiny": 1e-7,
        "fixed": 1e-6,
        "large": 1e30,
        "unicode": "한글",
    }

    assert canonical_json_bytes(payload) == (
        b'{"fixed":0.000001,"large":1e+30,"negativeZero":0,"one":1,'
        b'"tiny":1e-7,"unicode":"\xed\x95\x9c\xea\xb8\x80","zero":0}'
    )


def _config(tmp_path: Path, **overrides: object) -> RunConfig:
    values = {
        "demo": True,
        "end_date": "2026-07-10",
        "output_dir": tmp_path / "output",
        "site_dir": tmp_path / "site",
        "cache_dir": tmp_path / "cache",
    }
    values.update(overrides)
    return RunConfig(**values)


def _market(
    *,
    price_hash: str = "a" * 64,
    comparison_hash: str = "c" * 64,
    as_of: str = "2026-07-10",
) -> MarketData:
    dates = pd.DatetimeIndex([pd.Timestamp(as_of)])
    prices = pd.DataFrame({"AAA": [10.0], "SPY": [100.0]}, index=dates)
    candidates = prices[["AAA"]]
    return MarketData(
        prices=prices,
        volumes=candidates * 100.0,
        dollar_volumes=candidates * 1_000.0,
        raw_closes=prices.copy(),
        eligibility_mask=pd.DataFrame(True, index=dates, columns=prices.columns),
        quality=pd.DataFrame(),
        universe=pd.DataFrame({"symbol": ["AAA"], "name": ["Alpha"]}),
        as_of=pd.Timestamp(as_of),
        source_mode="live_market",
        source_label="fixture",
        price_basis="adjusted_close",
        volume_basis="raw_share_volume",
        input_sha256={
            "prices": price_hash,
            "volumes": "b" * 64,
            "comparisonPrices": comparison_hash,
        },
        benchmark="SPY",
        requested_through=as_of,
        requested_candidate_count=1,
        provider_returned_candidate_count=1,
        provider="fixture",
        comparison_prices=prices[["SPY"]],
    )


def test_result_key_changes_for_every_public_research_input(tmp_path: Path) -> None:
    base = _config(tmp_path)
    base_key = build_result_identity(base, _market())["resultKey"]
    changes = (
        {"rebalance_frequency": "W"},
        {"evaluation_window_days": 1_008},
        {"top_n": 30},
        {"max_weight": 0.08},
        {"transaction_cost_bps": 7.0},
        {"slippage_bps": 9.0},
        {"min_history_days": 300},
        {"min_price": 10.0},
        {"min_avg_dollar_volume": 5_000_000.0},
        {"min_avg_volume": 100_000.0},
        {"liquidity_lookback_days": 84},
        {"min_liquidity_observations": 40},
        {"max_price_missing_ratio": 0.04},
        {"max_volume_missing_ratio": 0.08},
        {"max_extreme_daily_return": 0.70},
        {"selection_min_sharpe": 0.10},
        {"selection_max_drawdown": 0.55},
        {"selection_max_annualized_cost_drag": 0.015},
        {"selection_min_effective_names": 9.0},
        {"selection_max_target_hhi": 0.14},
        {"selection_max_target_weight": 0.14},
        {"selection_max_abs_security_day_contribution": 0.20},
        {"selection_max_security_absolute_contribution_share": 0.30},
        {"selection_max_leave_one_security_cagr_delta": 0.20},
        {"selection_extreme_event_action": "warn"},
        {"selection_extreme_event_penalty_points": 15.0},
    )
    for override in changes:
        assert (
            build_result_identity(_config(tmp_path, **override), _market())["resultKey"] != base_key
        )


def test_same_as_of_market_content_change_invalidates_result_key(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = build_result_identity(config, _market(price_hash="a" * 64))
    second = build_result_identity(config, _market(price_hash="f" * 64))
    assert (
        first["keyParts"]["marketSnapshot"]["dataAsOf"]
        == second["keyParts"]["marketSnapshot"]["dataAsOf"]
    )
    assert first["resultKey"] != second["resultKey"]
    assert first["keyParts"]["canonicalJsonVersion"] == CANONICAL_JSON_VERSION


def test_same_primary_market_with_changed_comparator_prices_invalidates_result_key(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first = build_result_identity(config, _market(comparison_hash="c" * 64))
    second = build_result_identity(config, _market(comparison_hash="d" * 64))

    assert first["keyParts"]["marketSnapshot"]["comparisonSymbols"] == ["SPY"]
    assert first["resultKey"] != second["resultKey"]


def test_market_basis_and_raw_close_proxy_semantics_invalidate_result_key(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    market = _market()
    baseline = build_result_identity(config, market)["resultKey"]

    market.price_basis = "different-adjustment-contract"
    changed_price_basis = build_result_identity(config, market)["resultKey"]
    market.price_basis = "adjusted_close"
    market.volume_basis = "different-volume-contract"
    changed_volume_basis = build_result_identity(config, market)["resultKey"]
    market.volume_basis = "raw_share_volume"
    market.raw_close_proxy_symbol_count = 1
    changed_proxy_count = build_result_identity(config, market)["resultKey"]

    assert len({baseline, changed_price_basis, changed_volume_basis, changed_proxy_count}) == 4


def test_operational_paths_refresh_and_ttl_do_not_change_research_inputs(tmp_path: Path) -> None:
    first = _config(tmp_path)
    second = _config(
        tmp_path,
        output_dir=tmp_path / "elsewhere",
        site_dir=tmp_path / "other-site",
        cache_dir=tmp_path / "other-cache",
        refresh_market_data=True,
        require_current_session=True,
        market_cache_max_age_hours=1.0,
    )
    assert normalized_research_inputs(first) == normalized_research_inputs(second)
    assert (
        build_result_identity(first, _market())["resultKey"]
        == build_result_identity(second, _market())["resultKey"]
    )


def test_analysis_cache_requires_full_embedded_identity_and_filename(tmp_path: Path) -> None:
    config = _config(tmp_path)
    identity = build_result_identity(config, _market())
    payload = {"schemaVersion": 4, "resultIdentity": identity}
    path = write_analysis_cache(config, identity, payload)
    assert path == analysis_cache_path(config, str(identity["resultKey"]))
    assert load_analysis_cache(config, identity) == payload

    mismatched = deepcopy(payload)
    mismatched["resultIdentity"]["keyParts"]["normalizedInputs"]["top_n"] = 99
    path.write_bytes(__import__("json").dumps(mismatched).encode())
    assert load_analysis_cache(config, identity) is None


def test_analysis_crossing_utc_midnight_keeps_cache_identity(tmp_path: Path, monkeypatch) -> None:
    class Clock(datetime):
        current = datetime(2026, 9, 17, 23, 59, 59, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr("factor_lab.config.datetime", Clock)
    config = _config(tmp_path, end_date=None)
    market = _market(as_of="2026-09-17")
    before_analysis = build_result_identity(config, market)
    Clock.current = datetime(2026, 9, 18, 0, 0, 1, tzinfo=UTC)
    after_analysis = build_result_identity(config, market)

    assert after_analysis == before_analysis
    normalized = after_analysis["keyParts"]["normalizedInputs"]
    assert normalized["end_date"] is None
    assert normalized["effective_end_date"] == "2026-09-17"
    assert "_resolved_end_date" not in normalized
    payload = {"schemaVersion": 5, "resultIdentity": after_analysis}
    write_analysis_cache(config, before_analysis, payload)
    assert load_analysis_cache(config, before_analysis) == payload
    next_run = build_result_identity(config.for_new_run(), market)
    assert next_run["resultKey"] != before_analysis["resultKey"]


def test_explicit_end_date_identity_ignores_run_start_day(tmp_path: Path, monkeypatch) -> None:
    class Clock(datetime):
        current = datetime(2026, 9, 17, 23, 59, 59, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr("factor_lab.config.datetime", Clock)
    config = _config(tmp_path)
    market = _market()
    first = build_result_identity(config, market)
    Clock.current = datetime(2026, 9, 18, 0, 0, 1, tzinfo=UTC)
    assert build_result_identity(config.for_new_run(), market) == first


def test_factor_policy_and_selection_digests_are_part_of_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_lab.identity as identity_module

    config = _config(tmp_path)
    baseline = build_result_identity(config, _market())["resultKey"]
    monkeypatch.setattr(identity_module, "factor_definition_sha256", lambda: "1" * 64)
    assert build_result_identity(config, _market())["resultKey"] != baseline
    monkeypatch.setattr(identity_module, "policy_definition_sha256", lambda: "2" * 64)
    second = build_result_identity(config, _market())["resultKey"]
    monkeypatch.setattr(identity_module, "selection_spec_sha256", lambda _config: "3" * 64)
    assert build_result_identity(config, _market())["resultKey"] != second
