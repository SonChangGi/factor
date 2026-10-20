from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .config import MAX_TOP_N, RunConfig
from .dashboard import dashboard_summary
from .data import (
    LIVE_SNAPSHOT_HASH_FIELDS,
    MarketData,
    _canonical_matrix_sha256,
    _ordered_symbols_sha256,
    _validated_provenance_frames,
    canonical_records_sha256,
    load_market_data,
)
from .identity import (
    RESULT_IDENTITY_VERSION,
    build_result_identity,
    canonical_json_bytes,
    canonical_sha256,
    load_analysis_cache,
    market_snapshot_identity,
    normalized_research_inputs,
    write_analysis_cache,
)
from .research_inputs import (
    RESEARCH_INPUTS_VERSION,
    ResearchInputError,
    ResearchInputs,
)
from .workflow import AnalysisResult, result_payload, run_analysis


LOCAL_API_CONTRACT = "momentum-local-research-api"
LOCAL_API_SCHEMA_VERSION = 1
MIN_FULL_UNIVERSE_SECURITY_COUNT = 2_700
MAX_REQUEST_BYTES = 128 * 1024
JOB_STATUSES = ("queued", "running", "failed", "complete")
DEFAULT_BROWSER_ALLOWED_ORIGINS = frozenset({"https://sonchanggi.github.io"})


class LocalAPIConfigurationError(ValueError):
    """Raised when the local service could expose a non-actual or unsafe run mode."""


class LocalAPIRequestError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class JobExecutor(Protocol):
    def submit(self, task: Callable[[], None]) -> None: ...

    def shutdown(self) -> None: ...


class SynchronousJobExecutor:
    """Run submitted work inline; useful for deterministic, thread-free tests."""

    def submit(self, task: Callable[[], None]) -> None:
        task()

    def shutdown(self) -> None:
        return None


class ThreadPoolJobExecutor:
    """Small owned executor used by the interactive local HTTP service."""

    def __init__(self, *, max_workers: int = 1) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="momentum-local-api",
        )

    def submit(self, task: Callable[[], None]) -> None:
        self._pool.submit(task)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=False)


@dataclass(frozen=True)
class APIResponse:
    status_code: int
    body: dict[str, Any]


@dataclass
class _RunJob:
    result_key: str
    identity: dict[str, object]
    research_inputs: ResearchInputs
    config: RunConfig
    market: MarketData | None
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None


MarketLoader = Callable[[RunConfig], MarketData]
IdentityBuilder = Callable[[RunConfig, MarketData], dict[str, object]]
CacheLoader = Callable[[RunConfig, dict[str, object]], dict[str, Any] | None]
CacheWriter = Callable[[RunConfig, dict[str, object], dict[str, Any]], Path]
AnalysisRunner = Callable[..., AnalysisResult]
PayloadBuilder = Callable[[AnalysisResult], dict[str, Any]]


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip()
    if not normalized:
        return False
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        pass
    try:
        addresses = {
            item[4][0] for item in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
        }
    except OSError:
        return False
    return bool(addresses) and all(
        ipaddress.ip_address(address).is_loopback for address in addresses
    )


def _is_exact_http_origin(origin: str) -> bool:
    if not isinstance(origin, str) or not origin or origin != origin.strip():
        return False
    try:
        parsed = urlsplit(origin)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or hostname is None:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path or parsed.query or parsed.fragment:
        return False
    return True


