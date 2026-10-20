from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any, Callable

import pandas as pd
import pytest

from factor_lab.config import MAX_TOP_N, RunConfig
from factor_lab.data import (
    MarketData,
    _canonical_matrix_sha256,
    _ordered_symbols_sha256,
    canonical_records_sha256,
)
from factor_lab.identity import build_result_identity, canonical_json_bytes
from factor_lab.local_api import (
    MIN_FULL_UNIVERSE_SECURITY_COUNT,
    LocalAPIConfigurationError,
    LocalResearchAPI,
    SynchronousJobExecutor,
)
from factor_lab.research_inputs import ResearchInputs
from factor_lab.universe import DEFAULT_UNIVERSE
from factor_lab.workflow import AnalysisResult, result_payload


_CANONICAL_PAYLOAD_TEMPLATE: dict[str, Any] | None = None


@pytest.fixture(scope="module", autouse=True)
def _canonical_payload_template(demo_result: AnalysisResult):
    global _CANONICAL_PAYLOAD_TEMPLATE
    _CANONICAL_PAYLOAD_TEMPLATE = result_payload(demo_result)
    yield
    _CANONICAL_PAYLOAD_TEMPLATE = None


def _base_config(tmp_path: Path, **overrides: object) -> RunConfig:
    values: dict[str, object] = {
        "live": True,
        "start_date": "2020-01-01",
        "end_date": "2026-07-10",
        "cache_dir": tmp_path / "cache",
        "output_dir": tmp_path / "output",
        "site_dir": tmp_path / "site",
    }
    values.update(overrides)
    return RunConfig(**values)


def _market(
    *,
    source_mode: str = "live_market",
    analyzed_count: int = MIN_FULL_UNIVERSE_SECURITY_COUNT,
    requested_count: int | None = None,
) -> MarketData:
    symbols = list(DEFAULT_UNIVERSE[:analyzed_count])
    resolved_requested_count = (
        requested_count if requested_count is not None else len(DEFAULT_UNIVERSE)
    )
    requested_symbols = list(DEFAULT_UNIVERSE[:resolved_requested_count])
    date = pd.Timestamp("2026-07-10")
    columns = ["SPY", *symbols]
    prices = pd.DataFrame([[100.0] * len(columns)], index=[date], columns=columns)
    comparison_prices = pd.DataFrame(
        [[100.0, 100.0, 100.0]],
        index=[date],
        columns=["SPY", "^IXIC", "QQQ"],
    )
    candidate = prices[symbols]
    volumes = candidate * 1_000.0
    dollar_volumes = candidate * 100_000.0
    raw_closes = prices.copy()
    market_caps = prices.mul(100_000_000.0)
    universe = pd.DataFrame({"symbol": requested_symbols, "name": requested_symbols})
    price_sources = pd.DataFrame(
        {"symbol": symbols, "price_source": ["fixture-live-provider"] * len(symbols)}
    )
    data_sources = pd.DataFrame([{"source": "fixture-live-provider", "status": "ok"}])
    market_cap_sources = pd.DataFrame(
        {
            "symbol": symbols,
            "mapping": ["fixture"] * len(symbols),
            "taxonomy": ["fixture"] * len(symbols),
            "tag": ["sharesOutstanding"] * len(symbols),
            "valueKind": ["shares"] * len(symbols),
            "latestMarketCapAvailable": [True] * len(symbols),
        }
    )
    return MarketData(
        prices=prices,
        volumes=volumes,
        dollar_volumes=dollar_volumes,
        raw_closes=raw_closes,
        eligibility_mask=pd.DataFrame(True, index=[date], columns=columns),
        quality=pd.DataFrame(),
        universe=universe,
        as_of=date,
        source_mode=source_mode,
        source_label="fixture-live-provider",
        price_basis="provider_adjusted_close",
        volume_basis="raw_share_volume",
        input_sha256={
            "prices": _canonical_matrix_sha256(prices),
            "volumes": _canonical_matrix_sha256(
                volumes.reindex(index=prices.index, columns=prices.columns)
            ),
            "dollarVolumes": _canonical_matrix_sha256(
                dollar_volumes.reindex(index=prices.index, columns=prices.columns)
            ),
            "rawCloses": _canonical_matrix_sha256(raw_closes),
            "requestedSymbols": _ordered_symbols_sha256(requested_symbols),
            "returnedSymbols": _ordered_symbols_sha256(symbols),
            "universeRecords": canonical_records_sha256(universe),
            "priceSources": canonical_records_sha256(price_sources),
            "dataSources": canonical_records_sha256(data_sources),
            "comparisonPrices": _canonical_matrix_sha256(comparison_prices),
            "marketCaps": _canonical_matrix_sha256(market_caps),
            "marketCapSources": canonical_records_sha256(market_cap_sources),
        },
        benchmark="SPY",
        requested_through="2026-07-10",
        requested_candidate_count=resolved_requested_count,
        provider_returned_candidate_count=analyzed_count,
        provider="fixture-live-provider",
        price_sources=price_sources,
        data_sources=data_sources,
        comparison_prices=comparison_prices,
        market_caps=market_caps,
        market_cap_sources=market_cap_sources,
    )


