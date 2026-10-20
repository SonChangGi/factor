"""Bind reviewed presentation bytes while preserving every financial proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release_preflight import PRESENTATION_FILES, check_files, differences, inventory  # noqa: E402


def prepare(site):
    from scripts.validate_integrated_publication import validate
    from factor_lab.integrated_service import atomic_json
    from factor_lab.publication_security import scan_publication_paths

    site = Path(site)
    manifest_path = site / 'publication.json'
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    observed = inventory(site)
    diff = differences(manifest['files'], observed)
    if diff['missing'] or diff['added'] or set(diff['changed']) - PRESENTATION_FILES:
        raise ValueError('Only existing presentation files can be rebound: '
                         + json.dumps(diff, sort_keys=True))
    if not diff['changed']:
        check_files(site)
        return []
    manifest['files'] = observed
    # Validate the proposed manifest in isolation; never bless a broken live tree.
    with tempfile.TemporaryDirectory(prefix='factor-presentation-') as folder:
        candidate = Path(folder) / 'site'
        shutil.copytree(site, candidate)
        atomic_json(candidate / 'publication.json', manifest)
        validate(candidate)
        if scan_publication_paths([candidate]):
            raise ValueError('Presentation failed publication security scan')
        if manifest_path.read_bytes() != original or inventory(site) != observed:
            raise RuntimeError('Publication changed during preparation')
        atomic_json(manifest_path, manifest)
    return diff['changed']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT / 'site')
    parser.add_argument('--write', action='store_true', help='Explicitly bind reviewed UI changes')
    args = parser.parse_args()
    if args.write:
        print(json.dumps({'presentationFilesUpdated': prepare(args.site)}))
    else:
        check_files(args.site)
        print('PASS presentation manifest; no files changed')


if __name__ == '__main__':
    main()
