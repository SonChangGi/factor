import hashlib
import inspect
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_lab import data
from factor_lab.config import RunConfig
from factor_lab.data import (
    build_eligibility_mask,
    load_market_data,
    read_market_data_snapshot,
    write_market_data_snapshot,
)
from factor_lab.identity import build_result_identity




def test_demo_uses_200_candidates_and_keeps_benchmark_out_of_eligibility() -> None:
    market = load_market_data(RunConfig(demo=True))
    assert len(market.candidate_symbols) == 200
    assert market.prices.shape[1] == 201
    assert int(market.eligibility_mask.iloc[-1].sum()) == 200
    assert not bool(market.eligibility_mask["SPY"].any())
    assert market.source_mode == "demo"
    assert market.price_basis == "synthetic_total_return_like"
    assert {
        "prices",
        "volumes",
        "rawCloses",
        "dollarVolumes",
        "demoSpecification",
        "generatorSource",
        "defaultUniverseFile",
        "resolvedOrderedUniverse",
        "marketCaps",
        "marketCapSources",
    } == set(market.input_sha256)
    assert market.input_sha256["rawCloses"] is None
    assert all(value is None or len(value) == 64 for value in market.input_sha256.values())


def test_demo_provenance_is_deterministic_and_binds_config_and_order(monkeypatch) -> None:
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        start_date="2020-01-01",
        end_date="2021-12-31",
    )
    first = load_market_data(config)
    repeated = load_market_data(config)
    pd.testing.assert_frame_equal(first.prices, repeated.prices)
    pd.testing.assert_frame_equal(first.volumes, repeated.volumes)
    assert first.input_sha256 == repeated.input_sha256

    changed_seed = load_market_data(
        RunConfig(
            demo=True,
            demo_symbol_count=50,
            demo_seed=43,
            start_date="2020-01-01",
            end_date="2021-12-31",
        )
    )
    assert changed_seed.input_sha256["demoSpecification"] != first.input_sha256["demoSpecification"]
    assert changed_seed.input_sha256["prices"] != first.input_sha256["prices"]

    changed_benchmark = load_market_data(
        RunConfig(
            demo=True,
            demo_symbol_count=50,
            benchmark="AAPL",
            start_date="2020-01-01",
            end_date="2021-12-31",
        )
    )
    assert (
        changed_benchmark.input_sha256["demoSpecification"]
        != first.input_sha256["demoSpecification"]
    )
    assert changed_benchmark.input_sha256["prices"] != first.input_sha256["prices"]

    monkeypatch.setattr(data, "DEFAULT_UNIVERSE", list(reversed(data.DEFAULT_UNIVERSE)))
    changed_order = load_market_data(config)
    assert (
        changed_order.input_sha256["defaultUniverseFile"]
        == first.input_sha256["defaultUniverseFile"]
    )
    assert (
        changed_order.input_sha256["resolvedOrderedUniverse"]
        != first.input_sha256["resolvedOrderedUniverse"]
    )
    assert (
        changed_order.input_sha256["demoSpecification"] != first.input_sha256["demoSpecification"]
    )
    assert changed_order.input_sha256["prices"] != first.input_sha256["prices"]


def test_demo_missing_ratio_adds_deterministic_sparse_gaps_but_preserves_final_date() -> None:
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        demo_missing_ratio=0.001,
        start_date="2020-01-01",
        end_date="2021-12-31",
    )
    first = load_market_data(config)
    repeated = load_market_data(config)
    complete = load_market_data(
        RunConfig(
            demo=True,
            demo_symbol_count=50,
            start_date="2020-01-01",
            end_date="2021-12-31",
        )
    )
    candidates = first.candidate_symbols
    price_missing = first.prices[candidates].isna()
    volume_missing = first.volumes[candidates].isna()
    eligible_cells = (len(first.prices.index) - 1) * len(candidates)

    assert int(price_missing.to_numpy().sum()) == int(np.ceil(eligible_cells * 0.001))
    pd.testing.assert_frame_equal(price_missing, volume_missing)
    assert not bool(price_missing.iloc[-1].any())
    assert not bool(first.prices[first.benchmark].isna().any())
    pd.testing.assert_frame_equal(first.prices, repeated.prices)
    assert first.input_sha256 == repeated.input_sha256
    assert first.input_sha256["demoSpecification"] != complete.input_sha256["demoSpecification"]
    assert first.input_sha256["prices"] != complete.input_sha256["prices"]
    assert "missing_ratio=0.001" in " ".join(first.notes)


