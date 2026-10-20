from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .cli import (
    _compute_payload,
    _config,
    _load_scheduled_config,
    _require_full_actual_publication,
)
from .config import MAX_TOP_N
from .dashboard import (
    MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES,
    dashboard_summary,
    externalize_factor_holding_history_sidecar,
)
from .data import load_market_data
from .identity import canonical_json_bytes, canonical_sha256
from .research_inputs import ResearchInputError, ResearchInputs


CONTROL_PROJECT_ID = "momentum"
CONTROL_INPUT_SCHEMA_VERSION = "momentum/v3"
PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION = "momentum/v2"
CONTROL_CONFIG_HASH_ALGORITHM = "momentum-research-inputs-rfc8785-v1"
CONTROL_ARTIFACT_CONTRACT_VERSION = "momentum/schema-v5-control-result-v1"
CONTROL_ARTIFACT_DIRECTORY = PurePosixPath("data/control-runs/v1")
DEFAULT_PUBLIC_SITE_URL = "https://sonchanggi.github.io/factor/"

_SAFE_CONTROL_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{7,199}$")

# These are the 26 independent public values accepted by ResearchInputs. The
# version marker is transport metadata and cannot be supplied as a second source
# of truth.
CONTROL_INPUT_KEYS = (
    "rebalanceFrequency",
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
    "selectionExtremeEventAction",
    "selectionExtremeEventPenaltyPoints",
)

CONTROL_INPUT_FIELDS = (
    {"key": "rebalanceFrequency", "type": "enum", "choices": ["W", "ME", "QE"]},
    {
        "key": "evaluationWindowDays",
        "type": "integer",
        "minimum": 21,
        "maximum": 2_520,
        "unit": "sessions",
    },
    {"key": "topN", "type": "integer", "minimum": 1, "maximum": MAX_TOP_N},
    {
        "key": "maxWeight",
        "type": "number",
        "exclusiveMinimum": 0.0,
        "maximum": 1.0,
    },
    {"key": "transactionCostBps", "type": "number", "minimum": 0.0, "unit": "bps"},
    {"key": "slippageBps", "type": "number", "minimum": 0.0, "unit": "bps"},
    {"key": "minHistoryDays", "type": "integer", "minimum": 21, "unit": "sessions"},
    {"key": "minPrice", "type": "number", "minimum": 0.0, "unit": "USD"},
    {"key": "minAvgDollarVolume", "type": "number", "minimum": 0.0, "unit": "USD"},
    {"key": "minAvgVolume", "type": "number", "minimum": 0.0, "unit": "shares"},
    {
        "key": "liquidityLookbackDays",
        "type": "integer",
        "minimum": 1,
        "unit": "sessions",
    },
    {
        "key": "minLiquidityObservations",
        "type": "integer",
        "minimum": 1,
        "unit": "sessions",
    },
    {
        "key": "maxPriceMissingRatio",
        "type": "number",
        "minimum": 0.0,
        "exclusiveMaximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "maxVolumeMissingRatio",
        "type": "number",
        "minimum": 0.0,
        "exclusiveMaximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "maxExtremeDailyReturn",
        "type": "number",
        "exclusiveMinimum": 0.0,
        "unit": "ratio",
    },
    {"key": "selectionMinSharpe", "type": "number", "minimum": -10.0},
    {
        "key": "selectionMaxDrawdown",
        "type": "number",
        "exclusiveMinimum": 0.0,
        "maximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMaxAnnualizedCostDrag",
        "type": "number",
        "minimum": 0.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMinEffectiveNames",
        "type": "number",
        "exclusiveMinimum": 0.0,
    },
    {
        "key": "selectionMaxTargetHhi",
        "type": "number",
        "exclusiveMinimum": 0.0,
        "maximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMaxTargetWeight",
        "type": "number",
        "exclusiveMinimum": 0.0,
        "maximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMaxAbsSecurityDayContribution",
        "type": "number",
        "minimum": 0.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMaxSecurityAbsoluteContributionShare",
        "type": "number",
        "minimum": 0.0,
        "maximum": 1.0,
        "unit": "ratio",
    },
    {
        "key": "selectionMaxLeaveOneSecurityCagrDelta",
        "type": "number",
        "minimum": 0.0,
        "unit": "ratio",
    },
    {
        "key": "selectionExtremeEventAction",
        "type": "enum",
        "choices": ["warn", "penalize", "exclude"],
    },
    {
        "key": "selectionExtremeEventPenaltyPoints",
        "type": "number",
        "minimum": 0.0,
        "unit": "points",
    },
)


