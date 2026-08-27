"""Formal Step 5 / E3 fair-QAOA comparison pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import yaml

from .e1_exactness import MixedRepresentation
from .e2_resources import (
    DesignEvaluation,
    _design_id,
    _evaluate_design,
    _full_actions,
    _verify_hash,
    beam_select_design,
    compile_sparse_design,
    matched_random_designs,
)
from .polynomial import Polynomial, Support, canonicalize, cubic_supports, evaluate_pubo
from .e1_exactness import verify_data_freeze


class E3QAOAError(RuntimeError):
    """Formal E3 cannot proceed or failed a mandatory fairness gate."""


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
    "optimizer",
    "optimizer_seed",
    "restart_id",
    "evaluation_budget",
    "evaluations",
    "shots",
    "circuit_seed",
    "measurement_seed",
    "initial_parameters_sha256",
    "optimized_parameters_json",
    "original_objective_mean",
    "original_objective_best",
    "optimum_hit_rate",
    "encoded_energy_mean",
    "auxiliary_inconsistency_rate",
    "statevector_norm",
    "optimizer_runtime_sec",
    "optimizer_terminated_early",
    "optimizer_message",
    "initialization_seed",
    "objective_scoring",
    "encoded_energy_role",
    "status",
    "failure_kind",
    "failure_message",
    "config_hash",
    "manifest_hash",
    "e2_summary_hash",
    "code_commit",
)


BUDGET_PLAN_FIELDS = (
    "instance_id",
    "family",
    "representation",
    "random_rep_seed",
    "design_id",
    "n_original",
    "n_aux",
    "n_qubits",
    "topology_id",
    "transpiler_seed_count",
    "compiled_2q_gates_by_seed_json",
    "compiled_2q_gates_per_layer",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


SUMMARY_FIELDS = (
    "family",
    "representation",
    "budget_mode",
    "budget_value",
    "p_min",
    "p_max",
    "instance_count",
    "run_count",
    "original_objective_mean",
    "original_objective_ci95_low",
    "original_objective_ci95_high",
    "paired_difference_vs_native_mean",
    "paired_difference_vs_native_ci95_low",
    "paired_difference_vs_native_ci95_high",
    "optimum_hit_rate_mean",
    "optimum_hit_rate_ci95_low",
    "optimum_hit_rate_ci95_high",
    "encoded_energy_mean",
    "auxiliary_inconsistency_rate_mean",
    "status",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


@dataclass(frozen=True)
class QAOADesign:
    representation: str
    random_rep_seed: int | None
    evaluation: DesignEvaluation

    @property
    def design_id(self) -> str:
        return _design_id(self.evaluation.actions)


@dataclass(frozen=True)
class QAOABudgetSpec:
    mode: str
    key: str
    p: int
    compiled_budget: int | None
    compiled_two_qubit_gates_per_layer: int
    actual_two_qubit_gates: int


@dataclass(frozen=True)
class StatevectorData:
    encoded_energies: np.ndarray
    original_energies: np.ndarray
    inconsistent: np.ndarray
    optimum_mask: np.ndarray


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E3QAOAError(f"Expected JSON object: {path}")
    return payload


def _canonical_polynomial(path: Path) -> tuple[str, Polynomial]:
    record = _load_json(path)
    terms = record.get("terms")
    if not isinstance(terms, list):
        raise E3QAOAError(f"Malformed canonical record: {path}")
    polynomial = canonicalize(
        (tuple(item["support"]), item["coefficient"])  # type: ignore[index]
        for item in terms
    )
    return str(record["family"]), polynomial


def _stable_seed(*parts: object) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _hash_parameters(values: Sequence[float]) -> str:
    payload = json.dumps(
        [float(value) for value in values], separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _uncertainty(values: Sequence[float]) -> tuple[float, float, float]:
    if not values:
        return math.nan, math.nan, math.nan
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half, mean + half


def verify_e3_inputs(
    *,
    config_path: Path,
    config_hash_path: Path,
    data_directory: Path,
    results_directory: Path,
) -> dict[str, object]:
    """Recheck the frozen data and formal E2 continuation gate."""

    freeze = verify_data_freeze(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["status"] != "frozen" or config["freeze_gate"]["blocked"]:
        raise E3QAOAError("E3 requires the formal frozen configuration")

    e2_artifacts = (
        results_directory / "e2_logical_resources.csv",
        results_directory / "e2_compiled_resources_by_seed.csv",
        results_directory / "e2_compiled_resources_summary.csv",
        results_directory / "selector_validation.csv",
        results_directory / "e2_designs.json",
        results_directory / "e2_validation_summary.json",
        results_directory.parent / "tables/table_e2_resources.tex",
        results_directory.parent / "figures/figure_e2_resources.pdf",
    )
    for artifact in e2_artifacts:
        _verify_hash(artifact, artifact.with_suffix(".sha256"))
    e2_summary_path = results_directory / "e2_validation_summary.json"
    e2_summary = _load_json(e2_summary_path)
    required_counts = {
        "compilation_instance_count": 180,
        "logical_row_count": 1440,
        "compiled_raw_row_count": 14400,
        "compiled_summary_row_count": 1440,
        "selector_validation_row_count": 180,
    }
    e2_gate = (
        e2_summary.get("status") == "pass"
        and e2_summary.get("e3_e6_may_continue") is True
        and all(int(e2_summary.get(key, -1)) == value for key, value in required_counts.items())
        and int(e2_summary.get("unexpected_compiler_failure_count", -1)) == 0
        and int(e2_summary.get("instance_alignment_failure_count", -1)) == 0
        and int(e2_summary.get("topology_bundle_failure_count", -1)) == 0
        and int(e2_summary.get("seed_bundle_failure_count", -1)) == 0
        and int(e2_summary.get("compiler_protocol_failure_count", -1)) == 0
        and int(e2_summary.get("selector_test_retuning_count", -1)) == 0
    )
    if not e2_gate:
        raise E3QAOAError("Formal E2 gate does not permit E3")

    qaoa_path = data_directory / "manifests/qaoa_v1.csv"
    qaoa_hash = _verify_hash(
        qaoa_path, data_directory / "manifests/qaoa_v1.sha256"
    )
    qaoa_rows = _read_csv(qaoa_path)
    test_rows = [row for row in qaoa_rows if row["split"] == "test"]
    family_counts: dict[str, int] = {}
    for row in test_rows:
        family_counts[row["family"]] = family_counts.get(row["family"], 0) + 1
        if row["all_four_within_qmax"] != "True":
            raise E3QAOAError(
                f"Qmax gate is not true for {row['instance_id']}"
            )
        qmax = int(row["qmax"])
        widths = (
            int(row["all_native_width"]),
            int(row["fully_quadratized_width"]),
            int(row["selective_width_upper_bound"]),
            int(row["matched_random_width_upper_bound"]),
        )
        if max(widths) > qmax:
            raise E3QAOAError(f"Qmax width mismatch: {row['instance_id']}")
    if family_counts != {"cubic_spin_glass": 7, "max3sat": 7}:
        raise E3QAOAError(f"Wrong frozen QAOA test counts: {family_counts}")

    ground_path = data_directory / "ground_truth/ground_truth_v1.csv"
    ground_hash = _verify_hash(
        ground_path, data_directory / "ground_truth/ground_truth_v1.sha256"
    )
    ground_rows = {
        row["instance_id"]: row for row in _read_csv(ground_path)
    }
    for row in test_rows:
        truth = ground_rows.get(row["instance_id"])
        if not truth or truth["status"] != "optimal" or truth["exact_truth"] != "True":
            raise E3QAOAError(
                f"QAOA test instance lacks exact original truth: {row['instance_id']}"
            )

    qaoa = config["qaoa"]
    if qaoa["budget_modes"] != ["equal_layer", "equal_compiled_two_qubit_gates"]:
        raise E3QAOAError("Frozen E3 budget modes changed")
    if qaoa["equal_layer_depths"] != [1, 2]:
        raise E3QAOAError("Frozen equal-layer depths changed")
    if qaoa["compiled_two_qubit_gate_budgets"] != [128, 256]:
        raise E3QAOAError("Frozen compiled 2Q budgets changed")
    optimizer = qaoa["optimizer"]
    if (
        optimizer["name"] != "COBYLA"
        or int(optimizer["objective_evaluations"]) != 60
        or int(optimizer["restarts"]) != 3
        or len(set(optimizer["seed_bundle"])) != 3
        or len(set(qaoa["circuit_seed_bundle"])) != 3
        or len(set(qaoa["measurement_seed_bundle"])) != 3
        or qaoa["retain_all_restarts"] is not True
        or qaoa["optimize_each_representation_independently"] is not True
    ):
        raise E3QAOAError("Frozen QAOA fairness settings changed")
    if config["scoring"]["primary_score"] != "original_family_objective":
        raise E3QAOAError("Primary E3 score is not the original objective")

    return {
        **freeze,
        "config": config,
        "qaoa_manifest_hash": qaoa_hash,
        "qaoa_test_rows": sorted(test_rows, key=lambda row: row["instance_id"]),
        "ground_truth_hash": ground_hash,
        "ground_truth_rows": ground_rows,
        "e2_summary": e2_summary,
        "e2_summary_hash": _sha256(e2_summary_path),
    }


def qaoa_designs(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    instance_id: str,
    config: Mapping[str, object],
) -> list[QAOADesign]:
    """Construct the frozen four representation families for one instance."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    selector = config["selector"]  # type: ignore[assignment]
    native = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=(None,) * len(cubics),
        selector=selector,
        apply_qaoa_hard_limits=True,
    )
    full = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=_full_actions(canonical),
        selector=selector,
        apply_qaoa_hard_limits=True,
    )
    selected_search = beam_select_design(
        canonical,
        n_original=n_original,
        selector=selector,
        apply_qaoa_hard_limits=True,
    )
    designs = [
        QAOADesign("all_native", None, native),
        QAOADesign("fully_quadratized", None, full),
        QAOADesign("selective", None, selected_search.evaluation),
    ]
    seeds = [
        int(seed)
        for seed in config["representations"]["matched_random"]["seed_bundle"]  # type: ignore[index]
    ]
    for seed, actions in matched_random_designs(
        canonical,
        selected_actions=selected_search.actions,
        instance_id=instance_id,
        seed_bundle=seeds,
    ):
        designs.append(
            QAOADesign(
                "matched_random_selective",
                seed,
                _evaluate_design(
                    canonical,
                    n_original=n_original,
                    actions=actions,
                    selector=selector,
                    apply_qaoa_hard_limits=True,
                ),
            )
        )
    if len(designs) != 8 or any(not design.evaluation.feasible for design in designs):
        raise E3QAOAError(f"QAOA representation feasibility failed: {instance_id}")
    return designs