def _payload(config: RunConfig, market: MarketData) -> dict[str, Any]:
    assert _CANONICAL_PAYLOAD_TEMPLATE is not None
    payload = deepcopy(_CANONICAL_PAYLOAD_TEMPLATE)
    identity = build_result_identity(config, market)
    result_key = str(identity["resultKey"])
    config_values = json.loads(canonical_json_bytes(config.to_dict()))
    public_config = payload["config"]
    for field in public_config:
        if field in config_values:
            public_config[field] = config_values[field]

    as_of = market.as_of.date().isoformat()
    analyzed_symbols = list(market.candidate_symbols)
    latest_eligible = int(payload["bestFactorPortfolio"]["eligibleSecurityCount"])
    data = payload["data"]
    data.update(
        {
            "mode": "live_market",
            "synthetic": False,
            "sourceLabel": market.source_label,
            "provider": market.provider,
            "priceBasis": market.price_basis,
            "volumeBasis": market.volume_basis,
            "inputSha256": market.input_sha256,
            "requestedThrough": market.requested_through,
            "asOf": as_of,
            "startDate": market.prices.index.min().date().isoformat(),
            "requestedCandidateCount": market.requested_candidate_count,
            "providerReturnedCandidateCount": market.provider_returned_candidate_count,
            "inputSecurityCount": len(analyzed_symbols),
            "analyzedSecurityCount": len(analyzed_symbols),
            "analyzedSymbols": analyzed_symbols,
            "latestEligibleSecurityCount": latest_eligible,
            "latestMarketCapSecurityCount": len(analyzed_symbols),
            "latestMarketCapCoverageRatio": 1.0,
            "rawCloseProxySymbolCount": market.raw_close_proxy_symbol_count,
            "rawCloseAvailable": not market.raw_closes.empty,
            "benchmark": market.benchmark,
            "benchmarkAvailable": market.benchmark in market.prices,
            "chartBenchmark": config.chart_benchmark,
            "additionalComparisonBenchmarks": list(config.additional_comparison_benchmarks),
            "comparisonBenchmarkAvailability": {
                symbol: bool(
                    symbol in market.comparison_prices
                    and market.comparison_prices[symbol].notna().any()
                )
                for symbol in config.comparison_benchmarks
            },
            "comparisonSymbols": list(market.comparison_symbols),
            "comparisonPricesSha256": market.input_sha256.get("comparisonPrices"),
            "liquidityFilterApplied": config.min_avg_dollar_volume > 0.0,
            "notes": list(market.notes),
        }
    )
    data["funnel"].update(
        {
            "requestedCandidateCount": market.requested_candidate_count,
            "providerUsableCandidateCount": market.provider_returned_candidate_count,
            "analyzedSecurityCount": len(analyzed_symbols),
            "latestEligibleSecurityCount": latest_eligible,
        }
    )

    payload["resultKey"] = result_key
    payload["resultIdentity"] = identity
    payload["researchInputs"] = ResearchInputs.from_config(config).to_dict()
    payload["priceSources"] = market.price_sources.to_dict(orient="records")
    payload["sourceHealth"] = market.data_sources.to_dict(orient="records")
    payload["researchScope"]["evidenceStatus"] = "same_sample_descriptive_actual_market"
    payload["bestFactorPortfolio"]["asOf"] = as_of
    payload["bestFactorPortfolio"]["signalDate"] = as_of
    payload["backtestHeldPortfolio"]["asOf"] = as_of
    payload["bestFactorTransition"]["asOf"] = as_of
    payload["bestFactorTransition"]["targetSignalDate"] = as_of
    factor_diagnostics = payload["factorDiagnostics"]
    rank_ic = factor_diagnostics["rankIc"]
    rank_ic["signalDates"][-1] = as_of
    rank_ic["requestedEndDate"] = as_of
    factor_diagnostics["redundancy"]["diagnosticDate"] = as_of
    for portfolio in payload["factorPortfolios"].values():
        portfolio["asOf"] = as_of
        portfolio["signalDate"] = as_of
    performance = payload["performance"]
    performance["dates"][-1] = as_of
    holding_history = payload["bestFactorBacktestHoldingHistory"]
    canonical_history_dates = performance["dates"][-holding_history["sessionCount"] :]
    for session, session_date in zip(
        holding_history["sessions"],
        canonical_history_dates,
        strict=True,
    ):
        session["date"] = session_date
    holding_history["startDate"] = canonical_history_dates[0]
    holding_history["endDate"] = canonical_history_dates[-1]
    for symbol, available in data["comparisonBenchmarkAvailability"].items():
        curve = performance["benchmarkCurves"].get(symbol)
        if available and (
            not isinstance(curve, list)
            or len(curve) != len(performance["dates"])
            or curve[-1] is None
        ):
            performance["benchmarkCurves"][symbol] = [None] * (len(performance["dates"]) - 1) + [
                1.0
            ]
        elif not available:
            performance["benchmarkCurves"][symbol] = None
    performance["benchmarkCurve"] = performance["benchmarkCurves"][market.benchmark]
    for period in performance["periods"]:
        period["endDate"] = as_of
    payload["factorSelectionDecision"]["evaluationEnd"] = as_of
    payload["contributionDiagnostics"]["evaluationEnd"] = as_of
    for field in (
        "factorDefinitionSha256",
        "policyDefinitionSha256",
        "selectionSpecSha256",
    ):
        payload["meta"][field] = identity["keyParts"][field]
    sidecar_manifest = payload["factorHoldingHistorySidecar"]
    sidecar = sidecar_manifest["data"]
    sidecar["resultKey"] = result_key
    sidecar["dates"] = canonical_history_dates
    sidecar["startDate"] = canonical_history_dates[0]
    sidecar["endDate"] = canonical_history_dates[-1]
    sidecar["factorDefinitionSha256"] = payload["meta"]["factorDefinitionSha256"]
    sidecar["policyDefinitionSha256"] = payload["meta"]["policyDefinitionSha256"]
    for factor_history in sidecar["factors"].values():
        factor_history["resultKey"] = result_key
    sidecar_bytes = canonical_json_bytes(sidecar)
    sidecar_manifest.update(
        {
            "resultKey": result_key,
            "path": f"data/factor-holding-history/{result_key}.json",
            "startDate": canonical_history_dates[0],
            "endDate": canonical_history_dates[-1],
            "sha256": hashlib.sha256(sidecar_bytes).hexdigest(),
            "bytes": len(sidecar_bytes),
        }
    )
    return payload