def _control_input_schema() -> dict[str, object]:
    defaults = ResearchInputs().to_dict()
    return {
        "projectId": CONTROL_PROJECT_ID,
        "inputSchemaVersion": CONTROL_INPUT_SCHEMA_VERSION,
        "completeObjectRequired": True,
        "additionalProperties": False,
        "fields": [
            {**field, "default": defaults[str(field["key"])]}
            for field in CONTROL_INPUT_FIELDS
        ],
        "crossFieldRules": [
            "minLiquidityObservations <= liquidityLookbackDays",
            "selectionMinEffectiveNames <= topN",
        ],
        "derivedFields": {
            "minimumEvaluationObservations": (
                "min(evaluationWindowDays, max(252, evaluationWindowDays - 252))"
            ),
        },
        "authoritativeValidator": "ResearchInputs.from_mapping:research-inputs-v2",
    }


CONTROL_INPUT_SCHEMA = _control_input_schema()
CONTROL_INPUT_SCHEMA_HASH = canonical_sha256(CONTROL_INPUT_SCHEMA)
PREVIOUS_CONTROL_INPUT_SCHEMA_HASH = (
    "a2240581098f496fc555edac9d4b0e342eee6221a87e046a47f51ee7f6a4e81e"
)


class ControlledRunError(ValueError):
    """Raised when a controlled run cannot prove its request/result binding."""


@dataclass(frozen=True, slots=True)
class ControlBinding:
    run_id: str
    input_schema_version: str
    input_schema_hash: str
    config_hash_algorithm: str
    config_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "projectId": CONTROL_PROJECT_ID,
            "runId": self.run_id,
            "inputSchemaVersion": self.input_schema_version,
            "inputSchemaHash": self.input_schema_hash,
            "configHashAlgorithm": self.config_hash_algorithm,
            "configHash": self.config_hash,
        }


def control_inputs_from_research_inputs(inputs: ResearchInputs) -> dict[str, object]:
    public = inputs.to_dict()
    normalized = {key: public[key] for key in CONTROL_INPUT_KEYS}
    if set(normalized) != set(CONTROL_INPUT_KEYS):  # pragma: no cover - construction invariant
        raise ControlledRunError("ResearchInputs does not cover the complete control schema")
    return normalized


def normalize_control_inputs(value: Mapping[str, Any]) -> tuple[ResearchInputs, dict[str, object]]:
    if not isinstance(value, Mapping):
        raise ControlledRunError("controlled inputs must be a JSON object")
    observed = set(value)
    required = set(CONTROL_INPUT_KEYS)
    missing = sorted(required - observed)
    unknown = sorted(observed - required)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise ControlledRunError(
            "controlled inputs must contain exactly all 26 fields (" + "; ".join(details) + ")"
        )
    try:
        inputs = ResearchInputs.from_mapping(dict(value))
    except (ResearchInputError, TypeError, ValueError) as exc:
        raise ControlledRunError(str(exc)) from exc
    normalized = control_inputs_from_research_inputs(inputs)
    return inputs, normalized


def control_config_hash(value: Mapping[str, Any]) -> str:
    _, normalized = normalize_control_inputs(value)
    return canonical_sha256(normalized)


