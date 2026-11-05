"""Reviewed full-period universe transition using accepted frozen market inputs."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

POLICY = Path(__file__).parent / "resources/integrated_historical_universe.json"


def historical_contract():
    raw = POLICY.read_bytes()
    policy = json.loads(raw)
    return {
        "policyVersion": policy["version"], "policySha256": sha256(raw).hexdigest(),
        "applyThrough": policy["applyThrough"], "excluded": policy["excluded"],
        "listedStockCount": policy["listedStockCount"], "sources": policy["sources"],
    }


def apply_historical_universe(market, contract):
    import pandas as pd

    if contract != historical_contract():
        raise ValueError("Historical universe differs from the reviewed policy")
    symbols = set(market.metadata["requestedSymbols"])
    if (set(contract["excluded"]) - symbols
            or len(symbols - set(contract["excluded"])) != contract["listedStockCount"]):
        raise ValueError("Historical universe does not match the collected security inventory")
    eligibility = market.eligibility.copy()
    eligibility.loc[eligibility.index <= pd.Timestamp(contract["applyThrough"]),
                    list(contract["excluded"])] = False
    return replace(market, eligibility=eligibility,
                   metadata={**market.metadata, "historicalUniverse": contract})


def validate_historical_targets(result):
    """Also used against the embedded source policy during publication checks."""
    contract = result["data"].get("historicalUniverse")
    if not contract:
        return
    from .integrated_validation import require

    require(contract["policySha256"] == result["resultIdentity"]["codeHashFiles"].get(
        "resources/integrated_historical_universe.json"), "Historical universe source binding")
    symbols = set(result["data"]["requestedSymbols"])
    require(set(contract["excluded"]) <= symbols
            and len(symbols - set(contract["excluded"])) == contract["listedStockCount"],
            "Historical universe inventory")
    for book in [result["selection"], *result["factors"]]:
        for row in book.get("history", []):
            if row["signalDate"] <= contract["applyThrough"]:
                require(set(contract["excluded"]).isdisjoint(
                    holding["symbol"] for holding in row.get("targetHoldings", [])),
                    "Historical target contains an excluded security")


def migrate(workspace, baseline, candidate, archive_root, source_commit):
    from .integrated_automation import current_source, tree_hash, validate_required_valuations
    from .integrated_data import load_integrated_market, save_integrated_market
    from .integrated_service import atomic_json, build_site, code_fingerprint, execute_run
    from .integrated_validation import validate_automated_result, write_automated_manifest

    workspace, baseline, candidate, archive_root = map(Path, (workspace, baseline, candidate, archive_root))
    if workspace.exists() or candidate.exists():
        raise FileExistsError("Choose a new immutable migration workspace and candidate")
    if current_source() != source_commit:
        raise ValueError("Migration checkout differs from the requested source")
    result_bytes = (baseline / "data/integrated-result.json").read_bytes()
    previous = json.loads(result_bytes)
    policy = json.loads(POLICY.read_bytes())
    if (previous["resultIdentity"]["resultId"] != policy["baselineResultId"]
            or previous["resultIdentity"]["inputHash"] != policy["baselineInputHash"]
            or sha256(result_bytes).hexdigest() != policy["baselineResultSha256"]
            or previous["data"]["asOf"] != policy["applyThrough"]
            or previous["data"]["universeSourceHash"] != policy["universeSourceHash"]):
        raise ValueError("Migration requires the exact reviewed production baseline")
    workspace.mkdir(parents=True)
    before, fingerprint = tree_hash(baseline), code_fingerprint()[0]
    cache = previous["data"]["inputCache"]
    status = dict(schemaVersion="factor-automation/v1", state="running",
                  sourceCommit=source_commit, baselineHash=before, inputCacheKey=cache["key"],
                  targetDataAsOf=policy["applyThrough"])
    atomic_json(workspace / "status.json", status)
    try:
        market = load_integrated_market(archive_root / "market")
        if market.metadata["snapshotId"] != previous["resultIdentity"]["inputHash"]:
            raise ValueError("Restored market differs from the accepted production result")
        # The raw and price vintage remain the accepted cache's exact inputs.
        if market.metadata.get("inputCache") != cache:
            raise ValueError("Restored market cache binding differs")
        market = apply_historical_universe(market, historical_contract())
        holdings_check = validate_required_valuations(market, previous, previous["data"]["asOf"])
        market = save_integrated_market(market, workspace / "market", compression_level=1)
        result = execute_run(market, previous["settings"], workspace / "analysis")
        if result["registry"] != previous["registry"] or result["settings"] != previous["settings"]:
            raise ValueError("Reviewed universe migration changed definitions or financial settings")
        validation = validate_automated_result(result, policy["applyThrough"])
        validation["universeReview"] = {
            "baselineResultId": policy["baselineResultId"], "baselineInputHash": policy["baselineInputHash"],
            "baselineResultSha256": policy["baselineResultSha256"],
            "policySha256": historical_contract()["policySha256"],
            "definitionsUnchanged": True, "settingsUnchanged": True,
            "acceptedInputCache": cache, "holdingValuations": holdings_check,
        }
        if (tree_hash(baseline) != before or current_source() != source_commit
                or code_fingerprint()[0] != fingerprint):
            raise RuntimeError("Source or baseline changed during the reviewed migration")
        build_site(candidate, result)
        write_automated_manifest(candidate, result, source_commit, validation,
                                 publication_type="reviewed_universe_migration")
        from .publication_security import scan_publication_paths
        if scan_publication_paths([candidate]):
            raise ValueError("Migration candidate failed publication scanning")
        status.update(state="validated", resultId=result["resultIdentity"]["resultId"],
                      dataAsOf=result["data"]["asOf"], candidateHash=tree_hash(candidate),
                      candidate=str(candidate.resolve()), validation=validation)
        atomic_json(workspace / "status.json", status)
        return status
    except Exception as exc:
        status.update(state="failed", errorType=type(exc).__name__, reason=str(exc),
                      lastGoodPreserved=tree_hash(baseline) == before)
        atomic_json(workspace / "status.json", status)
        raise


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "baseline", "candidate", "archive-root"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    print(json.dumps(migrate(args.workspace, args.baseline, args.candidate,
                             args.archive_root, args.source_commit)))


if __name__ == "__main__":
    main()