def _api(
    tmp_path: Path,
    *,
    market: MarketData | None = None,
    executor=None,
    runner=None,
    cache_loader=None,
    cache_writer=None,
) -> tuple[LocalResearchAPI, list[tuple[RunConfig, MarketData]]]:
    selected_market = market or _market()
    calls: list[tuple[RunConfig, MarketData]] = []

    def default_runner(config: RunConfig, *, market_data: MarketData):
        calls.append((config, market_data))
        return SimpleNamespace(config=config, market=market_data)

    def payload_builder(result: SimpleNamespace):
        return _payload(result.config, result.market)

    kwargs = {}
    if cache_loader is not None:
        kwargs["cache_loader"] = cache_loader
    if cache_writer is not None:
        kwargs["cache_writer"] = cache_writer
    api = LocalResearchAPI(
        _base_config(tmp_path),
        executor=executor or SynchronousJobExecutor(),
        market_loader=lambda _config: selected_market,
        analysis_runner=runner or default_runner,
        payload_builder=payload_builder,
        **kwargs,
    )
    return api, calls


def _post(api: LocalResearchAPI, inputs: ResearchInputs | None = None):
    selected = inputs or ResearchInputs()
    return api.dispatch("POST", "/api/runs", canonical_json_bytes(selected.to_dict()))


