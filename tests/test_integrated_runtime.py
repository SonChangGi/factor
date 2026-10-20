"""The published runtime must match the frozen dependency source."""
from copy import deepcopy
import hashlib
import pytest
from factor_lab.integrated_validation import validate_runtime_lock

NAMES = ('numpy', 'pandas', 'exchange-calendars', 'rfc8785', 'yfinance', 'finance-datareader')


def fixture():
    lock = ''.join(f'[[package]]\nname = "{name}"\nversion = "1.2.3"\n\n' for name in NAMES).encode()
    identity = {'runtime': {'pythonVersion': '3.12.11',
                'dependencyLockHash': hashlib.sha256(lock).hexdigest(),
                'packageVersions': dict.fromkeys(NAMES, '1.2.3')}}
    return identity, lock


def test_frozen_runtime_accepts_exact_versions():
    identity, lock = fixture()
    validate_runtime_lock(identity, lock)


@pytest.mark.parametrize('mutation', ['version', 'absent', 'lock', 'python'])
def test_different_or_missing_runtime_is_rejected(mutation):
    identity, lock = fixture()
    identity = deepcopy(identity)
    runtime = identity['runtime']
    if mutation == 'version':
        runtime['packageVersions']['pandas'] = '1.2.4'
    elif mutation == 'absent':
        runtime['packageVersions']['yfinance'] = None
    elif mutation == 'lock':
        lock += b'# changed source\n'
    else:
        runtime['pythonVersion'] = 'unknown'
    with pytest.raises(ValueError):
        validate_runtime_lock(identity, lock)
