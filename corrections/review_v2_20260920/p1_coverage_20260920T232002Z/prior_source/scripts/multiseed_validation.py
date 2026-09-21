"""Shared validation for persisted compilation evidence and scientific resources."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

DIMENSIONS = ('Q', 'G', 'D', 'M')
TERMINAL = {'compiled', 'width_exceeded', 'compile_error', 'timeout'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def natural_key(row):
    return tuple(str(row[k]) for k in ('instance_id', 'candidate_id', 'topology', 'synthesis')) + (int(row['seed']),)

def task_id(row):
    return digest({k: int(row[k]) if k == 'seed' else row[k] for k in ('instance_id', 'candidate_id', 'topology', 'synthesis', 'seed')})[:24]

def validate_resources(resources, candidate=None):
    for d in DIMENSIONS:
        value = resources.get(d)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid resource: ' + d)
        if d != 'M' and int(value) != value:
            raise ValueError('Noninteger resource: ' + d)
    if resources['Q'] > 12 or resources['Q'] < 1:
        raise ValueError('Resource Q outside device capacity')
    if candidate is not None:
        if resources['Q'] < int(candidate['logical_Q']):
            raise ValueError('Resource Q below logical width')
        if abs(resources['M'] - float(candidate['maximum_penalty'])) > 1e-9:
            raise ValueError('Penalty differs from candidate')
        score = (int(candidate['n_aux']) / 4 + resources['G'] / 160 + resources['D'] / 120 + resources['M'] / 8) / 4
        if not math.isfinite(float(resources.get('J', float('nan')))) or abs(resources['J'] - score) > 1e-12:
            raise ValueError('Invalid resource score J')

def capacity_excluded(candidate, row):
    # Candidate width is bound to the frozen manifest by validate_rows/load_run.
    try:
        return row.get('status') == 'width_exceeded' and int(candidate['logical_Q']) > 12
    except (KeyError, ValueError, TypeError):
        return False

def validate_rows(tasks, rows, candidates, run=None, require_success=False):
    expected = Counter(natural_key(t) for t in tasks)
    observed = Counter(natural_key(r) for r in rows)
    if any(n != 1 for n in expected.values()) or any(n != 1 for n in observed.values()) or expected != observed:
        raise ValueError('Task coverage mismatch: missing, extra or duplicate natural keys')
    lookup = {c['candidate_id']: c for c in candidates}
    task_lookup = {natural_key(t): t for t in tasks}
    links = {}
    root = Path(run).resolve() if run is not None else None
    for row in rows:
        task = task_lookup[natural_key(row)]
        if row.get('task_id') not in {task.get('task_id'), task_id(row)}:
            raise ValueError('Task ID not canonical or declared legacy ID')
        c = lookup[row['candidate_id']]
        if row.get('status') not in TERMINAL:
            raise ValueError('Result is not terminal')
        if row['status'] == 'width_exceeded' and not capacity_excluded(c, row):
            raise ValueError('Unproven capacity exclusion')
        if require_success and row['status'] not in {'compiled', 'width_exceeded'}:
            raise ValueError('P1 requires successful compilation')
        if row['status'] != 'compiled':
            continue
        validate_resources(json.loads(row['resources_json']), c)
        if not isinstance(row.get('circuit_sha256'), str) or len(row['circuit_sha256']) != 64:
            raise ValueError('Missing circuit digest')
        if run is not None:
            relative = row['circuit_path']
            if relative not in links:
                path = (root / relative).resolve()
                if not path.is_relative_to(root):
                    raise ValueError('Digest path outside run')
                links[relative] = json.loads(path.read_text(encoding='utf-8-sig'))
            link = links[relative].get(row['task_id'], {})
            if link.get('sha256') != row['circuit_sha256'] or link.get('trace') != row.get('trace_json', ''):
                raise ValueError('Circuit digest/trace linkage mismatch')
    counts = Counter(r['status'] for r in rows)
    return {'coverage_complete': True, 'compiled_count': counts['compiled'],
            'failed_count': counts['compile_error'] + counts['timeout'],
            'capacity_excluded_count': counts['width_exceeded'], 'terminal_counts': dict(counts)}

def validate_config(run, config):
    if digest({k: v for k, v in config.items() if k != 'config_hash'}) != config.get('config_hash'):
        raise ValueError('Configuration content hash mismatch')
    manifest = json.loads((run / 'INPUT_COPY_MANIFEST.json').read_text(encoding='utf-8-sig'))
    for relative, expected in manifest['files'].items():
        path = (run / 'inputs' / relative).resolve()
        if not path.is_relative_to((run / 'inputs').resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen input hash mismatch: ' + relative)
    for relative, field in [('experiments/compiled_study.py', 'compiled_study_source_sha256'), ('experiments/compiled_results/freeze.json', 'source_freeze_sha256')]:
        if hashlib.sha256((run / 'inputs' / relative).read_bytes()).hexdigest() != config[field]:
            raise ValueError('Configuration input identity mismatch: ' + field)
    # This version implements one declared protocol. Unsupported edits must fail,
    # even when the user has recomputed the config digest.
    compiler = config['compiler']
    fixed = {'optimization_level': 3, 'basis_gates': ['rz', 'sx', 'x', 'cx'], 'routing': 'sabre',
             'heuristic': 'decay', 'initial_layout': 'identity', 'layout_method': 'trivial'}
    for k, v in fixed.items():
        if compiler.get(k) != v:
            raise ValueError('Unsupported compiler setting: ' + k)
    if type(compiler['sabre_trials']) is not int or compiler['sabre_trials'] < 1:
        raise ValueError('Invalid SABRE trials')
    if config.get('control_seed') != 1729 or config.get('T_cap_seconds') is not None:
        raise ValueError('Unsupported control seed or total cap')
    parallel = config['parallelism']
    if parallel.get('thread_env') != {'QISKIT_PARALLEL':'FALSE', 'RAYON_NUM_THREADS':'1', 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}:
        raise ValueError('Unsupported thread environment')
    if type(parallel['formal_workers']) is not int or parallel['formal_workers'] < 1:
        raise ValueError('Invalid worker count')
    timeout = parallel['task_timeout_seconds']
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Invalid timeout')

def retention_metrics(seed_classes, control=1729):
    import numpy as np
    base = seed_classes[control] == 1
    other = np.vstack([a == 1 for s, a in seed_classes.items() if s != control])
    common = int(np.sum(base & np.all(other, axis=0)))
    total = int(base.sum())
    unknown = int(np.sum(base & np.any(np.vstack([a == 2 for s, a in seed_classes.items() if s != control]), axis=0)))
    return {'baseline_true_cells': total, 'common_true_cells': common,
            'lost_in_any_other_seed': total - common,
            'lost_in_all_other_seeds': int(np.sum(base & ~np.any(other, axis=0))),
            'new_true_cells': int(np.sum(~base & np.any(other, axis=0))),
            'baseline_unknown_under_other_seeds': unknown,
            'retention': common / total if total else 'N/A',
            'classification': 'empty_baseline' if not total else ('unknown' if unknown else ('stable' if common == total else ('partial' if common else 'disappeared')))}

def selector_metrics(candidates, baseline_rows, current_rows, budgets):
    import numpy as np
    def winner(rows):
        choices = [(json.loads(r['resources_json'])['J'], c['candidate_id'], c['category'])
                   for c in candidates for r in rows.get(c['candidate_id'], []) if r['status'] == 'compiled']
        return min(choices) if choices else None
    baseline, selected = winner(baseline_rows), winner(current_rows)
    out = {'selected_candidate_id': selected[1] if selected else '', 'selected_category': selected[2] if selected else '',
           'baseline_selected_candidate_id': baseline[1] if baseline else '', 'baseline_selected_feasible': 'UNKNOWN',
           'baseline_budget_cells': 0, 'retained_baseline_budget_cells': 'UNKNOWN', 'baseline_coverage_retention': 'N/A',
           'baseline_resource_task_id': '', 'current_resource_task_id': '',
           'budget_set_definition': 'all complete grid tuples feasible for the fixed baseline J winner'}
    if baseline is None:
        return out
    cid = baseline[1]
    br = baseline_rows[cid][0]
    def mask(row):
        r = json.loads(row['resources_json'])
        validate_resources(r)
        return np.all(np.array([r[d] for d in DIMENSIONS]) <= budgets + [0, 0, 0, 1e-9], axis=1)
    base = mask(br)
    n = int(base.sum())
    out.update(baseline_budget_cells=n, baseline_resource_task_id=br['task_id'])
    if not n:
        out.update(baseline_selected_feasible='N/A', retained_baseline_budget_cells=0)
        return out
    rows = current_rows.get(cid, [])
    if len(rows) != 1 or rows[0]['status'] != 'compiled':
        return out
    kept = int(np.sum(base & mask(rows[0])))
    out.update(current_resource_task_id=rows[0]['task_id'], retained_baseline_budget_cells=kept,
               baseline_coverage_retention=kept / n, baseline_selected_feasible='TRUE' if kept == n else 'FALSE')
    return out