def compile_budget_plan(
    *,
    instance_id: str,
    family: str,
    design: QAOADesign,
    config: Mapping[str, object],
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
) -> dict[str, object]:
    """Compile one QAOA cost layer under every frozen sparse seed."""

    compiler = config["compiler"]  # type: ignore[assignment]
    seeds = [int(seed) for seed in compiler["transpiler_seed_bundle"]]  # type: ignore[index]
    gates: list[int] = []
    for seed in seeds:
        result = compile_sparse_design(
            design.evaluation,
            compiler_config=compiler,
            transpiler_seed=seed,
        )
        if result["status"] != "pass":
            raise E3QAOAError(
                f"Sparse E3 layer compilation failed: {instance_id} / "
                f"{design.representation} / {seed} / {result['status']}"
            )
        gates.append(int(result["two_qubit_gates"]))
    per_layer = int(statistics.median(gates))
    if per_layer <= 0:
        raise E3QAOAError("Compiled per-layer 2Q cost must be positive")
    representation = design.evaluation.representation
    return {
        "instance_id": instance_id,
        "family": family,
        "representation": design.representation,
        "random_rep_seed": design.random_rep_seed or "",
        "design_id": design.design_id,
        "n_original": representation.original_width,
        "n_aux": representation.n_auxiliary,
        "n_qubits": representation.n_qubits,
        "topology_id": "device_sparse_v1",
        "transpiler_seed_count": len(seeds),
        "compiled_2q_gates_by_seed_json": json.dumps(gates, separators=(",", ":")),
        "compiled_2q_gates_per_layer": per_layer,
        "config_hash": config_hash,
        "manifest_hash": manifest_hash,
        "code_commit": code_commit,
    }