def _is_loopback_origin(origin: str) -> bool:
    if not _is_exact_http_origin(origin):
        return False
    host = urlsplit(origin).hostname
    if host is None:  # pragma: no cover - guarded by _is_exact_http_origin
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_base_config(config: RunConfig) -> None:
    try:
        config.validate()
    except ValueError as error:
        raise LocalAPIConfigurationError(str(error)) from error
    if not config.live or config.demo or config.prices_path is not None:
        raise LocalAPIConfigurationError("local API requires the actual live-market data mode")
    if config.volumes_path is not None:
        raise LocalAPIConfigurationError("local API cannot use local volume files")
    if config.market_caps_path is not None:
        raise LocalAPIConfigurationError("local API cannot use local market-cap files")
    if config.max_price_symbols is not None:
        raise LocalAPIConfigurationError("local API cannot cap the requested price universe")
    if len(set(config.universe)) < MIN_FULL_UNIVERSE_SECURITY_COUNT:
        raise LocalAPIConfigurationError(
            f"local API requires at least {MIN_FULL_UNIVERSE_SECURITY_COUNT:,} universe symbols"
        )


def _validate_market(market: MarketData) -> None:
    if market.source_mode != "live_market":
        raise LocalAPIRequestError(
            503,
            "actual_market_required",
            "the local API accepts only live-market data and has no demo or synthetic fallback",
        )
    requested = market.requested_candidate_count
    analyzed = len(market.candidate_symbols)
    if (
        not isinstance(requested, int)
        or isinstance(requested, bool)
        or requested < MIN_FULL_UNIVERSE_SECURITY_COUNT
        or analyzed < MIN_FULL_UNIVERSE_SECURITY_COUNT
    ):
        raise LocalAPIRequestError(
            503,
            "full_universe_required",
            "the actual-market snapshot does not contain the required 2,700+ security universe",
        )
    hashes = market.input_sha256
    if set(hashes) != set(LIVE_SNAPSHOT_HASH_FIELDS) or any(
        not isinstance(hashes.get(field), str)
        or len(str(hashes[field])) != 64
        or any(character not in "0123456789abcdef" for character in str(hashes[field]))
        for field in LIVE_SNAPSHOT_HASH_FIELDS
    ):
        raise LocalAPIRequestError(
            503,
            "actual_market_contract_invalid",
            "the actual-market input hash contract is incomplete",
        )
    if market.universe.empty or "symbol" not in market.universe:
        raise LocalAPIRequestError(
            503,
            "actual_market_contract_invalid",
            "the actual-market universe metadata is missing",
        )
    universe_symbols = [str(symbol).strip().upper() for symbol in market.universe["symbol"]]
    candidate_symbols = list(market.candidate_symbols)
    candidate_set = set(candidate_symbols)
    if (
        any(not symbol for symbol in universe_symbols)
        or len(set(universe_symbols)) != len(universe_symbols)
        or [symbol for symbol in universe_symbols if symbol in candidate_set] != candidate_symbols
        or requested != len(universe_symbols)
        or market.provider_returned_candidate_count != analyzed
    ):
        raise LocalAPIRequestError(
            503,
            "actual_market_contract_invalid",
            "the actual-market universe order or counts are inconsistent",
        )
    try:
        price_sources, data_sources = _validated_provenance_frames(
            market.price_sources,
            market.data_sources,
            candidate_symbols,
        )
    except ValueError as error:
        raise LocalAPIRequestError(
            503,
            "actual_market_contract_invalid",
            str(error),
        ) from error
    observed_hashes = {
        "prices": _canonical_matrix_sha256(market.prices),
        "volumes": _canonical_matrix_sha256(
            market.volumes.reindex(index=market.prices.index, columns=market.prices.columns)
        ),
        "dollarVolumes": _canonical_matrix_sha256(
            market.dollar_volumes.reindex(
                index=market.prices.index,
                columns=market.prices.columns,
            )
        ),
        "rawCloses": _canonical_matrix_sha256(
            market.raw_closes.reindex(index=market.prices.index, columns=market.prices.columns)
        ),
        "requestedSymbols": _ordered_symbols_sha256(universe_symbols),
        "returnedSymbols": _ordered_symbols_sha256(candidate_symbols),
        "universeRecords": canonical_records_sha256(market.universe),
        "priceSources": canonical_records_sha256(price_sources),
        "dataSources": canonical_records_sha256(data_sources),
        "comparisonPrices": _canonical_matrix_sha256(
            market.comparison_prices.reindex(index=market.prices.index)
        ),
        "marketCaps": _canonical_matrix_sha256(
            market.market_caps.reindex(index=market.prices.index, columns=market.prices.columns)
        ),
        "marketCapSources": canonical_records_sha256(market.market_cap_sources),
    }
    if observed_hashes != hashes:
        raise LocalAPIRequestError(
            503,
            "actual_market_contract_invalid",
            "the actual-market input hashes differ from the loaded data",
        )


