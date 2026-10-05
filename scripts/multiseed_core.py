"""Scientific primitives for a frozen, finite-library compilation experiment."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np
try:
    from .multiseed_validation import validate_resources, capacity_excluded
except ImportError:
    from multiseed_validation import validate_resources, capacity_excluded

SEEDS = [1729, 2718, 31415, 57721, 65537]
DIMENSIONS = ['Q', 'G', 'D', 'M']
TRUE, FALSE, UNKNOWN = 1, 0, 2
TERMINAL = {'compiled', 'width_exceeded', 'timeout', 'compile_error'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, sort_keys=True, ensure_ascii=False, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def strict_mixed(candidate):
    evidence = candidate.get('evidence', {})
    if not (evidence.get('applicable') and evidence.get('mismatch_count') == 0
            and evidence.get('inconsistent_minimiser_count') == 0):
        return None
    if 'n_aux' not in candidate or 'retained_cubic' not in candidate:
        return None
    return candidate['n_aux'] > 0 and candidate['retained_cubic'] > 0


def candidate_states(candidate, result, budgets):
    """1 feasible, 0 excluded, 2 unknown; complete vectors, no synthetic minima."""
    if result is None or result['status'] not in TERMINAL:
        return np.full(len(budgets), UNKNOWN, np.uint8)
    if result['status'] == 'width_exceeded':
        return np.full(len(budgets), FALSE if capacity_excluded(candidate, result) else UNKNOWN, np.uint8)
    if result['status'] != 'compiled' or strict_mixed(candidate) is None:
        return np.full(len(budgets), UNKNOWN, np.uint8)
    resources = result['resources']
    try:
        validate_resources(resources)
    except (ValueError, TypeError, KeyError):
        return np.full(len(budgets), UNKNOWN, np.uint8)
    v = np.array([resources[d] for d in DIMENSIONS])
    return np.all(v <= budgets + np.array([0, 0, 0, 1e-9]), axis=1).astype(np.uint8)


def classify(candidates, results, budgets):
    mixed_yes = np.zeros(len(budgets), bool)
    nonmixed_yes = mixed_yes.copy()
    mixed_unknown = mixed_yes.copy()
    nonmixed_unknown = mixed_yes.copy()
    for c, r in zip(candidates, results):
        kind = strict_mixed(c)
        states = candidate_states(c, r, budgets)
        if kind is None:
            # Invalid certification cannot contribute a witness or exclusion.
            mixed_unknown |= states != FALSE
            nonmixed_unknown |= states != FALSE
        elif kind:
            mixed_yes |= states == TRUE
            mixed_unknown |= states == UNKNOWN
        else:
            nonmixed_yes |= states == TRUE
            nonmixed_unknown |= states == UNKNOWN
    out = np.full(len(budgets), UNKNOWN, np.uint8)
    out[nonmixed_yes | ~(mixed_yes | mixed_unknown)] = FALSE
    out[mixed_yes & ~nonmixed_yes & ~nonmixed_unknown] = TRUE
    return out


def pooled_classify(candidates, attempts, budgets):
    # Union is over actual complete circuit vectors, equally for every candidate.
    expanded, results = [], []
    for c, rows in zip(candidates, attempts):
        for r in rows:
            expanded.append(c)
            results.append(r)
    return classify(expanded, results, budgets)


def frontier(candidates, results):
    rows = [(c['candidate_id'], r['resources']) for c, r in zip(candidates, results)
            if r is not None and r['status'] == 'compiled' and strict_mixed(c) is not None]
    vectors = np.array([[r[d] for d in DIMENSIONS] for _, r in rows])
    keys = set()
    for i, (key, _) in enumerate(rows):
        if not np.any(np.all(vectors <= vectors[i] + 1e-10, axis=1)
                      & np.any(vectors < vectors[i] - 1e-10, axis=1)):
            keys.add(key)
    complete = all(r is not None and r['status'] in {'compiled', 'width_exceeded'}
                   and strict_mixed(c) is not None for c, r in zip(candidates, results))
    return keys, complete


def validate_cached(task, result, config_hash, implementation_hash, run):
    for key, expected in [('task_id', task['task_id']), ('input_hash', task['input_hash']),
                          ('config_hash', config_hash), ('implementation_hash', implementation_hash)]:
        if result.get(key) != expected:
            raise ValueError('Cache mismatch: ' + key)
    if result.get('status') not in TERMINAL:
        raise ValueError('Cache is not terminal')
    if result['status'] == 'compiled':
        if sha(Path(run) / result['circuit_path']) != result['circuit_sha256']:
            raise ValueError('Compiled circuit hash mismatch')


def verify_exactness(compiler, instance, actions):
    """Enumerate every x,y and explicitly check the unique consistent lift."""
    poly, logical = compiler.representation(instance, actions)
    n, width = instance['n'], logical['Q']
    idx = np.arange(1 << width, dtype=np.uint64)
    energies = np.zeros(len(idx))
    for support, coefficient in poly.items():
        mask = sum(1 << i for i in support)
        energies += coefficient * ((idx & mask) == mask)
    original_idx = np.arange(1 << n, dtype=np.uint64)
    original = np.zeros(len(original_idx))
    for support, coefficient in compiler.original(instance).items():
        mask = sum(1 << i for i in support)
        original += coefficient * ((original_idx & mask) == mask)
    table = energies.reshape((-1, 1 << n))
    minima = table.min(axis=0)
    mismatch = int(np.count_nonzero(np.abs(minima - original) > 1e-9))
    active = sorted({compiler.pairs(edge)[a] for (edge, _), a in zip(compiler.cubic_terms(instance), actions) if a >= 0})
    correct_aux = np.zeros(len(original_idx), dtype=np.uint64)
    for j, (u, v) in enumerate(active):
        correct_aux |= (((original_idx >> u) & 1) * ((original_idx >> v) & 1)) << j
    minimisers = np.abs(table - minima[None, :]) <= 1e-9
    inconsistent = int(np.count_nonzero(minimisers & (np.arange(table.shape[0])[:, None] != correct_aux[None, :])))
    return {'applicable': True, 'method': 'exhaustive_all_x_y_unique_consistent_lift',
            'assignments_checked': 1 << width, 'mismatch_count': mismatch,
            'inconsistent_minimiser_count': inconsistent, 'encoded_polynomial_hash': digest(sorted((list(k), v) for k, v in poly.items()))}
