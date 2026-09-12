"""Read-only plan/input verification. Does not run QAOA or approve execution."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csvrows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parent
    repo = args.repo.resolve()
    errors = []
    for name, base in [('SHA256_MANIFEST.csv', bundle), ('SOURCE_INPUT_MANIFEST.csv', repo)]:
        for row in csvrows(bundle / name):
            file = (base / row['relative_path']).resolve()
            if not file.is_relative_to(base):
                errors.append('Unsafe path: ' + row['relative_path'])
            elif not file.is_file():
                errors.append('Missing: ' + str(file))
            elif digest(file) != row['sha256'] or file.stat().st_size != int(row['size_bytes']):
                errors.append('Byte hash/size mismatch: ' + str(file))
    manifest = bundle / 'SHA256_MANIFEST.csv'
    if digest(manifest) != (bundle / 'SHA256_MANIFEST.sha256').read_text().split()[0]:
        errors.append('Bundle manifest sidecar mismatch')
    plan = json.loads((bundle / 'EXPERIMENT_PLAN.json').read_text(encoding='utf-8'))
    rows = csvrows(bundle / plan['expected_runs_manifest'])
    counts = collections.Counter(r['study'] for r in rows)
    ids = [r['task_id'] for r in rows]
    if len(ids) != len(set(ids)):
        errors.append('Duplicate task IDs')
    identity = plan['run_identity_fields']
    for r in rows:
        value = {k: r[k] for k in identity}
        key = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if key != r['task_id']:
            errors.append('Task identity mismatch: ' + r['task_id'])
    for study, spec in plan['studies'].items():
        if counts[study] != spec['expected_rows']:
            errors.append('Count mismatch: ' + study)
        schedule = [r for r in rows if r['study'] == study]
        actions = dict(collections.Counter(r['planned_action'] for r in schedule))
        if actions != spec['actions']:
            errors.append('Action counts mismatch: ' + study)
        source = repo / spec['raw_source']
        if source.is_file():
            raw = csvrows(source)
            keys = [k for k in identity if k != 'study']
            a = collections.Counter(tuple(r[k] for k in keys) for r in schedule)
            b = collections.Counter(tuple(r[k] for k in keys) for r in raw)
            if a != b:
                errors.append('Source-to-schedule key mismatch: ' + study)
            for task in schedule:
                index = int(task['source_csv_row_number']) - 2
                if index < 0 or index >= len(raw):
                    errors.append('Source row outside bounds: ' + task['task_id'])
                    continue
                source_row = raw[index]
                for field in source_row.keys() & task.keys():
                    if field not in {'code_commit', 'config_hash'} and source_row[field] != task[field]:
                        errors.append('Frozen source field mismatch: ' + task['task_id'] + '/' + field)
    print(json.dumps({'input_plan_check': 'FAIL' if errors else 'PASS',
                      'task_counts': dict(counts), 'errors': errors,
                      'execution_binding': 'PENDING_LOCAL_CODE_AND_EVIDENCE_BINDING',
                      'qaoa_runs_started': False}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