PayloadMutation = Callable[[dict[str, Any]], None]


def _omit_factor_policy_ranking(payload: dict[str, Any]) -> None:
    payload.pop("factorRanking")


def _omit_selection_decision(payload: dict[str, Any]) -> None:
    payload.pop("factorSelectionDecision")


def _omit_current_research_target(payload: dict[str, Any]) -> None:
    payload.pop("bestFactorPortfolio")


def _mutate_guardrail_profile(payload: dict[str, Any]) -> None:
    payload["factorSelectionDecision"]["guardrailProfile"]["rules"][0]["threshold"] += 0.01


def _selected_row(payload: dict[str, Any]) -> dict[str, Any]:
    return next(row for row in payload["factorRanking"] if row["selected"] is True)


def _fail_selected_historical_concentration(payload: dict[str, Any]) -> None:
    _selected_row(payload)["min_target_effective_names"] = 0.0


def _fail_selected_current_concentration(payload: dict[str, Any]) -> None:
    _selected_row(payload)["current_target_hhi"] = 1.0


def _fail_selected_eligibility(payload: dict[str, Any]) -> None:
    _selected_row(payload)["selection_eligible"] = False


def _http_request(
    api: LocalResearchAPI,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    server = api.create_http_server(port=0)
    worker = Thread(target=server.handle_request)
    worker.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    encoded = response.read()
    response_headers = {key: value for key, value in response.getheaders()}
    status = response.status
    connection.close()
    worker.join(timeout=5)
    server.server_close()
    assert not worker.is_alive()
    return status, response_headers, encoded


def test_capabilities_and_loopback_http_server_contract(tmp_path: Path) -> None:
    api, _ = _api(tmp_path)

    response = api.dispatch("GET", "/api/capabilities")
    server = api.create_http_server(port=0)

    assert response.status_code == 200
    assert response.body["contract"] == "momentum-local-research-api"
    assert response.body["actualMarketOnly"] is True
    assert response.body["fullUniverseMinimum"] == 2_700
    assert response.body["demoSupported"] is False
    assert response.body["syntheticFallback"] is False
    assert response.body["staticPresetFallback"] is False
    assert response.body["researchInputs"]["defaults"] == ResearchInputs().to_dict()
    assert response.body["researchInputs"]["limits"]["topN"] == {
        "minimum": 1,
        "maximum": MAX_TOP_N,
    }
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()
    api.close()


def test_loopback_http_server_allows_project_pages_cors_preflight(tmp_path: Path) -> None:
    api, _ = _api(tmp_path)
    origin = "https://sonchanggi.github.io"

    status, headers, _ = _http_request(
        api,
        "OPTIONS",
        "/api/runs",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    api.close()

    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == origin
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Vary"] == "Origin"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "https://127.0.0.1:4443",
        "http://127.0.0.2",
        "http://[::1]:8765",
    ],
)
def test_loopback_browser_origins_allow_arbitrary_local_ports(
    tmp_path: Path,
    origin: str,
) -> None:
    api, _ = _api(tmp_path)

    status, headers, _ = _http_request(
        api,
        "OPTIONS",
        "/api/runs",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    api.close()

    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == origin
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Vary"] == "Origin"


def test_constructor_adds_exact_allowed_browser_origin(tmp_path: Path) -> None:
    origin = "https://research.example:4443"
    api = LocalResearchAPI(
        _base_config(tmp_path),
        allowed_origins={origin},
        executor=SynchronousJobExecutor(),
        market_loader=lambda _config: _market(),
    )

    status, headers, _ = _http_request(
        api,
        "GET",
        "/api/capabilities",
        headers={"Origin": origin},
    )
    api.close()

    assert status == 200
    assert headers["Access-Control-Allow-Origin"] == origin
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Vary"] == "Origin"


@pytest.mark.parametrize(
    "allowed_origins",
    [
        "https://research.example",
        {"*"},
        {"null"},
        {"https://research.example/path"},
        {"ftp://research.example"},
        {"http://[::1"},
    ],
)
def test_constructor_rejects_non_exact_allowed_origins(
    tmp_path: Path,
    allowed_origins,
) -> None:
    with pytest.raises(LocalAPIConfigurationError, match="allowed_origins"):
        LocalResearchAPI(
            _base_config(tmp_path),
            allowed_origins=allowed_origins,
            executor=SynchronousJobExecutor(),
        )


def test_originless_cli_http_request_remains_allowed_without_cors_header(tmp_path: Path) -> None:
    api, _ = _api(tmp_path)

    status, headers, encoded = _http_request(api, "GET", "/api/capabilities")
    api.close()

    assert status == 200
    assert json.loads(encoded)["contract"] == "momentum-local-research-api"
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Vary"] == "Origin"


def test_allowed_pages_origin_post_reflects_origin_and_runs_analysis(tmp_path: Path) -> None:
    api, calls = _api(tmp_path)
    origin = "https://sonchanggi.github.io"
    body = canonical_json_bytes(ResearchInputs().to_dict())

    status, headers, _ = _http_request(
        api,
        "POST",
        "/api/runs",
        body=body,
        headers={"Origin": origin, "Content-Type": "application/json"},
    )
    api.close()

    assert status == 202
    assert headers["Access-Control-Allow-Origin"] == origin
    assert headers["Access-Control-Allow-Private-Network"] == "true"
    assert headers["Vary"] == "Origin"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("OPTIONS", "/api/runs", None),
        ("GET", "/api/capabilities", None),
        ("POST", "/api/runs", canonical_json_bytes(ResearchInputs().to_dict())),
    ],
)
def test_external_browser_origin_is_403_before_dispatch_or_market_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: bytes | None,
) -> None:
    market_calls = []
    dispatch_calls = []

    def market_loader(config: RunConfig) -> MarketData:
        market_calls.append(config)
        return _market()

    api = LocalResearchAPI(
        _base_config(tmp_path),
        executor=SynchronousJobExecutor(),
        market_loader=market_loader,
    )

    def dispatch(
        dispatch_method: str,
        dispatch_path: str,
        dispatch_body: bytes | None = None,
    ) -> None:
        dispatch_calls.append((dispatch_method, dispatch_path, dispatch_body))
        raise AssertionError("forbidden Origin reached API dispatch")

    monkeypatch.setattr(api, "dispatch", dispatch)
    origin = "https://attacker.example"
    headers = {
        "Origin": origin,
        "Content-Type": "application/json",
        "Access-Control-Request-Method": "POST",
    }

    status, response_headers, encoded = _http_request(
        api,
        method,
        path,
        body=body,
        headers=headers,
    )
    api.close()

    assert status == 403
    assert json.loads(encoded)["error"]["code"] == "origin_forbidden"
    assert "Access-Control-Allow-Origin" not in response_headers
    assert "Access-Control-Allow-Private-Network" not in response_headers
    assert response_headers["Vary"] == "Origin"
    assert dispatch_calls == []
    assert market_calls == []


