"""Formal Step 8 / E6 limited-noise study pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from .e2_resources import _verify_hash
from .e3_qaoa import (
    QAOABudgetSpec,
    _canonical_polynomial,
    budget_specs,
    compile_budget_plan,
    optimize_qaoa_run,
    qaoa_designs,
    statevector_data,
    verify_e3_inputs,
)
from .polynomial import Support, evaluate_pubo


class E6NoiseError(RuntimeError):
    """Formal E6 cannot proceed or failed a mandatory scope/fairness gate."""


RUN_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "random_rep_seed",
    "design_id",
    "budget_mode",
    "budget_key",
    "p",
    "compiled_2q_budget",
    "compiled_2q_gates_per_layer",
    "actual_2q_gates",
    "topology_id",
    "transpiler_seed",
    "optimizer",
    "optimizer_seed",
    "restart_id",
    "optimizer_evaluations",
    "optimized_parameters_sha256",
    "optimized_parameters_json",
    "shots",
    "circuit_seed",
    "measurement_seed",
    "noise_model_id",
    "noise_level",
    "one_qubit_depolarizing_probability",
    "two_qubit_depolarizing_probability",
    "symmetric_readout_probability",
    "original_objective_mean",
    "original_objective_best",
    "optimum_hit_rate",
    "encoded_energy_mean",
    "auxiliary_inconsistency_rate",
    "paired_degradation_vs_noiseless",
    "simulation_runtime_sec",
    "objective_scoring",
    "auxiliary_scoring_rule",
    "status",
    "failure_kind",
    "failure_message",
    "config_hash",
    "noise_manifest_hash",
    "protocol_config_hash",
    "e3_validation_summary_hash",
    "e5_validation_summary_hash",
    "code_commit",
)


SUMMARY_FIELDS = (
    "family",
    "representation",
    "noise_level",
    "instance_count",
    "design_count",
    "run_count",
    "original_objective_mean",
    "original_objective_ci95_low",
    "original_objective_ci95_high",
    "paired_degradation_vs_noiseless_mean",
    "paired_degradation_vs_noiseless_ci95_low",
    "paired_degradation_vs_noiseless_ci95_high",
    "optimum_hit_rate_mean",
    "optimum_hit_rate_ci95_low",
    "optimum_hit_rate_ci95_high",
    "auxiliary_inconsistency_rate_mean",
    "auxiliary_inconsistency_rate_ci95_low",
    "auxiliary_inconsistency_rate_ci95_high",
    "status",
    "config_hash",
    "noise_manifest_hash",
    "protocol_config_hash",
    "code_commit",
)


NOISE_LEVEL_ORDER = ("noiseless", "realistic_low", "realistic_high")
REPRESENTATION_ORDER = (
    "all_native",
    "fully_quadratized",
    "selective",
    "matched_random_selective",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E6NoiseError(f"Expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_hash(path: Path) -> str:
    digest = _sha256(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def _uncertainty(values: Sequence[float]) -> tuple[float, float, float]:
    if not values:
        return math.nan, math.nan, math.nan
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half, mean + half


def _parameter_hash(values: Sequence[float]) -> str:
    payload = json.dumps(
        [float(value) for value in values], separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _validate_protocol_config(
    protocol: Mapping[str, object], parent: Mapping[str, object]
) -> None:
    required = {
        "protocol_version": "e6_noise_v1",
        "scope": "formal_step8_e6_limited_noise_study",
        "noise_subset_path": "data/manifests/noise_subset_v1.csv",
        "required_instance_count": 18,
        "required_instances_per_family": 9,
        "budget_mode": "equal_compiled_two_qubit_gates",
        "compiled_2q_budget": 256,
        "depth_rule": "largest_positive_p_with_full_compiled_measured_circuit_at_or_below_budget",
        "shots": 4096,
        "topology_id": "device_sparse_v1",
        "parameter_policy": "fresh_noiseless_e3_protocol_per_noise_subset_design",
        "transpiler_seed_rule": "smallest_frozen_seed_attaining_median_single_layer_2q_cost",
        "primary_score": "original_family_objective_after_discarding_auxiliaries",
        "real_device_required": False,
    }
    for key, expected in required.items():
        if protocol.get(key) != expected:
            raise E6NoiseError(f"Frozen E6 protocol mismatch: {key}")
    if protocol.get("noise_level_order") != list(NOISE_LEVEL_ORDER):
        raise E6NoiseError("E6 must retain noiseless plus exactly two noise levels")
    if protocol.get("one_qubit_error_gates") != ["sx", "x"]:
        raise E6NoiseError("Frozen one-qubit error gate set changed")
    if protocol.get("two_qubit_error_gates") != ["cx"]:
        raise E6NoiseError("Frozen two-qubit error gate set changed")
    qaoa = parent["qaoa"]  # type: ignore[index]
    if int(protocol["shots"]) != int(qaoa["shots"]["sampled_or_noisy_runs"]):  # type: ignore[index]
        raise E6NoiseError("E6 shots differ from the frozen QAOA protocol")
    if int(protocol["compiled_2q_budget"]) not in qaoa["compiled_two_qubit_gate_budgets"]:  # type: ignore[operator,index]
        raise E6NoiseError("E6 budget is not a frozen E3 compiled budget")
    if protocol["topology_id"] != parent["noise"]["topology_id"]:  # type: ignore[index]
        raise E6NoiseError("E6 topology differs from the frozen noise topology")


def _noise_row_qmax(row: Mapping[str, str], frozen_qmax: int) -> int:
    """Resolve Qmax without requiring noise-subset rows to duplicate it."""

    declared = row.get("qmax", "").strip()
    if not declared:
        return frozen_qmax
    try:
        manifest_qmax = int(declared)
    except ValueError as error:
        raise E6NoiseError(f"Invalid noise-subset qmax: {declared!r}") from error
    if manifest_qmax != frozen_qmax:
        raise E6NoiseError(
            "Noise-subset qmax differs from the frozen experiment config"
        )
    return frozen_qmax

def verify_e6_inputs(
    *,
    config_path: Path,
    config_hash_path: Path,
    protocol_config_path: Path,
    protocol_config_hash_path: Path,
    data_directory: Path,
    results_directory: Path,
) -> dict[str, object]:
    """Recheck every frozen input and the E5 continuation gate."""

    frozen = verify_e3_inputs(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
        results_directory=results_directory,
    )
    config = frozen["config"]  # type: ignore[assignment]
    protocol_hash = _verify_hash(protocol_config_path, protocol_config_hash_path)
    protocol = _load_json(protocol_config_path)
    _validate_protocol_config(protocol, config)

    noise_path = data_directory / "manifests/noise_subset_v1.csv"
    noise_hash = _verify_hash(
        noise_path, data_directory / "manifests/noise_subset_v1.sha256"
    )
    noise_rows = _read_csv(noise_path)
    frozen_qmax = int(
        config["dataset"]["tiers"]["qaoa"]["common_width_limit_qmax"]  # type: ignore[index]
    )
    family_counts: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    for row in noise_rows:
        instance_id = row["instance_id"]
        if instance_id in seen:
            raise E6NoiseError(f"Duplicate noise-subset instance: {instance_id}")
        seen.add(instance_id)
        family_counts[row["family"]] += 1
        if row["all_four_within_qmax"] != "True":
            raise E6NoiseError(f"Noise-subset Qmax failure: {instance_id}")
        widths = (
            int(row["all_native_width"]),
            int(row["fully_quadratized_width"]),
            int(row["selective_width_upper_bound"]),
            int(row["matched_random_width_upper_bound"]),
        )
        if max(widths) > _noise_row_qmax(row, frozen_qmax):
            raise E6NoiseError(f"Noise-subset width mismatch: {instance_id}")
        truth = frozen["ground_truth_rows"].get(instance_id)  # type: ignore[index,union-attr]
        if not truth or truth["status"] != "optimal" or truth["exact_truth"] != "True":
            raise E6NoiseError(f"Noise-subset truth is not exact: {instance_id}")
    required_count = int(protocol["required_instance_count"])
    per_family = int(protocol["required_instances_per_family"])
    if len(noise_rows) != required_count or dict(family_counts) != {
        "cubic_spin_glass": per_family,
        "max3sat": per_family,
    }:
        raise E6NoiseError(f"Wrong frozen noise-subset coverage: {dict(family_counts)}")

    declared_levels = config["noise"]["levels"]  # type: ignore[index]
    if [item["id"] for item in declared_levels] != list(NOISE_LEVEL_ORDER):
        raise E6NoiseError("Frozen parent noise-level order changed")
    nonzero = [item for item in declared_levels if item["id"] != "noiseless"]
    if len(nonzero) != 2 or config["noise"]["require_exactly_two_nonzero_levels"] is not True:  # type: ignore[index]
        raise E6NoiseError("E6 requires exactly two frozen nonzero levels")

    for stem in (
        "e3_qaoa_runs",
        "e3_budget_plan",
        "e3_qaoa_summary",
        "e3_validation_summary",
    ):
        path = results_directory / f"{stem}.csv"
        if stem == "e3_validation_summary":
            path = results_directory / f"{stem}.json"
        _verify_hash(path, path.with_suffix(".sha256"))
    e3_path = results_directory / "e3_validation_summary.json"
    e3 = _load_json(e3_path)
    if e3.get("status") != "pass" or e3.get("e4_e6_may_continue") is not True:
        raise E6NoiseError("Formal E3 gate does not permit E6")

    e5_path = results_directory / "e5_validation_summary.json"
    e5_hash = _verify_hash(e5_path, e5_path.with_suffix(".sha256"))
    e5 = _load_json(e5_path)
    e5_gate = (
        e5.get("status") == "pass"
        and e5.get("e6_may_continue") is True
        and int(e5.get("instance_level_row_count", -1)) == 272
        and int(e5.get("winner_based_instance_selection_count", -1)) == 0
        and int(e5.get("unexpected_failure_count", -1)) == 0
    )
    if not e5_gate:
        raise E6NoiseError("Formal E5 gate does not permit E6")
    for relative, expected in e5.get("artifact_hashes", {}).items():
        artifact = results_directory.parent / str(relative)
        if _sha256(artifact) != expected:
            raise E6NoiseError(f"E5 artifact changed after formal completion: {artifact}")

    return {
        **frozen,
        "protocol": protocol,
        "protocol_hash": protocol_hash,
        "noise_manifest_hash": noise_hash,
        "noise_rows": sorted(noise_rows, key=lambda row: row["instance_id"]),
        "noise_levels": declared_levels,
        "e3_validation_summary_hash": _sha256(e3_path),
        "e5_validation_summary_hash": e5_hash,
    }


def representative_transpiler_seed(
    seeds: Sequence[int], gate_counts: Sequence[int]
) -> int:
    """Choose a deterministic structurally median seed before noise outcomes."""

    if len(seeds) != len(gate_counts) or not seeds:
        raise ValueError("Transpiler seeds and gate counts must be non-empty and aligned")
    median = int(statistics.median(gate_counts))
    candidates = [seed for seed, count in zip(seeds, gate_counts) if count == median]
    if not candidates:
        raise E6NoiseError("Median compiled cost was not attained by a frozen seed")
    return min(candidates)


def _selected_budget_spec(plan: Mapping[str, object], protocol: Mapping[str, object], qaoa: Mapping[str, object]) -> QAOABudgetSpec:
    desired = f"equal_2q_budget_{int(protocol['compiled_2q_budget'])}"
    specs = budget_specs(int(plan["compiled_2q_gates_per_layer"]), qaoa)
    matches = [spec for spec in specs if spec.key == desired]
    if len(matches) != 1 or matches[0].p <= 0:
        raise E6NoiseError(f"E6 frozen budget is infeasible: {plan['instance_id']} / {plan['design_id']}")
    return matches[0]


def feasible_full_circuit_spec(
    evaluation,
    *,
    initial_spec: QAOABudgetSpec,
    compiler_config: Mapping[str, object],
    transpiler_seed: int,
) -> tuple[QAOABudgetSpec, int]:
    """Reduce p until the complete compiled circuit obeys the frozen budget."""

    budget = int(initial_spec.compiled_budget or 0)
    for depth in range(initial_spec.p, 0, -1):
        probe = _build_compiled_qaoa_circuit(
            evaluation,
            gammas=[0.2718281828459045] * depth,
            betas=[0.3141592653589793] * depth,
            compiler_config=compiler_config,
            transpiler_seed=transpiler_seed,
        )
        actual = sum(1 for item in probe.data if len(item.qubits) == 2)
        if actual <= budget:
            return (
                QAOABudgetSpec(
                    initial_spec.mode,
                    initial_spec.key,
                    depth,
                    initial_spec.compiled_budget,
                    initial_spec.compiled_two_qubit_gates_per_layer,
                    actual,
                ),
                actual,
            )
    raise E6NoiseError("No positive E6 depth fits the frozen compiled budget")


def _build_compiled_qaoa_circuit(
    evaluation,
    *,
    gammas: Sequence[float],
    betas: Sequence[float],
    compiler_config: Mapping[str, object],
    transpiler_seed: int,
):
    try:
        from qiskit import QuantumCircuit, transpile
        from qiskit.transpiler import CouplingMap
    except ImportError as error:
        raise E6NoiseError("Formal E6 requires the frozen Qiskit stack") from error

    if len(gammas) != len(betas) or not gammas:
        raise ValueError("E6 QAOA parameters require equal positive gamma/beta lengths")
    n_qubits = evaluation.representation.n_qubits
    circuit = QuantumCircuit(n_qubits, n_qubits)
    circuit.h(range(n_qubits))
    pauli = evaluation.reference.pauli
    for gamma, beta in zip(gammas, betas):
        for support, coefficient in sorted(pauli.items(), key=lambda item: (len(item[0]), item[0])):
            angle = 2.0 * float(gamma) * float(coefficient)
            if not support:
                circuit.global_phase -= float(gamma) * float(coefficient)
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
        for qubit in range(n_qubits):
            circuit.rx(2.0 * float(beta), qubit)
    circuit.measure(range(n_qubits), range(n_qubits))

    sparse = next(
        item
        for item in compiler_config["architectures"]  # type: ignore[index]
        if item["id"] == "device_sparse_v1"
    )
    coupling = [tuple(edge) for edge in sparse["coupling_map"]]
    return transpile(
        circuit,
        basis_gates=list(compiler_config["basis_gates"]),
        coupling_map=CouplingMap(coupling),
        optimization_level=int(compiler_config["optimization_level"]),
        layout_method=str(compiler_config["layout_method"]),
        routing_method=str(compiler_config["routing_method"]),
        translation_method=str(compiler_config["translation_method"]),
        seed_transpiler=int(transpiler_seed),
    )


def build_noise_model(
    level: Mapping[str, object],
    *,
    measured_qubit_count: int,
    protocol: Mapping[str, object],
):
    """Build the frozen local depolarizing plus symmetric readout model."""

    if level["id"] == "noiseless":
        return None
    try:
        from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error
    except ImportError as error:
        raise E6NoiseError("Formal E6 requires qiskit-aer==0.17.2") from error
    parameters = level["parameters"]
    p1 = float(parameters["one_qubit_depolarizing_probability"])
    p2 = float(parameters["two_qubit_depolarizing_probability"])
    readout = float(parameters["symmetric_readout_probability"])
    if not (0.0 < p1 < 1.0 and 0.0 < p2 < 1.0 and 0.0 < readout < 0.5):
        raise E6NoiseError(f"Out-of-scope E6 noise probability: {level['id']}")
    model = NoiseModel()
    model.add_all_qubit_quantum_error(
        depolarizing_error(p1, 1), list(protocol["one_qubit_error_gates"])
    )
    model.add_all_qubit_quantum_error(
        depolarizing_error(p2, 2), list(protocol["two_qubit_error_gates"])
    )
    readout_error = ReadoutError([[1.0 - readout, readout], [readout, 1.0 - readout]])
    for qubit in range(measured_qubit_count):
        model.add_readout_error(readout_error, [qubit])
    return model


def metrics_from_counts(
    counts: Mapping[str, int],
    *,
    original: Mapping[Support, object],
    representation,
    optimum_original: float,
) -> dict[str, float]:
    """Score measured logical bits after projecting away every auxiliary bit."""

    shots = sum(int(value) for value in counts.values())
    if shots <= 0:
        raise E6NoiseError("No E6 measurement shots were returned")
    original_total = 0.0
    encoded_total = 0.0
    optimum_hits = 0
    inconsistent = 0
    best = math.inf
    n_qubits = representation.n_qubits
    n_original = representation.original_width
    for label, raw_count in counts.items():
        clean = str(label).replace(" ", "")
        if len(clean) < n_qubits:
            clean = clean.zfill(n_qubits)
        bits = tuple(int(bit) for bit in clean[::-1][:n_qubits])
        original_bits = bits[:n_original]
        count = int(raw_count)
        original_value = float(evaluate_pubo(original, original_bits))
        encoded_value = float(evaluate_pubo(representation.polynomial, bits))
        original_total += count * original_value
        encoded_total += count * encoded_value
        best = min(best, original_value)
        if abs(original_value - optimum_original) <= 1e-10:
            optimum_hits += count
        if any(
            bits[index - 1] != bits[pair[0] - 1] * bits[pair[1] - 1]
            for pair, index in representation.auxiliary_indices.items()
        ):
            inconsistent += count
    return {
        "original_objective_mean": original_total / shots,
        "original_objective_best": best,
        "optimum_hit_rate": optimum_hits / shots,
        "encoded_energy_mean": encoded_total / shots,
        "auxiliary_inconsistency_rate": inconsistent / shots,
    }


def simulate_noise_row(
    *,
    compiled_circuit,
    original: Mapping[Support, object],
    representation,
    optimum_original: float,
    level: Mapping[str, object],
    protocol: Mapping[str, object],
    measurement_seed: int,
) -> tuple[dict[str, float], float]:
    try:
        from qiskit_aer import AerSimulator
    except ImportError as error:
        raise E6NoiseError("Formal E6 requires qiskit-aer==0.17.2") from error
    model = build_noise_model(
        level,
        measured_qubit_count=compiled_circuit.num_qubits,
        protocol=protocol,
    )
    backend = AerSimulator(method="automatic", noise_model=model)
    started = time.perf_counter()
    result = backend.run(
        compiled_circuit,
        shots=int(protocol["shots"]),
        seed_simulator=int(measurement_seed),
    ).result()
    runtime = time.perf_counter() - started
    counts = result.get_counts(compiled_circuit)
    return (
        metrics_from_counts(
            counts,
            original=original,
            representation=representation,
            optimum_original=optimum_original,
        ),
        runtime,
    )


def attach_paired_degradation(rows: Sequence[dict[str, object]]) -> None:
    groups: dict[tuple[object, ...], dict[str, dict[str, object]]] = defaultdict(dict)
    fields = (
        "instance_id",
        "representation",
        "random_rep_seed",
        "design_id",
        "restart_id",
        "optimized_parameters_sha256",
        "transpiler_seed",
        "circuit_seed",
        "measurement_seed",
    )
    for row in rows:
        groups[tuple(row[field] for field in fields)][str(row["noise_level"])] = row
    for key, levels in groups.items():
        if set(levels) != set(NOISE_LEVEL_ORDER):
            raise E6NoiseError(f"Incomplete paired E6 noise levels: {key}")
        baseline = float(levels["noiseless"]["original_objective_mean"])
        for level, row in levels.items():
            degradation = float(row["original_objective_mean"]) - baseline
            row["paired_degradation_vs_noiseless"] = degradation
            if level == "noiseless" and abs(degradation) > 1e-12:
                raise E6NoiseError("Noiseless E6 paired degradation is not zero")


def fairness_audit(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_design_count: int,
    protocol: Mapping[str, object],
) -> dict[str, int]:
    groups: dict[tuple[object, ...], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        key = (
            row["instance_id"],
            row["representation"],
            row["random_rep_seed"],
            row["design_id"],
            row["restart_id"],
        )
        groups[key].append(row)
    missing_level = 0
    protocol_mismatch = 0
    parameter_mismatch = 0
    budget_exceed = 0
    non_original_score = 0
    for group in groups.values():
        if {str(row["noise_level"]) for row in group} != set(NOISE_LEVEL_ORDER):
            missing_level += 1
        comparable = (
            "shots",
            "topology_id",
            "transpiler_seed",
            "circuit_seed",
            "measurement_seed",
        )
        if any(len({row[field] for row in group}) != 1 for field in comparable):
            protocol_mismatch += 1
        if len({row["optimized_parameters_sha256"] for row in group}) != 1:
            parameter_mismatch += 1
        if any(int(row["actual_2q_gates"]) > int(protocol["compiled_2q_budget"]) for row in group):
            budget_exceed += 1
        if any(row["objective_scoring"] != "original_family_objective_after_discarding_auxiliaries" for row in group):
            non_original_score += 1
    expected_groups = expected_design_count * 3
    return {
        "paired_group_count_mismatch": int(len(groups) != expected_groups),
        "missing_noise_level_group_count": missing_level,
        "cross_level_protocol_mismatch_count": protocol_mismatch,
        "cross_level_parameter_mismatch_count": parameter_mismatch,
        "compiled_budget_exceed_count": budget_exceed,
        "non_original_primary_score_count": non_original_score,
    }


def summarise_noise_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if row["status"] == "pass":
            groups[(str(row["family"]), str(row["representation"]), str(row["noise_level"]))].append(row)
    summary: list[dict[str, object]] = []
    for key in sorted(
        groups,
        key=lambda item: (
            item[0],
            REPRESENTATION_ORDER.index(item[1]),
            NOISE_LEVEL_ORDER.index(item[2]),
        ),
    ):
        group = groups[key]
        objective = _uncertainty([float(row["original_objective_mean"]) for row in group])
        degradation = _uncertainty([float(row["paired_degradation_vs_noiseless"]) for row in group])
        hit = _uncertainty([float(row["optimum_hit_rate"]) for row in group])
        inconsistency = _uncertainty([float(row["auxiliary_inconsistency_rate"]) for row in group])
        summary.append(
            {
                "family": key[0],
                "representation": key[1],
                "noise_level": key[2],
                "instance_count": len({str(row["instance_id"]) for row in group}),
                "design_count": len({(str(row["instance_id"]), str(row["design_id"])) for row in group}),
                "run_count": len(group),
                "original_objective_mean": objective[0],
                "original_objective_ci95_low": objective[1],
                "original_objective_ci95_high": objective[2],
                "paired_degradation_vs_noiseless_mean": degradation[0],
                "paired_degradation_vs_noiseless_ci95_low": degradation[1],
                "paired_degradation_vs_noiseless_ci95_high": degradation[2],
                "optimum_hit_rate_mean": hit[0],
                "optimum_hit_rate_ci95_low": hit[1],
                "optimum_hit_rate_ci95_high": hit[2],
                "auxiliary_inconsistency_rate_mean": inconsistency[0],
                "auxiliary_inconsistency_rate_ci95_low": inconsistency[1],
                "auxiliary_inconsistency_rate_ci95_high": inconsistency[2],
                "status": "pass",
                "config_hash": group[0]["config_hash"],
                "noise_manifest_hash": group[0]["noise_manifest_hash"],
                "protocol_config_hash": group[0]["protocol_config_hash"],
                "code_commit": group[0]["code_commit"],
            }
        )
    return summary


def _latex_table(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated formal E6 summary; do not edit by hand.",
        "\\begin{tabular}{lllrrrr}",
        "\\toprule",
        "Family & Representation & Noise & $n$ & Runs & $\\Delta$ objective & Aux. inconsistency \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{str(row['family']).replace('_', ' ')} & "
            f"{str(row['representation']).replace('_', ' ')} & "
            f"{str(row['noise_level']).replace('_', ' ')} & "
            f"{row['instance_count']} & {row['run_count']} & "
            f"{float(row['paired_degradation_vs_noiseless_mean']):.4f} & "
            f"{float(row['auxiliary_inconsistency_rate_mean']):.4f} \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            "% Frozen E6: 18 instances, 4096 shots, device_sparse_v1, paired 95% normal intervals.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_noise_figure_pdf(path: Path, rows: Sequence[Mapping[str, object]]) -> str:
    try:
        import reportlab
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.shapes import Drawing, String
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E6NoiseError("Formal E6 figure requires reportlab") from error

    page = landscape(letter)
    pdf = canvas.Canvas(str(path), pagesize=page)
    pdf.setTitle("Formal E6 limited-noise study")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(36, page[1] - 32, "Formal E6: paired degradation under frozen limited noise")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(36, page[1] - 47, "Positive degradation is worse; primary score discards auxiliary bits before original-objective scoring.")
    legend = (
        ("noiseless", colors.HexColor("#2a9d8f")),
        ("realistic low", colors.HexColor("#6c63b5")),
        ("realistic high", colors.HexColor("#d95f02")),
    )
    legend_x = 500
    for label, colour in legend:
        pdf.setFillColor(colour)
        pdf.rect(legend_x, page[1] - 51, 7, 7, fill=1, stroke=0)
        pdf.setFillColor(colors.black)
        pdf.drawString(legend_x + 10, page[1] - 50, label)
        legend_x += 86

    lookup = {
        (str(row["family"]), str(row["representation"]), str(row["noise_level"])): row
        for row in rows
    }
    panels = (
        ("max3sat", "Max-3SAT: objective degradation", "paired_degradation_vs_noiseless_mean"),
        ("cubic_spin_glass", "Spin glass: objective degradation", "paired_degradation_vs_noiseless_mean"),
        ("max3sat", "Max-3SAT: auxiliary inconsistency", "auxiliary_inconsistency_rate_mean"),
        ("cubic_spin_glass", "Spin glass: auxiliary inconsistency", "auxiliary_inconsistency_rate_mean"),
    )
    positions = ((36, 300), (405, 300), (36, 55), (405, 55))
    palette = [colors.HexColor("#2a9d8f"), colors.HexColor("#6c63b5"), colors.HexColor("#d95f02")]
    for (family, title, metric), (x, y) in zip(panels, positions):
        drawing = Drawing(350, 220)
        drawing.add(String(8, 202, title, fontName="Helvetica-Bold", fontSize=9))
        chart = VerticalBarChart()
        chart.x = 42
        chart.y = 43
        chart.width = 294
        chart.height = 140
        chart.data = [
            [float(lookup[(family, rep, level)][metric]) for rep in REPRESENTATION_ORDER]
            for level in NOISE_LEVEL_ORDER
        ]
        chart.categoryAxis.categoryNames = ["native", "full", "selected", "matched"]
        chart.categoryAxis.labels.fontSize = 6
        chart.valueAxis.valueMin = min(0.0, min(min(series) for series in chart.data))
        maximum = max(max(series) for series in chart.data)
        chart.valueAxis.valueMax = max(0.01, maximum * 1.15)
        chart.valueAxis.labels.fontSize = 6
        chart.barSpacing = 1
        chart.groupSpacing = 5
        for index, colour in enumerate(palette):
            chart.bars[index].fillColor = colour
        drawing.add(chart)
        drawing.wrapOn(pdf, 350, 220)
        drawing.drawOn(pdf, x, y)
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(page[0] - 36, 20, "Frozen E6 v1: noiseless + realistic_low + realistic_high; diagnostic auxiliary inconsistency shown separately")
    pdf.save()
    return reportlab.Version


def run_e6_noise_pipeline(
    *,
    config_path: Path | str,
    config_hash_path: Path | str,
    protocol_config_path: Path | str,
    protocol_config_hash_path: Path | str,
    data_directory: Path | str,
    results_directory: Path | str,
    tables_directory: Path | str,
    figures_directory: Path | str,
    code_commit: str,
    assumptions_path: Path | str | None = None,
    run_commands_path: Path | str | None = None,
    progress=None,
) -> dict[str, object]:
    project_root = Path(results_directory).resolve().parent
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    figures_directory = Path(figures_directory)
    targets = (
        Path("results/e6_noise_runs.csv"),
        Path("results/e6_noise_summary.csv"),
        Path("results/e6_noise_provenance.json"),
        Path("results/e6_validation_summary.json"),
        Path("tables/table_e6_noise.tex"),
        Path("figures/figure_e6_noise.pdf"),
    )
    if any((project_root / target).exists() for target in targets):
        raise FileExistsError("Formal E6 output already exists; refusing overwrite")
    staging = project_root / "e6_step8_building"
    if staging.exists():
        raise E6NoiseError(f"Incomplete E6 staging directory exists: {staging}")

    frozen = verify_e6_inputs(
        config_path=Path(config_path),
        config_hash_path=Path(config_hash_path),
        protocol_config_path=Path(protocol_config_path),
        protocol_config_hash_path=Path(protocol_config_hash_path),
        data_directory=data_directory,
        results_directory=results_directory,
    )
    config = frozen["config"]  # type: ignore[assignment]
    protocol = frozen["protocol"]  # type: ignore[assignment]
    qaoa = config["qaoa"]
    compiler = config["compiler"]
    seeds = [int(value) for value in compiler["transpiler_seed_bundle"]]
    ground_truth = frozen["ground_truth_rows"]
    noise_levels = frozen["noise_levels"]
    config_hash = str(frozen["config_hash"])
    manifest_hash = str(frozen["noise_manifest_hash"])
    protocol_hash = str(frozen["protocol_hash"])
    staging.mkdir(parents=True)
    run_rows: list[dict[str, object]] = []
    design_count = 0
    optimizer_run_count = 0
    full_circuit_depth_reduction_count = 0

    for ordinal, row in enumerate(frozen["noise_rows"], start=1):
        canonical_path = data_directory / row["canonical_file"]
        if _sha256(canonical_path) != row["canonical_sha256"]:
            raise E6NoiseError(f"Canonical coefficient hash mismatch: {row['instance_id']}")
        family, polynomial = _canonical_polynomial(canonical_path)
        if family != row["family"]:
            raise E6NoiseError(f"Noise-subset family mismatch: {row['instance_id']}")
        optimum = float(ground_truth[row["instance_id"]]["optimum_original"])
        designs = qaoa_designs(
            polynomial,
            n_original=int(row["n"]),
            instance_id=row["instance_id"],
            config=config,
        )
        design_count += len(designs)
        for design in designs:
            plan = compile_budget_plan(
                instance_id=row["instance_id"],
                family=family,
                design=design,
                config=config,
                config_hash=config_hash,
                manifest_hash=manifest_hash,
                code_commit=code_commit,
            )
            gate_counts = json.loads(str(plan["compiled_2q_gates_by_seed_json"]))
            transpiler_seed = representative_transpiler_seed(seeds, gate_counts)
            initial_spec = _selected_budget_spec(plan, protocol, qaoa)
            spec, _ = feasible_full_circuit_spec(
                design.evaluation,
                initial_spec=initial_spec,
                compiler_config=compiler,
                transpiler_seed=transpiler_seed,
            )
            if spec.p < initial_spec.p:
                full_circuit_depth_reduction_count += 1
            state_data = statevector_data(
                polynomial,
                design.evaluation.representation,
                optimum_original=optimum,
            )
            for restart_id in range(int(qaoa["optimizer"]["restarts"])):
                optimized = optimize_qaoa_run(
                    instance_id=row["instance_id"],
                    family=family,
                    design=design,
                    spec=spec,
                    data=state_data,
                    restart_id=restart_id,
                    optimizer_seed=int(qaoa["optimizer"]["seed_bundle"][restart_id]),
                    circuit_seed=int(qaoa["circuit_seed_bundle"][restart_id]),
                    measurement_seed=int(qaoa["measurement_seed_bundle"][restart_id]),
                    qaoa_config=qaoa,
                    config_hash=config_hash,
                    manifest_hash=manifest_hash,
                    e2_summary_hash=str(frozen["e2_summary_hash"]),
                    code_commit=code_commit,
                )
                optimizer_run_count += 1
                if optimized["status"] != "pass":
                    raise E6NoiseError(
                        f"E6 noiseless parameter optimization failed: {row['instance_id']} / {design.design_id} / {restart_id}"
                    )
                parameters = json.loads(str(optimized["optimized_parameters_json"]))
                parameter_hash = _parameter_hash(parameters)
                circuit = _build_compiled_qaoa_circuit(
                    design.evaluation,
                    gammas=parameters[: spec.p],
                    betas=parameters[spec.p :],
                    compiler_config=compiler,
                    transpiler_seed=transpiler_seed,
                )
                actual_two_qubit = sum(1 for item in circuit.data if len(item.qubits) == 2)
                if actual_two_qubit > int(protocol["compiled_2q_budget"]):
                    raise E6NoiseError(
                        f"E6 compiled budget exceeded: {row['instance_id']} / {design.design_id} / {actual_two_qubit}"
                    )
                for level in noise_levels:
                    parameters_level = level["parameters"]
                    try:
                        metrics, runtime = simulate_noise_row(
                            compiled_circuit=circuit,
                            original=polynomial,
                            representation=design.evaluation.representation,
                            optimum_original=optimum,
                            level=level,
                            protocol=protocol,
                            measurement_seed=int(qaoa["measurement_seed_bundle"][restart_id]),
                        )
                        status = "pass"
                        failure_kind = ""
                        failure_message = ""
                    except Exception as error:
                        metrics = {
                            "original_objective_mean": "",
                            "original_objective_best": "",
                            "optimum_hit_rate": "",
                            "encoded_energy_mean": "",
                            "auxiliary_inconsistency_rate": "",
                        }
                        runtime = 0.0
                        status = "simulation_failure"
                        failure_kind = error.__class__.__name__
                        failure_message = str(error)[:500]
                    run_rows.append(
                        {
                            "instance_id": row["instance_id"],
                            "family": family,
                            "split": row["split"],
                            "representation": design.representation,
                            "random_rep_seed": design.random_rep_seed or "",
                            "design_id": design.design_id,
                            "budget_mode": spec.mode,
                            "budget_key": spec.key,
                            "p": spec.p,
                            "compiled_2q_budget": spec.compiled_budget,
                            "compiled_2q_gates_per_layer": spec.compiled_two_qubit_gates_per_layer,
                            "actual_2q_gates": actual_two_qubit,
                            "topology_id": protocol["topology_id"],
                            "transpiler_seed": transpiler_seed,
                            "optimizer": "COBYLA",
                            "optimizer_seed": qaoa["optimizer"]["seed_bundle"][restart_id],
                            "restart_id": restart_id,
                            "optimizer_evaluations": optimized["evaluations"],
                            "optimized_parameters_sha256": parameter_hash,
                            "optimized_parameters_json": json.dumps(parameters, separators=(",", ":")),
                            "shots": protocol["shots"],
                            "circuit_seed": qaoa["circuit_seed_bundle"][restart_id],
                            "measurement_seed": qaoa["measurement_seed_bundle"][restart_id],
                            "noise_model_id": config["noise"]["model_id"],
                            "noise_level": level["id"],
                            "one_qubit_depolarizing_probability": parameters_level.get("one_qubit_depolarizing_probability", 0.0),
                            "two_qubit_depolarizing_probability": parameters_level.get("two_qubit_depolarizing_probability", 0.0),
                            "symmetric_readout_probability": parameters_level.get("symmetric_readout_probability", 0.0),
                            **metrics,
                            "paired_degradation_vs_noiseless": "",
                            "simulation_runtime_sec": runtime,
                            "objective_scoring": protocol["primary_score"],
                            "auxiliary_scoring_rule": "discard_for_primary_score_and_report_inconsistency_diagnostic",
                            "status": status,
                            "failure_kind": failure_kind,
                            "failure_message": failure_message,
                            "config_hash": config_hash,
                            "noise_manifest_hash": manifest_hash,
                            "protocol_config_hash": protocol_hash,
                            "e3_validation_summary_hash": frozen["e3_validation_summary_hash"],
                            "e5_validation_summary_hash": frozen["e5_validation_summary_hash"],
                            "code_commit": code_commit,
                        }
                    )
        if progress:
            progress(f"E6 noise: {ordinal}/{len(frozen['noise_rows'])} frozen subset instances completed")

    failure_count = sum(1 for row in run_rows if row["status"] != "pass")
    if failure_count:
        raise E6NoiseError(f"Formal E6 retained {failure_count} failed simulations")
    attach_paired_degradation(run_rows)
    expected_design_count = len(frozen["noise_rows"]) * 8
    expected_run_count = expected_design_count * 3 * len(NOISE_LEVEL_ORDER)
    audit = fairness_audit(
        run_rows,
        expected_design_count=expected_design_count,
        protocol=protocol,
    )
    summary_rows = summarise_noise_rows(run_rows)
    gates = (
        design_count == expected_design_count
        and optimizer_run_count == expected_design_count * 3
        and len(run_rows) == expected_run_count
        and len(summary_rows) == 24
        and failure_count == 0
        and all(value == 0 for value in audit.values())
    )

    runs_path = staging / "results/e6_noise_runs.csv"
    summary_path = staging / "results/e6_noise_summary.csv"
    provenance_path = staging / "results/e6_noise_provenance.json"
    validation_path = staging / "results/e6_validation_summary.json"
    table_path = staging / "tables/table_e6_noise.tex"
    figure_path = staging / "figures/figure_e6_noise.pdf"
    _write_csv(runs_path, run_rows, RUN_FIELDS)
    _write_csv(summary_path, summary_rows, SUMMARY_FIELDS)
    table_path.parent.mkdir(parents=True, exist_ok=True)
    table_path.write_text(_latex_table(summary_rows), encoding="utf-8", newline="\n")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    reportlab_version = write_noise_figure_pdf(figure_path, summary_rows)
    provenance = {
        "protocol_version": protocol["protocol_version"],
        "noise_model_id": config["noise"]["model_id"],
        "calibration_provenance": protocol["calibration_provenance"],
        "noise_levels": noise_levels,
        "one_qubit_error_gates": protocol["one_qubit_error_gates"],
        "two_qubit_error_gates": protocol["two_qubit_error_gates"],
        "readout_model": "independent_symmetric_bit_flip_per_measured_physical_qubit",
        "topology_id": protocol["topology_id"],
        "basis_gates": compiler["basis_gates"],
        "transpilation_protocol": {
            "layout_method": compiler["layout_method"],
            "routing_method": compiler["routing_method"],
            "translation_method": compiler["translation_method"],
            "optimization_level": compiler["optimization_level"],
            "representative_seed_rule": protocol["transpiler_seed_rule"],
            "frozen_seed_bundle": compiler["transpiler_seed_bundle"],
            "depth_rule": protocol["depth_rule"],
        },
        "shots": protocol["shots"],
        "circuit_seed_bundle": qaoa["circuit_seed_bundle"],
        "measurement_seed_bundle": qaoa["measurement_seed_bundle"],
        "parameter_policy": protocol["parameter_policy"],
        "primary_score": protocol["primary_score"],
        "real_device_used": False,
        "config_hash": config_hash,
        "noise_manifest_hash": manifest_hash,
        "protocol_config_hash": protocol_hash,
        "code_commit": code_commit,
    }
    _write_json(provenance_path, provenance)
    artifact_hashes = {
        str(path.relative_to(staging)): _write_hash(path)
        for path in (runs_path, summary_path, provenance_path, table_path, figure_path)
    }
    validation = {
        "status": "pass" if gates else "fail",
        "scope": "formal_step8_e6_limited_noise_study",
        "config_hash": config_hash,
        "noise_manifest_hash": manifest_hash,
        "protocol_config_hash": protocol_hash,
        "e3_validation_summary_hash": frozen["e3_validation_summary_hash"],
        "e5_validation_summary_hash": frozen["e5_validation_summary_hash"],
        "code_commit": code_commit,
        "reportlab_version": reportlab_version,
        "frozen_noise_subset_instance_count": len(frozen["noise_rows"]),
        "instances_per_family": 9,
        "representation_family_count": 4,
        "matched_random_seed_count": 5,
        "scheduled_design_count": design_count,
        "parameter_optimization_run_count": optimizer_run_count,
        "full_circuit_depth_reduction_count": full_circuit_depth_reduction_count,
        "run_row_count": len(run_rows),
        "summary_row_count": len(summary_rows),
        "noise_level_count": len(NOISE_LEVEL_ORDER),
        "nonzero_noise_level_count": 2,
        "shots_per_run": int(protocol["shots"]),
        "topology_id": protocol["topology_id"],
        "primary_score": "original_family_objective_after_discarding_auxiliaries",
        "auxiliary_inconsistency_reported": True,
        "real_device_used": False,
        "failed_run_count": failure_count,
        **audit,
        "artifact_hashes": artifact_hashes,
        "final_result_pack_may_be_built": gates,
    }
    _write_json(validation_path, validation)
    _write_hash(validation_path)
    if not gates:
        raise E6NoiseError(f"Formal E6 gate failed; staging retained at {staging}")
    for relative in targets:
        source = staging / relative
        target = project_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        shutil.move(str(source.with_suffix(".sha256")), str(target.with_suffix(".sha256")))
    shutil.rmtree(staging)

    if assumptions_path is not None:
        assumptions = Path(assumptions_path)
        section = f"""
