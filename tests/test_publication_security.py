from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from factor_lab.live_data import _sanitize_public_source_health
from factor_lab.publication_security import (
    PUBLIC_CACHE_REFERENCE,
    REDACTED_TEXT,
    main,
    redact_credential_like_text,
    scan_publication_paths,
)


def _aiven_shaped_value() -> str:
    return "AVNS_" + "A1b2C3d4E5f6G7h8"


def test_public_source_health_removes_local_cache_paths_before_hashing() -> None:
    frame = pd.DataFrame(
        [
            {
                "source": "yahoo-chart-adjusted-daily-fallback",
                "status": "cache_hit",
                "cache_path": "outputs/cache/yahoo_chart/local-symbol_2016-01-01_2026-07-28.csv",
                "error": None,
            },
            {
                "source": "packaged-default-universe",
                "status": "loaded",
                "cache_path": "package-resource",
                "error": None,
            },
        ]
    )

    sanitized = _sanitize_public_source_health(frame)

    assert sanitized.iloc[0]["cache_path"] == PUBLIC_CACHE_REFERENCE
    assert sanitized.iloc[1]["cache_path"] == "package-resource"
    assert "local-symbol" not in sanitized.to_json()


def test_provider_shaped_value_is_redacted_without_logging_value() -> None:
    raw = f"provider failed with {_aiven_shaped_value()}"
    sanitized = redact_credential_like_text(raw)

    assert sanitized == f"provider failed with {REDACTED_TEXT}"
    assert _aiven_shaped_value() not in str(sanitized)


def test_publication_scan_finds_provider_secret_without_returning_match(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    secret = _aiven_shaped_value()
    artifact.write_text(json.dumps({"diagnostic": secret}), encoding="utf-8")

    findings = scan_publication_paths([artifact])

    assert [(finding.path, finding.label) for finding in findings] == [
        (artifact, "aiven_service_password")
    ]
    assert all(secret not in repr(finding) for finding in findings)


def test_publication_scan_rejects_sensitive_json_fields(tmp_path: Path, capsys) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text(
        json.dumps({"provider": {"api_token": "runtime-value-without-provider-prefix"}}),
        encoding="utf-8",
    )

    assert main([str(artifact)]) == 1
    output = capsys.readouterr().out
    assert "publication_secret_scan=failed" in output
    assert "sensitive_json_field" in output
    assert "runtime-value-without-provider-prefix" not in output


def test_publication_scan_rejects_camel_case_and_header_credentials(
    tmp_path: Path,
    capsys,
) -> None:
    artifact = tmp_path / "result.json"
    sensitive_keys = ("apiToken", "clientSecret", "Authorization", "setCookie")
    artifact.write_text(
        json.dumps({key: f"value-{index}" for index, key in enumerate(sensitive_keys)}),
        encoding="utf-8",
    )

    findings = scan_publication_paths([artifact])

    assert len(
        [finding for finding in findings if finding.label == "sensitive_json_field"]
    ) == len(sensitive_keys)
    assert all(
        finding.json_path == "$.<sensitive-key>"
        for finding in findings
        if finding.label == "sensitive_json_field"
    )
    assert main([str(artifact)]) == 1
    output = capsys.readouterr().out
    assert all(key not in output for key in sensitive_keys)
    assert all(f"value-{index}" not in output for index in range(len(sensitive_keys)))


def test_publication_scan_never_logs_secret_shaped_json_key(
    tmp_path: Path,
    capsys,
) -> None:
    secret_shaped_key = _aiven_shaped_value()
    artifact = tmp_path / "result.json"
    artifact.write_text(
        json.dumps({secret_shaped_key: {"clientSecret": "opaque-runtime-value"}}),
        encoding="utf-8",
    )

    findings = scan_publication_paths([artifact])

    sensitive_finding = next(
        finding for finding in findings if finding.label == "sensitive_json_field"
    )
    assert sensitive_finding.json_path == "$.<redacted-key>.<sensitive-key>"
    assert secret_shaped_key not in repr(findings)
    assert main([str(artifact)]) == 1
    output = capsys.readouterr().out
    assert secret_shaped_key not in output
    assert "opaque-runtime-value" not in output
    assert "$.<redacted-key>.<sensitive-key>" in output


def test_committed_publication_is_clean_under_precommit_gate() -> None:
    assert scan_publication_paths([Path("docs")]) == []