def budget_specs(
    per_layer_gates: int,
    qaoa_config: Mapping[str, object],
) -> list[QAOABudgetSpec]:
    if per_layer_gates <= 0:
        raise ValueError("Per-layer 2Q gates must be positive")
    specs: list[QAOABudgetSpec] = []
    for p in qaoa_config["equal_layer_depths"]:  # type: ignore[index]
        depth = int(p)
        specs.append(
            QAOABudgetSpec(
                "equal_layer",
                f"equal_layer_p{depth}",
                depth,
                None,
                per_layer_gates,
                depth * per_layer_gates,
            )
        )
    for value in qaoa_config["compiled_two_qubit_gate_budgets"]:  # type: ignore[index]
        budget = int(value)
        depth = budget // per_layer_gates
        actual = depth * per_layer_gates
        if actual > budget:
            raise E3QAOAError("Compiled 2Q budget was exceeded")
        specs.append(
            QAOABudgetSpec(
                "equal_compiled_two_qubit_gates",
                f"equal_2q_budget_{budget}",
                depth,
                budget,
                per_layer_gates,
                actual,
            )
        )
    return specs


def statevector_data(
    original: Mapping[Support, object],
    representation: MixedRepresentation,
    *,
    optimum_original: float,
) -> StatevectorData:
    """Precompute diagonal objectives and consistency masks exactly."""

    n_original = representation.original_width
    original_values = np.asarray(
        [
            float(
                evaluate_pubo(
                    original,
                    tuple((index >> bit) & 1 for bit in range(n_original)),
                )
            )
            for index in range(1 << n_original)
        ],
        dtype=np.float64,
    )
    size = 1 << representation.n_qubits
    encoded = np.empty(size, dtype=np.float64)
    projected = np.empty(size, dtype=np.float64)
    inconsistent = np.zeros(size, dtype=np.float64)
    original_mask = (1 << n_original) - 1
    auxiliary_indices = representation.auxiliary_indices
    for index in range(size):
        bits = tuple(
            (index >> bit) & 1 for bit in range(representation.n_qubits)
        )
        encoded[index] = float(evaluate_pubo(representation.polynomial, bits))
        projected[index] = original_values[index & original_mask]
        for pair, variable in auxiliary_indices.items():
            expected = bits[pair[0] - 1] * bits[pair[1] - 1]
            if bits[variable - 1] != expected:
                inconsistent[index] = 1.0
                break
    optimum_mask = np.isclose(projected, optimum_original, atol=1e-10).astype(
        np.float64
    )
    return StatevectorData(encoded, projected, inconsistent, optimum_mask)


def _apply_mixer(state: np.ndarray, beta: float, n_qubits: int) -> None:
    cosine = math.cos(beta)
    sine = -1j * math.sin(beta)
    for qubit in range(n_qubits):
        stride = 1 << qubit
        block = stride << 1
        view = state.reshape((-1, block))
        low = view[:, :stride].copy()
        high = view[:, stride:].copy()
        view[:, :stride] = cosine * low + sine * high
        view[:, stride:] = sine * low + cosine * high


def simulate_qaoa(
    data: StatevectorData,
    *,
    gammas: Sequence[float],
    betas: Sequence[float],
) -> np.ndarray:
    if len(gammas) != len(betas):
        raise ValueError("Gamma and beta vectors must have equal length")
    size = len(data.encoded_energies)
    n_qubits = int(math.log2(size))
    if 1 << n_qubits != size:
        raise ValueError("Statevector diagonal length must be a power of two")
    state = np.full(size, 1 / math.sqrt(size), dtype=np.complex128)
    for gamma, beta in zip(gammas, betas):
        state *= np.exp(-1j * float(gamma) * data.encoded_energies)
        _apply_mixer(state, float(beta), n_qubits)
    return state


