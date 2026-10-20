"""Explicit reviewed migration of three verified source-return contracts.

This is not a daily-refresh override. Unchanged definitions must still pass the
normal historical NAV check; only the three named definitions and dependent
selection may be revised, with new versions and an inspectable comparison.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

from .integrated_automation import current_source, history_revision, tree_hash
from .integrated_service import atomic_json, build_site, code_fingerprint
from .integrated_validation import require, validate_automated_result, write_automated_manifest

REVIEW_CONTRACTS = {
    'CONSISTENCY12_1': ('signInput', 'provider-close-cash-source-interval-v1'),
    'MAX1M': ('returnInput', 'provider-close-cash-holding-return-v1'),
    'SIGNED_VP63': ('signInput', 'provider-close-cash-source-interval-v1'),
}


def reviewed_revision(baseline, candidate):
    old = {r['id']: r for r in baseline['registry']}
    new = {r['id']: r for r in candidate['registry']}
    require(old.keys() == new.keys(), 'Reviewed migration cannot change the definition set')
    changed = [key for key in old if old[key] != new[key]]
    require(changed == list(REVIEW_CONTRACTS), 'Only the three reviewed source-return definitions may change')
    for key, (prefix, contract) in REVIEW_CONTRACTS.items():
        before, after = copy.deepcopy(old[key]), copy.deepcopy(new[key])
        require(before.pop('version') == '1.0.0' and after.pop('version') == '1.1.0',
                'Unexpected reviewed migration versions: ' + key)
        require(after.pop(prefix + 'Contract') == contract, 'Unexpected source-return contract: ' + key)
        require(isinstance(after.pop(prefix + 'Notes'), str) and before == after,
                'Reviewed migration cannot alter the economic hypothesis: ' + key)
    # Compare every old date with the ordinary 10bp/null/choice checks. The
    # catalog difference is separately checked above, never silently ignored.
    comparable = {**baseline, 'registry': candidate['registry']}
    comparison = history_revision(comparable, candidate)
    permitted = set(REVIEW_CONTRACTS) | {'MONTHLY_SELECTION'}
    unexpected = [row for row in comparison['issues'] if row['curveId'] not in permitted]
    require(not unexpected, 'Unchanged factor history changed; review cannot admit the candidate')
    counts = {}
    for row in comparison['issues']:
        key = row['curveId']
        counts[key] = counts.get(key, 0) + 1
    return dict(schemaVersion='factor-definition-review/v1', status='passed',
                baselineResultId=baseline['resultIdentity']['resultId'],
                baselineInputHash=baseline['resultIdentity']['inputHash'],
                candidateResultId=candidate['resultIdentity']['resultId'],
                candidateInputHash=candidate['resultIdentity']['inputHash'],
                reviewedDefinitionIds=list(REVIEW_CONTRACTS),
                definitionsBefore={key: old[key] for key in REVIEW_CONTRACTS},
                definitionsAfter={key: new[key] for key in REVIEW_CONTRACTS},
                reason='Verified provider-close and cash inputs replace adjusted-close sign noise in CONSISTENCY/SIGNED and backward dividend-adjustment ratios in MAX1M. No return-size threshold or new ranking policy.',
                unchangedDefinitions=dict(status='passed', maximumPermittedRelativeNavRevision=.001,
                                          nullMasksPreserved=True),
                comparison=dict(comparedObservations=comparison['comparedObservations'],
                                maximumRelativeNavRevision=comparison['maximumRelativeNavRevision'],
                                maximumDifference=comparison['maximumDifference'],
                                revisedObservationCounts=counts))


def prepare(result_path, baseline_path, candidate_path, source_commit,
            expected_baseline_result, expected_input_hash, expected_input_cache_id):
    result_path, baseline_path, candidate_path = map(Path, (result_path, baseline_path, candidate_path))
    require(not candidate_path.exists(), 'Choose a new reviewed candidate directory')
    require(current_source() == source_commit, 'Reviewed source checkout differs')
    result = json.loads(result_path.read_text())
    baseline_file = baseline_path / 'data/integrated-result.json'
    baseline = json.loads(baseline_file.read_text())
    require(baseline['resultIdentity']['resultId'] == expected_baseline_result, 'Baseline result changed')
    require(result['resultIdentity']['inputHash'] == expected_input_hash, 'Candidate input changed')
    require(result['resultIdentity']['codeHash'] == code_fingerprint()[0], 'Candidate code changed')
    key = result['data'].get('inputCache', {}).get('key', '')
    require(re.fullmatch(r'factor-input-v1-[0-9]+-[0-9]+', key) is not None,
            'Reviewed primary inputs have no exact bounded cache key')
    require(str(expected_input_cache_id).isdigit(), 'Expected input cache ID is required')
    caches = json.loads(subprocess.check_output(
        ['gh', 'api', 'repos/SonChangGi/factor/actions/caches?key=' + key], text=True))
    require(any(row['key'] == key and str(row['id']) == str(expected_input_cache_id)
                for row in caches.get('actions_caches', [])), 'Reviewed primary input cache is unavailable')
    before = tree_hash(baseline_path)
    validation = validate_automated_result(result, result['data']['asOf'])
    validation['inputCacheVerified'] = dict(key=key, cacheId=str(expected_input_cache_id),
                                           verifiedAtUtc=datetime.now(timezone.utc).isoformat())
    report = reviewed_revision(baseline, result)
    report.update(sourceCommit=source_commit,
                  baselineSha256=hashlib.sha256(baseline_file.read_bytes()).hexdigest(),
                  resultIdentity=result['resultIdentity'])
    build_site(candidate_path, result)
    atomic_json(candidate_path / 'data/definition-review.json', report)
    validation['definitionReview'] = dict(path='data/definition-review.json',
        sha256=hashlib.sha256((candidate_path / 'data/definition-review.json').read_bytes()).hexdigest(),
        baselineResultId=expected_baseline_result, candidateResultId=result['resultIdentity']['resultId'],
        reviewedDefinitionIds=list(REVIEW_CONTRACTS))
    write_automated_manifest(candidate_path, result, source_commit, validation,
                             publication_type='reviewed_definition_migration')
    require(tree_hash(baseline_path) == before and current_source() == source_commit,
            'Baseline/source changed during review')
    from .publication_security import scan_publication_paths
    require(not scan_publication_paths([candidate_path]), 'Reviewed candidate failed secret scan')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('result', 'baseline', 'candidate', 'source-commit', 'expected-baseline-result', 'expected-input-hash', 'expected-input-cache-id'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.result, args.baseline, args.candidate, args.source_commit,
                            args.expected_baseline_result, args.expected_input_hash, args.expected_input_cache_id)))


if __name__ == '__main__':
    main()