def test_cache_miss_is_202_then_get_returns_canonical_result_and_next_post_is_200(
    tmp_path: Path,
) -> None:
    api, calls = _api(tmp_path)

    submitted = _post(api)
    result_key = submitted.body["resultKey"]
    status = api.dispatch("GET", f"/api/runs/{result_key}")
    cached = _post(api)

    assert submitted.status_code == 202
    assert submitted.body["status"] == "complete", status.body
    assert submitted.body["statusUrl"] == f"/api/runs/{result_key}"
    assert "result" not in submitted.body
    assert status.status_code == 200
    assert status.body["status"] == "complete"
    assert status.body["result"]["schemaVersion"] == 5
    assert status.body["result"]["resultKey"] == result_key
    assert status.body["result"]["resultIdentity"]["resultKey"] == result_key
    assert len(status.body["result"]["factorRanking"]) == 64
    accounting = status.body["result"]["factorAccounting"]
    assert accounting["independentFactorCount"] == 61
    assert accounting["expectedIndependentFactorCount"] == 61
    assert accounting["evaluatedIndependentFactorCount"] == 61
    assert (
        accounting["availableIndependentFactorCount"] + accounting["excludedIndependentFactorCount"]
        == 61
    )
    assert accounting["missingIndependentFactorCount"] == 0
    assert accounting["diagnosticAliasFactorCount"] == 3
    guardrail_rules = status.body["result"]["factorSelectionDecision"]["guardrailProfile"]["rules"]
    assert len(guardrail_rules) == 12
    assert {
        "min_target_effective_names",
        "current_target_effective_names",
        "max_target_hhi",
        "current_target_hhi",
        "max_target_weight",
        "current_target_max_weight",
    }.issubset({rule["metric"] for rule in guardrail_rules})
    selected = _selected_row(status.body["result"])
    assert selected["selection_eligible"] is True
    assert all(
        selected[field] is True
        for field in (
            "guardrail_historical_effective_names",
            "guardrail_current_effective_names",
            "guardrail_historical_target_hhi",
            "guardrail_current_target_hhi",
            "guardrail_historical_target_weight",
            "guardrail_current_target_weight",
        )
    )
    history = status.body["result"]["bestFactorBacktestHoldingHistory"]
    assert [session["date"] for session in history["sessions"]] == status.body["result"][
        "performance"
    ]["dates"][-history["sessionCount"] :]
    assert cached.status_code == 200
    assert cached.body == status.body["result"]
    assert len(calls) == 1


