#!/usr/bin/env python3
"""Prepare/apply only the validated local Best retirement. Default is dry-run."""

from __future__ import annotations
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from verify_best_retirement import check

MESSAGE = "Best Factor는 Factor로 통합되었습니다. factor integrated-run을 사용하세요. 기존 Best 입력은 자동 변환하지 않습니다."
MARKER = "# Local retirement: integrated Momentum replaces this execution path."
BEST = Path("/Users/changgison/projects/best-factor")
COPY = Path(
    "/Users/changgison/Documents/Codex/2026-09-06/codex-app-omx-pc/work/pipeline-sources/best-factor"
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retired_source(text, functions):
    if MARKER in text:
        raise ValueError(
            "Source is already retired; inspect the recorded execution before retrying"
        )
    for name in functions:
        pattern = rf"(^def {name}\([^\n]*\).*:\n)"
        if name == "main":
            guard = f"    {MARKER}\n    import sys\n    print({MESSAGE!r}, file=sys.stderr)\n    return 2\n"
        else:
            guard = f"    {MARKER}\n    raise RuntimeError({MESSAGE!r})\n"
        text, count = re.subn(
            pattern, lambda match: match.group(1) + guard, text, count=1, flags=re.M
        )
        if count != 1:
            raise ValueError(f"Expected unique {name} entrypoint")
    compile(text, "<retired source>", "exec")
    return text


def guide_page(source, momentum_url):
    parsed = urlparse(momentum_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Momentum target must be the verified loopback HTTP page")
    navigation = re.search(r"<nav\b[\s\S]*?</nav>", source)
    if not navigation:
        raise ValueError("Current Best navigation could not be preserved")
    nav = navigation.group(0)
    target = html.escape(momentum_url, quote=True)
    page = f'''<!doctype html><html lang="ko" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>Best Factor · Momentum 통합</title><link rel="stylesheet" href="styles.css"><link rel="stylesheet" href="shared-nav.css"><script>try{{document.documentElement.dataset.theme=localStorage.getItem('quant-research-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light')}}catch(e){{}}</script></head><body id="top" class="has-quant-shared-nav"><a class="skip-link" href="#main-content">본문으로 건너뛰기</a>{nav}<main id="main-content"><section class="panel"><h1>Momentum으로 통합했습니다.</h1><p>팩터 연구와 월별 선택을 한곳에서 확인하세요.</p><a href="{target}">Momentum 통합 화면 열기</a></section></main><script>var themeButton=document.getElementById('theme-toggle');var isDark=document.documentElement.dataset.theme==='dark';themeButton.setAttribute('aria-pressed',String(isDark));themeButton.setAttribute('aria-label',isDark?'라이트 모드로 전환':'다크 모드로 전환');themeButton.onclick=function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;localStorage.setItem('quant-research-theme',t);this.setAttribute('aria-pressed',String(t==='dark'));this.setAttribute('aria-label',t==='dark'?'라이트 모드로 전환':'다크 모드로 전환')}}</script></body></html>'''
    if nav not in page:
        raise ValueError("Navigation preservation failed")
    return page, hashlib.sha256(nav.encode()).hexdigest()


def prepare(momentum_url):
    writes = []
    for root in (BEST, COPY):
        targets = [
            (root / "src/best_factor/cli.py", ("main", "run", "build_site")),
            (root / ".github/scripts/build_live_universe.py", ("main",)),
        ]
        if root == BEST:
            targets.append((root / ".github/scripts/refresh_dashboard_tickers.py", ("main",)))
        for path, functions in targets:
            writes.append(
                {
                    "path": path,
                    "before": digest(path),
                    "text": retired_source(path.read_text(), functions),
                }
            )
    path = BEST / "docs/index.html"
    page, nav_hash = guide_page(path.read_text(), momentum_url)
    writes.append({"path": path, "before": digest(path), "text": page})
    return writes, nav_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs/integration/cleanup-manifest.json",
    )
    parser.add_argument("--validation-report", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--momentum-url", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the gated exact local changes; never modifies remote/schedule/workflow files",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "outputs/integration/retirement-result.json",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    validation = json.loads(args.validation_report.read_text())
    result = json.loads(args.result.read_text())
    preflight = check(manifest, validation, result)
    if not preflight["ready"]:
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        return 2
    writes, nav_hash = prepare(args.momentum_url)
    plan = {
        "dryRun": not args.apply,
        "resultIdentity": result["resultIdentity"],
        "navigationHash": nav_hash,
        "modified": [str(w["path"]) for w in writes],
        "deleted": [r["path"] for r in manifest["files"]],
        "emptyDirectories": manifest.get("emptyDirectories", []),
        "completed": False,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    # Recheck every input before the first mutation, including current user edits.
    second = check(manifest, validation, result)
    if not second["ready"] or any(digest(w["path"]) != w["before"] for w in writes):
        raise RuntimeError("Preflight inputs changed; nothing applied")
    report = {**plan, "modified": [], "deleted": [], "removedEmptyDirectories": []}
    try:
        for write in writes:
            path = write["path"]
            temporary = path.with_name(path.name + ".retirement.tmp")
            if temporary.exists():
                raise RuntimeError(f"Unexpected existing temporary file: {temporary}")
            temporary.write_text(write["text"])
            temporary.replace(path)
            report["modified"].append(
                {"path": str(path), "beforeHash": write["before"], "afterHash": digest(path)}
            )
        for row in manifest["files"]:
            path = Path(row["path"])
            if digest(path) != row["sha256"]:
                raise RuntimeError(f"Candidate changed during retirement: {path}")
            path.unlink()
            report["deleted"].append(str(path))
        for value in manifest.get("emptyDirectories", []):
            path = Path(value)
            path.rmdir()
            report["removedEmptyDirectories"].append(value)
        changed = {w["path"].as_posix() for w in writes}
        for path, expected in validation["protectedHashes"].items():
            if path not in changed and digest(path) != expected:
                raise RuntimeError(f"Protected file changed: {path}")
        report["completed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
