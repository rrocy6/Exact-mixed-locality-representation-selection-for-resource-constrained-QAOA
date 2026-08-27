"""Small statevector timing probes for the reference compiler pilot."""

from __future__ import annotations

from math import log2
from numbers import Number
from time import perf_counter
from typing import Mapping, Sequence

from .polynomial import Support, evaluate_pubo
from .reference_compiler import ReferenceCompilation, compile_reference


def _load_quantum_stack():
    try:
        import numpy
        import psutil
        import qiskit
        import qiskit_aer
        from qiskit import QuantumCircuit
        from qiskit_aer import AerSimulator
    except ImportError as error:
        raise RuntimeError(
            "Reference QAOA pilot requires qiskit==2.4.2 and "
            "qiskit-aer==0.17.2 in the active environment"
        ) from error
    return {
        "numpy": numpy,
        "psutil": psutil,
        "qiskit": qiskit,
        "qiskit_aer": qiskit_aer,
        "QuantumCircuit": QuantumCircuit,
        "AerSimulator": AerSimulator,
    }


def build_cold_qaoa_circuit(
    compilation: ReferenceCompilation,
    *,
    gammas: Sequence[float],
    betas: Sequence[float],
):
    """Build the fixed reference cost layer with a standard cold mixer."""

    if len(gammas) != len(betas) or not gammas:
        raise ValueError("gammas and betas must have the same positive length")
    stack = _load_quantum_stack()
    circuit = stack["QuantumCircuit"](compilation.n_qubits)
    circuit.h(range(compilation.n_qubits))

    for gamma, beta in zip(gammas, betas):
        for support, coefficient in compilation.pauli.items():
            angle = 2.0 * gamma * float(coefficient)
            if not support:
                circuit.global_phase -= gamma * float(coefficient)
            elif len(support) == 1:
                circuit.rz(angle, support[0] - 1)
            else:
                target = support[-1] - 1
                controls = [variable - 1 for variable in support[:-1]]
                for control in controls:
                    circuit.cx(control, target)
                circuit.rz(angle, target)
                for control in reversed(controls):
                    circuit.cx(control, target)
        for qubit in range(compilation.n_qubits):
            circuit.rx(2.0 * beta, qubit)
    return circuit


def _expectation(
    statevector,
    *,
    scoring_polynomial: Mapping[Support, Number],
    n_original: int,
) -> float:
    probabilities = abs(statevector) ** 2
    total = 0.0
    for index, probability in enumerate(probabilities):
        if probability == 0:
            continue
        bits = tuple((index >> bit) & 1 for bit in range(n_original))
        total += float(probability) * float(
            evaluate_pubo(scoring_polynomial, bits)
        )
    return total


def run_statevector_probe(
    encoded_polynomial: Mapping[Support, Number],
    *,
    n_qubits: int,
    scoring_polynomial: Mapping[Support, Number],
    n_original: int,
    gammas: Sequence[float],
    betas: Sequence[float],
    simulator_seed: int,
) -> dict[str, object]:
    """Build and run one exact statevector evaluation with timing evidence."""

    if n_original > n_qubits:
        raise ValueError("n_original cannot exceed n_qubits")
    stack = _load_quantum_stack()
    compilation = compile_reference(
        encoded_polynomial, n_qubits=n_qubits
    )
    circuit = build_cold_qaoa_circuit(
        compilation, gammas=gammas, betas=betas
    )
    circuit.save_statevector()
    process = None
    rss_before = None
    try:
        process = stack["psutil"].Process()
        rss_before = process.memory_info().rss
    except (stack["psutil"].Error, OSError):
        # Some containers do not expose the current PID through /proc.  The
        # simulation remains valid; the audit row records that RSS sampling
        # was unavailable instead of inventing a value.
        pass
    backend = stack["AerSimulator"](method="statevector")
    started = perf_counter()
    result = backend.run(
        circuit, seed_simulator=simulator_seed
    ).result()
    elapsed = perf_counter() - started
    statevector = stack["numpy"].asarray(result.get_statevector(circuit))
    rss_after = None
    if process is not None:
        try:
            rss_after = process.memory_info().rss
        except (stack["psutil"].Error, OSError):
            pass
    norm = float(stack["numpy"].sum(abs(statevector) ** 2))

    return {
        "status": "pass" if abs(norm - 1.0) <= 1e-9 else "fail",
        "n_original": n_original,
        "n_qubits": n_qubits,
        "qaoa_depth": len(gammas),
        "gamma_values": list(gammas),
        "beta_values": list(betas),
        "simulator_seed": simulator_seed,
        "simulation_runtime_sec": elapsed,
        "statevector_amplitudes": len(statevector),
        "statevector_raw_mib": len(statevector) * 16 / (1024**2),
        "process_rss_status": (
            "measured"
            if rss_before is not None and rss_after is not None
            else "unavailable"
        ),
        "process_rss_delta_mib": (
            (rss_after - rss_before) / (1024**2)
            if rss_before is not None and rss_after is not None
            else None
        ),
        "statevector_norm": norm,
        "projected_original_expectation": _expectation(
            statevector,
            scoring_polynomial=scoring_polynomial,
            n_original=n_original,
        ),
        "circuit_depth_all_gates": circuit.depth(),
        "circuit_size_all_gates": circuit.size(),
        "two_qubit_gate_count_per_cost_layer": (
            compilation.two_qubit_gate_count
        ),
        "two_qubit_depth_per_cost_layer": compilation.two_qubit_depth,
        "qiskit_version": stack["qiskit"].__version__,
        "qiskit_aer_version": stack["qiskit_aer"].__version__,
    }


def synthetic_width_polynomial(n_qubits: int) -> dict[Support, int]:
    """Create a deterministic degree-three stress polynomial for width probes."""

    if n_qubits < 3:
        raise ValueError("Synthetic width probes require at least three qubits")
    terms: dict[Support, int] = {
        (variable,): 1 if variable % 2 else -1
        for variable in range(1, n_qubits + 1)
    }
    for first in range(1, n_qubits - 1):
        terms[(first, first + 1, first + 2)] = (
            1 if first % 2 else -1
        )
    return terms


def statevector_width_from_amplitudes(amplitudes: int) -> int:
    """Return log2(amplitudes), rejecting non-power-of-two lengths."""

    if amplitudes < 1 or amplitudes & (amplitudes - 1):
        raise ValueError("Statevector length must be a positive power of two")
    return int(log2(amplitudes))