def validate_control_binding(
    *,
    run_id: str,
    input_schema_version: str,
    input_schema_hash: str,
    config_hash_algorithm: str,
    config_hash: str,
    normalized_inputs: Mapping[str, Any],
    allow_fallback: bool,
) -> ControlBinding:
    if not _SAFE_CONTROL_RUN_ID.fullmatch(run_id):
        raise ControlledRunError("control run id must be 8-128 path-safe ASCII characters")
    supported_schema_hashes = {
        CONTROL_INPUT_SCHEMA_VERSION: CONTROL_INPUT_SCHEMA_HASH,
        PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION: PREVIOUS_CONTROL_INPUT_SCHEMA_HASH,
    }
    if input_schema_version not in supported_schema_hashes:
        raise ControlledRunError(
            f"input schema mismatch: expected {CONTROL_INPUT_SCHEMA_VERSION}"
        )
    if input_schema_hash != supported_schema_hashes[input_schema_version]:
        raise ControlledRunError("input schema hash does not match this worker")
    if input_schema_version == PREVIOUS_CONTROL_INPUT_SCHEMA_VERSION:
        previous_window = normalized_inputs.get("evaluationWindowDays")
        if (
            not isinstance(previous_window, int)
            or isinstance(previous_window, bool)
            or not 252 <= previous_window <= 2_520
        ):
            raise ControlledRunError(
                "momentum/v2 evaluationWindowDays must be between 252 and 2520"
            )
    if config_hash_algorithm != CONTROL_CONFIG_HASH_ALGORITHM:
        raise ControlledRunError("config hash algorithm does not match this worker")
    if not _SHA256.fullmatch(config_hash):
        raise ControlledRunError("config hash must be a lowercase SHA-256 digest")
    observed_hash = control_config_hash(normalized_inputs)
    if config_hash != observed_hash:
        raise ControlledRunError("normalized controlled inputs do not reproduce config hash")
    if allow_fallback:
        raise ControlledRunError("Momentum controlled runs require allowFallback=false")
    return ControlBinding(
        run_id=run_id,
        input_schema_version=input_schema_version,
        input_schema_hash=input_schema_hash,
        config_hash_algorithm=config_hash_algorithm,
        config_hash=config_hash,
    )


def _validated_public_site_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ControlledRunError("public site URL must be a credential-free HTTPS base URL")
    path = parsed.path.rstrip("/") + "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_base_config(config_path: Path):
    namespace = argparse.Namespace(config=config_path, site_dir=None, title=None)
    run_namespace, _, _, _, _ = _load_scheduled_config(namespace)
    config = _config(run_namespace)
    if not config.live or config.demo or config.prices_path is not None:
        raise ControlledRunError("controlled runs require the saved actual-market live mode")
    if config.max_price_symbols is not None:
        raise ControlledRunError("controlled runs require the uncapped full universe")
    if config.end_date is not None:
        raise ControlledRunError("controlled runs require a rolling live end date")
    return config


def _data_identity(payload: Mapping[str, Any]) -> dict[str, str]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ControlledRunError("result payload has no data identity")
    as_of = data.get("asOf")
    input_hashes = data.get("inputSha256")
    if not isinstance(as_of, str) or not as_of:
        raise ControlledRunError("result payload has no data as-of date")
    if not isinstance(input_hashes, Mapping) or not input_hashes:
        raise ControlledRunError("result payload has no input hashes")
    if any(
        value is not None
        and (not isinstance(value, str) or not _SHA256.fullmatch(value))
        for value in input_hashes.values()
    ):
        raise ControlledRunError("result payload contains an invalid input hash")
    if data.get("mode") == "live_market" and any(
        value is None for value in input_hashes.values()
    ):
        raise ControlledRunError("live result payload contains a missing input hash")
    return {
        "source": "momentum-live-market-input-hashes",
        "sourceHash": canonical_sha256(dict(sorted(input_hashes.items()))),
        "dataAsOf": as_of,
    }