def statevector_metrics(state: np.ndarray, data: StatevectorData) -> dict[str, float]:
    probabilities = np.abs(state) ** 2
    norm = float(np.sum(probabilities))
    support = probabilities > 1e-15
    return {
        "original_objective_mean": float(probabilities @ data.original_energies),
        "original_objective_best": float(np.min(data.original_energies[support])),
        "optimum_hit_rate": float(probabilities @ data.optimum_mask),
        "encoded_energy_mean": float(probabilities @ data.encoded_energies),
        "auxiliary_inconsistency_rate": float(probabilities @ data.inconsistent),
        "statevector_norm": norm,
    }


def _initial_parameters(
    *,
    instance_id: str,
    design_id: str,
    representation: str,
    random_rep_seed: int | None,
    budget_key: str,
    restart_id: int,
    optimizer_seed: int,
    p: int,
    qaoa_config: Mapping[str, object],
) -> tuple[list[float], int]:
    seed = _stable_seed(
        "e3-independent-parameters-v1",
        instance_id,
        design_id,
        representation,
        random_rep_seed if random_rep_seed is not None else "none",
        budget_key,
        restart_id,
        optimizer_seed,
    )
    rng = random.Random(seed)
    initialization = qaoa_config["parameter_initialization"]  # type: ignore[assignment]
    gamma_low, gamma_high = initialization["gamma_interval"]  # type: ignore[index]
    beta_low, beta_high = initialization["beta_interval"]  # type: ignore[index]
    values = [rng.uniform(float(gamma_low), float(gamma_high)) for _ in range(p)]
    values.extend(rng.uniform(float(beta_low), float(beta_high)) for _ in range(p))
    return values, seed


def optimize_qaoa_run(
    *,
    instance_id: str,
    family: str,
    design: QAOADesign,
    spec: QAOABudgetSpec,
    data: StatevectorData,
    restart_id: int,
    optimizer_seed: int,
    circuit_seed: int,
    measurement_seed: int,
    qaoa_config: Mapping[str, object],
    config_hash: str,
    manifest_hash: str,
    e2_summary_hash: str,
    code_commit: str,
) -> dict[str, object]:
    """Run one independent fixed-budget COBYLA restart and retain it."""

    from scipy.optimize import minimize

    optimizer = qaoa_config["optimizer"]  # type: ignore[assignment]
    evaluation_budget = int(optimizer["objective_evaluations"])
    initial, initialization_seed = _initial_parameters(
        instance_id=instance_id,
        design_id=design.design_id,
        representation=design.representation,
        random_rep_seed=design.random_rep_seed,
        budget_key=spec.key,
        restart_id=restart_id,
        optimizer_seed=optimizer_seed,
        p=spec.p,
        qaoa_config=qaoa_config,
    )
    best_value = math.inf
    best_parameters = list(initial)
    evaluations = 0

    def objective(values) -> float:
        nonlocal best_value, best_parameters, evaluations
        evaluations += 1
        state = simulate_qaoa(
            data,
            gammas=values[: spec.p],
            betas=values[spec.p :],
        )
        value = float(np.abs(state) ** 2 @ data.original_energies)
        if value < best_value:
            best_value = value
            best_parameters = [float(item) for item in values]
        return value

    started = time.perf_counter()
    try:
        if spec.p == 0:
            while evaluations < evaluation_budget:
                objective(np.asarray([], dtype=np.float64))
            terminated_early = False
            optimizer_message = (
                "fixed p=0 zero-layer baseline; no trainable parameters"
            )
        else:
            result = minimize(
                objective,
                np.asarray(initial, dtype=np.float64),
                method="COBYLA",
                options={
                    "maxiter": evaluation_budget,
                    "tol": float(optimizer["tolerance"]),
                },
            )
            terminated_early = evaluations < evaluation_budget
            while evaluations < evaluation_budget:
                objective(np.asarray(best_parameters, dtype=np.float64))
            optimizer_message = str(result.message)
        final_state = simulate_qaoa(
            data,
            gammas=best_parameters[: spec.p],
            betas=best_parameters[spec.p :],
        )
        metrics = statevector_metrics(final_state, data)
        if abs(metrics["statevector_norm"] - 1.0) > 1e-9:
            raise E3QAOAError("Statevector norm check failed")
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
            "statevector_norm": "",
        }
        status = "simulation_failure"
        failure_kind = error.__class__.__name__
        failure_message = str(error)[:500]
        optimizer_message = ""
        terminated_early = evaluations < evaluation_budget
    runtime = time.perf_counter() - started
    return {
        "instance_id": instance_id,
        "family": family,
        "split": "test",
        "representation": design.representation,
        "random_rep_seed": design.random_rep_seed or "",
        "design_id": design.design_id,
        "budget_mode": spec.mode,
        "budget_key": spec.key,
        "p": spec.p,
        "compiled_2q_budget": spec.compiled_budget or "",
        "compiled_2q_gates_per_layer": spec.compiled_two_qubit_gates_per_layer,
        "actual_2q_gates": spec.actual_two_qubit_gates,
        "optimizer": "COBYLA",
        "optimizer_seed": optimizer_seed,
        "restart_id": restart_id,
        "evaluation_budget": evaluation_budget,
        "evaluations": evaluations,
        "shots": 0,
        "circuit_seed": circuit_seed,
        "measurement_seed": measurement_seed,
        "initial_parameters_sha256": _hash_parameters(initial),
        "optimized_parameters_json": json.dumps(
            best_parameters, separators=(",", ":")
        ),
        **metrics,
        "optimizer_runtime_sec": runtime,
        "optimizer_terminated_early": terminated_early,
        "optimizer_message": optimizer_message,
        "initialization_seed": initialization_seed,
        "objective_scoring": "original_family_objective_projected_from_statevector",
        "encoded_energy_role": "diagnostic_only",
        "status": status,
        "failure_kind": failure_kind,
        "failure_message": failure_message,
        "config_hash": config_hash,
        "manifest_hash": manifest_hash,
        "e2_summary_hash": e2_summary_hash,
        "code_commit": code_commit,
    }