def test_wide_local_csv_defines_the_analyzed_universe(tmp_path) -> None:
    dates = pd.bdate_range("2022-01-03", periods=320)
    frame = pd.DataFrame(
        {
            "date": dates,
            "AAA": np.linspace(20.0, 40.0, len(dates)),
            "BBB": np.linspace(30.0, 45.0, len(dates)),
            "SPY": np.linspace(400.0, 470.0, len(dates)),
        }
    )
    path = tmp_path / "prices.csv"
    frame.to_csv(path, index=False)
    market = load_market_data(
        RunConfig(
            prices_path=path,
            start_date="2022-01-03",
            top_n=2,
            min_history_days=252,
            evaluation_window_days=252,
            min_evaluation_observations=252,
            min_daily_risk_observations=252,
            selection_min_effective_names=2,
        )
    )
    assert market.candidate_symbols == ["AAA", "BBB"]
    assert int(market.eligibility_mask.iloc[-1].sum()) == 2
    assert market.source_label == "prices.csv"
    assert market.price_basis == "user_supplied_adjusted"
    assert market.input_sha256["prices"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_long_local_csv_is_supported(tmp_path) -> None:
    dates = pd.bdate_range("2023-01-02", periods=260)
    rows = [
        {"date": date, "symbol": symbol, "price": 20 + offset + i / 100}
        for i, date in enumerate(dates)
        for offset, symbol in enumerate(("AAA", "BBB"))
    ]
    path = tmp_path / "long.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    market = load_market_data(
        RunConfig(
            prices_path=path,
            start_date="2023-01-02",
            top_n=2,
            min_history_days=252,
            evaluation_window_days=252,
            min_evaluation_observations=252,
            min_daily_risk_observations=252,
            selection_min_effective_names=2,
        )
    )
    assert market.prices.columns.tolist() == ["AAA", "BBB"]


def test_raw_close_long_column_is_rejected_as_ambiguous_price_basis(tmp_path) -> None:
    path = tmp_path / "raw-close.csv"
    pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-03"],
            "symbol": ["AAA", "AAA"],
            "close": [10.0, 11.0],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="requires one of"):
        load_market_data(RunConfig(prices_path=path, top_n=1, selection_min_effective_names=1))


@pytest.mark.parametrize(
    ("kind", "contents", "value"),
    [
        ("prices", "date,AAA\n2024-01-02,10\n2024-01-03,oops\n", "oops"),
        (
            "prices",
            "date,symbol,price\n2024-01-02,AAA,10\n2024-01-03,AAA,oops\n",
            "oops",
        ),
        ("volumes", "date,AAA\n2024-01-02,10\n2024-01-03,inf\n", "inf"),
        (
            "volumes",
            "date,symbol,volume\n2024-01-02,AAA,10\n2024-01-03,AAA,-inf\n",
            "-inf",
        ),
    ],
)
def test_nonblank_malformed_and_infinite_values_fail_with_cell_context(
    tmp_path,
    kind: str,
    contents: str,
    value: str,
) -> None:
    path = tmp_path / f"bad-{kind}.csv"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError) as captured:
        data._read_local_matrix(path, kind=kind)

    message = str(captured.value)
    assert str(path) in message
    assert "row=3" in message
    assert "date='2024-01-03'" in message
    assert "symbol='AAA'" in message
    assert f"value='{value}'" in message