def _bounded_result_payload(
    payload: Mapping[str, Any],
    data_identity: Mapping[str, str],
) -> dict[str, Any]:
    portfolio = payload.get("bestFactorPortfolio")
    weights = portfolio.get("weights", []) if isinstance(portfolio, Mapping) else []
    return {
        "schemaVersion": payload.get("schemaVersion"),
        "resultKey": payload.get("resultKey"),
        "resultIdentity": payload.get("resultIdentity"),
        "researchInputs": payload.get("researchInputs"),
        "bestFactor": payload.get("bestFactor"),
        "weightingPolicy": payload.get("weightingPolicy"),
        "dataIdentity": dict(data_identity),
        "selectedSecurityCount": (
            portfolio.get("selectedSecurityCount") if isinstance(portfolio, Mapping) else None
        ),
        "holdings": list(weights[:50]) if isinstance(weights, list) else [],
    }


def write_control_artifact(
    *,
    payload: Mapping[str, Any],
    normalized_inputs: Mapping[str, Any],
    binding: ControlBinding,
    code_version: str,
    site_dir: Path,
    manifest_path: Path,
    public_site_url: str = DEFAULT_PUBLIC_SITE_URL,
) -> dict[str, Any]:
    if not _CODE_VERSION.fullmatch(code_version):
        raise ControlledRunError("code version must be an explicit 8-200 character identifier")
    if not isinstance(payload, dict):
        raise ControlledRunError("analysis result must be a JSON object")
    validate_control_binding(
        run_id=binding.run_id,
        input_schema_version=binding.input_schema_version,
        input_schema_hash=binding.input_schema_hash,
        config_hash_algorithm=binding.config_hash_algorithm,
        config_hash=binding.config_hash,
        normalized_inputs=normalized_inputs,
        allow_fallback=False,
    )
    expected_inputs = ResearchInputs.from_mapping(dict(normalized_inputs)).to_dict()
    if payload.get("researchInputs") != expected_inputs:
        raise ControlledRunError(
            "analysis result researchInputs do not match the controlled request"
        )
    dashboard_summary(payload)
    public_payload, sidecar_bytes = externalize_factor_holding_history_sidecar(payload)
    if sidecar_bytes is None:
        raise ControlledRunError("analysis result has no embedded factor-history sidecar")
    if len(sidecar_bytes) > MAX_FACTOR_HOLDING_HISTORY_SIDECAR_BYTES:
        raise ControlledRunError("factor-history sidecar exceeds the publication limit")

    result_key = public_payload.get("resultKey")
    if not isinstance(result_key, str) or not _SHA256.fullmatch(result_key):
        raise ControlledRunError("analysis resultKey must be a lowercase SHA-256 digest")
    artifact_relative = CONTROL_ARTIFACT_DIRECTORY / binding.run_id / f"{result_key}.json"
    artifact_path = site_dir.joinpath(*artifact_relative.parts)
    artifact_bytes = canonical_json_bytes(public_payload)
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()

    sidecar_manifest = public_payload.get("factorHoldingHistorySidecar")
    sidecar_relative = (
        PurePosixPath(str(sidecar_manifest.get("path")))
        if isinstance(sidecar_manifest, Mapping)
        else PurePosixPath()
    )
    if (
        sidecar_relative.is_absolute()
        or ".." in sidecar_relative.parts
        or sidecar_relative.as_posix() == "."
    ):
        raise ControlledRunError("factor-history sidecar path is unsafe")
    sidecar_path = site_dir.joinpath(*sidecar_relative.parts)

    public_base = _validated_public_site_url(public_site_url)
    artifact_url = public_base + artifact_relative.as_posix()
    data_identity = _data_identity(public_payload)
    calculated_at = public_payload.get("generatedAtUtc")
    if not isinstance(calculated_at, str) or not calculated_at:
        raise ControlledRunError("analysis result has no calculation timestamp")
    manifest = {
        "binding": binding.to_dict(),
        "requestedInputs": dict(normalized_inputs),
        "normalizedInputs": dict(normalized_inputs),
        "effectiveInputs": dict(normalized_inputs),
        "effectiveConfigHash": binding.config_hash,
        "ignoredInputs": [],
        "fallbacks": [],
        "fallbackUsed": False,
        "fallbackReason": None,
        "dataAsOf": data_identity["dataAsOf"],
        "calculatedAt": calculated_at,
        "codeVersion": code_version,
        "dataIdentity": data_identity,
        "artifact": {
            "url": artifact_url,
            "sha256": artifact_sha256,
            "byteSize": len(artifact_bytes),
            "contractVersion": CONTROL_ARTIFACT_CONTRACT_VERSION,
        },
        "payload": _bounded_result_payload(public_payload, data_identity),
    }
    _atomic_write(artifact_path, artifact_bytes)
    _atomic_write(sidecar_path, sidecar_bytes)
    _atomic_write(manifest_path, canonical_json_bytes(manifest))
    return {
        "manifest": manifest,
        "manifestPath": str(manifest_path),
        "artifactPath": str(artifact_path),
        "sidecarPath": str(sidecar_path),
    }