def fairness_audit(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_design_count: int,
    qaoa_config: Mapping[str, object],
) -> dict[str, int]:
    evaluations = int(qaoa_config["optimizer"]["objective_evaluations"])  # type: ignore[index]
    restart_count = int(qaoa_config["optimizer"]["restarts"])  # type: ignore[index]
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, object]]] = {}
    for row in rows:
        key = (
            str(row["instance_id"]),
            str(row["representation"]),
            str(row["random_rep_seed"]),
            str(row["design_id"]),
            str(row["budget_key"]),
        )
        groups.setdefault(key, []).append(row)
    missing_restart_groups = 0
    evaluation_mismatches = 0
    seed_policy_mismatches = 0
    initialization_reuse = 0
    budget_exceeds = 0
    non_original_primary_score = 0
    best_only_failures = 0
    expected_restarts = set(range(restart_count))
    optimizer_seeds = list(qaoa_config["optimizer"]["seed_bundle"])  # type: ignore[index]
    circuit_seeds = list(qaoa_config["circuit_seed_bundle"])  # type: ignore[index]
    measurement_seeds = list(qaoa_config["measurement_seed_bundle"])  # type: ignore[index]
    for group in groups.values():
        observed = {int(row["restart_id"]) for row in group}
        if observed != expected_restarts:
            missing_restart_groups += 1
        for row in group:
            restart = int(row["restart_id"])
            if int(row["evaluation_budget"]) != evaluations or int(row["evaluations"]) != evaluations:
                evaluation_mismatches += 1
            if (
                int(row["optimizer_seed"]) != int(optimizer_seeds[restart])
                or int(row["circuit_seed"]) != int(circuit_seeds[restart])
                or int(row["measurement_seed"]) != int(measurement_seeds[restart])
            ):
                seed_policy_mismatches += 1
            if row["budget_mode"] == "equal_compiled_two_qubit_gates" and int(
                row["actual_2q_gates"]
            ) > int(row["compiled_2q_budget"]):
                budget_exceeds += 1
            if row["objective_scoring"] != "original_family_objective_projected_from_statevector":
                non_original_primary_score += 1
    by_initialization: dict[tuple[str, str, int], list[str]] = {}
    for row in rows:
        if int(row["p"]) == 0:
            continue
        key = (
            str(row["instance_id"]),
            str(row["budget_key"]),
            int(row["restart_id"]),
        )
        by_initialization.setdefault(key, []).append(str(row["initial_parameters_sha256"]))
    for values in by_initialization.values():
        if len(values) != len(set(values)):
            initialization_reuse += 1
    if len(groups) != expected_design_count * 4:
        best_only_failures = abs(expected_design_count * 4 - len(groups))
    return {
        "missing_restart_group_count": missing_restart_groups,
        "evaluation_budget_mismatch_count": evaluation_mismatches,
        "seed_policy_mismatch_count": seed_policy_mismatches,
        "initial_parameter_reuse_group_count": initialization_reuse,
        "compiled_budget_exceed_count": budget_exceeds,
        "non_original_primary_score_count": non_original_primary_score,
        "best_only_or_missing_budget_group_count": best_only_failures,
    }


