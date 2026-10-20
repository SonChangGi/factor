from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


@dataclass(frozen=True, slots=True)
class SecretPattern:
    label: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class SecretFinding:
    path: Path
    label: str
    offset: int | None = None
    json_path: str | None = None


# These are high-confidence provider prefixes supported by GitHub/GitLab push
# protection. Deliberately do not use entropy-only matching: result identities,
# content hashes, and UUIDs are expected publication data.
SECRET_PATTERNS = (
    SecretPattern("aiven_service_password", re.compile(r"\bAVNS_[0-9A-Za-z_-]{15,123}\b")),
    SecretPattern("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    SecretPattern(
        "github_token",
        re.compile(
            r"\b(?:gh[pousr]_[0-9A-Za-z]{36,255}|"
            r"github_pat_[0-9A-Za-z]{22}_[0-9A-Za-z]{59})\b"
        ),
    ),
    SecretPattern(
        "openai_api_key",
        re.compile(r"\bsk-(?:proj-|svcacct-)?[0-9A-Za-z_-]{20,}\b"),
    ),
    SecretPattern(
        "slack_token",
        re.compile(r"\bxox(?:b|p|a|r|s)-[0-9A-Za-z-]{20,}\b"),
    ),
    SecretPattern(
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    SecretPattern(
        "credentialed_url",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
    ),
)

SENSITIVE_JSON_TERMS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
SENSITIVE_COMPACT_JSON_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "apitoken",
        "authorizationheader",
        "clientsecret",
        "proxyauthorization",
        "refreshtoken",
        "setcookie",
    }
)
REDACTED_TEXT = "[redacted credential-like diagnostic]"
PUBLIC_CACHE_REFERENCE = "local-cache-path-redacted"
_SAFE_SENSITIVE_VALUES = frozenset(
    {
        "",
        "disabled",
        "none",
        "null",
        "redacted",
        REDACTED_TEXT,
        PUBLIC_CACHE_REFERENCE,
    }
)


def redact_credential_like_text(value: object) -> object:
    """Remove provider-shaped credentials from untrusted diagnostic text.

    The returned value keeps non-string types unchanged. The actual matched
    value is never returned or logged.
    """

    if not isinstance(value, str):
        return value
    sanitized = value
    for secret_pattern in SECRET_PATTERNS:
        sanitized = secret_pattern.pattern.sub(REDACTED_TEXT, sanitized)
    return sanitized


def scan_publication_paths(paths: Iterable[str | Path]) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in _iter_files(paths):
        try:
            encoded = path.read_bytes()
        except OSError:
            findings.append(SecretFinding(path=path, label="unreadable_publication_file"))
            continue
        text = encoded.decode("utf-8", errors="replace")
        for secret_pattern in SECRET_PATTERNS:
            findings.extend(
                SecretFinding(
                    path=path,
                    label=secret_pattern.label,
                    offset=match.start(),
                )
                for match in secret_pattern.pattern.finditer(text)
            )
        if path.suffix.lower() == ".json":
            findings.extend(_sensitive_json_findings(path, text))
    return findings


def _iter_files(paths: Iterable[str | Path]) -> Iterable[Path]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (candidate for candidate in sorted(path.rglob("*")) if candidate.is_file())
        else:
            yield path


def _sensitive_json_findings(path: Path, text: str) -> list[SecretFinding]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    findings: list[SecretFinding] = []
    _walk_sensitive_json(payload, path=path, json_path="$", findings=findings)
    return findings


def _walk_sensitive_json(
    value: Any,
    *,
    path: Path,
    json_path: str,
    findings: list[SecretFinding],
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{json_path}.{_safe_json_key_segment(key)}"
            if _is_sensitive_json_key(key) and _contains_unsafe_sensitive_value(child):
                findings.append(
                    SecretFinding(
                        path=path,
                        label="sensitive_json_field",
                        json_path=child_path,
                    )
                )
            _walk_sensitive_json(child, path=path, json_path=child_path, findings=findings)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_sensitive_json(
                child,
                path=path,
                json_path=f"{json_path}[{index}]",
                findings=findings,
            )


def _normalize_json_key(value: object) -> str:
    raw = str(value)
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    return re.sub(r"[^0-9A-Za-z]+", "_", camel_split).strip("_").lower()


def _is_sensitive_json_key(value: object) -> bool:
    normalized = _normalize_json_key(value)
    if not normalized:
        return False
    ordered_terms = normalized.split("_")
    terms = frozenset(ordered_terms)
    compact = normalized.replace("_", "")
    contains_api_key = any(
        left == "api" and right == "key"
        for left, right in zip(ordered_terms, ordered_terms[1:])
    )
    return (
        bool(terms.intersection(SENSITIVE_JSON_TERMS))
        or compact in SENSITIVE_COMPACT_JSON_KEYS
        or contains_api_key
    )


def _safe_json_key_segment(value: object) -> str:
    if _is_sensitive_json_key(value):
        return "<sensitive-key>"
    raw = str(value)
    if redact_credential_like_text(raw) != raw:
        return "<redacted-key>"
    return raw


def _contains_unsafe_sensitive_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in _SAFE_SENSITIVE_VALUES
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail closed when generated public artifacts contain credential material."
    )
    parser.add_argument("paths", nargs="+", help="Publication files or directories to scan")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    findings = scan_publication_paths(args.paths)
    if not findings:
        print("publication_secret_scan=passed")
        return 0
    print(f"publication_secret_scan=failed findings={len(findings)}")
    for finding in findings:
        location = (
            f" json_path={finding.json_path}"
            if finding.json_path
            else (
                f" offset={finding.offset}"
                if finding.offset is not None
                else ""
            )
        )
        # Never print the matching bytes.
        safe_path = redact_credential_like_text(str(finding.path))
        print(f"path={safe_path} detector={finding.label}{location}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