def _validate_identity(
    identity: object,
    config: RunConfig,
    market: MarketData,
) -> dict[str, object]:
    if not isinstance(identity, dict):
        raise LocalAPIRequestError(500, "identity_mismatch", "result identity must be an object")
    if identity.get("identityVersion") != RESULT_IDENTITY_VERSION:
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "result identity version is unsupported",
        )
    result_key = identity.get("resultKey")
    key_parts = identity.get("keyParts")
    if (
        not isinstance(result_key, str)
        or len(result_key) != 64
        or any(character not in "0123456789abcdef" for character in result_key)
        or not isinstance(key_parts, dict)
        or canonical_sha256(key_parts) != result_key
    ):
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "resultKey does not match canonical identity keyParts",
        )
    if key_parts.get("normalizedInputs") != normalized_research_inputs(config):
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "identity normalized inputs differ from the requested run",
        )
    snapshot = key_parts.get("marketSnapshot")
    if not isinstance(snapshot, dict):
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "identity market snapshot is missing",
        )
    if snapshot != market_snapshot_identity(market):
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "identity market snapshot differs from the loaded actual-market data",
        )
    return deepcopy(identity)


def _parse_research_inputs(value: object) -> ResearchInputs:
    if not isinstance(value, Mapping):
        raise LocalAPIRequestError(400, "invalid_research_inputs", "request JSON must be an object")
    supplied = dict(value)
    try:
        inputs = ResearchInputs.from_mapping(supplied)
    except ResearchInputError as error:
        raise LocalAPIRequestError(400, "invalid_research_inputs", str(error)) from error
    canonical = inputs.to_dict()
    if canonical_json_bytes(supplied) != canonical_json_bytes(canonical):
        raise LocalAPIRequestError(
            400,
            "invalid_research_inputs",
            "request body must be the complete canonical ResearchInputs JSON object",
        )
    return inputs


def _validate_result_payload(
    payload: object,
    *,
    identity: dict[str, object],
    research_inputs: ResearchInputs,
    market: MarketData,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LocalAPIRequestError(500, "result_contract_mismatch", "result must be an object")
    result_key = str(identity["resultKey"])
    if payload.get("schemaVersion") != 5:
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            "local API result must use schemaVersion 5",
        )
    if payload.get("resultIdentity") != identity or payload.get("resultKey") != result_key:
        raise LocalAPIRequestError(
            500,
            "identity_mismatch",
            "result payload identity differs from the requested resultKey",
        )
    if payload.get("researchInputs") != research_inputs.to_dict():
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            "result payload researchInputs differ from the request",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            "result payload data object is missing",
        )
    expected_data = {
        "mode": "live_market",
        "synthetic": False,
        "asOf": market.as_of.date().isoformat(),
        "analyzedSecurityCount": len(market.candidate_symbols),
        "analyzedSymbols": list(market.candidate_symbols),
    }
    for field, expected in expected_data.items():
        if data.get(field) != expected:
            raise LocalAPIRequestError(
                500,
                "result_contract_mismatch",
                f"result payload data differs at {field}",
            )
    price_sources = payload.get("priceSources")
    source_health = payload.get("sourceHealth")
    input_hashes = data.get("inputSha256")
    expected_price_sources_hash = canonical_records_sha256(market.price_sources)
    expected_source_health_hash = canonical_records_sha256(market.data_sources)
    if (
        not isinstance(price_sources, list)
        or len(price_sources) < len(market.candidate_symbols)
        or not isinstance(source_health, list)
        or not source_health
        or not isinstance(input_hashes, dict)
        or input_hashes != market.input_sha256
        or input_hashes.get("priceSources") != expected_price_sources_hash
        or input_hashes.get("dataSources") != expected_source_health_hash
        or canonical_records_sha256(price_sources) != expected_price_sources_hash
        or canonical_records_sha256(source_health) != expected_source_health_hash
    ):
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            "result payload provider provenance is missing or inconsistent",
        )
    try:
        canonical_json_bytes(payload)
    except (TypeError, ValueError) as error:
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            f"result payload is not canonical JSON: {error}",
        ) from error
    try:
        dashboard_summary(payload)
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise LocalAPIRequestError(
            500,
            "result_contract_mismatch",
            f"result payload violates the canonical dashboard contract: {error}",
        ) from error
    return deepcopy(payload)