def summarise_runs(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Aggregate run rows after pairing each representation to native by instance."""

    passed = [row for row in rows if row["status"] == "pass"]
    per_instance: dict[tuple[str, str, str], dict[str, float]] = {}
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    for row in passed:
        key = (str(row["instance_id"]), str(row["representation"]), str(row["budget_key"]))
        groups.setdefault(key, []).append(row)
    for key, group in groups.items():
        per_instance[key] = {
            "objective": statistics.fmean(float(row["original_objective_mean"]) for row in group),
            "hit": statistics.fmean(float(row["optimum_hit_rate"]) for row in group),
            "encoded": statistics.fmean(float(row["encoded_energy_mean"]) for row in group),
            "inconsistent": statistics.fmean(float(row["auxiliary_inconsistency_rate"]) for row in group),
        }

    output: list[dict[str, object]] = []
    summary_groups: dict[tuple[str, str, str, str], list[Mapping[str, object]]] = {}
    for row in passed:
        key = (
            str(row["family"]),
            str(row["representation"]),
            str(row["budget_mode"]),
            str(row["budget_key"]),
        )
        summary_groups.setdefault(key, []).append(row)
    for key, group in sorted(summary_groups.items()):
        instance_ids = sorted({str(row["instance_id"]) for row in group})
        objectives = [per_instance[(instance, key[1], key[3])]["objective"] for instance in instance_ids]
        hits = [per_instance[(instance, key[1], key[3])]["hit"] for instance in instance_ids]
        encoded = [per_instance[(instance, key[1], key[3])]["encoded"] for instance in instance_ids]
        inconsistent = [per_instance[(instance, key[1], key[3])]["inconsistent"] for instance in instance_ids]
        differences = [
            per_instance[(instance, key[1], key[3])]["objective"]
            - per_instance[(instance, "all_native", key[3])]["objective"]
            for instance in instance_ids
        ]
        objective_mean, objective_low, objective_high = _uncertainty(objectives)
        difference_mean, difference_low, difference_high = _uncertainty(differences)
        hit_mean, hit_low, hit_high = _uncertainty(hits)
        first = group[0]
        budget_value = (
            int(first["p"])
            if key[2] == "equal_layer"
            else int(first["compiled_2q_budget"])
        )
        output.append(
            {
                "family": key[0],
                "representation": key[1],
                "budget_mode": key[2],
                "budget_value": budget_value,
                "p_min": min(int(row["p"]) for row in group),
                "p_max": max(int(row["p"]) for row in group),
                "instance_count": len(instance_ids),
                "run_count": len(group),
                "original_objective_mean": objective_mean,
                "original_objective_ci95_low": objective_low,
                "original_objective_ci95_high": objective_high,
                "paired_difference_vs_native_mean": difference_mean,
                "paired_difference_vs_native_ci95_low": difference_low,
                "paired_difference_vs_native_ci95_high": difference_high,
                "optimum_hit_rate_mean": hit_mean,
                "optimum_hit_rate_ci95_low": hit_low,
                "optimum_hit_rate_ci95_high": hit_high,
                "encoded_energy_mean": statistics.fmean(encoded),
                "auxiliary_inconsistency_rate_mean": statistics.fmean(inconsistent),
                "status": "pass",
                "config_hash": first["config_hash"],
                "manifest_hash": first["manifest_hash"],
                "code_commit": first["code_commit"],
            }
        )
    return output


def _latex_table(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated formal E3 QAOA summary; do not edit by hand.",
        "\\begin{tabular}{llllrrrr}",
        "\\toprule",
        "Family & Representation & Budget & Value & $N$ & $\\bar f$ & $\\Delta$ native & Opt. hit \\\\",
        "\\midrule",
    ]
    for row in rows:
        labels = [
            str(row["family"]),
            str(row["representation"]),
            str(row["budget_mode"]),
        ]
        labels = [label.replace("_", "\\_") for label in labels]
        lines.append(
            f"{labels[0]} & {labels[1]} & {labels[2]} & {row['budget_value']} & "
            f"{row['instance_count']} & {float(row['original_objective_mean']):.4f} & "
            f"{float(row['paired_difference_vs_native_mean']):.4f} & "
            f"{float(row['optimum_hit_rate_mean']):.4f} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _register_fonts(pdfmetrics, TTFont) -> tuple[str, str]:
    candidates = (
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
    )
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("E3Sans", str(regular)))
            pdfmetrics.registerFont(TTFont("E3SansBold", str(bold)))
            return "E3Sans", "E3SansBold"
    return "Helvetica", "Helvetica-Bold"


def write_qaoa_figure_pdf(
    path: Path,
    summary_rows: Sequence[Mapping[str, object]],
    *,
    budget_mode: str,
) -> str:
    """Create one two-panel vector PDF for a frozen E3 budget mode."""

    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E3QAOAError("Formal E3 PDF output requires reportlab==4.4.9") from error
    if reportlab.Version != "4.4.9":
        raise E3QAOAError(
            f"ReportLab version mismatch: expected 4.4.9, received {reportlab.Version}"
        )
    rows = [row for row in summary_rows if row["budget_mode"] == budget_mode]
    values = sorted({int(row["budget_value"]) for row in rows})
    if len(values) != 2:
        raise E3QAOAError(f"Expected two frozen values for {budget_mode}")
    representations = (
        "all_native",
        "fully_quadratized",
        "selective",
        "matched_random_selective",
    )
    labels = ("Native", "Full", "Selected", "Matched random")
    palette = (
        colors.HexColor("#1F77B4"),
        colors.HexColor("#FF7F0E"),
        colors.HexColor("#2CA02C"),
        colors.HexColor("#9467BD"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    regular, bold = _register_fonts(pdfmetrics, TTFont)
    title = (
        "Formal E3: equal-layer QAOA"
        if budget_mode == "equal_layer"
        else "Formal E3: equal compiled-2Q-budget QAOA"
    )
    pdf.setTitle(title)
    pdf.setAuthor("URSS formal pipeline")
    pdf.setFillColor(colors.HexColor("#17324D"))
    pdf.setFont(bold, 18)
    pdf.drawString(42, height - 44, title)
    pdf.setFont(regular, 8.5)
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.drawString(
        42,
        height - 60,
        "Paired original-objective difference versus native; negative values favour the representation.",
    )
    left = 42
    gap = 20
    panel_width = (width - 2 * left - gap) / 2
    panel_height = height - 150
    for panel_index, budget_value in enumerate(values):
        x0 = left + panel_index * (panel_width + gap)
        y0 = 74
        pdf.setFillColor(colors.white)
        pdf.setStrokeColor(colors.HexColor("#CFD8DC"))
        pdf.roundRect(x0, y0, panel_width, panel_height, 5, fill=1, stroke=1)
        panel_title = (
            f"Equal layer p={budget_value}"
            if budget_mode == "equal_layer"
            else f"Compiled 2Q budget={budget_value}"
        )
        pdf.setFillColor(colors.HexColor("#17324D"))
        pdf.setFont(bold, 11)
        pdf.drawString(x0 + 14, y0 + panel_height - 22, panel_title)
        combined: dict[str, list[float]] = {name: [] for name in representations}
        for row in rows:
            if int(row["budget_value"]) == budget_value:
                combined[str(row["representation"])].append(
                    float(row["paired_difference_vs_native_mean"])
                )
        chart_values = [statistics.fmean(combined[name]) for name in representations]
        extent = max(max(abs(value) for value in chart_values), 1e-9)
        chart_bottom = y0 + 58
        chart_top = y0 + panel_height - 48
        zero = (chart_bottom + chart_top) / 2
        scale = (chart_top - chart_bottom) * 0.42 / extent
        pdf.setStrokeColor(colors.HexColor("#607D8B"))
        pdf.line(x0 + 18, zero, x0 + panel_width - 18, zero)
        bar_gap = 15
        bar_width = (panel_width - 42 - 3 * bar_gap) / 4
        for index, (label, value) in enumerate(zip(labels, chart_values)):
            x = x0 + 21 + index * (bar_width + bar_gap)
            height_value = abs(value) * scale
            y = zero if value >= 0 else zero - height_value
            pdf.setFillColor(palette[index])
            pdf.rect(x, y, bar_width, height_value, fill=1, stroke=0)
            pdf.setFillColor(colors.HexColor("#263238"))
            pdf.setFont(bold, 7.5)
            value_y = y + height_value + 4 if value >= 0 else y - 10
            pdf.drawCentredString(x + bar_width / 2, value_y, f"{value:.4f}")
            pdf.setFont(regular, 6.5)
            pdf.drawCentredString(x + bar_width / 2, chart_bottom - 18, label)
    pdf.setFont(regular, 7)
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.drawRightString(width - 42, 28, "Generated by the frozen formal E3 pipeline")
    pdf.showPage()
    pdf.save()
    return reportlab.Version


def run_e3_qaoa_pipeline(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    data_directory: str | Path,
    results_directory: str | Path,
    tables_directory: str | Path,
    figures_directory: str | Path,
    code_commit: str,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
    progress=None,
) -> dict[str, object]:
    """Run formal E3 and emit raw rows, paired summaries, table, and figures."""

    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    figures_directory = Path(figures_directory)
    project_root = results_directory.parent
    relative_targets = (
        Path("results/e3_qaoa_runs.csv"),
        Path("results/e3_qaoa_summary.csv"),
        Path("results/e3_budget_plan.csv"),
        Path("results/e3_validation_summary.json"),
        Path("tables/table_e3_qaoa.tex"),
        Path("figures/figure_e3_equal_layer.pdf"),
        Path("figures/figure_e3_equal_2q_budget.pdf"),
    )
    if any((project_root / path).exists() for path in relative_targets):
        raise FileExistsError("Formal E3 output already exists; refusing overwrite")
    staging = project_root / "e3_step5_building"
    if staging.exists():
        raise E3QAOAError(f"Incomplete E3 staging directory exists: {staging}")

    frozen = verify_e3_inputs(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
        results_directory=results_directory,
    )
    config = frozen["config"]  # type: ignore[assignment]
    qaoa_config = config["qaoa"]  # type: ignore[index]
    config_hash = str(frozen["config_hash"])
    manifest_hash = str(frozen["qaoa_manifest_hash"])
    e2_summary_hash = str(frozen["e2_summary_hash"])
    ground_truth = frozen["ground_truth_rows"]  # type: ignore[assignment]
    test_rows = frozen["qaoa_test_rows"]  # type: ignore[assignment]
    staging.mkdir(parents=True)
    run_rows: list[dict[str, object]] = []
    plan_rows: list[dict[str, object]] = []
    design_count = 0
    try:
        for ordinal, row in enumerate(test_rows, start=1):
            canonical_path = data_directory / row["canonical_file"]
            if _sha256(canonical_path) != row["canonical_sha256"]:
                raise E3QAOAError(
                    f"Canonical coefficient hash mismatch: {row['instance_id']}"
                )
            family, polynomial = _canonical_polynomial(canonical_path)
            if family != row["family"]:
                raise E3QAOAError(f"Family mismatch: {row['instance_id']}")
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
                plan_rows.append(plan)
                data = statevector_data(
                    polynomial,
                    design.evaluation.representation,
                    optimum_original=optimum,
                )
                specs = budget_specs(
                    int(plan["compiled_2q_gates_per_layer"]), qaoa_config
                )
                restarts = int(qaoa_config["optimizer"]["restarts"])  # type: ignore[index]
                for spec in specs:
                    for restart_id in range(restarts):
                        run_rows.append(
                            optimize_qaoa_run(
                                instance_id=row["instance_id"],
                                family=family,
                                design=design,
                                spec=spec,
                                data=data,
                                restart_id=restart_id,
                                optimizer_seed=int(
                                    qaoa_config["optimizer"]["seed_bundle"][restart_id]  # type: ignore[index]
                                ),
                                circuit_seed=int(
                                    qaoa_config["circuit_seed_bundle"][restart_id]  # type: ignore[index]
                                ),
                                measurement_seed=int(
                                    qaoa_config["measurement_seed_bundle"][restart_id]  # type: ignore[index]
                                ),
                                qaoa_config=qaoa_config,
                                config_hash=config_hash,
                                manifest_hash=manifest_hash,
                                e2_summary_hash=e2_summary_hash,
                                code_commit=code_commit,
                            )
                        )
            if progress:
                progress(
                    f"E3 QAOA: {ordinal}/{len(test_rows)} frozen test instances completed"
                )

        expected_design_count = len(test_rows) * 8
        expected_run_count = expected_design_count * 4 * 3
        fairness = fairness_audit(
            run_rows,
            expected_design_count=expected_design_count,
            qaoa_config=qaoa_config,
        )
        failure_count = sum(1 for row in run_rows if row["status"] != "pass")
        zero_layer_runs = sum(1 for row in run_rows if int(row["p"]) == 0)
        summary_rows = summarise_runs(run_rows)
        gates = (
            design_count == expected_design_count
            and len(plan_rows) == expected_design_count
            and len(run_rows) == expected_run_count
            and len(summary_rows) == 32
            and failure_count == 0
            and all(value == 0 for value in fairness.values())
        )

        runs_path = staging / "results/e3_qaoa_runs.csv"
        summary_path = staging / "results/e3_qaoa_summary.csv"
        plan_path = staging / "results/e3_budget_plan.csv"
        validation_path = staging / "results/e3_validation_summary.json"
        table_path = staging / "tables/table_e3_qaoa.tex"
        equal_layer_path = staging / "figures/figure_e3_equal_layer.pdf"
        equal_budget_path = staging / "figures/figure_e3_equal_2q_budget.pdf"
        _write_csv(runs_path, run_rows, RUN_FIELDS)
        _write_csv(summary_path, summary_rows, SUMMARY_FIELDS)
        _write_csv(plan_path, plan_rows, BUDGET_PLAN_FIELDS)
        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(
            _latex_table(summary_rows), encoding="utf-8", newline="\n"
        )
        reportlab_version = write_qaoa_figure_pdf(
            equal_layer_path, summary_rows, budget_mode="equal_layer"
        )
        write_qaoa_figure_pdf(
            equal_budget_path,
            summary_rows,
            budget_mode="equal_compiled_two_qubit_gates",
        )
        artifact_hashes = {
            str(path.relative_to(staging)): _write_hash(path)
            for path in (
                runs_path,
                summary_path,
                plan_path,
                table_path,
                equal_layer_path,
                equal_budget_path,
            )
        }
        validation = {
            "status": "pass" if gates else "fail",
            "scope": "formal_step5_e3_fair_qaoa",
            "config_hash": config_hash,
            "qaoa_manifest_hash": manifest_hash,
            "ground_truth_hash": frozen["ground_truth_hash"],
            "e2_validation_summary_hash": e2_summary_hash,
            "code_commit": code_commit,
            "reportlab_version": reportlab_version,
            "frozen_test_instance_count": len(test_rows),
            "representation_family_count": 4,
            "matched_random_seed_count": 5,
            "scheduled_design_count": design_count,
            "budget_plan_row_count": len(plan_rows),
            "run_row_count": len(run_rows),
            "summary_row_count": len(summary_rows),
            "failed_run_count": failure_count,
            "zero_layer_budget_run_count": zero_layer_runs,
            "optimizer": "COBYLA",
            "objective_evaluations_per_restart": 60,
            "restarts_per_design_budget": 3,
            "primary_score": "original_family_objective",
            "encoded_energy_role": "diagnostic_only",
            "matched_random_aggregation": "five_frozen_auxiliary_count_matched_seeds",
            **fairness,
            "artifact_hashes": artifact_hashes,
            "e4_e6_may_continue": gates,
        }
        _write_json(validation_path, validation)
        _write_hash(validation_path)
        if not gates:
            raise E3QAOAError(
                f"Formal E3 fairness gate failed; staging retained at {staging}"
            )
        for relative in relative_targets:
            source = staging / relative
            target = project_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            shutil.move(
                str(source.with_suffix(".sha256")),
                str(target.with_suffix(".sha256")),
            )
        shutil.rmtree(staging)
    except Exception:
        raise

    if assumptions_path is not None:
        assumptions = Path(assumptions_path)
        section = f"""
## Formal Step 5 / E3 fair QAOA (v1)

- Status: `pass`; E4-E6 continuation is allowed.
- Frozen QAOA test instances: `14` (`7` per family); four representation families all obey Qmax `12`.
- Equal-layer depths: `p=1,2`; equal compiled-2Q budgets: `128,256` on `device_sparse_v1` using the five frozen transpiler seeds and median per-layer cost.
- If a frozen compiled budget is smaller than one sparse cost layer, the maximum feasible depth is recorded as `p=0` with `actual_2q_gates=0`; those scheduled zero-layer baselines are retained rather than exceeding the budget or deleting the comparison.
- Every fixed design/budget retains all `3` independent COBYLA restarts and exactly `60` objective evaluations. Matched-random is averaged over all five frozen auxiliary-count-matched representation seeds.
- Primary optimization and reporting score: projected original-family objective. Encoded energy and auxiliary inconsistency are diagnostics only.
- Raw run rows: `{len(run_rows)}`; summary rows: `{len(summary_rows)}`; failed runs: `0`.
- Config hash: `{config_hash}`; frozen QAOA manifest hash: `{manifest_hash}`; E2 validation summary hash: `{e2_summary_hash}`.
"""
        assumptions.write_text(
            assumptions.read_text(encoding="utf-8").rstrip()
            + "\n"
            + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if run_commands_path is not None:
        commands = Path(run_commands_path)
        section = """
## Formal Step 5 / E3 command (v1)

```powershell
python .\\run_e3_qaoa.py `
  --config .\\configs\\experiment_config_v1.yaml `
  --config-hash .\\configs\\experiment_config_v1.sha256 `
  --data .\\data `
  --results .\\results `
  --tables .\\tables `
  --figures .\\figures `
  --assumptions .\\assumptions_and_decisions.md `
  --run-commands .\\RUN_COMMANDS.md
```

Required result: `E3 FAIRNESS GATE: pass` and `e4_e6_may_continue=true`.
"""
        commands.write_text(
            commands.read_text(encoding="utf-8").rstrip()
            + "\n"
            + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if progress:
        progress("E3 FAIRNESS GATE: pass")
    return validation
