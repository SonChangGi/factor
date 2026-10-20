import json
from pathlib import Path

from factor_lab.cli import LEGACY_SCHEDULED_ARGUMENTS, build_parser

ROOT = Path(__file__).resolve().parents[1]


def _published_actual_grid() -> list[tuple[dict[str, object], dict[str, object]]]:
    grid_root = ROOT / "docs" / "data" / "grid" / "v1"
    manifest = json.loads((grid_root / "manifest.json").read_text(encoding="utf-8"))
    entries: list[tuple[dict[str, object], dict[str, object]]] = []
    for entry in manifest["entries"]:
        detail = json.loads((grid_root / entry["detail"]["path"]).read_text(encoding="utf-8"))
        assert detail["data"]["mode"] == "live_market"
        assert detail["data"]["synthetic"] is False
        assert detail["data"]["analyzedSecurityCount"] >= 2_700
        entries.append((entry, detail))
    return entries


def _input_differences(left: dict[str, object], right: dict[str, object]) -> set[str]:
    return {key for key in set(left) | set(right) if left.get(key) != right.get(key)}


def _allocation_signature(
    detail: dict[str, object],
) -> tuple[tuple[str, ...], tuple[tuple[str, float], ...]]:
    weights = detail["bestFactorPortfolio"]["weights"]
    return (
        tuple(row["symbol"] for row in weights),
        tuple((row["symbol"], round(float(row["weight"]), 12)) for row in weights),
    )


def test_published_actual_grid_regresses_web_input_and_market_asof_outcome_changes() -> None:
    entries = _published_actual_grid()
    observed_changes: set[str] = set()
    web_input_comparisons = 0
    market_asof_comparisons = 0

    for index, (left_entry, left) in enumerate(entries):
        for right_entry, right in entries[index + 1 :]:
            differences = _input_differences(
                left_entry["normalizedInputs"],
                right_entry["normalizedInputs"],
            )
            left_symbols, left_weights = _allocation_signature(left)
            right_symbols, right_weights = _allocation_signature(right)

            if differences == {"top_n"}:
                web_input_comparisons += 1
                left_top_n = left_entry["normalizedInputs"]["top_n"]
                right_top_n = right_entry["normalizedInputs"]["top_n"]
                left_count = left["bestFactorPortfolio"]["selectedSecurityCount"]
                right_count = right["bestFactorPortfolio"]["selectedSecurityCount"]
                assert left_count == left_top_n
                assert right_count == right_top_n
                assert left_count != right_count
                assert left_symbols != right_symbols
                assert left_weights != right_weights
                observed_changes.update({"portfolio_size", "holdings", "weights"})

            if differences == {"end_date", "effective_end_date"}:
                market_asof_comparisons += 1
                assert left["data"]["asOf"] != right["data"]["asOf"]
                assert left_symbols != right_symbols
                assert left_weights != right_weights
                observed_changes.update({"holdings", "weights"})

    assert web_input_comparisons >= 1
    assert market_asof_comparisons >= 1
    assert observed_changes == {"portfolio_size", "holdings", "weights"}


def test_readme_declares_the_live_2700_factor_and_fixed_method_contract() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()

    required = (
        "2,700개 이상",
        "64개 팩터",
        "61개 독립 팩터",
        "compatibility alias 3개",
        "score_liquidity_rank",
        "0.70",
        "0.30",
        "시가총액은 이 고정 방법에 사용하지 않으며",
        "고정",
        "live_market",
        "local_file",
        "demo",
        "64개 팩터 행",
        "one-way turnover",
        "schema-v5",
        "result identity",
        "로컬 api",
    )
    for text in required:
        assert text.lower() in readme
    assert "demo는 테스트 전용" in readme
    assert "실제시장 수집 실패를 demo나 기존 정적 결과로 대체하지 않습니다" in readme
    assert "bestfactorportfolio" in readme
    assert "currentresearchtarget" not in readme


def test_methodology_matches_the_current_shared_kernel_research_contract() -> None:
    methodology = (ROOT / "docs/methodology.md").read_text(encoding="utf-8").lower()

    required = (
        "2,700",
        "64",
        "61",
        "alias",
        "score_liquidity_rank",
        "0.70",
        "0.30",
        "시가총액은 사용하지 않고",
        "factorranking",
        "cash",
        "turnover",
        "schema v5",
        "bestfactorportfolio",
        "resultidentity",
        "leave-one",
    )
    for text in required:
        assert text in methodology

    forbidden_legacy_contracts = (
        "recommendations",
        "research_signals",
        "--factor-selection-mode",
        "--frozen-policy-path",
        "--target-aum",
        "--max-adv-participation",
        "pdf",
        "excel",
        "xlsx",
    )
    for text in forbidden_legacy_contracts:
        assert text not in methodology
    assert "이전 `currentresearchtarget`" in methodology