def execute_controlled_run(
    *,
    research_inputs: Mapping[str, Any],
    binding: ControlBinding,
    code_version: str,
    config_path: Path,
    site_dir: Path,
    output_dir: Path,
    public_site_url: str = DEFAULT_PUBLIC_SITE_URL,
) -> dict[str, Any]:
    inputs, normalized = normalize_control_inputs(research_inputs)
    if canonical_sha256(normalized) != binding.config_hash:
        raise ControlledRunError("controlled inputs changed after binding validation")
    config = inputs.apply(_load_base_config(config_path))
    config.output_dir = output_dir / "analysis"
    config.site_dir = site_dir
    config.validate()
    market = load_market_data(config)
    payload, _ = _compute_payload(config, market)
    _require_full_actual_publication(payload, config)
    return write_control_artifact(
        payload=payload,
        normalized_inputs=normalized,
        binding=binding,
        code_version=code_version,
        site_dir=site_dir,
        manifest_path=output_dir / "result-manifest.json",
        public_site_url=public_site_url,
    )


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ControlledRunError(f"research inputs are not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ControlledRunError("research inputs JSON must be an object")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m factor_lab.control_run",
        description="Run the existing Momentum Python engine for one bound remote request.",
    )
    parser.add_argument("--research-inputs-json", required=True)
    parser.add_argument("--control-run-id", required=True)
    parser.add_argument("--control-input-schema-version", required=True)
    parser.add_argument("--control-input-schema-hash", required=True)
    parser.add_argument("--control-config-hash-algorithm", required=True)
    parser.add_argument("--control-config-hash", required=True)
    parser.add_argument(
        "--allow-fallback",
        choices=["true", "false"],
        default="false",
    )
    parser.add_argument("--code-version", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(".github/factor-dashboard-config.json"),
    )
    parser.add_argument("--site-dir", type=Path, default=Path("docs"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/controlled-run"),
    )
    parser.add_argument("--public-site-url", default=DEFAULT_PUBLIC_SITE_URL)
    parser.add_argument("--github-output", type=Path)
    return parser


def _append_github_outputs(path: Path, receipt: Mapping[str, Any]) -> None:
    manifest = receipt["manifest"]
    artifact = manifest["artifact"]
    values = {
        "manifest_path": receipt["manifestPath"],
        "artifact_path": receipt["artifactPath"],
        "sidecar_path": receipt["sidecarPath"],
        "artifact_url": artifact["url"],
        "artifact_sha256": artifact["sha256"],
        "artifact_byte_size": artifact["byteSize"],
    }
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw_inputs = _parse_json_object(args.research_inputs_json)
        _, normalized = normalize_control_inputs(raw_inputs)
        binding = validate_control_binding(
            run_id=args.control_run_id,
            input_schema_version=args.control_input_schema_version,
            input_schema_hash=args.control_input_schema_hash,
            config_hash_algorithm=args.control_config_hash_algorithm,
            config_hash=args.control_config_hash,
            normalized_inputs=normalized,
            allow_fallback=args.allow_fallback == "true",
        )
        receipt = execute_controlled_run(
            research_inputs=normalized,
            binding=binding,
            code_version=args.code_version,
            config_path=args.config,
            site_dir=args.site_dir,
            output_dir=args.output_dir,
            public_site_url=args.public_site_url,
        )
        if args.github_output is not None:
            _append_github_outputs(args.github_output, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except (ControlledRunError, ResearchInputError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
