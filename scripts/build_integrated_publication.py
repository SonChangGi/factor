"""Assemble reviewed integrated UI plus explicitly retained legacy API artifacts.

Legacy JSON stays byte-identical and is never interpreted as integrated results.
Scheduled legacy writers cannot replace the reviewed integrated entry point.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(output, site=None, legacy=None, source_sha=None):
    output = Path(output)
    site = Path(site) if site else ROOT / 'site'
    legacy = Path(legacy) if legacy else ROOT / 'docs/data'
    if output.exists():
        raise FileExistsError('Choose an empty publication directory')
    shutil.copytree(site, output, symlinks=False)
    files = {}
    for path in sorted(legacy.rglob('*')):
        if path.is_symlink():
            raise ValueError('Public artifacts cannot be symbolic links')
        if not path.is_file():
            continue
        relative = Path('data') / path.relative_to(legacy)
        target = output / relative
        if target.exists():
            raise ValueError(f'Legacy artifact collides with reviewed integrated asset: {relative}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        'schemaVersion': 'legacy-publication/v1',
        'role': 'legacy_momentum_api_compatibility',
        'sourceCommit': source_sha or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'integratedResult': 'data/integrated-result.json',
        'integratedRefresh': 'separate_reviewed_snapshot',
        'files': files,
    }
    (output / 'legacy-publication.json').write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    print(f'Assembled integrated site with {len(files)} unchanged legacy API artifacts')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