@pytest.mark.parametrize(
    ("kind", "contents"),
    [
        ("prices", "date,AAA\n2024-01-02,10\n2024-01-03,\n"),
        ("prices", "date,symbol,price\n2024-01-02,AAA,10\n2024-01-03,AAA,\n"),
        ("volumes", "date,AAA\n2024-01-02,10\n2024-01-03,\n"),
        ("volumes", "date,symbol,volume\n2024-01-02,AAA,10\n2024-01-03,AAA,\n"),
    ],
)
def test_trailing_all_blank_rows_cannot_extend_actual_as_of(
    tmp_path,
    kind: str,
    contents: str,
) -> None:
    path = tmp_path / f"blank-{kind}.csv"
    path.write_text(contents, encoding="utf-8")
    matrix = data._read_local_matrix(path, kind=kind)
    assert pd.Timestamp("2024-01-03") not in matrix.index
    assert matrix.index.max() == pd.Timestamp("2024-01-02")


def test_duplicate_raw_and_normalized_csv_headers_are_rejected(tmp_path) -> None:
    raw_duplicate = tmp_path / "raw-duplicate.csv"
    raw_duplicate.write_text("date,AAA,AAA\n2024-01-02,10,11\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate raw CSV headers"):
        data._read_local_matrix(raw_duplicate, kind="prices")

    normalized_duplicate = tmp_path / "normalized-duplicate.csv"
    normalized_duplicate.write_text(
        "date,BRK.B,BRK-B\n2024-01-02,10,11\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate normalized symbols"):
        data._read_local_matrix(normalized_duplicate, kind="prices")


@pytest.mark.parametrize(
    "contents",
    [
        "date,BAD SYMBOL\n2024-01-02,10\n",
        "date,symbol,price\n2024-01-02,$BROKEN,10\n",
    ],
)
def test_invalid_wide_headers_and_long_symbol_values_are_rejected(tmp_path, contents: str) -> None:
    path = tmp_path / "invalid-symbol.csv"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported security symbols"):
        data._read_local_matrix(path, kind="prices")


def test_eligibility_is_date_t_causal() -> None:
    dates = pd.bdate_range("2023-01-02", periods=300)
    prices = pd.DataFrame({"AAA": np.linspace(10.0, 30.0, len(dates))}, index=dates)
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        min_history_days=100,
        evaluation_window_days=252,
        min_evaluation_observations=252,
        min_daily_risk_observations=252,
    )
    original = build_eligibility_mask(prices, pd.DataFrame(index=dates), config)
    changed = prices.copy()
    changed.loc[dates[250] :, "AAA"] = np.nan
    modified = build_eligibility_mask(changed, pd.DataFrame(index=dates), config)
    pd.testing.assert_series_equal(
        original.loc[: dates[249], "AAA"], modified.loc[: dates[249], "AAA"]
    )


def test_invalid_prices_and_duplicate_long_rows_are_rejected(tmp_path) -> None:
    dates = pd.bdate_range("2022-01-03", periods=260)
    wide = pd.DataFrame({"date": dates, "AAA": 10.0})
    wide.loc[10, "AAA"] = -1.0
    path = tmp_path / "bad.csv"
    wide.to_csv(path, index=False)
    with pytest.raises(ValueError, match="strictly positive"):
        load_market_data(
            RunConfig(
                prices_path=path,
                top_n=1,
                min_history_days=252,
                evaluation_window_days=252,
                min_evaluation_observations=252,
                min_daily_risk_observations=252,
                selection_min_effective_names=1,
            )
        )


def test_sparse_local_matrix_still_rejects_observed_non_positive_price(tmp_path) -> None:
    dates = pd.bdate_range("2022-01-03", periods=260)
    wide = pd.DataFrame(
        {
            "date": dates,
            "AAA": np.linspace(10.0, 20.0, len(dates)),
            "BBB": np.nan,
        }
    )
    wide.loc[10, "AAA"] = 0.0
    wide.loc[20:, "BBB"] = np.linspace(8.0, 18.0, len(dates) - 20)
    path = tmp_path / "sparse-zero.csv"
    wide.to_csv(path, index=False)

    with pytest.raises(ValueError, match="strictly positive"):
        load_market_data(
            RunConfig(
                prices_path=path,
                top_n=1,
                min_history_days=252,
                evaluation_window_days=252,
                min_evaluation_observations=252,
                min_daily_risk_observations=252,
                selection_min_effective_names=1,
            )
        )








