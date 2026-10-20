from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from factor_lab.config import WEIGHTING_POLICIES
from factor_lab.data import canonical_records_sha256
from factor_lab.dashboard import (
    MAX_DASHBOARD_BYTES,
    dashboard_summary,
    externalize_factor_holding_history_sidecar,
)
from factor_lab.identity import (
    canonical_json_bytes,
    canonical_sha256,
)
from factor_lab.static_grid import (
    MAX_STATIC_GRID_ENTRIES,
    STATIC_GRID_CONTRACT,
    STATIC_GRID_VERSION,
    StaticGridArtifact,
    StaticGridContractError,
    UnsupportedStaticGridInputs,
    load_resolved_static_result,
    resolve_exact_inputs,
    validate_manifest,
    validate_static_grid,
    write_static_grid,
)
from factor_lab.workflow import (
    MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES,
    PERFORMANCE_CONTRACT_VERSION,
    AnalysisResult,
    result_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _actual_market_detail(source: AnalysisResult) -> dict[str, object]:
    detail = result_payload(source)
    analyzed_count = 2_861
    data = detail["data"]
    price_sources = [
        {
            "symbol": f"FIX{index:04d}",
            "price_source": "fixture-provider",
            "adjustment_note": "canonical actual-market fixture",
        }
        for index in range(analyzed_count)
    ]
    source_health = [
        {
            "source": "fixture-provider",
            "status": "ok",
            "records": int(data["observations"]),
            "cache_hit": False,
        }
    ]
    market_cap_sources = [
        {
            "symbol": row["symbol"],
            "mapping": "fixture",
            "taxonomy": "fixture",
            "tag": "sharesOutstanding",
            "valueKind": "shares",
            "latestMarketCapAvailable": True,
        }
        for row in price_sources
    ]
    hashes = {
        "prices": "c" * 64,
        "volumes": "d" * 64,
        "dollarVolumes": "e" * 64,
        "rawCloses": "f" * 64,
        "requestedSymbols": "1" * 64,
        "returnedSymbols": "2" * 64,
        "universeRecords": "3" * 64,
        "priceSources": canonical_records_sha256(price_sources),
        "dataSources": canonical_records_sha256(source_health),
        "comparisonPrices": "4" * 64,
        "marketCaps": "5" * 64,
        "marketCapSources": canonical_records_sha256(market_cap_sources),
    }
    data.update(
        {
            "mode": "live_market",
            "synthetic": False,
            "sourceLabel": "fixture actual-market provider",
            "provider": "fixture-provider",
            "priceBasis": "provider_adjusted_close",
            "volumeBasis": "raw_close_x_raw_volume",
            "rawCloseProxySymbolCount": 0,
            "inputSha256": hashes,
            "requestedCandidateCount": analyzed_count,
            "providerReturnedCandidateCount": analyzed_count,
            "inputSecurityCount": analyzed_count,
            "analyzedSecurityCount": analyzed_count,
            "analyzedSymbols": [row["symbol"] for row in price_sources],
            "rawCloseAvailable": True,
            "pointInTimeMarketCapAvailable": True,
            "latestMarketCapSecurityCount": analyzed_count,
            "latestMarketCapCoverageRatio": 1.0,
            "marketCapSourcesSha256": hashes["marketCapSources"],
            "comparisonPricesSha256": hashes["comparisonPrices"],
        }
    )
    data["funnel"].update(
        {
            "requestedCandidateCount": analyzed_count,
            "providerUsableCandidateCount": analyzed_count,
            "analyzedSecurityCount": analyzed_count,
        }
    )
    detail["config"]["data_mode"] = "live_market"
    detail["researchScope"]["evidenceStatus"] = "same_sample_descriptive_actual_market"
    detail["priceSources"] = price_sources
    detail["sourceHealth"] = source_health

    identity = detail["resultIdentity"]
    key_parts = identity["keyParts"]
    normalized = key_parts["normalizedInputs"]
    normalized.update({"data_mode": "live_market", "demo": False, "live": True})
    key_parts["marketSnapshot"].update(
        {
            "sourceMode": data["mode"],
            "sourceLabel": data["sourceLabel"],
            "provider": data["provider"],
            "priceBasis": data["priceBasis"],
            "volumeBasis": data["volumeBasis"],
            "rawCloseProxySymbolCount": data["rawCloseProxySymbolCount"],
            "requestedThrough": data["requestedThrough"],
            "dataAsOf": data["asOf"],
            "inputSha256": hashes,
            "requestedCandidateCount": analyzed_count,
            "providerReturnedCandidateCount": analyzed_count,
            "analyzedSecurityCount": analyzed_count,
            "candidateSymbolsSha256": canonical_sha256(data["analyzedSymbols"]),
            "comparisonSymbols": data["comparisonSymbols"],
            "comparisonPricesSha256": hashes["comparisonPrices"],
        }
    )
    result_key = canonical_sha256(key_parts)
    identity["resultKey"] = result_key
    identity["canonicalKeyPartsJson"] = canonical_json_bytes(key_parts).decode("utf-8")
    detail["resultKey"] = result_key
    sidecar_manifest = detail["factorHoldingHistorySidecar"]
    sidecar = sidecar_manifest["data"]
    sidecar["resultKey"] = result_key
    for factor_history in sidecar["factors"].values():
        factor_history["resultKey"] = result_key
    sidecar_bytes = canonical_json_bytes(sidecar)
    sidecar_manifest.update(
        {
            "resultKey": result_key,
            "path": f"data/factor-holding-history/{result_key}.json",
            "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
            "bytes": len(sidecar_bytes),
        }
    )
    return detail


@pytest.fixture(scope="session")
def canonical_actual_artifact(demo_result: AnalysisResult) -> StaticGridArtifact:
    detail = _actual_market_detail(demo_result)
    return StaticGridArtifact(detail=detail, summary=dashboard_summary(detail))


def _refresh_detail_identity(detail: dict[str, object]) -> None:
    identity = detail["resultIdentity"]
    key_parts = identity["keyParts"]
    result_key = canonical_sha256(key_parts)
    identity["resultKey"] = result_key
    identity["canonicalKeyPartsJson"] = canonical_json_bytes(key_parts).decode("utf-8")
    detail["resultKey"] = result_key
    sidecar_manifest = detail["factorHoldingHistorySidecar"]
    sidecar = sidecar_manifest["data"]
    sidecar["resultKey"] = result_key
    for factor_history in sidecar["factors"].values():
        factor_history["resultKey"] = result_key
    sidecar_bytes = canonical_json_bytes(sidecar)
    sidecar_manifest.update(
        {
            "resultKey": result_key,
            "path": f"data/factor-holding-history/{result_key}.json",
            "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
            "bytes": len(sidecar_bytes),
        }
    )


def _artifact(
    base: StaticGridArtifact,
    *,
    top_n: int = 20,
    market_variant: str | None = None,
    preset_id: str | None = None,
) -> StaticGridArtifact:
    detail = deepcopy(base.detail)
    detail["config"]["top_n"] = top_n
    detail["researchInputs"]["topN"] = top_n
    detail["allocationMethod"]["parameters"]["topN"] = top_n
    shortage_reason = "fewer_complete_policy_inputs_than_top_n"
    cash_reason = "max_weight_capacity_or_missing_policy_inputs"
    portfolios = detail["factorPortfolios"]
    for portfolio in portfolios.values():
        if portfolio["status"] != "available":
            continue
        reasons = [reason for reason in portfolio["reasons"] if reason != shortage_reason]
        if len(portfolio["weights"]) < top_n:
            insert_at = reasons.index(cash_reason) if cash_reason in reasons else len(reasons)
            reasons.insert(insert_at, shortage_reason)
        portfolio["reasons"] = reasons

    selected_factor = detail["bestFactor"]
    detail["bestFactorPortfolio"] = deepcopy(portfolios[selected_factor])
    selected_policy = detail["weightingPolicy"]
    for row in detail["factorRanking"]:
        if row["policy_id"] != selected_policy:
            continue
        portfolio = portfolios[row["factor"]]
        row["current_portfolio_input_reasons"] = (
            [] if portfolio["status"] == "available" else list(portfolio["reasons"])
        )
    identity = detail["resultIdentity"]
    key_parts = identity["keyParts"]
    key_parts["normalizedInputs"]["top_n"] = top_n
    if market_variant is not None:
        price_digest = canonical_sha256({"marketVariant": market_variant})
        detail["data"]["inputSha256"]["prices"] = price_digest
        key_parts["marketSnapshot"]["inputSha256"]["prices"] = price_digest
    _refresh_detail_identity(detail)
    summary = dashboard_summary(detail)
    return StaticGridArtifact(detail=detail, summary=summary, preset_id=preset_id)


def _remove_price_sources_hash(artifact: StaticGridArtifact) -> None:
    artifact.detail["data"]["inputSha256"].pop("priceSources")
    artifact.detail["resultIdentity"]["keyParts"]["marketSnapshot"]["inputSha256"].pop(
        "priceSources", None
    )
    _refresh_detail_identity(artifact.detail)
    artifact.summary["resultKey"] = artifact.detail["resultKey"]
    artifact.summary["resultIdentity"] = deepcopy(artifact.detail["resultIdentity"])


def _result_key(artifact: StaticGridArtifact) -> str:
    return str(artifact.detail["resultIdentity"]["resultKey"])


def test_writes_sparse_content_addressed_grid_and_default_aliases(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    first = _artifact(canonical_actual_artifact, top_n=20)
    second = _artifact(canonical_actual_artifact, top_n=35)
    default_key = _result_key(second)

    written = write_static_grid(
        tmp_path / "data",
        [first, second],
        default_result_key=default_key,
        write_default_aliases=True,
    )
    manifest_path = written["manifest"]
    manifest = validate_static_grid(manifest_path)

    assert manifest["contract"] == STATIC_GRID_CONTRACT
    assert manifest["gridVersion"] == STATIC_GRID_VERSION
    assert manifest["bounded"] is True
    assert manifest["entryCount"] == 2
    assert manifest["defaultResultKey"] == default_key
    assert {entry["resultKey"] for entry in manifest["entries"]} == {
        _result_key(first),
        _result_key(second),
    }

    for entry in manifest["entries"]:
        assert entry["normalizedInputs"] == entry["identity"]["keyParts"]["normalizedInputs"]
        assert entry["resultKey"] == entry["identity"]["resultKey"]
        for kind in ("detail", "summary"):
            path = manifest_path.parent / entry[kind]["path"]
            encoded = path.read_bytes()
            assert entry[kind]["bytes"] == len(encoded)
            assert entry[kind]["sha256"] == hashlib.sha256(encoded).hexdigest()

    default_entry = next(
        entry for entry in manifest["entries"] if entry["resultKey"] == default_key
    )
    default_detail = (manifest_path.parent / default_entry["detail"]["path"]).read_bytes()
    default_summary = (manifest_path.parent / default_entry["summary"]["path"]).read_bytes()
    published_detail = json.loads(default_detail)
    benchmark_order = published_detail["performance"]["benchmarkOrder"]
    assert benchmark_order == published_detail["config"]["comparison_benchmarks"]
    assert set(published_detail["data"]["comparisonBenchmarkAvailability"]) == set(benchmark_order)
    assert set(published_detail["performance"]["benchmarkCurves"]) == set(benchmark_order)
    assert all(
        set(period["benchmarks"]) == set(benchmark_order)
        for period in published_detail["performance"]["periods"]
    )
    assert (manifest_path.parent / "latest.json").read_bytes() == default_detail
    assert (manifest_path.parent / "latest-summary.json").read_bytes() == default_summary
    assert (tmp_path / "data" / "dashboard.json").read_bytes() == default_detail
    assert (tmp_path / "data" / "summary.json").read_bytes() == default_summary


def test_writes_unique_stable_preset_ids_for_result_key_rotation(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    first = _artifact(canonical_actual_artifact, top_n=20, preset_id="latest-top20")
    second = _artifact(
        canonical_actual_artifact,
        top_n=35,
        preset_id="latest-top35",
    )

    manifest_path = write_static_grid(
        tmp_path / "data",
        [first, second],
        default_result_key=_result_key(first),
    )["manifest"]
    manifest = validate_static_grid(manifest_path)

    assert {entry["presetId"] for entry in manifest["entries"]} == {
        "latest-top20",
        "latest-top35",
    }


@pytest.mark.parametrize(
    ("artifact_specs", "message"),
    [
        (
            [{"top_n": 20, "preset_id": "latest"}, {"top_n": 35}],
            "every entry or none",
        ),
        (
            [
                {"top_n": 20, "preset_id": "latest"},
                {"top_n": 35, "preset_id": "latest"},
            ],
            "duplicate presetId",
        ),
        ([{"preset_id": "Latest Top20"}], "lowercase stable"),
    ],
)
def test_rejects_partial_duplicate_or_invalid_preset_ids(
    artifact_specs: list[dict[str, object]],
    message: str,
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifacts = [
        _artifact(canonical_actual_artifact, **artifact_spec) for artifact_spec in artifact_specs
    ]
    with pytest.raises(StaticGridContractError, match=message):
        write_static_grid(
            tmp_path / "data",
            artifacts,
            default_result_key=_result_key(artifacts[0]),
        )


def test_rewriting_grid_prunes_content_addressed_artifacts_not_in_new_manifest(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    first = _artifact(canonical_actual_artifact, top_n=20)
    second = _artifact(canonical_actual_artifact, top_n=35)
    first_key = _result_key(first)
    second_key = _result_key(second)
    data_dir = tmp_path / "data"

    write_static_grid(
        data_dir,
        [first, second],
        default_result_key=first_key,
    )
    grid_root = data_dir / "grid" / "v1"
    assert (grid_root / "results" / f"{second_key}.json").is_file()
    assert (grid_root / "summaries" / f"{second_key}.json").is_file()

    write_static_grid(
        data_dir,
        [first],
        default_result_key=first_key,
    )

    assert (grid_root / "results" / f"{first_key}.json").is_file()
    assert (grid_root / "summaries" / f"{first_key}.json").is_file()
    assert not (grid_root / "results" / f"{second_key}.json").exists()
    assert not (grid_root / "summaries" / f"{second_key}.json").exists()


def test_rewriting_without_default_aliases_removes_previous_public_aliases(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    result_key = _result_key(artifact)
    data_dir = tmp_path / "data"
    grid_root = data_dir / "grid" / "v1"
    aliases = (
        grid_root / "latest.json",
        grid_root / "latest-summary.json",
        data_dir / "dashboard.json",
        data_dir / "summary.json",
    )

    write_static_grid(
        data_dir,
        [artifact],
        default_result_key=result_key,
        write_default_aliases=True,
    )
    assert all(path.is_file() for path in aliases)

    manifest_path = write_static_grid(
        data_dir,
        [artifact],
        default_result_key=result_key,
        write_default_aliases=False,
    )["manifest"]
    manifest = validate_static_grid(manifest_path)

    assert "defaultAliases" not in manifest
    assert all(not path.exists() and not path.is_symlink() for path in aliases)


def test_exact_tuple_resolution_has_no_partial_or_nearest_fallback(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact, top_n=20)
    manifest_path = write_static_grid(
        tmp_path / "data",
        [artifact],
        default_result_key=_result_key(artifact),
    )["manifest"]
    manifest = validate_static_grid(manifest_path)
    exact_inputs = artifact.detail["resultIdentity"]["keyParts"]["normalizedInputs"]

    entry = resolve_exact_inputs(manifest, exact_inputs)
    resolved = load_resolved_static_result(manifest_path, exact_inputs)

    assert entry["resultKey"] == _result_key(artifact)
    assert resolved.entry == entry
    expected_detail, expected_sidecar = externalize_factor_holding_history_sidecar(artifact.detail)
    assert expected_sidecar is not None
    assert resolved.detail == expected_detail
    assert resolved.summary == artifact.summary
    with pytest.raises(UnsupportedStaticGridInputs, match="local backend/API"):
        resolve_exact_inputs(manifest, {"top_n": 20})
    with pytest.raises(UnsupportedStaticGridInputs, match="local backend/API"):
        resolve_exact_inputs(manifest, {**exact_inputs, "top_n": 21})


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda artifact: artifact.detail["data"].update({"synthetic": True, "mode": "demo"}),
            "actual-market, non-synthetic",
        ),
        (
            lambda artifact: artifact.detail["data"].update(
                {"synthetic": False, "mode": "local_file"}
            ),
            "actual-market, non-synthetic",
        ),
        (
            lambda artifact: artifact.detail["data"].update({"analyzedSecurityCount": 2_699}),
            "at least 2,700 securities",
        ),
        (
            lambda artifact: artifact.summary.update({"bestFactor": "different"}),
            "summary differs from canonical",
        ),
        (
            lambda artifact: artifact.summary.update({"weights": [], "cashWeight": 1.0}),
            "summary differs from canonical",
        ),
        (
            lambda artifact: artifact.detail["bestFactorPortfolio"]["weights"][0].update(
                {"weight": -0.25}
            ),
            "schema-v5 dashboard contract",
        ),
        (
            lambda artifact: artifact.summary.update({"resultIdentity": {}}),
            "summary differs from canonical",
        ),
        (
            lambda artifact: artifact.detail.update({"resultKey": "f" * 64}),
            "differs from resultIdentity.resultKey",
        ),
    ],
)
def test_rejects_non_actual_or_non_parity_payloads(
    mutator,
    message: str,
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    mutator(artifact)

    with pytest.raises(StaticGridContractError, match=message):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("researchScope", "missing schema-v5 fields: researchScope"),
        ("selectionMethod", "missing schema-v5 fields: selectionMethod"),
        ("bestFactorTransition", "missing schema-v5 fields: bestFactorTransition"),
        ("priceSources", "provider provenance contract is incomplete"),
        ("sourceHealth", "provider provenance contract is incomplete"),
    ],
)
def test_rejects_partial_payload_missing_browser_or_quant_contract(
    field: str,
    message: str,
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    del artifact.detail[field]

    with pytest.raises(StaticGridContractError, match=message):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_one_factor_partial_schema_v5_payload(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    detail = artifact.detail
    selected_factor = detail["bestFactor"]
    detail["factorDefinitions"] = [
        next(
            definition
            for definition in detail["factorDefinitions"]
            if definition["factor"] == selected_factor
        )
    ]
    detail["factorRanking"] = [
        next(row for row in detail["factorRanking"] if row["factor"] == selected_factor)
    ]

    with pytest.raises(StaticGridContractError, match="schema-v5 dashboard contract"):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda artifact: artifact.detail["researchScope"].update({"researchOnly": False}),
            "summary differs from canonical",
        ),
        (
            _remove_price_sources_hash,
            "input snapshot hash contract is incomplete",
        ),
        (
            lambda artifact: artifact.detail["priceSources"].__setitem__(
                1, deepcopy(artifact.detail["priceSources"][0])
            ),
            "priceSources rows are invalid or duplicated",
        ),
        (
            lambda artifact: artifact.detail.update(
                {"priceSources": artifact.detail["priceSources"][:-1]}
            ),
            "priceSources do not cover the analyzed universe",
        ),
        (
            lambda artifact: artifact.detail["sourceHealth"][0].update({"status": ""}),
            "sourceHealth source/status rows are invalid",
        ),
    ],
)
def test_rejects_incomplete_or_ambiguous_public_provenance(
    mutator,
    message: str,
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    mutator(artifact)

    with pytest.raises(StaticGridContractError, match=message):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_summary_that_is_not_exact_canonical_generated_summary(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    artifact.summary["researchOnly"] = False

    with pytest.raises(
        StaticGridContractError,
        match=r"summary differs from canonical dashboard_summary\(detail\)",
    ):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_detail_larger_than_dashboard_publication_limit(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    artifact.detail["publicationPadding"] = "x" * MAX_DASHBOARD_BYTES
    assert len(canonical_json_bytes(artifact.detail)) > MAX_DASHBOARD_BYTES

    with pytest.raises(
        StaticGridContractError,
        match=rf"detail payload is .* bytes; limit is {MAX_DASHBOARD_BYTES:,}",
    ):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_sidecar_larger_than_publication_limit_before_writing(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    original_externalize = externalize_factor_holding_history_sidecar

    def oversized_externalize(detail):
        public_detail, sidecar_bytes = original_externalize(detail)
        assert sidecar_bytes is not None
        oversized = b"x" * (MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES + 1)
        manifest = public_detail["factorHoldingHistorySidecar"]
        manifest["bytes"] = len(oversized)
        manifest["sha256"] = hashlib.sha256(oversized).hexdigest()
        return public_detail, oversized

    monkeypatch.setattr(
        "factor_lab.static_grid.externalize_factor_holding_history_sidecar",
        oversized_externalize,
    )
    data_dir = tmp_path / "data"

    with pytest.raises(
        StaticGridContractError,
        match=rf"limit is {MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:,}",
    ):
        write_static_grid(
            data_dir,
            [artifact],
            default_result_key=_result_key(artifact),
        )
    assert not data_dir.exists()


def _add_excluded_independent_pair(artifact: StaticGridArtifact) -> None:
    detail = artifact.detail
    summary = artifact.summary
    excluded_factor = next(
        definition["factor"]
        for definition in detail["factorDefinitions"]
        if definition.get("selection_eligible") is True
        and definition["factor"] != detail["bestFactor"]
    )
    row = next(
        row
        for row in detail["factorRanking"]
        if row["factor"] == excluded_factor and row["policy_id"] == WEIGHTING_POLICIES[0]
    )
    row.update(
        {
            "comparison_status": "insufficient_history",
            "exclusion_reason_codes": ["insufficient_observations"],
            "exclusion_reasons": [
                {
                    "code": "insufficient_observations",
                    "observed": 100,
                    "required": 504,
                }
            ],
        }
    )
    detail["factorAccounting"] = {
        **detail["factorAccounting"],
        "availableIndependentFactorCount": 60,
        "excludedIndependentFactorCount": 1,
        "commonComparableFactorCount": 60,
        "exclusionReasonCounts": {"insufficient_observations": 1},
    }
    summary["factorAccounting"] = deepcopy(detail["factorAccounting"])


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"expectedIndependentFactorCount": 999}
            ),
            "factorAccounting is inconsistent",
        ),
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"availableIndependentFactorCount": 0}
            ),
            "factorAccounting is inconsistent",
        ),
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"evaluatedIndependentFactorCount": 0}
            ),
            "factorAccounting is inconsistent",
        ),
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"excludedIndependentFactorCount": 1}
            ),
            "factorAccounting is inconsistent",
        ),
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"missingIndependentFactorCount": 1}
            ),
            "factorAccounting is inconsistent",
        ),
        (
            lambda artifact: artifact.detail["factorAccounting"].update(
                {"expectedIndependentFactorCount": True}
            ),
            "factorAccounting is inconsistent",
        ),
    ],
)
def test_rejects_inconsistent_independent_grid_counts(
    mutator,
    message: str,
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    mutator(artifact)

    with pytest.raises(StaticGridContractError, match=message):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_inconsistent_independent_exclusion_reason_totals(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    _add_excluded_independent_pair(artifact)
    artifact.detail["factorAccounting"]["exclusionReasonCounts"] = {"fabricated_reason": 1}
    artifact.summary["factorAccounting"] = deepcopy(artifact.detail["factorAccounting"])

    with pytest.raises(StaticGridContractError, match="schema-v5 dashboard contract"):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_summary_grid_accounting_that_differs_from_detail(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    artifact.summary["factorAccounting"] = {
        **artifact.summary["factorAccounting"],
        "expectedIndependentFactorCount": 999,
    }

    with pytest.raises(StaticGridContractError, match="summary differs from canonical"):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_exclusion_code_that_differs_from_structured_reason(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    _add_excluded_independent_pair(artifact)
    excluded = next(
        row
        for row in artifact.detail["factorRanking"]
        if row["comparison_status"] == "insufficient_history"
    )
    excluded["exclusion_reason_codes"] = ["fabricated_reason"]

    with pytest.raises(StaticGridContractError, match="schema-v5 dashboard contract"):
        write_static_grid(
            tmp_path / "data",
            [artifact],
            default_result_key=_result_key(artifact),
        )


def test_rejects_duplicate_result_keys_and_input_tuples(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    with pytest.raises(StaticGridContractError, match="duplicate resultKey"):
        write_static_grid(
            tmp_path / "duplicate-key",
            [artifact, artifact],
            default_result_key=_result_key(artifact),
        )

    first = _artifact(canonical_actual_artifact, market_variant="first")
    second = _artifact(canonical_actual_artifact, market_variant="second")

    with pytest.raises(StaticGridContractError, match="duplicate normalized input tuple"):
        write_static_grid(
            tmp_path / "duplicate-inputs",
            [first, second],
            default_result_key=_result_key(first),
        )


def test_rejects_missing_default_and_bound_overflow(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    with pytest.raises(StaticGridContractError, match="not present"):
        write_static_grid(
            tmp_path / "missing-default",
            [artifact],
            default_result_key="f" * 64,
        )
    with pytest.raises(StaticGridContractError, match="cannot exceed"):
        write_static_grid(
            tmp_path / "bad-bound",
            [artifact],
            default_result_key=_result_key(artifact),
            max_entries=MAX_STATIC_GRID_ENTRIES + 1,
        )


def test_validator_fails_closed_on_missing_hash_and_manifest_parity(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    artifact = _artifact(canonical_actual_artifact)
    result_key = _result_key(artifact)
    manifest_path = write_static_grid(
        tmp_path / "data",
        [artifact],
        default_result_key=result_key,
    )["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    detail_path = manifest_path.parent / entry["detail"]["path"]
    original = detail_path.read_bytes()
    replacement = b"[" + original[1:]
    detail_path.write_bytes(replacement)
    with pytest.raises(StaticGridContractError, match="SHA-256 differs"):
        validate_static_grid(manifest_path)

    detail_path.write_bytes(original + b"\n")
    with pytest.raises(StaticGridContractError, match="byte count differs"):
        validate_static_grid(manifest_path)
    detail_path.unlink()
    with pytest.raises(StaticGridContractError, match="missing or unreadable"):
        validate_static_grid(manifest_path)

    manifest["entries"][0]["normalizedInputs"]["top_n"] = 999
    with pytest.raises(StaticGridContractError, match="differs from identity"):
        validate_manifest(manifest)


def test_validator_rejects_alias_that_is_not_default_copy(
    canonical_actual_artifact: StaticGridArtifact,
    tmp_path: Path,
) -> None:
    first = _artifact(canonical_actual_artifact, top_n=20)
    second = _artifact(canonical_actual_artifact, top_n=30)
    manifest_path = write_static_grid(
        tmp_path / "data",
        [first, second],
        default_result_key=_result_key(first),
        write_default_aliases=True,
    )["manifest"]
    other_bytes = (manifest_path.parent / f"results/{_result_key(second)}.json").read_bytes()
    alias_path = manifest_path.parent / "latest.json"
    alias_path.write_bytes(other_bytes)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference = manifest["defaultAliases"]["artifacts"]["latestDetail"]
    reference["bytes"] = len(other_bytes)
    reference["sha256"] = hashlib.sha256(other_bytes).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(StaticGridContractError, match="not a byte-for-byte copy"):
        validate_static_grid(manifest_path)


def test_tracked_three_entry_grid_matches_one_complete_publication_contract(
    tmp_path: Path,
) -> None:
    manifest_path = ROOT / "docs" / "data" / "grid" / "v1" / "manifest.json"
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = validate_manifest(raw_manifest)
    assert manifest["entryCount"] == 3

    artifacts = []
    for entry in manifest["entries"]:
        detail = json.loads(
            (manifest_path.parent / entry["detail"]["path"]).read_text(encoding="utf-8")
        )
        sidecar_manifest = detail.get("factorHoldingHistorySidecar")
        if isinstance(sidecar_manifest, dict) and sidecar_manifest.get("storage") == "external":
            sidecar_path = ROOT / "docs" / str(sidecar_manifest["path"])
            sidecar_manifest["storage"] = "embedded"
            sidecar_manifest["data"] = json.loads(sidecar_path.read_text(encoding="utf-8"))
        artifacts.append(
            StaticGridArtifact(
                detail=detail,
                summary=json.loads(
                    (manifest_path.parent / entry["summary"]["path"]).read_text(encoding="utf-8")
                ),
                preset_id=entry.get("presetId"),
            )
        )
    performance_contracts = {
        artifact.detail.get("performance", {}).get("contractVersion") for artifact in artifacts
    }
    if performance_contracts == {None}:
        # The checked-in publication predates the Python-owned period and
        # comparison-benchmark contract.  Preserve and verify that deployment
        # byte-for-byte until an explicitly approved three-run regeneration;
        # do not pretend it satisfies the stricter current publication schema.
        for entry in manifest["entries"]:
            for kind in ("detail", "summary"):
                reference = entry[kind]
                encoded = (manifest_path.parent / reference["path"]).read_bytes()
                assert len(encoded) == reference["bytes"]
                assert hashlib.sha256(encoded).hexdigest() == reference["sha256"]

        default_entry = next(
            entry
            for entry in manifest["entries"]
            if entry["resultKey"] == manifest["defaultResultKey"]
        )
        default_bytes = {
            "detail": (manifest_path.parent / default_entry["detail"]["path"]).read_bytes(),
            "summary": (manifest_path.parent / default_entry["summary"]["path"]).read_bytes(),
        }
        for name, reference in manifest["defaultAliases"]["artifacts"].items():
            encoded = (manifest_path.parent / reference["path"]).read_bytes()
            assert len(encoded) == reference["bytes"]
            assert hashlib.sha256(encoded).hexdigest() == reference["sha256"]
            expected_kind = "summary" if "Summary" in name else "detail"
            assert encoded == default_bytes[expected_kind]

        with pytest.raises(
            StaticGridContractError,
            match=(
                r"^detail fails the canonical schema-v4 dashboard contract: "
                r"dashboard payload missing fields: "
                r"factorDiagnostics, factorHoldingHistorySidecar, "
                r"selectedBacktestHoldingHistory$"
            ),
        ):
            validate_static_grid(manifest_path)
        return

    assert performance_contracts == {PERFORMANCE_CONTRACT_VERSION}, (
        "tracked static-grid publication mixes legacy and current performance contracts"
    )
    manifest = validate_static_grid(manifest_path)
    rebuilt_path = write_static_grid(
        tmp_path / "data",
        artifacts,
        default_result_key=manifest["defaultResultKey"],
        write_default_aliases=True,
    )["manifest"]
    rebuilt = validate_static_grid(rebuilt_path)

    assert rebuilt["entryCount"] == 3
    assert rebuilt["defaultResultKey"] == manifest["defaultResultKey"]
    assert {entry["resultKey"] for entry in rebuilt["entries"]} == {
        entry["resultKey"] for entry in manifest["entries"]
    }
