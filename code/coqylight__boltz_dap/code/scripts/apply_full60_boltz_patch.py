"""Apply the full60 patch only to the exact recorded upstream source state."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    if not path.is_file():
        return None
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def apply(source, manifest_path, *, check_only=False):
    manifest = json.loads(manifest_path.read_text())
    changed = False
    for entry in manifest['files']:
        actual = digest(source / entry['path'])
        if actual != entry['before_sha256']:
            raise ValueError('Unexpected upstream source state: ' + entry['path'])
        changed |= entry['before_sha256'] != entry['after_sha256']
    patch_path = manifest_path.with_name('full60-bf16.patch')
    if digest(patch_path) != manifest['patch_sha256'] or not changed:
        raise ValueError('Patch identity or change inventory is invalid')
    subprocess.run(['git', 'apply', '--check', '--whitespace=nowarn', str(patch_path)], cwd=source, check=True)
    if check_only:
        return
    subprocess.run(['git', 'apply', '--whitespace=nowarn', str(patch_path)], cwd=source, check=True)
    for entry in manifest['files']:
        if digest(source / entry['path']) != entry['after_sha256']:
            raise ValueError('Patched source verification failed: ' + entry['path'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boltz-checkout', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    manifest = Path(__file__).resolve().parents[1] / 'patches/boltz-2.2.1/manifest.json'
    apply(args.boltz_checkout.resolve(), manifest, check_only=args.check_only)
    print('PASS: exact upstream patch preconditions' if args.check_only else 'PASS: patch applied and every native dependency hash verified')


if __name__ == '__main__':
    main()