@pytest.mark.parametrize(
    ("symbol", "event_position", "event_multiplier"),
    [("EVENT_A", 32, 3.0), ("EVENT_B", 47, 0.10)],
)
def test_causal_extreme_return_gate_is_symbol_and_date_agnostic(
    symbol: str,
    event_position: int,
    event_multiplier: float,
) -> None:
    dates = pd.bdate_range("2024-01-02", periods=80)
    baseline_prices = pd.DataFrame(
        {symbol: np.linspace(100.0, 200.0, len(dates))},
        index=dates,
    )
    volumes = pd.DataFrame(1_000_000.0, index=dates, columns=[symbol])
    config = RunConfig(
        demo=True,
        min_history_days=20,
        data_quality_lookback_days=10,
        max_extreme_daily_return=0.80,
        top_n=1,
        max_weight=1.0,
        selection_min_effective_names=1.0,
    )
    baseline = build_eligibility_mask(baseline_prices, volumes, config)
    event_date = dates[event_position]
    changed_prices = baseline_prices.copy()
    changed_prices.loc[event_date:, symbol] *= event_multiplier

    changed = build_eligibility_mask(changed_prices, volumes, config)

    pd.testing.assert_series_equal(
        baseline.loc[: dates[event_position - 1], symbol],
        changed.loc[: dates[event_position - 1], symbol],
    )
    assert baseline.loc[event_date, symbol]
    assert not changed.loc[event_date, symbol]
    assert not changed.loc[dates[event_position + 9], symbol]
    assert changed.loc[dates[event_position + 10], symbol]


