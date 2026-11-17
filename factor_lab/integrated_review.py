"""Explicit reviewed migration of three verified source-return contracts.

This is not a daily-refresh override. Unchanged definitions must still pass the
normal historical NAV check; only the three named definitions and dependent
selection may be revised, with new versions and an inspectable comparison.
"""
from __future__ import annotations

import copy

from .integrated_automation import history_revision
from .integrated_validation import require

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
