"""Explicit reviewed migration of the CONSISTENCY source-precision contract.

This is not a daily-refresh override. Unchanged definitions must still pass the
normal historical NAV check; only CONSISTENCY and its dependent selection may
be revised, with a new definition version and an inspectable comparison.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from .integrated_automation import current_source, history_revision, tree_hash
from .integrated_service import atomic_json, build_site, code_fingerprint
from .integrated_validation import require, validate_automated_result, write_automated_manifest


def reviewed_revision(baseline, candidate):
    old = {r['id']: r for r in baseline['registry']}
    new = {r['id']: r for r in candidate['registry']}
    require(old.keys() == new.keys(), 'Reviewed migration cannot change the definition set')
    changed = [key for key in old if old[key] != new[key]]
    require(changed == ['CONSISTENCY12_1'], 'Only the reviewed CONSISTENCY definition may change')
    before, after = copy.deepcopy(old[changed[0]]), copy.deepcopy(new[changed[0]])
    require(before.pop('version') == '1.0.0' and after.pop('version') == '1.1.0',
            'Unexpected CONSISTENCY migration versions')
    require(after.pop('signInputContract') == 'provider-close-cash-source-interval-v1',
            'Unexpected source-precision contract')
    require(isinstance(after.pop('signInputNotes'), str) and before == after,
            'Reviewed migration cannot alter the economic hypothesis')
    # Compare every old date with the ordinary 10bp/null/choice checks. The
    # catalog difference is separately checked above, never silently ignored.
    comparable = {**baseline, 'registry': candidate['registry']}
    comparison = history_revision(comparable, candidate)
    permitted = {'CONSISTENCY12_1', 'MONTHLY_SELECTION'}
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
                reviewedDefinitionIds=['CONSISTENCY12_1'],
                definitionBefore=old['CONSISTENCY12_1'], definitionAfter=new['CONSISTENCY12_1'],
                reason='Source-precision intervals replace adjusted-close rounding signs; no return-size threshold.',
                unchangedDefinitions=dict(status='passed', maximumPermittedRelativeNavRevision=.001,
                                          nullMasksPreserved=True),
                comparison=dict(comparedObservations=comparison['comparedObservations'],
                                maximumRelativeNavRevision=comparison['maximumRelativeNavRevision'],
                                maximumDifference=comparison['maximumDifference'],
                                revisedObservationCounts=counts))


def prepare(result_path, baseline_path, candidate_path, source_commit,
            expected_baseline_result, expected_input_hash):
    result_path, baseline_path, candidate_path = map(Path, (result_path, baseline_path, candidate_path))
    require(not candidate_path.exists(), 'Choose a new reviewed candidate directory')
    require(current_source() == source_commit, 'Reviewed source checkout differs')
    result = json.loads(result_path.read_text())
    baseline_file = baseline_path / 'data/integrated-result.json'
    baseline = json.loads(baseline_file.read_text())
    require(baseline['resultIdentity']['resultId'] == expected_baseline_result, 'Baseline result changed')
    require(result['resultIdentity']['inputHash'] == expected_input_hash, 'Candidate input changed')
    require(result['resultIdentity']['codeHash'] == code_fingerprint()[0], 'Candidate code changed')
    before = tree_hash(baseline_path)
    validation = validate_automated_result(result, result['data']['asOf'])
    report = reviewed_revision(baseline, result)
    report.update(sourceCommit=source_commit,
                  baselineSha256=hashlib.sha256(baseline_file.read_bytes()).hexdigest(),
                  resultIdentity=result['resultIdentity'])
    build_site(candidate_path, result)
    atomic_json(candidate_path / 'data/definition-review.json', report)
    validation['definitionReview'] = dict(path='data/definition-review.json',
        sha256=hashlib.sha256((candidate_path / 'data/definition-review.json').read_bytes()).hexdigest(),
        baselineResultId=expected_baseline_result, candidateResultId=result['resultIdentity']['resultId'],
        reviewedDefinitionIds=['CONSISTENCY12_1'])
    write_automated_manifest(candidate_path, result, source_commit, validation,
                             publication_type='reviewed_definition_migration')
    require(tree_hash(baseline_path) == before and current_source() == source_commit,
            'Baseline/source changed during review')
    from .publication_security import scan_publication_paths
    require(not scan_publication_paths([candidate_path]), 'Reviewed candidate failed secret scan')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('result', 'baseline', 'candidate', 'source-commit', 'expected-baseline-result', 'expected-input-hash'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.result, args.baseline, args.candidate, args.source_commit,
                            args.expected_baseline_result, args.expected_input_hash)))


if __name__ == '__main__':
    main()
