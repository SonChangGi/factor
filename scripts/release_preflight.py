"""Read-only release gates shared by local work, PRs, Pages and daily updates."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESENTATION_FILES = frozenset({
    'index.html', 'assets/integrated.js', 'assets/integrated_charts.js',
    'assets/integrated.css', 'assets/styles.css', 'assets/shared-nav.css',
})
FINANCIAL_SETTINGS = (
    'start_date', 'end_date', 'evaluation_window_days', 'top_n', 'max_weight',
    'transaction_cost_bps', 'slippage_bps', 'execution_delay_sessions',
    'weighting', 'common_universe', 'comparison_factors',
)


def inventory(site):
    site = Path(site)
    if site.is_symlink():
        raise ValueError('Publication root cannot be a symbolic link')
    files = {}
    for path in sorted(site.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Publication contains a symbolic link: {path.relative_to(site)}')
        if path.is_file() and path != site / 'publication.json':
            files[path.relative_to(site).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def differences(expected, observed):
    return {
        'missing': sorted(expected.keys() - observed.keys()),
        'added': sorted(observed.keys() - expected.keys()),
        'changed': sorted(key for key in expected.keys() & observed.keys()
                          if expected[key] != observed[key]),
    }


def check_files(site):
    site = Path(site)
    manifest = json.loads((site / 'publication.json').read_text())
    diff = differences(manifest['files'], inventory(site))
    if any(diff.values()):
        hint = (' For presentation-only edits, run: '
                'python scripts/prepare_presentation_release.py --write')
        raise ValueError('Publication contains missing, changed or unreviewed files: '
                         + json.dumps(diff, sort_keys=True) + hint)
    return manifest


def daily_compatibility(result, *, registry=None, symbols=None, settings=None, lock=None):
    """Reject migrations before collection, without manufacturing a new baseline."""
    from factor_lab.integrated_data import integrated_universe
    from factor_lab.integrated_engine import IntegratedConfig
    from factor_lab.integrated_factors import factor_registry
    from factor_lab.integrated_validation import validate_runtime_lock

    registry = factor_registry() if registry is None else registry
    expected = {row['id']: row for row in result['registry']}
    current = {row['id']: row for row in registry}
    changed = sorted(key for key in expected.keys() | current.keys()
                     if expected.get(key) != current.get(key))
    if changed or result['registry'] != registry:
        raise ValueError('Daily update requires a reviewed definition baseline: '
                         + ', '.join(changed or ['catalog order']))
    symbols = ({row['symbol'] for row in integrated_universe()['symbols']}
               if symbols is None else set(symbols))
    if set(result['data']['requestedSymbols']) != symbols:
        raise ValueError('Daily update requires a reviewed universe baseline')
    settings = asdict(IntegratedConfig()) if settings is None else settings
    changed_settings = [key for key in FINANCIAL_SETTINGS
                        if json.dumps(result['settings'].get(key), sort_keys=True)
                        != json.dumps(settings.get(key), sort_keys=True)]
    if changed_settings:
        raise ValueError('Daily update requires reviewed financial settings: '
                         + ', '.join(changed_settings))
    validate_runtime_lock(result['resultIdentity'],
                          (ROOT / 'uv.lock').read_bytes() if lock is None else lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'site')
    parser.add_argument('--mode', choices=['files', 'daily', 'release'], default='release')
    args = parser.parse_args()
    try:
        check_files(args.site)
        if args.mode != 'files':
            result = json.loads((args.site / 'data/integrated-result.json').read_text())
            daily_compatibility(result)
        if args.mode == 'release':
            from scripts.validate_integrated_publication import validate
            from factor_lab.publication_security import scan_publication_paths
            validate(args.site)
            if scan_publication_paths([args.site, ROOT / 'docs']):
                raise ValueError('Publication security scan failed')
        print(f'PASS {args.mode} preflight (no collection, calculation or publication)')
        return 0
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        print(f'BLOCKED {args.mode} preflight: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