def test_distinct_complete_inputs_run_python_with_distinct_configs_and_results(
    tmp_path: Path,
) -> None:
    api, calls = _api(tmp_path)
    first_inputs = ResearchInputs()
    second_inputs = ResearchInputs(min_price=7.5)

    first_submission = _post(api, first_inputs)
    second_submission = _post(api, second_inputs)
    first = api.dispatch("GET", first_submission.body["statusUrl"])
    second = api.dispatch("GET", second_submission.body["statusUrl"])

    assert first_submission.status_code == second_submission.status_code == 202
    assert first.body["status"] == second.body["status"] == "complete"
    assert first_submission.body["resultKey"] != second_submission.body["resultKey"]
    assert [call[0].min_price for call in calls] == [5.0, 7.5]
    assert all(call[1] is calls[0][1] for call in calls)
    for response, submitted_inputs in (
        (first, first_inputs),
        (second, second_inputs),
    ):
        result = response.body["result"]
        assert result["schemaVersion"] == 5
        assert result["researchInputs"] == submitted_inputs.to_dict()
        assert len(result["factorRanking"]) == 64
        assert len(result["factorPortfolios"]) == 64
        assert result["bestFactorPortfolio"] == result["factorPortfolios"][result["bestFactor"]]


def test_api_refreshes_request_date_and_keeps_queued_identity_across_midnight(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Clock(datetime):
        current = datetime(2026, 9, 17, 23, 59, 59, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    tasks = []

    class ManualExecutor:
        def submit(self, task):
            tasks.append(task)

        def shutdown(self):
            return None

    monkeypatch.setattr("factor_lab.config.datetime", Clock)
    api, calls = _api(tmp_path, executor=ManualExecutor())
    api.base_config.end_date = None
    first_submission = _post(api)
    Clock.current = datetime(2026, 9, 18, 0, 0, 1, tzinfo=UTC)
    second_submission = _post(api)
    assert first_submission.status_code == second_submission.status_code == 202
    assert first_submission.body["resultKey"] != second_submission.body["resultKey"]

    for task in tasks:
        task()
    assert [config.effective_end_date for config, _market_data in calls] == [
        "2026-09-17",
        "2026-09-18",
    ]
    for submission in (first_submission, second_submission):
        completed = api.dispatch("GET", submission.body["statusUrl"])
        assert completed.body["status"] == "complete", completed.body
        assert b"_resolved_end_date" not in canonical_json_bytes(completed.body)
    assert api.base_config.effective_end_date == "2026-09-17"


def test_queued_running_and_complete_states_need_no_background_thread(tmp_path: Path) -> None:
    tasks = []

    class ManualExecutor:
        def submit(self, task):
            tasks.append(task)

        def shutdown(self):
            return None

    observed_statuses = []
    api: LocalResearchAPI

    def runner(config: RunConfig, *, market_data: MarketData):
        identity = build_result_identity(config, market_data)
        observed_statuses.append(
            api.dispatch("GET", f"/api/runs/{identity['resultKey']}").body["status"]
        )
        return SimpleNamespace(config=config, market=market_data)

    api, _ = _api(tmp_path, executor=ManualExecutor(), runner=runner)
    submitted = _post(api)
    result_key = submitted.body["resultKey"]

    assert submitted.status_code == 202
    assert submitted.body["status"] == "queued"
    assert api.dispatch("GET", f"/api/runs/{result_key}").body["status"] == "queued"
    assert len(tasks) == 1
    tasks.pop()()
    completed = api.dispatch("GET", f"/api/runs/{result_key}")

    assert observed_statuses == ["running"]
    assert completed.body["status"] == "complete"
    assert completed.body["result"]["resultKey"] == result_key


def test_failed_job_is_visible_and_is_never_written_to_cache(tmp_path: Path) -> None:
    writes = []

    def failing_runner(config: RunConfig, *, market_data: MarketData):
        raise RuntimeError("deterministic analysis failure")

    def cache_writer(config, identity, payload):
        writes.append((config, identity, payload))
        return config.cache_dir / "unexpected.json"

    api, _ = _api(
        tmp_path,
        runner=failing_runner,
        cache_loader=lambda _config, _identity: None,
        cache_writer=cache_writer,
    )

    submitted = _post(api)
    failed = api.dispatch("GET", submitted.body["statusUrl"])

    assert submitted.status_code == 202
    assert failed.status_code == 200
    assert failed.body["status"] == "failed"
    assert failed.body["error"]["type"] == "RuntimeError"
    assert "deterministic analysis failure" in failed.body["error"]["message"]
    assert writes == []


def test_post_accepts_nonannual_evaluation_window_as_canonical_v2_input(
    tmp_path: Path,
) -> None:
    tasks = []

    class ManualExecutor:
        def submit(self, task):
            tasks.append(task)

        def shutdown(self):
            return None

    api, _ = _api(tmp_path, executor=ManualExecutor())

    baseline = _post(api, ResearchInputs())
    changed = _post(api, ResearchInputs(evaluation_window_days=126))

    assert baseline.status_code == changed.status_code == 202
    assert baseline.body["resultKey"] != changed.body["resultKey"]
    assert len(tasks) == 2


@pytest.mark.parametrize(
    "body",
    [
        {**ResearchInputs().to_dict(), "nearestPreset": True},
        {"version": "research-inputs-v1", "topN": 20},
        {
            **ResearchInputs().to_dict(),
            "version": "research-inputs-v1",
            "evaluationYears": 3,
        },
        {**ResearchInputs().to_dict(), "evaluationWindowDays": 20},
        {**ResearchInputs().to_dict(), "topN": 0},
        {**ResearchInputs().to_dict(), "topN": MAX_TOP_N + 1},
    ],
)
def test_post_requires_complete_exact_research_inputs_and_rejects_unknown_fields(
    tmp_path: Path,
    body: dict[str, object],
) -> None:
    api, calls = _api(tmp_path)

    response = api.dispatch("POST", "/api/runs", canonical_json_bytes(body))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_research_inputs"
    assert calls == []


@pytest.mark.parametrize(
    "config",
    [
        RunConfig(demo=True),
        RunConfig(live=True, max_price_symbols=200),
        RunConfig(live=True, universe=list(DEFAULT_UNIVERSE[:200])),
    ],
)
def test_constructor_rejects_demo_subset_and_capped_modes(
    config: RunConfig,
) -> None:
    with pytest.raises(LocalAPIConfigurationError):
        LocalResearchAPI(config, executor=SynchronousJobExecutor())


def test_non_loopback_bind_requires_explicit_opt_in(tmp_path: Path) -> None:
    config = _base_config(tmp_path)
    with pytest.raises(LocalAPIConfigurationError, match="allow_non_loopback"):
        LocalResearchAPI(
            config,
            bind_host="0.0.0.0",
            executor=SynchronousJobExecutor(),
        )

    api = LocalResearchAPI(
        config,
        bind_host="0.0.0.0",
        allow_non_loopback=True,
        executor=SynchronousJobExecutor(),
    )
    assert api.bind_host == "0.0.0.0"


@pytest.mark.parametrize(
    "market",
    [
        _market(source_mode="demo"),
        _market(analyzed_count=2_699),
        _market(requested_count=2_699),
    ],
)
def test_post_rejects_non_live_or_incomplete_market_without_fallback(
    tmp_path: Path,
    market: MarketData,
) -> None:
    api, calls = _api(tmp_path, market=market)

    response = _post(api)

    assert response.status_code == 503
    assert response.body["error"]["code"] in {
        "actual_market_required",
        "full_universe_required",
    }
    assert calls == []


def test_market_failure_returns_503_without_demo_or_cached_fallback(tmp_path: Path) -> None:
    calls = []

    def unavailable(_config: RunConfig):
        calls.append("market")
        raise OSError("provider unavailable")

    api = LocalResearchAPI(
        _base_config(tmp_path),
        executor=SynchronousJobExecutor(),
        market_loader=unavailable,
    )

    response = _post(api)

    assert response.status_code == 503
    assert response.body["error"]["code"] == "market_data_unavailable"
    assert calls == ["market"]


def test_post_rejects_incomplete_actual_market_hash_contract(tmp_path: Path) -> None:
    market = _market()
    market.input_sha256.pop("dollarVolumes")
    api, calls = _api(tmp_path, market=market)

    response = _post(api)

    assert response.status_code == 503
    assert response.body["error"]["code"] == "actual_market_contract_invalid"
    assert calls == []


def test_cached_identity_mismatch_fails_closed_instead_of_serving_result(tmp_path: Path) -> None:
    wrong = {
        "schemaVersion": 5,
        "resultKey": "f" * 64,
        "resultIdentity": {
            "identityVersion": "momentum-result-identity-v1",
            "resultKey": "f" * 64,
            "keyParts": {},
        },
    }
    api, calls = _api(
        tmp_path,
        cache_loader=lambda _config, _identity: wrong,
    )

    response = _post(api)

    assert response.status_code == 500
    assert response.body["error"]["code"] == "identity_mismatch"
    assert calls == []


def test_cached_result_without_provider_provenance_fails_closed(tmp_path: Path) -> None:
    market = _market()

    def missing_provenance(config: RunConfig, _identity):
        payload = _payload(config, market)
        payload["priceSources"] = []
        return payload

    api, calls = _api(
        tmp_path,
        market=market,
        cache_loader=missing_provenance,
    )

    response = _post(api)

    assert response.status_code == 500
    assert response.body["error"]["code"] == "result_contract_mismatch"
    assert "provenance" in response.body["error"]["message"]
    assert calls == []


@pytest.mark.parametrize(
    "mutate",
    [
        _omit_factor_policy_ranking,
        _omit_selection_decision,
        _omit_current_research_target,
        _mutate_guardrail_profile,
        _fail_selected_historical_concentration,
        _fail_selected_current_concentration,
        _fail_selected_eligibility,
    ],
    ids=lambda mutate: mutate.__name__,
)
def test_cached_result_must_satisfy_the_full_canonical_dashboard_contract(
    tmp_path: Path,
    mutate: PayloadMutation,
) -> None:
    market = _market()

    def malformed_result(config: RunConfig, _identity):
        payload = _payload(config, market)
        mutate(payload)
        return payload

    api, calls = _api(
        tmp_path,
        market=market,
        cache_loader=malformed_result,
    )

    response = _post(api)

    assert response.status_code == 500
    assert response.body["error"]["code"] == "result_contract_mismatch"
    assert "canonical dashboard contract" in response.body["error"]["message"]
    assert calls == []


def test_runner_identity_mismatch_marks_job_failed_and_skips_cache_write(tmp_path: Path) -> None:
    writes = []

    def runner(config: RunConfig, *, market_data: MarketData):
        return SimpleNamespace(config=config, market=market_data)

    def bad_payload(result: SimpleNamespace):
        payload = _payload(result.config, result.market)
        payload["resultKey"] = "f" * 64
        return payload

    api = LocalResearchAPI(
        _base_config(tmp_path),
        executor=SynchronousJobExecutor(),
        market_loader=lambda _config: _market(),
        cache_loader=lambda _config, _identity: None,
        cache_writer=lambda *args: writes.append(args),
        analysis_runner=runner,
        payload_builder=bad_payload,
    )

    submitted = _post(api)
    failed = api.dispatch("GET", submitted.body["statusUrl"])

    assert submitted.status_code == 202
    assert failed.body["status"] == "failed"
    assert failed.body["error"]["type"] == "LocalAPIRequestError"
    assert "identity" in failed.body["error"]["message"]
    assert writes == []


def test_unknown_routes_methods_and_result_keys_fail_closed(tmp_path: Path) -> None:
    api, _ = _api(tmp_path)

    assert api.dispatch("GET", "/unknown").status_code == 404
    assert api.dispatch("POST", "/api/capabilities").status_code == 405
    assert api.dispatch("GET", "/api/runs/not-a-key").status_code == 404