def test_factor_catalog_documents_all_64_factors_and_alias_status() -> None:
    catalog = (ROOT / "docs/factor-catalog.md").read_text(encoding="utf-8").lower()

    assert "total factors: **64**" in catalog
    assert "independent selection-eligible factors: **61**" in catalog
    assert "compatibility aliases: **3**" in catalog
    assert "`volume_confirmed_mom_6m`" in catalog
    assert "`signed_volume_pressure_3m`" in catalog
    assert "`acceleration`" in catalog
    assert "`short_acceleration`" in catalog
    assert "`relative_strength_6m`" in catalog


def test_scheduled_dashboard_config_parses_as_uncapped_live_input() -> None:
    config_path = ROOT / ".github/factor-dashboard-config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    run_args = payload["run_args"]
    namespace = build_parser().parse_args(["run", *run_args])
    supplied_flags = {
        item.split("=", maxsplit=1)[0]
        for item in run_args
        if isinstance(item, str) and item.startswith("--")
    }

    assert namespace.command == "run"
    assert namespace.live is True
    assert namespace.demo is False
    assert namespace.prices is None
    assert namespace.max_price_symbols is None
    assert namespace.export_input_snapshot is True
    assert not supplied_flags.intersection(LEGACY_SCHEDULED_ARGUMENTS)
    assert "--demo" not in supplied_flags
    assert "--max-price-symbols" not in supplied_flags


def test_daily_workflow_runs_freshness_and_monotonic_schema_gates() -> None:
    workflow = (ROOT / ".github/workflows/daily-dashboard.yml").read_text()
    watchdog = (ROOT / ".github/workflows/daily-dashboard-watchdog.yml").read_text()
    runner = (ROOT / "factor_lab/integrated_automation.py").read_text()
    assert "factor_lab.integrated_automation freshness" in workflow
    assert "factor_lab.integrated_automation run" in workflow
    assert "factor_lab.integrated_automation promote" in workflow
    assert "scheduled-dashboard" not in workflow
    assert "--site site" in workflow and "--site site" in watchdog
    assert "continue-on-error" not in workflow and "continue-on-error" not in watchdog
    assert workflow.index("Bind current production source") < workflow.index("uv sync --frozen")
    assert 'uv==0.11.17' in workflow and 'uv==0.11.17' in watchdog
    assert 'uv sync --frozen --extra live' in workflow
    assert workflow.index('Verify the saved input cache') < workflow.index('Promote and commit')
    assert 'actions/cache/save@caa296126883cff596d87d8935842f9db880ef25' in workflow
    assert 'gh api "repos/${GITHUB_REPOSITORY}/actions/caches?key=${CACHE_KEY}"' in workflow
    assert 'inputCacheVerified' in runner and 'history_revision(' in runner
    assert 'candidateHash' in runner and 'baselineHash' in runner
    assert workflow.index('publication_security site') < workflow.index('git add -- site')
    assert 'expected_source_sha="${SOURCE_SHA}"' in workflow
    assert '--exit-status' in workflow and 'refresh-result:' in workflow
    assert '-f watchdog_origin=true' in watchdog
    assert 'latest_data_as_of' in watchdog and 'target_data_as_of' in watchdog
    assert 'latest_run_kst' not in watchdog and 'cutoff_kst' not in watchdog


def test_pages_workflow_has_one_owner_current_main_and_exact_readback() -> None:
    daily = (ROOT / ".github/workflows/daily-dashboard.yml").read_text(encoding="utf-8")
    controlled = (ROOT / ".github/workflows/controlled-analysis.yml").read_text(
        encoding="utf-8"
    )
    pages = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "actions: write" in daily
    assert "request-pages-deployment:" in daily
    assert "gh workflow run deploy-pages.yml" in daily
    assert "request_origin=daily-dashboard" in daily
    assert "actions: write" in controlled
    assert "gh workflow run deploy-pages.yml" in controlled
    assert "request_origin=controlled-analysis" in controlled
    assert "push:" in pages
    assert "workflow_dispatch:" in pages
    assert "Check out the current production branch" in pages
    assert "ref: ${{ github.event.repository.default_branch }}" in pages
    assert "Confirm workflow owns Pages publication" in pages
    assert "timeout 30s gh api" in pages
    assert '[[ "${build_type}" != "workflow" ]]' in pages
    assert "Refusing stale Pages artifact" in pages
    assert "Reject a stale main after artifact upload" in pages
    assert "Test and validate the committed static publication" in pages
    assert "actions/configure-pages@" in pages
    assert "actions/upload-pages-artifact@" in pages
    assert "actions/deploy-pages@" in pages
    assert "find public -type f -print0" in pages
    assert "path: public" in pages
    assert "python scripts/build_integrated_publication.py --output public" in pages
    assert "python scripts/validate_integrated_publication.py site" in pages
    assert '--header "Cache-Control: no-cache"' in pages
    assert "--connect-timeout 10" in pages
    assert "--max-time 120" in pages
    assert "cmp --silent" in pages
    assert "continue-on-error:" not in pages
    assert "public-site-health:" in pages
    assert "required_paths=(index.html publication.json data/integrated-result.json)" in pages
    assert "build_type=workflow" in readme
    assert "GITHUB_TOKEN" in readme
