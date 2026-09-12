"""Verify the consolidated original archives without rerunning experiments."""
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile

from verify_selected_qaoa_results import verify as verify_qaoa
from verify_resources_e5_results import verify as verify_resources

DELIVERY = Path('delivery/20260913')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def extract_result(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 600_000_000:
            raise ValueError('Unexpected expanded archive size')
        seen = set()
        for info in z.infolist():
            relative = PurePosixPath(info.filename.replace('\\', '/'))
            name = str(relative)
            if (relative.is_absolute() or '..' in relative.parts or
                    any(':' in part for part in relative.parts) or
                    name.casefold() in seen or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError('Unsafe or duplicate archive member')
            seen.add(name.casefold())
            path = destination / name
            if info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(info))


def verify(repo, workspace, check_manifest=True):
    repo, workspace = Path(repo).resolve(), Path(workspace).resolve()
    delivery = repo / DELIVERY
    manifest_count = 0
    if check_manifest:
        manifest = delivery / 'ARTIFACT_MANIFEST.csv'
        if sha(manifest) != (delivery / 'ARTIFACT_MANIFEST.sha256').read_text().strip():
            raise ValueError('Delivery manifest digest mismatch')
        with manifest.open(encoding='utf-8-sig', newline='') as stream:
            entries = list(csv.DictReader(stream))
        if len(entries) != len({r['path'] for r in entries}):
            raise ValueError('Duplicate delivery manifest entry')
        for row in entries:
            path = (repo / row['path']).resolve()
            if (not path.is_relative_to(repo) or not path.is_file() or
                    path.stat().st_size != int(row['size_bytes']) or sha(path) != row['sha256']):
                raise ValueError('Delivery file differs: ' + row['path'])
        manifest_count = len(entries)
    inventory = read_json(delivery / 'ARCHIVES.json')
    archives = {}
    for item in inventory:
        path = (repo / item['path']).resolve()
        if (not path.is_relative_to(repo) or path.stat().st_size != item['size_bytes'] or
                sha(path) != item['sha256']):
            raise ValueError('Original archive digest mismatch: ' + item['kind'])
        archives[item['kind']] = path
    qroot, rroot = workspace / 'qaoa', workspace / 'resources'
    extract_result(archives['qaoa_windows'], qroot)
    extract_result(archives['resources_windows'], rroot)
    qresult, rresult = verify_qaoa(qroot), verify_resources(rroot)
    qsha = sha(qroot / 'results/E3_merged_runs.csv')
    if qsha != sha(rroot / 'inputs/E3_merged_runs.csv'):
        raise ValueError('E5 did not use this QAOA result')
    for name in ['EXECUTION_AUDIT.json', 'EXECUTION_BINDING.json', 'COVERAGE.csv']:
        if sha(qroot / name) != sha(rroot / 'inputs/qaoa_provenance' / name):
            raise ValueError('QAOA provenance differs: ' + name)
    if read_json(rroot / 'inputs/qaoa_provenance/INPUT_VERIFICATION.json') != qresult:
        raise ValueError('Stored QAOA verification differs from independent verification')
    for path in (rroot / 'inputs/selection').iterdir():
        if path.is_file() and sha(path) != sha(qroot / 'inputs/selection' / path.name):
            raise ValueError('Shared selector input differs')
    # The original 4,800-task audit reconstructs all 60 primary contrasts.
    from run_delivery_closeout import audit_correction
    old_audit_dir = workspace / 'original_correction_audit'
    old_audit_dir.mkdir()
    old = audit_correction(repo, old_audit_dir, archives['warmstart_original'])
    return dict(status='PASS', checked_delivery_manifest_entries=manifest_count,
                original_correction=old, qaoa=qresult, resources=rresult,
                E5_input_sha256=qsha, cross_package_provenance='PASS',
                experiment_optimizations_executed_by_verifier=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='urss_delivery_verify_') as directory:
        result = verify(args.repo, Path(directory))
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