## Formal Step 8 / E6 limited noise study (v1)

- Status: `pass`; the E1-E6 result set is complete and the final result pack may be built.
- Frozen structural noise subset: `18` instances (`9` per family), selected before noise outcomes and used without replacement.
- Noise scope: sampled noiseless baseline plus exactly `realistic_low` and `realistic_high`; no real device was used.
- Every design uses `device_sparse_v1`, the same compiler protocol, `4096` shots, and the same three circuit/measurement seed pairs. The deterministic representative transpiler seed is the smallest frozen seed attaining the median one-layer two-qubit cost.
- Parameters are optimized independently under the frozen noiseless E3 protocol for the single predeclared `256` compiled-two-qubit budget, then held fixed across all three paired noise levels. Depth is reduced structurally when necessary until the complete compiled measured circuit, not a per-layer estimate, obeys the budget.
- Primary score discards auxiliary bits before evaluating the original-family objective; encoded energy and auxiliary inconsistency remain diagnostics.
- Raw noise rows: `{len(run_rows)}`; summary rows: `{len(summary_rows)}`; failed runs: `0`.
- Config hash: `{config_hash}`; frozen noise manifest hash: `{manifest_hash}`; E6 protocol hash: `{protocol_hash}`.
"""
        assumptions.write_text(
            assumptions.read_text(encoding="utf-8").rstrip() + "\n" + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if run_commands_path is not None:
        commands = Path(run_commands_path)
        section = """
## Formal Step 8 / E6 command (v1)

```powershell
python .\\run_e6_noise.py `
  --config .\\configs\\experiment_config_v1.yaml `
  --config-hash .\\configs\\experiment_config_v1.sha256 `
  --protocol-config .\\configs\\e6_noise_v1.json `
  --protocol-config-hash .\\configs\\e6_noise_v1.sha256 `
  --data .\\data `
  --results .\\results `
  --tables .\\tables `
  --figures .\\figures `
  --assumptions .\\assumptions_and_decisions.md `
  --run-commands .\\RUN_COMMANDS.md
```

Required result: `E6 LIMITED-NOISE GATE: pass` and `final_result_pack_may_be_built=true`.
"""
        commands.write_text(
            commands.read_text(encoding="utf-8").rstrip() + "\n" + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if progress:
        progress("E6 LIMITED-NOISE GATE: pass")
    return validation