def test_exported_actual_market_snapshot_replays_only_after_hash_verification(
    tmp_path,
    monkeypatch,
) -> None:
    dates = pd.bdate_range("2026-01-02", periods=30)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(100.0, 110.0, len(dates)),
            "AAA": np.linspace(20.0, 30.0, len(dates)),
        },
        index=dates,
    )
    volumes = pd.DataFrame(1_000_000.0, index=dates, columns=prices.columns)
    volumes["SPY"] = 0.0
    raw_closes = prices.copy()
    dollar_volumes = raw_closes * volumes
    comparison_prices = pd.DataFrame(
        {
            "SPY": prices["SPY"],
            "^IXIC": np.linspace(15_000.0, 16_000.0, len(dates)),
            "QQQ": np.linspace(300.0, 330.0, len(dates)),
        },
        index=dates,
    )
    config = RunConfig(
        live=True,
        start_date=dates.min().date().isoformat(),
        end_date=dates.max().date().isoformat(),
        top_n=1,
        min_history_days=21,
        selection_min_effective_names=1.0,
    )
    eligibility = build_eligibility_mask(
        prices,
        volumes,
        config,
        dollar_volumes=dollar_volumes,
    )
    universe = pd.DataFrame({"symbol": ["AAA"], "name": ["Refresh-only Alpha Incorporated"]})
    price_sources = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "price_source": "yfinance-adjusted-daily",
                "adjustment_note": "fixture adjusted close",
            }
        ]
    )
    data_sources = pd.DataFrame(
        [
            {
                "source": "yfinance-adjusted-daily",
                "status": "ok",
                "records": len(dates),
                "cache_hit": False,
            }
        ]
    )
    market_caps = raw_closes.mul(100_000_000.0)
    market_cap_sources = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "mapping": "fixture",
                "taxonomy": "fixture",
                "tag": "sharesOutstanding",
                "valueKind": "shares",
                "latestMarketCapAvailable": True,
            }
        ]
    )
    hashes = {
        "prices": data._canonical_matrix_sha256(prices),
        "volumes": data._canonical_matrix_sha256(volumes),
        "rawCloses": data._canonical_matrix_sha256(raw_closes),
        "dollarVolumes": data._canonical_matrix_sha256(dollar_volumes),
        "requestedSymbols": data._ordered_symbols_sha256(["AAA"]),
        "returnedSymbols": data._ordered_symbols_sha256(["AAA"]),
        "universeRecords": data.canonical_records_sha256(universe),
        "priceSources": data.canonical_records_sha256(price_sources),
        "dataSources": data.canonical_records_sha256(data_sources),
        "comparisonPrices": data._canonical_matrix_sha256(comparison_prices),
        "marketCaps": data._canonical_matrix_sha256(market_caps),
        "marketCapSources": data.canonical_records_sha256(market_cap_sources),
    }
    market = data.MarketData(
        prices=prices,
        volumes=volumes,
        dollar_volumes=dollar_volumes,
        raw_closes=raw_closes,
        eligibility_mask=eligibility,
        quality=pd.DataFrame(),
        universe=universe,
        as_of=dates.max(),
        source_mode="live_market",
        source_label="actual-provider-fixture",
        price_basis="provider_adjusted_close",
        volume_basis="raw_close_x_raw_volume_with_disclosed_fallback_proxy",
        input_sha256=hashes,
        benchmark="SPY",
        requested_through=dates.max().date().isoformat(),
        requested_candidate_count=1,
        provider_returned_candidate_count=1,
        provider="actual-provider-fixture",
        price_sources=price_sources,
        data_sources=data_sources,
        comparison_prices=comparison_prices,
        market_caps=market_caps,
        market_cap_sources=market_cap_sources,
    )
    snapshot_dir = tmp_path / "snapshot"
    write_market_data_snapshot(market, snapshot_dir)

    replayed = read_market_data_snapshot(config, snapshot_dir)
    assert replayed.source_mode == "live_market"
    assert replayed.as_of == dates.max()
    assert replayed.input_sha256 == hashes
    pd.testing.assert_frame_equal(replayed.comparison_prices, comparison_prices, check_freq=False)
    assert build_result_identity(config, replayed) == build_result_identity(config, market)
    stricter_replay = read_market_data_snapshot(
        RunConfig(
            live=True,
            start_date=dates.min().date().isoformat(),
            end_date=dates.max().date().isoformat(),
            top_n=1,
            min_history_days=21,
            min_price=31.0,
            selection_min_effective_names=1.0,
        ),
        snapshot_dir,
    )
    assert (
        int(stricter_replay.eligibility_mask.drop(columns=["SPY"], errors="ignore").iloc[-1].sum())
        == 0
    )
    pd.testing.assert_frame_equal(replayed.prices, prices, check_freq=False)
    assert data._canonical_records_json_bytes(
        replayed.price_sources
    ) == data._canonical_records_json_bytes(market.price_sources)
    assert data._canonical_records_json_bytes(
        replayed.data_sources
    ) == data._canonical_records_json_bytes(market.data_sources)
    assert data._canonical_records_json_bytes(
        replayed.universe
    ) == data._canonical_records_json_bytes(market.universe)
    assert any("Verified replay" in note for note in replayed.notes)

    original_price_hash = market.input_sha256["prices"]
    market.input_sha256["prices"] = "f" * 64
    with pytest.raises(ValueError, match="differs from observed prices"):
        write_market_data_snapshot(market, tmp_path / "rejected-snapshot")
    assert not (tmp_path / "rejected-snapshot").exists()
    market.input_sha256["prices"] = original_price_hash

    original_volumes = market.volumes.copy()
    market.volumes.loc[dates[10], "AAA"] = 0.0
    with pytest.raises(ValueError, match="candidate zero-volume close policy"):
        write_market_data_snapshot(market, tmp_path / "rejected-zero-volume-snapshot")
    assert not (tmp_path / "rejected-zero-volume-snapshot").exists()
    market.volumes = original_volumes

    market.source_mode = "demo"
    with pytest.raises(ValueError, match="actual live-market"):
        write_market_data_snapshot(market, tmp_path / "rejected-demo-snapshot")
    market.source_mode = "live_market"
    original_price_source_frame = market.price_sources
    market.price_sources = pd.DataFrame()
    with pytest.raises(ValueError, match="provider provenance"):
        write_market_data_snapshot(market, tmp_path / "rejected-empty-provenance")
    market.price_sources = original_price_source_frame

    manifest_path = snapshot_dir / "market_data_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 4
    assert manifest["files"]["priceSources"] == "price_sources.json"
    assert manifest["files"]["marketCaps"] == "point_in_time_market_caps.csv.gz"
    assert manifest["files"]["marketCapSources"] == "market_cap_sources.json"
    assert manifest["files"]["dataSources"] == "data_sources.json"
    assert manifest["files"]["universe"] == "universe.json"
    assert manifest["files"]["comparisonPrices"] == "comparison_adjusted_prices.csv.gz"
    assert manifest["comparisonSymbols"] == ["SPY", "^IXIC", "QQQ"]
    assert manifest["readContract"] == data.SNAPSHOT_READ_CONTRACT
    assert manifest["readContract"]["candidateZeroVolumeClosePolicy"] == (
        "mask_adjusted_and_raw_v1"
    )

    transitional_dir = tmp_path / "legacy-contract-sanitized-v3-snapshot"
    shutil.copytree(snapshot_dir, transitional_dir)
    transitional_manifest_path = transitional_dir / "market_data_manifest.json"
    transitional_manifest = json.loads(transitional_manifest_path.read_text(encoding="utf-8"))
    transitional_manifest["readContract"] = data.LEGACY_SNAPSHOT_READ_CONTRACT
    legacy_matrix_frames = {
        "prices": market.prices,
        "volumes": market.volumes,
        "dollarVolumes": market.dollar_volumes,
        "rawCloses": market.raw_closes,
        "comparisonPrices": market.comparison_prices,
        "marketCaps": market.market_caps,
    }
    for component, frame in legacy_matrix_frames.items():
        transitional_manifest["matrixSha256"][component] = data._legacy_canonical_matrix_sha256(
            frame, datetime_unit="s"
        )
    transitional_manifest_path.write_text(
        json.dumps(transitional_manifest),
        encoding="utf-8",
    )
    transitional_replay = read_market_data_snapshot(config, transitional_dir)
    pd.testing.assert_frame_equal(
        transitional_replay.prices,
        replayed.prices,
        check_freq=False,
    )
    assert transitional_replay.input_sha256 == replayed.input_sha256 == hashes
    assert build_result_identity(config, transitional_replay) == build_result_identity(
        config,
        replayed,
    )

    mixed_unit_dir = tmp_path / "legacy-contract-mixed-unit-v3-snapshot"
    shutil.copytree(transitional_dir, mixed_unit_dir)
    mixed_unit_manifest_path = mixed_unit_dir / "market_data_manifest.json"
    mixed_unit_manifest = json.loads(mixed_unit_manifest_path.read_text(encoding="utf-8"))
    mixed_unit_manifest["matrixSha256"]["volumes"] = data._legacy_canonical_matrix_sha256(
        market.volumes, datetime_unit="us"
    )
    mixed_unit_manifest_path.write_text(
        json.dumps(mixed_unit_manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no common datetime unit"):
        read_market_data_snapshot(config, mixed_unit_dir)

    unsanitized_dir = tmp_path / "legacy-contract-unsanitized-v3-snapshot"
    shutil.copytree(transitional_dir, unsanitized_dir)
    unsanitized_manifest_path = unsanitized_dir / "market_data_manifest.json"
    unsanitized_manifest = json.loads(unsanitized_manifest_path.read_text(encoding="utf-8"))
    volume_path = unsanitized_dir / unsanitized_manifest["files"]["volumes"]
    unsanitized_volumes = pd.read_csv(
        volume_path,
        index_col=0,
        parse_dates=True,
        float_precision="round_trip",
    )
    unsanitized_volumes.loc[dates[10], "AAA"] = 0.0
    unsanitized_volumes.to_csv(
        volume_path,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    unsanitized_manifest["matrixSha256"]["volumes"] = data._legacy_canonical_matrix_sha256(
        unsanitized_volumes,
        datetime_unit="s",
    )
    unsanitized_manifest["fileSha256"]["volumes"] = data._sha256_file(volume_path)
    unsanitized_manifest_path.write_text(
        json.dumps(unsanitized_manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="candidate zero-volume close policy"):
        read_market_data_snapshot(config, unsanitized_dir)
    unsanitized_manifest["readContract"] = data.SNAPSHOT_READ_CONTRACT
    for component, filename in unsanitized_manifest["files"].items():
        if component not in legacy_matrix_frames:
            continue
        frame = pd.read_csv(
            unsanitized_dir / filename,
            index_col=0,
            parse_dates=True,
            float_precision="round_trip",
        )
        unsanitized_manifest["matrixSha256"][component] = data._canonical_matrix_sha256(frame)
    unsanitized_manifest_path.write_text(
        json.dumps(unsanitized_manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="candidate zero-volume close policy"):
        read_market_data_snapshot(config, unsanitized_dir)

    legacy_dir = tmp_path / "legacy-v2-snapshot"
    shutil.copytree(snapshot_dir, legacy_dir)
    legacy_manifest_path = legacy_dir / "market_data_manifest.json"
    legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["schemaVersion"] = 2
    legacy_manifest["readContract"] = data.LEGACY_SNAPSHOT_READ_CONTRACT
    for field in ("comparisonSymbols", "comparisonPriceBasis", "comparisonAsOf"):
        legacy_manifest.pop(field)
    for component in ("comparisonPrices", "marketCaps", "marketCapSources"):
        legacy_manifest["matrixSha256"].pop(component)
        filename = legacy_manifest["files"].pop(component)
        legacy_manifest["fileSha256"].pop(component)
        (legacy_dir / filename).unlink()
    for component, frame in legacy_matrix_frames.items():
        if component in {"comparisonPrices", "marketCaps"}:
            continue
        legacy_manifest["matrixSha256"][component] = data._legacy_canonical_matrix_sha256(
            frame,
            datetime_unit="s",
        )
    legacy_manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

    legacy_replay = read_market_data_snapshot(config, legacy_dir)
    assert legacy_replay.comparison_symbols == ["SPY"]
    assert "comparisonPrices" not in legacy_replay.input_sha256
    assert any("Legacy schema-v2" in note for note in legacy_replay.notes)

    original_manifest_bytes = manifest_path.read_bytes()
    with monkeypatch.context() as scoped:
        scoped.setattr(
            data,
            "_sha256_file",
            lambda _path: (_ for _ in ()).throw(OSError("injected staging failure")),
        )
        with pytest.raises(OSError, match="injected staging failure"):
            write_market_data_snapshot(market, snapshot_dir)
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert read_market_data_snapshot(config, snapshot_dir).input_sha256 == hashes
    assert not list(snapshot_dir.parent.glob(f".{snapshot_dir.name}.staging-*"))

    original_replace = Path.replace

    def fail_staging_commit(path: Path, target: Path) -> Path:
        if path.name.startswith(f".{snapshot_dir.name}.staging-") and Path(target) == snapshot_dir:
            raise OSError("injected directory-swap failure")
        return original_replace(path, target)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "replace", fail_staging_commit)
        with pytest.raises(OSError, match="injected directory-swap failure"):
            write_market_data_snapshot(market, snapshot_dir)
    assert manifest_path.read_bytes() == original_manifest_bytes
    assert read_market_data_snapshot(config, snapshot_dir).input_sha256 == hashes
    assert not list(snapshot_dir.parent.glob(f".{snapshot_dir.name}.staging-*"))
    assert not list(snapshot_dir.parent.glob(f".{snapshot_dir.name}.backup-*"))

    for field in (
        "sourceLabel",
        "provider",
        "priceBasis",
        "volumeBasis",
        "requestedThrough",
    ):
        invalid_manifest = json.loads(json.dumps(manifest))
        invalid_manifest.pop(field)
        manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
        with pytest.raises(ValueError, match="metadata contract"):
            read_market_data_snapshot(config, snapshot_dir)
    manifest_path.write_bytes(original_manifest_bytes)

    invalid_manifest = json.loads(json.dumps(manifest))
    invalid_manifest["requestedCandidateCount"] += 1
    manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="universe counts"):
        read_market_data_snapshot(config, snapshot_dir)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    invalid_manifest = json.loads(json.dumps(manifest))
    invalid_manifest["matrixSha256"].pop("universeRecords")
    manifest_path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="input hash contract"):
        read_market_data_snapshot(config, snapshot_dir)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    changed_semantics_manifest = json.loads(json.dumps(manifest))
    changed_semantics_manifest["priceBasis"] = "mutated-adjustment-contract"
    manifest_path.write_text(json.dumps(changed_semantics_manifest), encoding="utf-8")
    changed_semantics = read_market_data_snapshot(config, snapshot_dir)
    assert build_result_identity(config, changed_semantics) != build_result_identity(config, market)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    universe_path = snapshot_dir / "universe.json"
    original_universe = universe_path.read_bytes()
    universe_path.write_bytes(original_universe + b" ")
    with pytest.raises(ValueError, match="universe file hash mismatch"):
        read_market_data_snapshot(config, snapshot_dir)
    universe_path.write_bytes(original_universe)

    price_sources_path = snapshot_dir / "price_sources.json"
    original_price_sources = price_sources_path.read_bytes()
    price_sources_path.write_bytes(original_price_sources + b" ")
    with pytest.raises(ValueError, match="priceSources file hash mismatch"):
        read_market_data_snapshot(config, snapshot_dir)
    price_sources_path.write_bytes(original_price_sources)

    prices_path = snapshot_dir / "adjusted_prices.csv.gz"
    prices_path.write_bytes(prices_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="prices file hash mismatch"):
        read_market_data_snapshot(config, snapshot_dir)


def test_record_provenance_hash_has_a_versioned_nullable_round_trip() -> None:
    frame = pd.DataFrame(
        [
            {
                "source": "provider-a",
                "status": "ok",
                "records": 42,
                "cache_hit": True,
                "ratio": 0.125,
                "error": None,
            },
            {
                "source": "provider-b",
                "status": "partial",
                "records": None,
                "cache_hit": False,
                "ratio": np.nan,
                "error": "fixture warning",
            },
        ]
    )
    records = json.loads(data._canonical_records_json_bytes(frame))

    assert data.SNAPSHOT_READ_CONTRACT["recordCanonicalization"] == (
        data.RECORD_CANONICALIZATION_VERSION
    )
    assert "candidateZeroVolumeClosePolicy" not in data.LEGACY_SNAPSHOT_READ_CONTRACT
    assert data.SNAPSHOT_READ_CONTRACT["candidateZeroVolumeClosePolicy"] == (
        "mask_adjusted_and_raw_v1"
    )
    assert data.SNAPSHOT_READ_CONTRACT["matrixCanonicalization"] == (
        data.MATRIX_CANONICALIZATION_VERSION
    )
    assert data.canonical_records_sha256(frame) == data.canonical_records_sha256(records)


def test_canonical_matrix_hash_is_datetime_unit_invariant() -> None:
    base = pd.DataFrame(
        {"AAA": [10.0, np.nan, 12.0]},
        index=pd.date_range("2026-01-02", periods=3, freq="D"),
    )
    frames = {
        unit: base.set_axis(pd.DatetimeIndex(base.index).as_unit(unit))
        for unit in data.LEGACY_MATRIX_DATETIME_UNITS
    }

    assert len({data._canonical_matrix_sha256(frame) for frame in frames.values()}) == 1
    assert (
        len(
            {
                data._legacy_canonical_matrix_sha256(frame, datetime_unit=unit)
                for unit, frame in frames.items()
            }
        )
        > 1
    )






def test_data_module_has_no_api_or_network_fallback() -> None:
    source = inspect.getsource(data).lower()
    for forbidden in ("urlopen", "requests", "yfinance", "yahoo", "api_key", "credential"):
        assert forbidden not in source
