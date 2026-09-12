"""Independent stdlib-only integrity and numerical audit of the E2/E5 update."""
import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import statistics


def read(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def jread(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def identity(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def reference_metrics(terms):
    # Expand x=(1-Z)/2 directly with exact rational arithmetic.
    coefficients = defaultdict(Fraction)
    for term in terms:
        support = term['support']
        c = Fraction(term['coefficient']) / (2 ** len(support))
        for size in range(len(support) + 1):
            for subset in combinations(support, size):
                coefficients[subset] += c * ((-1) ** size)
    availability = defaultdict(int)
    gates = depth = 0
    for support, c in sorted(coefficients.items(), key=lambda item: (len(item[0]), item[0])):
        if c == 0 or len(support) < 2:
            continue
        target = support[-1]
        for control in [*support[:-1], *reversed(support[:-1])]:
            layer = max(availability[control], availability[target]) + 1
            availability[control] = availability[target] = layer
            gates += 1
            depth = max(depth, layer)
    nz = [abs(c) for s, c in coefficients.items() if s and c]
    return gates, depth, float(max(nz) / min(nz)) if nz else 0.


def audit_e5(root):
    old = read(root / 'inputs/old_E5.csv')
    primary = read(root / 'analysis/E5_instance_level.csv')
    additional = read(root / 'analysis/E5_additional_topologies_instance_level.csv')
    key_fields = ['instance_id', 'metric', 'budget_mode', 'budget_key', 'topology_id']
    k = lambda r: tuple(r[f] for f in key_fields)
    require(len(primary) == len(old) == 272 and {k(r) for r in primary} == {k(r) for r in old}, 'E5 endpoint set differs')
    resources = read(root / 'results/E2_merged_rows.csv') + read(root / 'results/E2_added_topologies_merged_rows.csv')
    qaoa = read(root / 'inputs/E3_merged_runs.csv')
    truth = {r['instance_id']: float(r['optimum_original']) for r in read(root / 'inputs/truth.csv') if r['exact_truth'] == 'True'}
    resource_index, qindex = defaultdict(list), defaultdict(list)
    for r in resources:
        if r['representation'] in ['selective', 'matched_random_selective']:
            resource_index[(r['instance_id'], r['topology_id'])].append(r)
    for r in qaoa:
        if r['representation'] in ['selective', 'matched_random_selective']:
            qindex[(r['instance_id'], r['budget_key'])].append(r)
    max_error = 0.
    fields = {'compiled_two_qubit_gates': 'two_qubit_gates', 'compiled_two_qubit_depth': 'two_qubit_depth', 'routing_overhead': 'routing_overhead', 'qaoa_original_objective': 'original_objective_mean'}
    for endpoint in primary + additional:
        is_q = endpoint['source_tier'] == 'qaoa'
        iid = endpoint['instance_id']
        rows = qindex[(iid, endpoint['budget_key'])] if is_q else resource_index[(iid, endpoint['topology_id'])]
        require(rows and {r['split'] for r in rows} == {'test'}, 'Non-test data in E5')
        statuses = {r['status'] for r in rows}
        if statuses == {'infeasible_width_exceeds_topology'}:
            require(endpoint['classification'] == 'not_estimable' and endpoint['effect'] == '', 'Capacity failure imputed')
            continue
        require(statuses == {'pass'}, 'Unexpected or mixed compiler failure in E5')
        group = defaultdict(list)
        repeat = 'restart_id' if is_q else 'transpiler_seed'
        for r in rows:
            group[r[repeat]].append(r)
        require(len(group) == (3 if is_q else 5), 'E5 repetition count differs')
        effects = []
        for items in group.values():
            selected = [r for r in items if r['representation'] == 'selective']
            random = [r for r in items if r['representation'] == 'matched_random_selective']
            require(len(selected) == 1 and len(random) == len({r['random_rep_seed'] for r in random}) == 5, 'Unmatched random draws')
            field = fields[endpoint['metric']]
            s = float(selected[0][field])
            c = sum(float(r[field]) for r in random) / 5
            scale = max(1, abs(truth[iid] if is_q else c))
            effects.append((c - s) / scale)
        mean = sum(effects) / len(effects)
        half = 1.96 * statistics.stdev(effects) / math.sqrt(len(effects))
        low, high = mean - half, mean + half
        tolerance = 0.01 if is_q else 0.05
        label = 'help' if low > tolerance else 'hurt' if high < -tolerance else 'little_effect'
        require(endpoint['classification'] == label, 'E5 classification mismatch')
        for field, actual in [('effect', mean), ('effect_ci95_low', low), ('effect_ci95_high', high), ('effect_tolerance', tolerance)]:
            err = abs(float(endpoint[field]) - actual)
            max_error = max(err, max_error)
            require(err < 1e-10, 'E5 numerical reconstruction mismatch')
    return {'primary_endpoints_verified': len(primary), 'additional_endpoints_verified': len(additional),
            'maximum_numeric_reconstruction_error': max_error, 'primary_counts': dict(Counter(r['classification'] for r in primary))}


def verify(root):
    root = root.resolve()
    manifest = root / 'SHA256_MANIFEST.csv'
    require(sha(manifest) == (root / 'SHA256_MANIFEST.sha256').read_text(encoding='utf-8').strip(), 'Manifest hash mismatch')
    entries = read(manifest)
    require(len(entries) == len({r['path'] for r in entries}), 'Duplicate manifest entries')
    for r in entries:
        p = (root / r['path']).resolve()
        require(p.is_relative_to(root) and p.is_file() and p.stat().st_size == int(r['size_bytes']) and sha(p) == r['sha256'], 'Artifact hash mismatch: ' + r['path'])
    plan = jread(root / 'PLAN.json')
    for name, expected in plan['frozen_files'].items():
        require(sha(root / name) == expected, 'Frozen input mismatch')
    jobs = jread(root / 'TASKS.json')
    require(len(jobs) == len({j['task_id'] for j in jobs}) == 285, 'Task coverage mismatch')
    new_index, statuses = {}, Counter()
    qiskit_count = reference_count = capacity_count = 0
    for job in jobs:
        p = root / 'task_results' / (job['task_id'] + '.json')
        require(sha(p) == p.with_suffix('.sha256').read_text(encoding='utf-8').strip(), 'Checkpoint hash mismatch')
        c = jread(p)
        require(c['status'] == 'PASS' and c['job_sha256'] == identity(job) and c['task_id'] == job['task_id'], 'Checkpoint identity differs')
        require(len(c['rows']) == 25, 'Missing resource rows')
        gates, depth, kappa = reference_metrics(job['record']['encoded_terms'])
        for r in c['rows']:
            k = (r['study'], int(r['source_csv_row']))
            require(k not in new_index and r['design_id'] != r['source_design_id'], 'Duplicate or unchanged new observation')
            new_index[k] = r
            statuses[r['status']] += 1
            require(abs(float(r['coefficient_dynamic_range_corrected']) - kappa) < 1e-10, 'Nonidentity coefficient range differs')
            if r['status'] == 'infeasible_width_exceeds_topology':
                require(int(r['n_qubits']) > int(r['topology_capacity']), 'False capacity failure')
                require(all(r[f] == '' for f in ['two_qubit_gates', 'two_qubit_depth', 'swap_count', 'routing_overhead']), 'Capacity failure has fabricated resources')
                capacity_count += 1
            elif r['status'] == 'pass':
                require(0 <= int(r['two_qubit_depth']) <= int(r['two_qubit_gates']), 'Invalid gates/depth')
                if r['topology_id'] == 'all_to_all_reference':
                    require(int(r['two_qubit_gates']) == gates and int(r['two_qubit_depth']) == depth, 'Exact reference resource mismatch')
                    reference_count += 1
                else:
                    require(int(r['n_qubits']) <= int(r['topology_capacity']), 'Passing circuit exceeds width')
                    require(int(r['routing_overhead']) == int(r['two_qubit_gates']) - gates, 'Routing overhead mismatch')
                    qiskit_count += 1
            else:
                raise ValueError('Unexpected compiler failure')
    reused = 0
    for study in ['E2', 'E2_added_topologies']:
        old = read(root / 'inputs' / (study + '.csv'))
        merged = read(root / 'results' / (study + '_merged_rows.csv'))
        require(len(old) == len(merged), 'Merged row coverage differs')
        for number, (a, b) in enumerate(zip(old, merged), 2):
            replacement = new_index.get((study, number))
            expected = a if replacement is None else replacement
            require(all(b[k] == str(v) for k, v in expected.items()), 'Resource field differs from source/checkpoint')
            reused += replacement is None
    return {'status': 'PASS', 'resource_design_groups': len(jobs), 'new_resource_rows': len(new_index),
            'qiskit_transpilation_rows': qiskit_count, 'reference_compilation_rows': reference_count,
            'expected_capacity_rows': capacity_count, 'new_resource_statuses': dict(statuses),
            'unchanged_resource_rows_verified': reused, 'E5': audit_e5(root)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(verify(a.output), indent=2))
