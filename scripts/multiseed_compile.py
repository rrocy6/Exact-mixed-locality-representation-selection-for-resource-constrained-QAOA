"""Fixed identity placement, explicit SABRE trials, persistent isolated workers."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import time
import traceback
from multiseed_core import atomic_json, digest, read, sha

THREAD_ENV = {'QISKIT_PARALLEL': 'FALSE', 'RAYON_NUM_THREADS': '1',
              'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
os.environ.update(THREAD_ENV)


def load_compiler(run):
    path = Path(run) / 'inputs/experiments/compiled_study.py'
    spec = importlib.util.spec_from_file_location('multiseed_frozen_compiler', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pass_manager(compiler, topology, logical_width, seed, trials):
    from qiskit.transpiler import CouplingMap
    from qiskit.transpiler.passes import SabreSwap
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager, common
    coupling = CouplingMap(compiler.topology(topology))
    pm = generate_preset_pass_manager(optimization_level=3, basis_gates=compiler.CONFIG['basis'],
            coupling_map=coupling, initial_layout=list(range(logical_width)),
            layout_method='trivial', routing_method='sabre', seed_transpiler=seed)
    # Public stage replacement: no unsupported transpile keyword or ignored YAML.
    # No VF2PostLayout: identity input placement is part of the controlled protocol.
    routing = SabreSwap(coupling, heuristic='decay', seed=seed, trials=trials)
    pm.routing = common.generate_routing_passmanager(routing, None, coupling_map=coupling,
            seed_transpiler=-1, vf2_call_limit=None, vf2_max_trials=None,
            use_barrier_before_measurement=True)
    return pm


def compile_task(run, task, attempt, semantic=False):
    import numpy as np
    from qiskit import qpy, QuantumCircuit
    from qiskit.quantum_info import Statevector
    run = Path(run)
    cfg = read(run / 'config.json')
    started = time.perf_counter()
    result = {**task, 'attempt_id': attempt, 'config_hash': digest(cfg),
              'implementation_hash': cfg['implementation_hash'], 'effective_trials': cfg['sabre_trials'],
              'actual_seed': task['seed'], 'resources': None, 'error': None}
    try:
        compiler = load_compiler(run)
        item = read(run / task['candidate_path'])
        if item['logical_Q'] > 12:
            result['status'] = 'width_exceeded'
            return result
        path = run / task['input_path']
        if sha(path) != task['input_hash']:
            raise ValueError('Frozen input circuit changed')
        with path.open('rb') as f:
            circuit = qpy.load(f)[0]
        trace, sabre = [], []
        def callback(**kwargs):
            operation = kwargs['pass_']
            name = type(operation).__name__
            trace.append(name)
            if name in {'SabreLayout', 'VF2Layout', 'VF2PostLayout'}:
                raise ValueError('Undeclared placement search: ' + name)
            if name == 'SabreSwap':
                actual = {'seed': operation.seed, 'trials': operation.trials, 'heuristic': operation.heuristic}
                if actual != {'seed': task['seed'], 'trials': cfg['sabre_trials'], 'heuristic': 'decay'}:
                    raise ValueError('Effective routing settings differ')
                sabre.append(actual)
        compiled = pass_manager(compiler, task['topology'], item['logical_Q'], task['seed'], cfg['sabre_trials']).run(circuit, callback=callback)
        initial = compiled.layout.initial_index_layout(filter_ancillas=True)
        if initial != list(range(item['logical_Q'])):
            raise ValueError('Initial placement is not identity')
        active = set(range(item['logical_Q']))
        allowed = set(compiler.topology(task['topology']))
        for instruction in compiled.data:
            bits = tuple(compiled.find_bit(q).index for q in instruction.qubits)
            active.update(bits)
            if len(bits) == 2 and (instruction.operation.name != 'cx' or bits not in allowed):
                raise ValueError('Wrong native entangling gate or coupling edge')
        if {p.name for p in compiled.parameters} != {p.name for p in circuit.parameters}:
            raise ValueError('Symbolic parameter changed')
        r = {'Q': len(active), 'logical_Q': item['logical_Q'], 'aux': item['n_aux'],
             'G': int(compiled.count_ops().get('cx', 0)),
             'D': int(compiled.depth(filter_function=lambda i: len(i.qubits) == 2)),
             'M': item['M'], 'total_gates': int(compiled.size()), 'all_gate_depth': int(compiled.depth()),
             'reduced': item['reduced']}
        r['J'] = (r['aux']/4 + r['G']/160 + r['D']/120 + r['M']/8)/4
        if semantic:
            # Independent diagonal phase evaluation on every basis input in a
            # uniform superposition, including final routing permutation.
            bound = compiled.assign_parameters({p: 0.371 for p in compiled.parameters})
            prep = QuantumCircuit(compiled.num_qubits)
            for i in range(item['logical_Q']):
                prep.h(i)
            prep.compose(bound, inplace=True)
            actual = Statevector.from_instruction(prep).data
            poly, _ = compiler.representation(item['instance'], item['actions'])
            idx = np.arange(1 << item['logical_Q'], dtype=np.uint64)
            values = np.zeros(len(idx))
            for support, coeff in poly.items():
                mask = sum(1 << i for i in support)
                values += coeff * ((idx & mask) == mask)
            final = compiled.layout.final_index_layout(filter_ancillas=True)
            positions = sum(((idx >> i) & 1) << site for i, site in enumerate(final))
            expected = np.zeros_like(actual)
            expected[positions.astype(int)] = np.exp(-1j * 0.371 * values) / np.sqrt(len(idx))
            overlap = np.vdot(expected, actual)
            error = float(np.max(np.abs(actual - overlap * expected)))
            if error > 1e-9 or abs(abs(overlap) - 1) > 1e-9:
                raise ValueError('Routed circuit phase equivalence failed: ' + str(error))
            result['semantic_max_error'] = error
        trace_hash = digest(trace)
        trace_path = run / 'pass_traces' / (trace_hash + '.json')
        if not trace_path.exists():
            atomic_json(trace_path, trace)
        relative = f'circuits/{task["task_id"]}_{attempt}.qpy'
        output = run / relative
        output.parent.mkdir(exist_ok=True)
        temp = output.with_suffix('.tmp')
        with temp.open('wb') as f:
            qpy.dump(compiled, f)
        os.replace(temp, output)
        result.update(status='compiled', resources=r, circuit_path=relative, circuit_sha256=sha(output),
                      pass_trace_hash=trace_hash, routing_executions=sabre,
                      identity_initial_layout_verified=True, symbolic_parameters=sorted(p.name for p in compiled.parameters))
    except Exception as exc:
        result.update(status='compile_error', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    finally:
        result['elapsed_seconds'] = time.perf_counter() - started
    return result


def worker(run, incoming, outgoing):
    os.environ.update(THREAD_ENV)
    while True:
        request = incoming.get()
        if request is None:
            break
        task, attempt, semantic = request
        result = compile_task(run, task, attempt, semantic)
        atomic_json(Path(run) / 'attempts' / (task['task_id'] + '_' + attempt + '.json'), result)
        outgoing.put(result)


def verify_formal_semantics(compiler, run, task, compiled):
    """Check all diagonal phases at two fixed angles and the final routing map."""
    import numpy as np
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Statevector
    candidate = task['candidate']
    instance = read(Path(run) / 'inputs/experiments/compiled_results/instances' / (task['instance_id'] + '.json'))['instance']
    actions = tuple(int(a) for a in candidate['actions'].split(',') if a)
    polynomial, logical = compiler.representation(instance, actions)
    width = int(logical['Q'])
    idx = np.arange(1 << width, dtype=np.uint64)
    energies = np.zeros(len(idx))
    for support, coefficient in polynomial.items():
        mask = sum(1 << i for i in support)
        energies += coefficient * ((idx & mask) == mask)
    final = compiled.layout.final_index_layout(filter_ancillas=True)
    positions = sum(((idx >> i) & 1) << site for i, site in enumerate(final))
    errors = []
    for angle in (0.371, -0.219):
        bound = compiled.assign_parameters({p: angle for p in compiled.parameters})
        prep = QuantumCircuit(compiled.num_qubits)
        for i in range(width):
            prep.h(i)
        prep.compose(bound, inplace=True)
        actual = Statevector.from_instruction(prep).data
        expected = np.zeros_like(actual)
        expected[positions.astype(int)] = np.exp(-1j * angle * energies) / np.sqrt(len(idx))
        overlap = np.vdot(expected, actual)
        error = float(np.max(np.abs(actual - overlap * expected)))
        if error > 1e-9 or abs(abs(overlap) - 1) > 1e-9:
            raise ValueError('Formal routed circuit phase equivalence failed: ' + str(error))
        errors.append(error)
    return {'status': 'pass', 'method': 'all diagonal phases in uniform superposition, final layout corrected, up to global phase',
            'angles': [0.371, -0.219], 'max_errors': errors, 'logical_width': width,
            'scope': 'formal explicit SABRE worker; finite angle samples'}