class LocalResearchAPI:
    def __init__(
        self,
        base_config: RunConfig,
        *,
        bind_host: str = "127.0.0.1",
        allow_non_loopback: bool = False,
        allowed_origins: Collection[str] | None = None,
        executor: JobExecutor | None = None,
        market_loader: MarketLoader = load_market_data,
        identity_builder: IdentityBuilder = build_result_identity,
        cache_loader: CacheLoader = load_analysis_cache,
        cache_writer: CacheWriter = write_analysis_cache,
        analysis_runner: AnalysisRunner = run_analysis,
        payload_builder: PayloadBuilder = result_payload,
    ) -> None:
        _validate_base_config(base_config)
        if not allow_non_loopback and not _is_loopback_host(bind_host):
            raise LocalAPIConfigurationError(
                "non-loopback bind hosts require allow_non_loopback=True"
            )
        if isinstance(allowed_origins, str):
            raise LocalAPIConfigurationError(
                "allowed_origins must be a collection of exact origins"
            )
        try:
            configured_origins = tuple(allowed_origins or ())
        except TypeError as error:
            raise LocalAPIConfigurationError(
                "allowed_origins must be a collection of exact origins"
            ) from error
        invalid_origins = sorted(
            str(origin)
            for origin in configured_origins
            if not isinstance(origin, str) or not _is_exact_http_origin(origin)
        )
        if invalid_origins:
            raise LocalAPIConfigurationError(
                "allowed_origins contains invalid exact origins: " + ", ".join(invalid_origins)
            )
        additions = frozenset(configured_origins)
        self.base_config = base_config
        self.bind_host = bind_host
        self.allow_non_loopback = allow_non_loopback
        self.allowed_origins = DEFAULT_BROWSER_ALLOWED_ORIGINS.union(additions)
        self.executor = executor if executor is not None else ThreadPoolJobExecutor()
        self._owns_executor = executor is None
        self.market_loader = market_loader
        self.identity_builder = identity_builder
        self.cache_loader = cache_loader
        self.cache_writer = cache_writer
        self.analysis_runner = analysis_runner
        self.payload_builder = payload_builder
        self._jobs: dict[str, _RunJob] = {}
        self._lock = RLock()

    def browser_origin_allowed(self, origin: str) -> bool:
        return origin in self.allowed_origins or _is_loopback_origin(origin)

    def close(self) -> None:
        if self._owns_executor:
            self.executor.shutdown()

    def capabilities(self) -> dict[str, Any]:
        return {
            "schemaVersion": LOCAL_API_SCHEMA_VERSION,
            "contract": LOCAL_API_CONTRACT,
            "bindHost": self.bind_host,
            "actualMarketOnly": True,
            "fullUniverseMinimum": MIN_FULL_UNIVERSE_SECURITY_COUNT,
            "demoSupported": False,
            "syntheticFallback": False,
            "staticPresetFallback": False,
            "arbitraryResearchInputs": True,
            "researchInputs": {
                "version": RESEARCH_INPUTS_VERSION,
                "canonicalRequestRequired": True,
                "unknownFieldsRejected": True,
                "limits": {"topN": {"minimum": 1, "maximum": MAX_TOP_N}},
                "defaults": ResearchInputs().to_dict(),
            },
            "endpoints": {
                "capabilities": "GET /api/capabilities",
                "createRun": "POST /api/runs",
                "runStatus": "GET /api/runs/<resultKey>",
            },
            "jobStatuses": list(JOB_STATUSES),
        }

    @staticmethod
    def _status_body(job: _RunJob) -> dict[str, Any]:
        body: dict[str, Any] = {
            "resultKey": job.result_key,
            "status": job.status,
            "statusUrl": f"/api/runs/{job.result_key}",
        }
        if job.status == "failed":
            body["error"] = deepcopy(job.error)
        elif job.status == "complete":
            body["result"] = deepcopy(job.result)
        return body

    @staticmethod
    def _submission_body(job: _RunJob) -> dict[str, Any]:
        return {
            "resultKey": job.result_key,
            "status": job.status,
            "statusUrl": f"/api/runs/{job.result_key}",
        }

    def _run_job(self, result_key: str) -> None:
        with self._lock:
            job = self._jobs.get(result_key)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            config = job.config
            market = job.market
            identity = deepcopy(job.identity)
            inputs = job.research_inputs
        if market is None:  # pragma: no cover - construction invariant
            return
        try:
            analysis = self.analysis_runner(config, market_data=market)
            payload = _validate_result_payload(
                self.payload_builder(analysis),
                identity=identity,
                research_inputs=inputs,
                market=market,
            )
            self.cache_writer(config, identity, payload)
        except Exception as error:
            with self._lock:
                job = self._jobs[result_key]
                job.status = "failed"
                job.error = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
                job.market = None
            return
        with self._lock:
            job = self._jobs[result_key]
            job.status = "complete"
            job.result = payload
            job.error = None
            job.market = None

    def _post_run(self, body: bytes) -> APIResponse:
        if len(body) > MAX_REQUEST_BYTES:
            raise LocalAPIRequestError(413, "request_too_large", "request body is too large")
        try:
            raw = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LocalAPIRequestError(400, "invalid_json", f"invalid JSON: {error}") from error
        inputs = _parse_research_inputs(raw)
        try:
            config = inputs.apply(self.base_config.for_new_run())
        except (ResearchInputError, ValueError) as error:
            raise LocalAPIRequestError(400, "invalid_research_inputs", str(error)) from error
        try:
            market = self.market_loader(config)
        except Exception as error:
            raise LocalAPIRequestError(
                503,
                "market_data_unavailable",
                f"actual market data could not be loaded: {error}",
            ) from error
        _validate_market(market)
        identity = _validate_identity(self.identity_builder(config, market), config, market)
        try:
            cached = self.cache_loader(config, identity)
        except Exception as error:
            raise LocalAPIRequestError(
                500,
                "cache_read_failed",
                f"analysis cache could not be read: {error}",
            ) from error
        if cached is not None:
            return APIResponse(
                200,
                _validate_result_payload(
                    cached,
                    identity=identity,
                    research_inputs=inputs,
                    market=market,
                ),
            )

        result_key = str(identity["resultKey"])
        with self._lock:
            existing = self._jobs.get(result_key)
            if existing is not None and existing.status == "complete":
                if existing.result is None:  # pragma: no cover - state invariant
                    raise LocalAPIRequestError(
                        500, "job_state_invalid", "completed job has no result"
                    )
                return APIResponse(200, deepcopy(existing.result))
            if existing is not None and existing.status in {"queued", "running"}:
                return APIResponse(202, self._submission_body(existing))
            job = _RunJob(
                result_key=result_key,
                identity=identity,
                research_inputs=inputs,
                config=config,
                market=market,
            )
            self._jobs[result_key] = job
        try:
            self.executor.submit(lambda: self._run_job(result_key))
        except Exception as error:
            with self._lock:
                job.status = "failed"
                job.error = {"type": type(error).__name__, "message": str(error)}
                job.market = None
            raise LocalAPIRequestError(
                500,
                "job_submission_failed",
                f"analysis job could not be submitted: {error}",
            ) from error
        with self._lock:
            return APIResponse(202, self._submission_body(self._jobs[result_key]))

    def _get_run(self, result_key: str) -> APIResponse:
        if len(result_key) != 64 or any(
            character not in "0123456789abcdef" for character in result_key
        ):
            raise LocalAPIRequestError(404, "run_not_found", "run was not found")
        with self._lock:
            job = self._jobs.get(result_key)
            if job is None:
                raise LocalAPIRequestError(404, "run_not_found", "run was not found")
            return APIResponse(200, self._status_body(job))

    def dispatch(self, method: str, path: str, body: bytes = b"") -> APIResponse:
        try:
            parsed = urlsplit(path)
            if parsed.query or parsed.fragment:
                raise LocalAPIRequestError(404, "endpoint_not_found", "endpoint was not found")
            if method == "GET" and parsed.path == "/api/capabilities":
                return APIResponse(200, self.capabilities())
            if method == "POST" and parsed.path == "/api/runs":
                return self._post_run(body)
            prefix = "/api/runs/"
            if method == "GET" and parsed.path.startswith(prefix):
                return self._get_run(parsed.path[len(prefix) :])
            if parsed.path in {"/api/capabilities", "/api/runs"} or parsed.path.startswith(prefix):
                raise LocalAPIRequestError(405, "method_not_allowed", "method is not allowed")
            raise LocalAPIRequestError(404, "endpoint_not_found", "endpoint was not found")
        except LocalAPIRequestError as error:
            return APIResponse(
                error.status_code,
                {"error": {"code": error.code, "message": str(error)}},
            )
        except Exception:
            return APIResponse(
                500,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "the local API failed closed on an unexpected error",
                    }
                },
            )

    def create_http_server(self, *, port: int = 0) -> HTTPServer:
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MomentumLocalAPI/1"

            def log_message(self, format: str, *args: object) -> None:
                return None

            def _send_cors_headers(self, origin: str | None) -> None:
                self.send_header("Vary", "Origin")
                if origin is None:
                    return
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def _send(self, response: APIResponse, *, origin: str | None = None) -> None:
                encoded = canonical_json_bytes(response.body)
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers(origin)
                self.end_headers()
                self.wfile.write(encoded)

            def _authorized_origin(self) -> tuple[bool, str | None]:
                origin = self.headers.get("Origin")
                if origin is None or api.browser_origin_allowed(origin):
                    return True, origin
                self._send(
                    APIResponse(
                        403,
                        {
                            "error": {
                                "code": "origin_forbidden",
                                "message": "browser Origin is not allowed",
                            }
                        },
                    )
                )
                return False, None

            def do_OPTIONS(self) -> None:  # noqa: N802
                allowed, origin = self._authorized_origin()
                if not allowed:
                    return
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self._send_cors_headers(origin)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                allowed, origin = self._authorized_origin()
                if not allowed:
                    return
                self._send(api.dispatch("GET", self.path), origin=origin)

            def do_POST(self) -> None:  # noqa: N802
                allowed, origin = self._authorized_origin()
                if not allowed:
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if length < 0 or length > MAX_REQUEST_BYTES:
                    self._send(
                        APIResponse(
                            413,
                            {
                                "error": {
                                    "code": "request_too_large",
                                    "message": "request body is too large",
                                }
                            },
                        ),
                        origin=origin,
                    )
                    return
                self._send(
                    api.dispatch("POST", self.path, self.rfile.read(length)),
                    origin=origin,
                )

        return HTTPServer((self.bind_host, port), Handler)
