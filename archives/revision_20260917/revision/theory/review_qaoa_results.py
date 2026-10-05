"""Read-only independent audit of the frozen new QAOA experiment."""
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import sys

HERE = Path(__file__).resolve().parent
REVISION = HERE.parent
sys.path.insert(0, str(REVISION / 'python_deps'))
import numpy as np

ROOT = REVISION / 'qaoa_new'
spec = importlib.util.spec_from_file_location('qaoa_audit_run', ROOT / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)
read = lambda path: json.loads(Path(path).read_text(encoding='utf-8'))
freeze = read(ROOT / 'freeze.json')
freeze_hash = hashlib.sha256((ROOT / 'freeze.json').read_bytes()).hexdigest()
for name, digest in freeze['hashes'].items():
    assert hashlib.sha256((REVISION / name).read_bytes()).hexdigest() == digest
data = [read(p) for p in sorted((ROOT / 'results').glob('*.json'))]
assert len(data) == len({r['instance_id'] for r in data}) == len({r['seed'] for r in data}) == 60
counts = {'equal_effort': 0, 'second_optimizer': 0, 'scan_refined': 0, 'grid': 0}
completion = {key: 0 for key in counts if key != 'grid'}
for r in data:
    assert r['freeze_sha256'] == freeze_hash
    assert len(r['rows']) == 8
    for row in r['rows']:
        for method in ('equal_effort', 'second_optimizer', 'scan_refined'):
            if method not in row:
                continue
            result = row[method]
            target = 960 if method == 'scan_refined' else 360
            assert len(result['trace']) == result['calls'] == target
            assert [t['call'] for t in result['trace']] == list(range(1, target + 1))
            assert abs(min(t['objective'] for t in result['trace']) - result['objective']) < 1e-10
            assert abs(result['objective'] - result['original_mean']) < 1e-10
            assert abs(result['norm'] - 1) < 1e-10
            assert all(result['trace'][i+1]['incumbent'] <= result['trace'][i]['incumbent'] + 1e-12
                       for i in range(target-1))
            counts[method] += target
            completion[method] += sum(t.get('uniform_completion_calls', 0) for t in result['trace'])
        if 'scan_refined' in row:
            grid = np.load(ROOT / row['grid_file'])['objective']
            assert grid.shape == (65, 65)
            assert abs(grid.min() - row['scan_refined']['grid_minimum']) < 1e-10
            assert row['scan_refined']['objective'] <= grid.min() + 1e-9
            assert np.max(np.abs(grid[0] - row['p0'])) < 1e-10
            counts['grid'] += grid.size
        if row['warming'] != 'cold':
            assert abs(row['p0'] - r['independent_sampling_expected_mean']) < 1e-10
    m = r['selections']['full']['domain_size']
    assert r['selections']['full']['calls'] == min(m, 128)
    m = r['selections']['proper_mixed']['domain_size']
    assert r['selections']['proper_mixed']['calls'] == min(m, 128)


def expectation_independent(poly, representation, probabilities, angles):
    width = representation.n_qubits
    original_n = representation.original_width
    bits = np.array([[(i >> q) & 1 for q in range(width)] for i in range(1 << width)])
    initial = np.sqrt(np.prod(np.where(bits, probabilities, 1-np.asarray(probabilities)), axis=1)).astype(complex)
    def vals(polynomial):
        return np.array([sum(float(c) for support, c in polynomial.items()
                             if all(b[q-1] for q in support)) for b in bits])
    original, encoded = vals(poly), vals(representation.polynomial)
    assert np.max(np.abs(encoded - np.rint(encoded))) < 1e-12
    gamma, beta = angles
    state = initial * np.exp(-1j * gamma * encoded)
    # Explicit Kronecker matrix, independent of both the vectorised scan and
    # the simulator's strided in-place mixer implementation.
    unitary = np.eye(1, dtype=complex)
    for probability in probabilities:
        x, z = 2 * np.sqrt(probability * (1-probability)), 1-2*probability
        B = np.array([[z, x], [x, -z]])
        u = math.cos(beta) * np.eye(2) - 1j * math.sin(beta) * B
        unitary = np.kron(u, unitary)
    state = unitary @ state
    return float(np.abs(state)**2 @ original), float(np.abs(initial)**2 @ original)


first = read(ROOT / 'results' / 'max3sat_00.json')
instance = read(ROOT / 'instances' / 'max3sat_00.json')
poly = run.max3sat_to_pubo(instance)
selection = first['selections']['proper_mixed']
representation = run.build_mixed_representation(poly, n_original=6,
    actions=tuple(None if a is None else tuple(a) for a in selection['actions']), default_margin=1)
row = next(r for r in first['rows'] if r['representation']=='proper_mixed' and r['warming']=='pair')
calculated, p0 = expectation_independent(poly, representation, np.array(row['probabilities']), row['equal_effort']['parameters'])
assert abs(calculated - row['equal_effort']['objective']) < 1e-10
assert abs(p0 - row['p0']) < 1e-10
grid = np.load(ROOT / row['grid_file'])['objective']
errors = []
for i, j in [(0,0),(0,38),(1,3),(11,19),(37,61),(64,64)]:
    computed, _ = expectation_independent(poly, representation, np.array(row['probabilities']),
                                         [2*math.pi*i/65, math.pi*j/65])
    errors.append(abs(computed-grid[i,j]))
assert max(errors) < 1e-10
_, regenerated_selection = run.select(poly, 6, read(ROOT/'protocol.json'), first['seed'])
assert regenerated_selection == first['selections']

summary = read(ROOT/'analysis'/'summary.json')
primary = {}
for family in ('max3sat','spin_glass'):
    group = [r for r in data if r['family'] == family]
    vals = np.array([next(x for x in r['rows'] if x['representation']=='native' and x['warming']=='pair')['p0'] -
                     next(x for x in r['rows'] if x['representation']=='native' and x['warming']=='pair')['equal_effort']['objective'] for r in group])
    rng = np.random.default_rng(3619)
    boot = vals[rng.integers(0,30,size=(10000,30))].mean(axis=1)
    interval = [float(vals.mean()), *np.quantile(boot,[.025,.975]).tolist()]
    saved = summary['families'][family]['native_incremental_gain']
    assert np.max(np.abs(np.array(interval) - [saved['mean'],saved['low'],saved['high']])) < 1e-12
    primary[family] = interval

audit = dict(freeze_files_checked=len(freeze['hashes']), instances=60, arms=480,
    method_calls=counts, uniform_completions=completion, primary_contrast_recomputed=primary,
    explicit_matrix_example={'instance':'max3sat_00','representation':'proper_mixed','warming':'pair',
        'width':representation.n_qubits,'original_p1':calculated,'p0':p0,
        'preparation_gain':first['cold_p0']-p0, 'evolution_gain':p0-calculated,
        'maximum_sampled_scan_error':max(errors)},
    reproduced_selection=True, all_checks_passed=True)
(HERE/'independent_qaoa_checks.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
print(json.dumps(audit,indent=2))
