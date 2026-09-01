"""Formal Step 6 / E4 warm-start and relaxation-ablation pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import yaml

from .e1_exactness import verify_data_freeze
from .e2_resources import _verify_hash
from .e3_qaoa import (
    QAOABudgetSpec,
    QAOADesign,
    StatevectorData,
    _canonical_polynomial,
    _hash_parameters,
    _initial_parameters,
    _read_csv,
    _register_fonts,
    _sha256,
    _stable_seed,
    _uncertainty,
    _write_csv,
    _write_hash,
    _write_json,
    budget_specs,
    qaoa_designs,
    simulate_qaoa,
    statevector_data,
    statevector_metrics,
)
from .polynomial import Support, canonicalize


class E4WarmStartError(RuntimeError):
    """Formal E4 cannot proceed or failed a mandatory protocol gate."""


RUN_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "random_rep_seed",
    "design_id",
    "n_original",
    "n_aux",
    "budget_mode",
    "budget_key",
    "p",
    "compiled_2q_budget",
    "compiled_2q_gates_per_layer",
    "actual_2q_gates",
    "warm_start_policy",
    "pair_closure",
    "relaxation_method",
    "relaxation_status",
    "relaxation_objective",
    "marginal_set_sha256",
    "mean_abs_original_margin",
    "weak_signal_flag",
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
    "e3_summary_hash",
    "code_commit",
)


MARGINAL_FIELDS = (
    "instance_id",
    "family",
    "split",
    "n_original",
    "moment_type",
    "variable_i",
    "variable_j",
    "raw_single_moment",
    "clipped_single_moment",
    "abs_single_margin_from_half",
    "raw_pair_moment",
    "clipped_pair_moment",
    "independence_pair_moment",
    "abs_pair_vs_independence",
    "active_auxiliary_design_count",
    "relaxation_method",
    "solver",
    "solver_method",
    "solver_status",
    "solver_objective",
    "solver_runtime_sec",
    "clipping_delta",
    "weak_signal_flag",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


SUMMARY_FIELDS = (
    "family",
    "representation",
    "budget_mode",
    "budget_key",
    "budget_value",
    "budget_label",
    "warm_start_policy",
    "pair_closure",
    "instance_count",
    "design_count",
    "run_count",
    "ci_unit",
    "ci_method",
    "original_objective_mean",
    "original_objective_ci95_low",
    "original_objective_ci95_high",
    "paired_difference_vs_cold_mean",
    "paired_difference_vs_cold_ci95_low",
    "paired_difference_vs_cold_ci95_high",
    "optimum_hit_rate_mean",
    "optimum_hit_rate_ci95_low",
    "optimum_hit_rate_ci95_high",
    "encoded_energy_mean",
    "auxiliary_inconsistency_rate_mean",
    "mean_abs_original_margin",
    "weak_signal_instance_count",
    "status",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


@dataclass(frozen=True)
class RelaxationMoments:
    objective: float
    singles: Mapping[int, float]
    pairs: Mapping[tuple[int, int], float]
    status: str
    solver_message: str
    runtime_sec: float


@dataclass(frozen=True)
class WarmStartSpec:
    policy: str
    pair_closure: str
    probabilities: tuple[float, ...] | None


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E4WarmStartError(f"Expected JSON object: {path}")
    return payload


def _moment_digest(moments: RelaxationMoments) -> str:
    payload = {
        "singles": {str(key): moments.singles[key] for key in sorted(moments.singles)},
        "pairs": {
            f"{pair[0]},{pair[1]}": moments.pairs[pair]
            for pair in sorted(moments.pairs)
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    return hashlib.sha256(encoded).hexdigest()


def solve_sa_rlt_level2(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    method: str = "highs",
    presolve: bool = True,
) -> RelaxationMoments:
    """Solve the declared lifted LP and return first and pair moments.

    The level-2 lift uses one variable for every first and pair moment.  A
    cubic support additionally receives a lifted triple variable.  Pair
    variables obey the Boolean McCormick/RLT envelope; triple variables obey
    both the three-variable envelope and every pair-to-single RLT envelope.
    """

    from scipy.optimize import linprog

    canonical = canonicalize(polynomial)
    singles = tuple(range(1, n_original + 1))
    pairs = tuple(combinations(singles, 2))
    triples = tuple(sorted(support for support in canonical if len(support) == 3))
    indices: dict[tuple[str, object], int] = {}
    for variable in singles:
        indices[("mu", variable)] = len(indices)
    for pair in pairs:
        indices[("q", pair)] = len(indices)
    for triple in triples:
        indices[("t", triple)] = len(indices)
    objective = np.zeros(len(indices), dtype=np.float64)
    constant = 0.0
    for support, coefficient in canonical.items():
        value = float(coefficient)
        if not support:
            constant += value
        elif len(support) == 1:
            objective[indices[("mu", support[0])]] += value
        elif len(support) == 2:
            objective[indices[("q", tuple(support))]] += value
        elif len(support) == 3:
            objective[indices[("t", tuple(support))]] += value
        else:
            raise E4WarmStartError("SA/RLT level-2 received degree above three")

    rows: list[np.ndarray] = []
    bounds: list[float] = []

    def inequality(terms: Mapping[tuple[str, object], float], upper: float) -> None:
        row = np.zeros(len(indices), dtype=np.float64)
        for key, coefficient in terms.items():
            row[indices[key]] = coefficient
        rows.append(row)
        bounds.append(float(upper))

    for i, j in pairs:
        pair = (i, j)
        inequality({("q", pair): 1, ("mu", i): -1}, 0)
        inequality({("q", pair): 1, ("mu", j): -1}, 0)
        inequality({("mu", i): 1, ("mu", j): 1, ("q", pair): -1}, 1)

    for triple in triples:
        i, j, k = triple
        t_key = ("t", triple)
        for variable in triple:
            inequality({t_key: 1, ("mu", variable): -1}, 0)
        inequality(
            {
                ("mu", i): 1,
                ("mu", j): 1,
                ("mu", k): 1,
                t_key: -1,
            },
            2,
        )
        for pair, remaining in (((i, j), k), ((i, k), j), ((j, k), i)):
            inequality({t_key: 1, ("q", pair): -1}, 0)
            inequality(
                {("q", pair): 1, ("mu", remaining): 1, t_key: -1},
                1,
            )

    started = time.perf_counter()
    result = linprog(
        objective,
        A_ub=np.asarray(rows, dtype=np.float64),
        b_ub=np.asarray(bounds, dtype=np.float64),
        bounds=[(0.0, 1.0)] * len(indices),
        method=method,
        options={"presolve": bool(presolve)},
    )
    runtime = time.perf_counter() - started
    if not result.success or result.x is None:
        raise E4WarmStartError(
            f"SA/RLT level-2 failed: status={result.status}; {result.message}"
        )
    values = np.asarray(result.x, dtype=np.float64)
    first = {i: float(values[indices[("mu", i)]]) for i in singles}
    lifted = {pair: float(values[indices[("q", pair)]]) for pair in pairs}
    if any(value < -1e-9 or value > 1 + 1e-9 for value in (*first.values(), *lifted.values())):
        raise E4WarmStartError("Relaxation moment outside [0,1]")
    return RelaxationMoments(
        objective=float(result.fun) + constant,
        singles=first,
        pairs=lifted,
        status="optimal",
        solver_message=str(result.message),
        runtime_sec=runtime,
    )


def _clip(value: float, delta: float) -> float:
    return min(1.0 - delta, max(delta, float(value)))


def warm_start_specs(
    design: QAOADesign,
    moments: RelaxationMoments,
    *,
    clipping_delta: float,
) -> list[WarmStartSpec]:
    """Return only the frozen E4 variants, deduplicating zero-aux designs."""

    representation = design.evaluation.representation
    originals = tuple(
        _clip(moments.singles[index], clipping_delta)
        for index in range(1, representation.original_width + 1)
    )
    original_only = originals + (0.5,) * representation.n_auxiliary
    specs = [
        WarmStartSpec("cold_start", "not_applicable", None),
        WarmStartSpec(
            "original_variables_only",
            "auxiliary_cold_half",
            original_only,
        ),
    ]
    if representation.n_auxiliary == 0:
        return specs
    pair_probabilities: list[float] = []
    independence_probabilities: list[float] = []
    for pair, variable in sorted(
        representation.auxiliary_indices.items(), key=lambda item: item[1]
    ):
        if pair not in moments.pairs:
            raise E4WarmStartError(f"Missing lifted pair moment for {pair}")
        pair_probabilities.append(_clip(moments.pairs[pair], clipping_delta))
        independence_probabilities.append(originals[pair[0] - 1] * originals[pair[1] - 1])
    specs.extend(
        (
            WarmStartSpec(
                "original_and_auxiliary_variables",
                "sa_rlt_level_2_pair_moments",
                originals + tuple(pair_probabilities),
            ),
            WarmStartSpec(
                "original_and_auxiliary_variables",
                "independence_mu_product_ablation",
                originals + tuple(independence_probabilities),
            ),
        )
    )
    if any(len(spec.probabilities or ()) != representation.n_qubits for spec in specs[1:]):
        raise E4WarmStartError("Warm-start width mismatch")
    return specs


def product_state(probabilities: Sequence[float]) -> np.ndarray:
    """Build the little-endian product state from Bernoulli marginals."""

    state = np.asarray([1.0 + 0.0j], dtype=np.complex128)
    for probability in probabilities:
        value = float(probability)
        if value < 0 or value > 1:
            raise ValueError("Warm-start probability must lie in [0,1]")
        qubit = np.asarray(
            [math.sqrt(1.0 - value), math.sqrt(value)], dtype=np.complex128
        )
        state = np.kron(qubit, state)
    return state


def _apply_matched_mixer(
    state: np.ndarray,
    beta: float,
    probabilities: Sequence[float],
) -> None:
    cosine = math.cos(float(beta))
    sine = math.sin(float(beta))
    for qubit, probability in enumerate(probabilities):
        omega = float(probability)
        x_weight = 2.0 * math.sqrt(omega * (1.0 - omega))
        z_weight = 1.0 - 2.0 * omega
        u00 = cosine + 1j * sine * z_weight
        u01 = 1j * sine * x_weight
        u10 = u01
        u11 = cosine - 1j * sine * z_weight
        stride = 1 << qubit
        block = stride << 1
        view = state.reshape((-1, block))
        low = view[:, :stride].copy()
        high = view[:, stride:].copy()
        view[:, :stride] = u00 * low + u01 * high
        view[:, stride:] = u10 * low + u11 * high


def simulate_warm_qaoa(
    data: StatevectorData,
    *,
    probabilities: Sequence[float],
    gammas: Sequence[float],
    betas: Sequence[float],
) -> np.ndarray:
    """Apply the paper's product warm state and matched local mixer."""

    if len(gammas) != len(betas):
        raise ValueError("Gamma and beta vectors must have equal length")
    n_qubits = int(math.log2(len(data.encoded_energies)))
    if len(probabilities) != n_qubits:
        raise ValueError("Warm-start marginal count does not match state width")
    state = product_state(probabilities)
    for gamma, beta in zip(gammas, betas):
        state *= np.exp(-1j * float(gamma) * data.encoded_energies)
        _apply_matched_mixer(state, float(beta), probabilities)
    return state


def _simulate(
    data: StatevectorData,
    spec: WarmStartSpec,
    parameters: Sequence[float],
    p: int,
) -> np.ndarray:
    gammas = parameters[:p]
    betas = parameters[p:]
    if spec.policy == "cold_start":
        return simulate_qaoa(data, gammas=gammas, betas=betas)
    if spec.probabilities is None:
        raise E4WarmStartError("Warm policy lacks marginal probabilities")
    return simulate_warm_qaoa(
        data,
        probabilities=spec.probabilities,
        gammas=gammas,
        betas=betas,
    )


def optimize_warmstart_run(
    *,
    instance_id: str,
    family: str,
    design: QAOADesign,
    budget: QAOABudgetSpec,
    data: StatevectorData,
    warm_spec: WarmStartSpec,
    moments: RelaxationMoments,
    restart_id: int,
    optimizer_seed: int,
    circuit_seed: int,
    measurement_seed: int,
    qaoa_config: Mapping[str, object],
    config_hash: str,
    manifest_hash: str,
    e3_summary_hash: str,
    code_commit: str,
) -> dict[str, object]:
    """Run one E4 restart without changing any E3 optimisation setting."""

    from scipy.optimize import minimize

    optimizer = qaoa_config["optimizer"]  # type: ignore[assignment]
    evaluation_budget = int(optimizer["objective_evaluations"])
    initial, initialization_seed = _initial_parameters(
        instance_id=instance_id,
        design_id=design.design_id,
        representation=design.representation,
        random_rep_seed=design.random_rep_seed,
        budget_key=budget.key,
        restart_id=restart_id,
        optimizer_seed=optimizer_seed,
        p=budget.p,
        qaoa_config=qaoa_config,
    )
    best_value = math.inf
    best_parameters = list(initial)
    evaluations = 0

    def objective(values) -> float:
        nonlocal best_value, best_parameters, evaluations
        evaluations += 1
        state = _simulate(data, warm_spec, values, budget.p)
        value = float(np.abs(state) ** 2 @ data.original_energies)
        if value < best_value:
            best_value = value
            best_parameters = [float(item) for item in values]
        return value

    started = time.perf_counter()
    try:
        if budget.p == 0:
            while evaluations < evaluation_budget:
                objective(np.asarray([], dtype=np.float64))
            terminated_early = False
            optimizer_message = "fixed p=0 zero-layer baseline; no trainable parameters"
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
        final_state = _simulate(data, warm_spec, best_parameters, budget.p)
        metrics = statevector_metrics(final_state, data)
        if abs(metrics["statevector_norm"] - 1.0) > 1e-9:
            raise E4WarmStartError("Statevector norm check failed")
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
    original_margins = [abs(value - 0.5) for value in moments.singles.values()]
    clipping_delta = float(qaoa_config["warm_start"]["clipping_delta"])  # type: ignore[index]
    return {
        "instance_id": instance_id,
        "family": family,
        "split": "test",
        "representation": design.representation,
        "random_rep_seed": design.random_rep_seed or "",
        "design_id": design.design_id,
        "n_original": design.evaluation.representation.original_width,
        "n_aux": design.evaluation.representation.n_auxiliary,
        "budget_mode": budget.mode,
        "budget_key": budget.key,
        "p": budget.p,
        "compiled_2q_budget": budget.compiled_budget or "",
        "compiled_2q_gates_per_layer": budget.compiled_two_qubit_gates_per_layer,
        "actual_2q_gates": budget.actual_two_qubit_gates,
        "warm_start_policy": warm_spec.policy,
        "pair_closure": warm_spec.pair_closure,
        "relaxation_method": "SA_RLT_level_2",
        "relaxation_status": moments.status,
        "relaxation_objective": moments.objective,
        "marginal_set_sha256": _moment_digest(moments),
        "mean_abs_original_margin": statistics.fmean(original_margins),
        "weak_signal_flag": statistics.median(original_margins) <= clipping_delta,
        "optimizer": "COBYLA",
        "optimizer_seed": optimizer_seed,
        "restart_id": restart_id,
        "evaluation_budget": evaluation_budget,
        "evaluations": evaluations,
        "shots": 0,
        "circuit_seed": circuit_seed,
        "measurement_seed": measurement_seed,
        "initial_parameters_sha256": _hash_parameters(initial),
        "optimized_parameters_json": json.dumps(best_parameters, separators=(",", ":")),
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
        "e3_summary_hash": e3_summary_hash,
        "code_commit": code_commit,
    }


def marginal_diagnostic_rows(
    *,
    instance_id: str,
    family: str,
    moments: RelaxationMoments,
    designs: Sequence[QAOADesign],
    clipping_delta: float,
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
    solver_package: str,
    solver_method: str,
) -> list[dict[str, object]]:
    active_counts: dict[tuple[int, int], int] = {}
    for design in designs:
        for pair in design.evaluation.representation.auxiliary_indices:
            active_counts[pair] = active_counts.get(pair, 0) + 1
    margins = [abs(value - 0.5) for value in moments.singles.values()]
    weak = statistics.median(margins) <= clipping_delta
    rows: list[dict[str, object]] = []
    for variable, value in sorted(moments.singles.items()):
        rows.append(
            {
                "instance_id": instance_id,
                "family": family,
                "split": "test",
                "n_original": len(moments.singles),
                "moment_type": "original_variable",
                "variable_i": variable,
                "variable_j": "",
                "raw_single_moment": value,
                "clipped_single_moment": _clip(value, clipping_delta),
                "abs_single_margin_from_half": abs(value - 0.5),
                "raw_pair_moment": "",
                "clipped_pair_moment": "",
                "independence_pair_moment": "",
                "abs_pair_vs_independence": "",
                "active_auxiliary_design_count": "",
                "relaxation_method": "SA_RLT_level_2",
                "solver": solver_package,
                "solver_method": solver_method,
                "solver_status": moments.status,
                "solver_objective": moments.objective,
                "solver_runtime_sec": moments.runtime_sec,
                "clipping_delta": clipping_delta,
                "weak_signal_flag": weak,
                "config_hash": config_hash,
                "manifest_hash": manifest_hash,
                "code_commit": code_commit,
            }
        )
    for (i, j), value in sorted(moments.pairs.items()):
        product = _clip(moments.singles[i], clipping_delta) * _clip(
            moments.singles[j], clipping_delta
        )
        rows.append(
            {
                "instance_id": instance_id,
                "family": family,
                "split": "test",
                "n_original": len(moments.singles),
                "moment_type": "lifted_pair",
                "variable_i": i,
                "variable_j": j,
                "raw_single_moment": "",
                "clipped_single_moment": "",
                "abs_single_margin_from_half": "",
                "raw_pair_moment": value,
                "clipped_pair_moment": _clip(value, clipping_delta),
                "independence_pair_moment": product,
                "abs_pair_vs_independence": abs(_clip(value, clipping_delta) - product),
                "active_auxiliary_design_count": active_counts.get((i, j), 0),
                "relaxation_method": "SA_RLT_level_2",
                "solver": solver_package,
                "solver_method": solver_method,
                "solver_status": moments.status,
                "solver_objective": moments.objective,
                "solver_runtime_sec": moments.runtime_sec,
                "clipping_delta": clipping_delta,
                "weak_signal_flag": weak,
                "config_hash": config_hash,
                "manifest_hash": manifest_hash,
                "code_commit": code_commit,
            }
        )
    return rows


def warmstart_audit(
    rows: Sequence[Mapping[str, object]],
    *,
    designs: Sequence[Mapping[str, object]],
    qaoa_config: Mapping[str, object],
    e3_rows: Sequence[Mapping[str, str]] | None = None,
) -> dict[str, int]:
    expected_evaluations = int(qaoa_config["optimizer"]["objective_evaluations"])  # type: ignore[index]
    expected_restarts = int(qaoa_config["optimizer"]["restarts"])  # type: ignore[index]
    optimizer_seeds = list(qaoa_config["optimizer"]["seed_bundle"])  # type: ignore[index]
    circuit_seeds = list(qaoa_config["circuit_seed_bundle"])  # type: ignore[index]
    measurement_seeds = list(qaoa_config["measurement_seed_bundle"])  # type: ignore[index]
    evaluation_mismatch = 0
    seed_mismatch = 0
    budget_mismatch = 0
    score_mismatch = 0
    illegal_variant = 0
    native_aux_duplicate = 0
    failed = 0
    groups: dict[tuple[str, ...], set[int]] = {}
    for row in rows:
        restart = int(row["restart_id"])
        if int(row["evaluations"]) != expected_evaluations or int(
            row["evaluation_budget"]
        ) != expected_evaluations:
            evaluation_mismatch += 1
        if (
            int(row["optimizer_seed"]) != int(optimizer_seeds[restart])
            or int(row["circuit_seed"]) != int(circuit_seeds[restart])
            or int(row["measurement_seed"]) != int(measurement_seeds[restart])
        ):
            seed_mismatch += 1
        if row["budget_mode"] == "equal_compiled_two_qubit_gates" and int(
            row["actual_2q_gates"]
        ) > int(row["compiled_2q_budget"]):
            budget_mismatch += 1
        if row["objective_scoring"] != "original_family_objective_projected_from_statevector":
            score_mismatch += 1
        policy = str(row["warm_start_policy"])
        closure = str(row["pair_closure"])
        allowed = {
            ("cold_start", "not_applicable"),
            ("original_variables_only", "auxiliary_cold_half"),
            ("original_and_auxiliary_variables", "sa_rlt_level_2_pair_moments"),
            ("original_and_auxiliary_variables", "independence_mu_product_ablation"),
        }
        if (policy, closure) not in allowed:
            illegal_variant += 1
        if int(row["n_aux"]) == 0 and policy == "original_and_auxiliary_variables":
            native_aux_duplicate += 1
        if row["status"] != "pass":
            failed += 1
        key = (
            str(row["instance_id"]),
            str(row["representation"]),
            str(row["random_rep_seed"]),
            str(row["design_id"]),
            str(row["budget_key"]),
            policy,
            closure,
        )
        groups.setdefault(key, set()).add(restart)
    missing_restart_groups = sum(
        observed != set(range(expected_restarts)) for observed in groups.values()
    )
    expected_rows = sum(
        (2 + (2 if int(design["n_aux"]) > 0 else 0)) * 4 * expected_restarts
        for design in designs
    )
    cold_reproduction = 0
    if e3_rows is not None:
        e3_index = {
            (
                row["instance_id"],
                row["representation"],
                row["random_rep_seed"],
                row["design_id"],
                row["budget_key"],
                row["restart_id"],
            ): row
            for row in e3_rows
        }
        for row in rows:
            if row["warm_start_policy"] != "cold_start" or row["status"] != "pass":
                continue
            key = (
                str(row["instance_id"]),
                str(row["representation"]),
                str(row["random_rep_seed"]),
                str(row["design_id"]),
                str(row["budget_key"]),
                str(row["restart_id"]),
            )
            reference = e3_index.get(key)
            if reference is None:
                cold_reproduction += 1
                continue
            for field in (
                "p",
                "actual_2q_gates",
                "evaluations",
                "optimizer_seed",
                "circuit_seed",
                "measurement_seed",
                "initial_parameters_sha256",
                "optimized_parameters_json",
            ):
                if str(row[field]) != str(reference[field]):
                    cold_reproduction += 1
                    break
            else:
                for field in (
                    "original_objective_mean",
                    "original_objective_best",
                    "optimum_hit_rate",
                    "encoded_energy_mean",
                    "auxiliary_inconsistency_rate",
                ):
                    if not math.isclose(
                        float(row[field]), float(reference[field]), rel_tol=1e-10, abs_tol=1e-10
                    ):
                        cold_reproduction += 1
                        break
    return {
        "expected_run_row_count": expected_rows,
        "run_row_count_mismatch": abs(expected_rows - len(rows)),
        "failed_run_count": failed,
        "missing_restart_group_count": missing_restart_groups,
        "evaluation_budget_mismatch_count": evaluation_mismatch,
        "seed_policy_mismatch_count": seed_mismatch,
        "compiled_budget_exceed_count": budget_mismatch,
        "non_original_primary_score_count": score_mismatch,
        "illegal_warmstart_variant_count": illegal_variant,
        "zero_auxiliary_duplicate_count": native_aux_duplicate,
        "cold_e3_reproduction_mismatch_count": cold_reproduction,
    }


def _summarise_warmstart_runs_legacy(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    passed = [row for row in rows if row["status"] == "pass"]
    per_design: dict[tuple[str, ...], dict[str, float]] = {}
    groups: dict[tuple[str, ...], list[Mapping[str, object]]] = {}
    for row in passed:
        key = (
            str(row["instance_id"]),
            str(row["design_id"]),
            str(row["budget_key"]),
            str(row["warm_start_policy"]),
            str(row["pair_closure"]),
        )
        groups.setdefault(key, []).append(row)
    for key, group in groups.items():
        per_design[key] = {
            "objective": statistics.fmean(float(row["original_objective_mean"]) for row in group),
            "hit": statistics.fmean(float(row["optimum_hit_rate"]) for row in group),
            "encoded": statistics.fmean(float(row["encoded_energy_mean"]) for row in group),
            "inconsistent": statistics.fmean(
                float(row["auxiliary_inconsistency_rate"]) for row in group
            ),
            "margin": statistics.fmean(float(row["mean_abs_original_margin"]) for row in group),
        }

    summary_groups: dict[tuple[str, ...], list[Mapping[str, object]]] = {}
    for row in passed:
        key = (
            str(row["family"]),
            str(row["representation"]),
            str(row["budget_mode"]),
            str(row["budget_key"]),
            str(row["warm_start_policy"]),
            str(row["pair_closure"]),
        )
        summary_groups.setdefault(key, []).append(row)
    output: list[dict[str, object]] = []
    for key, group in sorted(summary_groups.items()):
        design_keys = sorted(
            {
                (str(row["instance_id"]), str(row["design_id"]))
                for row in group
            }
        )
        objectives: list[float] = []
        differences: list[float] = []
        hits: list[float] = []
        encoded: list[float] = []
        inconsistent: list[float] = []
        margins: list[float] = []
        weak_instances: set[str] = set()
        for instance_id, design_id in design_keys:
            current_key = (instance_id, design_id, key[3], key[4], key[5])
            cold_key = (instance_id, design_id, key[3], "cold_start", "not_applicable")
            current = per_design[current_key]
            cold = per_design[cold_key]
            objectives.append(current["objective"])
            differences.append(current["objective"] - cold["objective"])
            hits.append(current["hit"])
            encoded.append(current["encoded"])
            inconsistent.append(current["inconsistent"])
            margins.append(current["margin"])
        for row in group:
            if str(row["weak_signal_flag"]) in {"True", "true", "1"} or row[
                "weak_signal_flag"
            ] is True:
                weak_instances.add(str(row["instance_id"]))
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
                "warm_start_policy": key[4],
                "pair_closure": key[5],
                "instance_count": len({instance for instance, _ in design_keys}),
                "design_count": len(design_keys),
                "run_count": len(group),
                "original_objective_mean": objective_mean,
                "original_objective_ci95_low": objective_low,
                "original_objective_ci95_high": objective_high,
                "paired_difference_vs_cold_mean": difference_mean,
                "paired_difference_vs_cold_ci95_low": difference_low,
                "paired_difference_vs_cold_ci95_high": difference_high,
                "optimum_hit_rate_mean": hit_mean,
                "optimum_hit_rate_ci95_low": hit_low,
                "optimum_hit_rate_ci95_high": hit_high,
                "encoded_energy_mean": statistics.fmean(encoded),
                "auxiliary_inconsistency_rate_mean": statistics.fmean(inconsistent),
                "mean_abs_original_margin": statistics.fmean(margins),
                "weak_signal_instance_count": len(weak_instances),
                "status": "pass",
                "config_hash": first["config_hash"],
                "manifest_hash": first["manifest_hash"],
                "code_commit": first["code_commit"],
            }
        )
    return output


def summarise_warmstart_runs(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Summarise E4 with instances, not restarts, as uncertainty units.

    Restarts are averaged within each design.  The five matched-random designs
    are then averaged within each instance.  Confidence intervals are computed
    only after that reduction, across instance-level observations.
    """

    passed = [row for row in rows if row["status"] == "pass"]
    if len(passed) != len(rows):
        raise E4WarmStartError(
            "E4 summary refuses to silently discard non-passing raw rows"
        )

    def concrete_budget(row: Mapping[str, object]) -> int:
        mode = str(row["budget_mode"])
        if mode == "equal_layer":
            return int(row["p"])
        if mode == "equal_compiled_two_qubit_gates":
            return int(row["compiled_2q_budget"])
        raise E4WarmStartError(f"Unknown E4 budget mode: {mode}")

    def display_budget(mode: str, value: int) -> str:
        return f"p={value}" if mode == "equal_layer" else f"2Q={value}"

    design_groups: dict[tuple[object, ...], list[Mapping[str, object]]] = {}
    for row in passed:
        value = concrete_budget(row)
        key = (
            str(row["instance_id"]),
            str(row["family"]),
            str(row["representation"]),
            str(row["design_id"]),
            str(row["budget_mode"]),
            str(row["budget_key"]),
            value,
            str(row["warm_start_policy"]),
            str(row["pair_closure"]),
        )
        design_groups.setdefault(key, []).append(row)

    per_design: list[dict[str, object]] = []
    for key, group in sorted(design_groups.items()):
        first = group[0]
        per_design.append(
            {
                "instance_id": key[0],
                "family": key[1],
                "representation": key[2],
                "design_id": key[3],
                "budget_mode": key[4],
                "budget_key": key[5],
                "budget_value": key[6],
                "warm_start_policy": key[7],
                "pair_closure": key[8],
                "objective": statistics.fmean(
                    float(row["original_objective_mean"]) for row in group
                ),
                "hit": statistics.fmean(
                    float(row["optimum_hit_rate"]) for row in group
                ),
                "encoded": statistics.fmean(
                    float(row["encoded_energy_mean"]) for row in group
                ),
                "inconsistent": statistics.fmean(
                    float(row["auxiliary_inconsistency_rate"]) for row in group
                ),
                "margin": statistics.fmean(
                    float(row["mean_abs_original_margin"]) for row in group
                ),
                "weak": any(
                    row["weak_signal_flag"] is True
                    or str(row["weak_signal_flag"]).lower() in {"true", "1"}
                    for row in group
                ),
                "run_count": len(group),
                "config_hash": first["config_hash"],
                "manifest_hash": first["manifest_hash"],
                "code_commit": first["code_commit"],
            }
        )

    instance_groups: dict[
        tuple[object, ...], list[Mapping[str, object]]
    ] = {}
    for design in per_design:
        key = (
            design["instance_id"],
            design["family"],
            design["representation"],
            design["budget_mode"],
            design["budget_key"],
            design["budget_value"],
            design["warm_start_policy"],
            design["pair_closure"],
        )
        instance_groups.setdefault(key, []).append(design)

    per_instance: dict[tuple[object, ...], dict[str, object]] = {}
    for key, designs in sorted(instance_groups.items()):
        first = designs[0]
        per_instance[key] = {
            "objective": statistics.fmean(
                float(item["objective"]) for item in designs
            ),
            "hit": statistics.fmean(float(item["hit"]) for item in designs),
            "encoded": statistics.fmean(
                float(item["encoded"]) for item in designs
            ),
            "inconsistent": statistics.fmean(
                float(item["inconsistent"]) for item in designs
            ),
            "margin": statistics.fmean(
                float(item["margin"]) for item in designs
            ),
            "weak": any(bool(item["weak"]) for item in designs),
            "design_count": len(designs),
            "run_count": sum(int(item["run_count"]) for item in designs),
            "config_hash": first["config_hash"],
            "manifest_hash": first["manifest_hash"],
            "code_commit": first["code_commit"],
        }

    summary_groups: dict[
        tuple[object, ...],
        list[tuple[tuple[object, ...], Mapping[str, object]]],
    ] = {}
    for instance_key, metrics in per_instance.items():
        summary_groups.setdefault(instance_key[1:], []).append(
            (instance_key, metrics)
        )

    output: list[dict[str, object]] = []
    for key, group in sorted(summary_groups.items()):
        objectives: list[float] = []
        differences: list[float] = []
        hits: list[float] = []
        encoded: list[float] = []
        inconsistent: list[float] = []
        margins: list[float] = []
        weak_instances: set[str] = set()

        for instance_key, current in group:
            cold_key = (
                instance_key[0],
                key[0],
                key[1],
                key[2],
                key[3],
                key[4],
                "cold_start",
                "not_applicable",
            )
            if cold_key not in per_instance:
                raise E4WarmStartError(
                    f"Missing instance-level cold reference: {cold_key}"
                )
            cold = per_instance[cold_key]
            objectives.append(float(current["objective"]))
            differences.append(
                float(current["objective"]) - float(cold["objective"])
            )
            hits.append(float(current["hit"]))
            encoded.append(float(current["encoded"]))
            inconsistent.append(float(current["inconsistent"]))
            margins.append(float(current["margin"]))
            if current["weak"]:
                weak_instances.add(str(instance_key[0]))

        objective_mean, objective_low, objective_high = _uncertainty(objectives)
        difference_mean, difference_low, difference_high = _uncertainty(
            differences
        )
        hit_mean, hit_low, hit_high = _uncertainty(hits)
        first = group[0][1]
        value = int(key[4])
        output.append(
            {
                "family": key[0],
                "representation": key[1],
                "budget_mode": key[2],
                "budget_key": key[3],
                "budget_value": value,
                "budget_label": display_budget(str(key[2]), value),
                "warm_start_policy": key[5],
                "pair_closure": key[6],
                "instance_count": len(group),
                "design_count": sum(
                    int(item[1]["design_count"]) for item in group
                ),
                "run_count": sum(int(item[1]["run_count"]) for item in group),
                "ci_unit": "instance",
                "ci_method": "instance_cluster_normal_95",
                "original_objective_mean": objective_mean,
                "original_objective_ci95_low": objective_low,
                "original_objective_ci95_high": objective_high,
                "paired_difference_vs_cold_mean": difference_mean,
                "paired_difference_vs_cold_ci95_low": difference_low,
                "paired_difference_vs_cold_ci95_high": difference_high,
                "optimum_hit_rate_mean": hit_mean,
                "optimum_hit_rate_ci95_low": hit_low,
                "optimum_hit_rate_ci95_high": hit_high,
                "encoded_energy_mean": statistics.fmean(encoded),
                "auxiliary_inconsistency_rate_mean": statistics.fmean(
                    inconsistent
                ),
                "mean_abs_original_margin": statistics.fmean(margins),
                "weak_signal_instance_count": len(weak_instances),
                "status": "pass",
                "config_hash": first["config_hash"],
                "manifest_hash": first["manifest_hash"],
                "code_commit": first["code_commit"],
            }
        )
    return output


def _latex_table_legacy(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated formal E4 warm-start summary; do not edit by hand.",
        "\\begin{tabular}{lllllrrrr}",
        "\\toprule",
        "Family & Representation & Budget & Initialisation & Closure & $N$ & $\\bar f$ & $\\Delta$ cold & Opt. hit \\\\",
        "\\midrule",
    ]
    for row in rows:
        labels = [
            str(row["family"]),
            str(row["representation"]),
            str(row["budget_mode"]),
            str(row["warm_start_policy"]),
            str(row["pair_closure"]),
        ]
        labels = [label.replace("_", "\\_") for label in labels]
        lines.append(
            f"{labels[0]} & {labels[1]} & {labels[2]} & {labels[3]} & {labels[4]} & "
            f"{row['design_count']} & {float(row['original_objective_mean']):.4f} & "
            f"{float(row['paired_difference_vs_cold_mean']):.4f} & "
            f"{float(row['optimum_hit_rate_mean']):.4f} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _latex_table(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated formal E4 instance-clustered summary; do not edit by hand.",
        "\\resizebox{\\linewidth}{!}{%",
        "\\begin{tabular}{lllllrrrr}",
        "\\toprule",
        "Family & Representation & Budget & Initialisation & Closure & "
        "$N_{\\rm inst}$ & $\\bar f$ [95\\% CI] & "
        "$\\Delta$ cold [95\\% CI] & Opt. hit [95\\% CI] \\\\",
        "\\midrule",
    ]
    for row in rows:
        labels = [
            str(row["family"]),
            str(row["representation"]),
            str(row["budget_label"]),
            str(row["warm_start_policy"]),
            str(row["pair_closure"]),
        ]
        labels = [label.replace("_", "\\_") for label in labels]
        lines.append(
            f"{labels[0]} & {labels[1]} & {labels[2]} & {labels[3]} & "
            f"{labels[4]} & {row['instance_count']} & "
            f"{float(row['original_objective_mean']):.4f} "
            f"[{float(row['original_objective_ci95_low']):.4f}, "
            f"{float(row['original_objective_ci95_high']):.4f}] & "
            f"{float(row['paired_difference_vs_cold_mean']):.4f} "
            f"[{float(row['paired_difference_vs_cold_ci95_low']):.4f}, "
            f"{float(row['paired_difference_vs_cold_ci95_high']):.4f}] & "
            f"{float(row['optimum_hit_rate_mean']):.4f} "
            f"[{float(row['optimum_hit_rate_ci95_low']):.4f}, "
            f"{float(row['optimum_hit_rate_ci95_high']):.4f}] \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}%", "}", ""))
    return "\n".join(lines)


def write_marginal_figure_pdf(
    path: Path,
    rows: Sequence[Mapping[str, object]],
) -> str:
    """Write the required two-panel marginal/pair-closure diagnostic PDF."""

    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E4WarmStartError("Formal E4 PDF requires reportlab==4.4.9") from error
    if reportlab.Version != "4.4.9":
        raise E4WarmStartError(
            f"ReportLab version mismatch: expected 4.4.9, received {reportlab.Version}"
        )
    families = ("cubic_spin_glass", "max3sat")
    palette = {
        "cubic_spin_glass": colors.HexColor("#1F77B4"),
        "max3sat": colors.HexColor("#E67E22"),
    }
    singles = {
        family: sorted(
            float(row["abs_single_margin_from_half"])
            for row in rows
            if row["family"] == family and row["moment_type"] == "original_variable"
        )
        for family in families
    }
    pair_differences = {
        family: sorted(
            float(row["abs_pair_vs_independence"])
            for row in rows
            if row["family"] == family
            and row["moment_type"] == "lifted_pair"
            and int(row["active_auxiliary_design_count"]) > 0
        )
        for family in families
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    regular, bold = _register_fonts(pdfmetrics, TTFont)
    pdf.setTitle("Formal E4: warm-start marginal diagnostics")
    pdf.setAuthor("URSS formal pipeline")
    pdf.setFillColor(colors.HexColor("#17324D"))
    pdf.setFont(bold, 18)
    pdf.drawString(42, height - 44, "Formal E4: warm-start marginal diagnostics")
    pdf.setFont(regular, 8.5)
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.drawString(
        42,
        height - 60,
        "Left: empirical CDF of original marginal signal. Right: active lifted-pair departure from independence.",
    )
    panels = (
        ("Original signal |mu - 0.5|", singles, 0.5),
        ("Active pair |q - mu_i mu_j|", pair_differences, None),
    )
    left = 42
    gap = 20
    panel_width = (width - 2 * left - gap) / 2
    panel_height = height - 150
    for panel_index, (title, data, fixed_max) in enumerate(panels):
        x0 = left + panel_index * (panel_width + gap)
        y0 = 74
        pdf.setFillColor(colors.white)
        pdf.setStrokeColor(colors.HexColor("#CFD8DC"))
        pdf.roundRect(x0, y0, panel_width, panel_height, 5, fill=1, stroke=1)
        pdf.setFillColor(colors.HexColor("#17324D"))
        pdf.setFont(bold, 11)
        pdf.drawString(x0 + 14, y0 + panel_height - 22, title)
        chart_left = x0 + 48
        chart_right = x0 + panel_width - 18
        chart_bottom = y0 + 45
        chart_top = y0 + panel_height - 48
        maximum = fixed_max or max(
            (max(values) if values else 0 for values in data.values()), default=0
        )
        maximum = max(float(maximum), 1e-9)
        pdf.setStrokeColor(colors.HexColor("#90A4AE"))
        pdf.line(chart_left, chart_bottom, chart_left, chart_top)
        pdf.line(chart_left, chart_bottom, chart_right, chart_bottom)
        pdf.setFont(regular, 7)
        pdf.setFillColor(colors.HexColor("#455A64"))
        pdf.drawRightString(chart_left - 4, chart_bottom - 2, "0")
        pdf.drawRightString(chart_left - 4, chart_top - 2, "1")
        pdf.drawCentredString(chart_left, chart_bottom - 14, "0")
        pdf.drawCentredString(chart_right, chart_bottom - 14, f"{maximum:.3f}")
        for family in families:
            values = data[family]
            if not values:
                continue
            points = [(0.0, 0.0)] + [
                (value, (index + 1) / len(values))
                for index, value in enumerate(values)
            ]
            pdf.setStrokeColor(palette[family])
            pdf.setLineWidth(2)
            previous = None
            for value, fraction in points:
                x = chart_left + min(value / maximum, 1.0) * (chart_right - chart_left)
                y = chart_bottom + fraction * (chart_top - chart_bottom)
                if previous is not None:
                    pdf.line(previous[0], previous[1], x, y)
                previous = (x, y)
        legend_y = y0 + 18
        for index, family in enumerate(families):
            x = x0 + 70 + index * 145
            pdf.setFillColor(palette[family])
            pdf.rect(x, legend_y, 10, 6, fill=1, stroke=0)
            pdf.setFillColor(colors.HexColor("#263238"))
            pdf.setFont(regular, 7)
            pdf.drawString(x + 14, legend_y - 1, family.replace("_", " "))
    pdf.setFont(regular, 7)
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.drawRightString(width - 42, 28, "Generated by the frozen formal E4 pipeline")
    pdf.showPage()
    pdf.save()
    return reportlab.Version


def verify_e4_inputs(
    *,
    config_path: Path,
    config_hash_path: Path,
    data_directory: Path,
    results_directory: Path,
    tables_directory: Path,
    figures_directory: Path,
) -> dict[str, object]:
    freeze = verify_data_freeze(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["status"] != "frozen" or config["freeze_gate"]["blocked"]:
        raise E4WarmStartError("E4 requires the formal frozen configuration")
    artifacts = (
        results_directory / "e3_qaoa_runs.csv",
        results_directory / "e3_qaoa_summary.csv",
        results_directory / "e3_budget_plan.csv",
        results_directory / "e3_validation_summary.json",
        tables_directory / "table_e3_qaoa.tex",
        figures_directory / "figure_e3_equal_layer.pdf",
        figures_directory / "figure_e3_equal_2q_budget.pdf",
    )
    for artifact in artifacts:
        _verify_hash(artifact, artifact.with_suffix(".sha256"))
    summary_path = results_directory / "e3_validation_summary.json"
    summary = _load_json(summary_path)
    required = (
        summary.get("status") == "pass"
        and summary.get("e4_e6_may_continue") is True
        and int(summary.get("frozen_test_instance_count", -1)) == 14
        and int(summary.get("scheduled_design_count", -1)) == 112
        and int(summary.get("run_row_count", -1)) == 1344
        and int(summary.get("summary_row_count", -1)) == 32
        and int(summary.get("failed_run_count", -1)) == 0
        and int(summary.get("evaluation_budget_mismatch_count", -1)) == 0
        and int(summary.get("seed_policy_mismatch_count", -1)) == 0
        and int(summary.get("compiled_budget_exceed_count", -1)) == 0
        and int(summary.get("non_original_primary_score_count", -1)) == 0
    )
    if not required:
        raise E4WarmStartError("Formal E3 gate does not permit E4")
    qaoa_path = data_directory / "manifests/qaoa_v1.csv"
    qaoa_hash = _verify_hash(qaoa_path, qaoa_path.with_suffix(".sha256"))
    ground_path = data_directory / "ground_truth/ground_truth_v1.csv"
    ground_hash = _verify_hash(ground_path, ground_path.with_suffix(".sha256"))
    test_rows = [row for row in _read_csv(qaoa_path) if row["split"] == "test"]
    if len(test_rows) != 14:
        raise E4WarmStartError("Wrong frozen E4 test count")
    ground = {row["instance_id"]: row for row in _read_csv(ground_path)}
    budget_rows = _read_csv(results_directory / "e3_budget_plan.csv")
    e3_rows = _read_csv(results_directory / "e3_qaoa_runs.csv")
    relaxation = config["relaxation"]
    qaoa = config["qaoa"]
    if (
        relaxation["primary_method"] != "SA_RLT_level_2"
        or relaxation["solver"]["package"] != "scipy.optimize.linprog"
        or relaxation["solver"]["method"] != "highs"
        or relaxation["independence_closure"]["enabled_only_as_ablation"] is not True
        or qaoa["warm_start_policies"]
        != [
            "cold_start",
            "original_variables_only",
            "original_and_auxiliary_variables",
        ]
        or qaoa["warm_start"]["primary_auxiliary_marginals"]
        != "SA_RLT_level_2_pair_moments"
        or qaoa["warm_start"]["independence_closure_is_ablation_only"] is not True
        or float(qaoa["warm_start"]["clipping_delta"]) != 0.05
    ):
        raise E4WarmStartError("Frozen E4 relaxation/warm-start settings changed")
    return {
        **freeze,
        "config": config,
        "qaoa_manifest_hash": qaoa_hash,
        "ground_truth_hash": ground_hash,
        "qaoa_test_rows": sorted(test_rows, key=lambda row: row["instance_id"]),
        "ground_truth_rows": ground,
        "e3_budget_rows": budget_rows,
        "e3_run_rows": e3_rows,
        "e3_summary": summary,
        "e3_summary_hash": _sha256(summary_path),
    }


def run_e4_warmstart_pipeline(
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
    expected_active_auxiliary_design_count: int | None = 20,
) -> dict[str, object]:
    """Run formal E4 and emit all warm-start, marginal, table and figure data."""

    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    figures_directory = Path(figures_directory)
    project_root = results_directory.parent
    relative_targets = (
        Path("results/e4_warmstart_runs.csv"),
        Path("results/e4_marginal_diagnostics.csv"),
        Path("results/e4_warmstart_summary.csv"),
        Path("results/e4_validation_summary.json"),
        Path("tables/table_e4_warmstart.tex"),
        Path("figures/figure_e4_marginals.pdf"),
    )
    if any((project_root / target).exists() for target in relative_targets):
        raise FileExistsError("Formal E4 output already exists; refusing overwrite")
    staging = project_root / "e4_step6_building"
    if staging.exists():
        raise E4WarmStartError(f"Incomplete E4 staging directory exists: {staging}")
    frozen = verify_e4_inputs(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
        results_directory=results_directory,
        tables_directory=tables_directory,
        figures_directory=figures_directory,
    )
    config = frozen["config"]
    qaoa_config = config["qaoa"]
    relaxation_config = config["relaxation"]
    config_hash = str(frozen["config_hash"])
    manifest_hash = str(frozen["qaoa_manifest_hash"])
    e3_summary_hash = str(frozen["e3_summary_hash"])
    budget_index = {
        (
            row["instance_id"],
            row["representation"],
            row["random_rep_seed"],
            row["design_id"],
        ): row
        for row in frozen["e3_budget_rows"]
    }
    optimizer_seeds = [int(value) for value in qaoa_config["optimizer"]["seed_bundle"]]
    circuit_seeds = [int(value) for value in qaoa_config["circuit_seed_bundle"]]
    measurement_seeds = [int(value) for value in qaoa_config["measurement_seed_bundle"]]
    clipping_delta = float(qaoa_config["warm_start"]["clipping_delta"])
    staging.mkdir(parents=True)
    run_rows: list[dict[str, object]] = []
    marginal_rows: list[dict[str, object]] = []
    design_rows: list[dict[str, object]] = []
    relaxation_count = 0
    active_aux_design_count = 0
    try:
        for ordinal, manifest_row in enumerate(frozen["qaoa_test_rows"], start=1):
            instance_id = manifest_row["instance_id"]
            family, polynomial = _canonical_polynomial(
                data_directory / manifest_row["canonical_file"]
            )
            if family != manifest_row["family"]:
                raise E4WarmStartError(f"Family mismatch: {instance_id}")
            truth = frozen["ground_truth_rows"].get(instance_id)
            if not truth or truth["status"] != "optimal" or truth["exact_truth"] != "True":
                raise E4WarmStartError(f"E4 instance lacks exact truth: {instance_id}")
            designs = qaoa_designs(
                polynomial,
                n_original=int(manifest_row["n"]),
                instance_id=instance_id,
                config=config,
            )
            moments = solve_sa_rlt_level2(
                polynomial,
                n_original=int(manifest_row["n"]),
                method=str(relaxation_config["solver"]["method"]),
                presolve=bool(relaxation_config["solver"]["presolve"]),
            )
            relaxation_count += 1
            marginal_rows.extend(
                marginal_diagnostic_rows(
                    instance_id=instance_id,
                    family=family,
                    moments=moments,
                    designs=designs,
                    clipping_delta=clipping_delta,
                    config_hash=config_hash,
                    manifest_hash=manifest_hash,
                    code_commit=code_commit,
                    solver_package=str(relaxation_config["solver"]["package"]),
                    solver_method=str(relaxation_config["solver"]["method"]),
                )
            )
            for design in designs:
                representation = design.evaluation.representation
                random_seed = str(design.random_rep_seed or "")
                key = (
                    instance_id,
                    design.representation,
                    random_seed,
                    design.design_id,
                )
                plan = budget_index.get(key)
                if plan is None:
                    raise E4WarmStartError(f"E3 design alignment failed: {key}")
                if (
                    int(plan["n_original"]) != representation.original_width
                    or int(plan["n_aux"]) != representation.n_auxiliary
                    or int(plan["n_qubits"]) != representation.n_qubits
                ):
                    raise E4WarmStartError(f"E3 design width changed: {key}")
                gates_per_layer = int(plan["compiled_2q_gates_per_layer"])
                design_rows.append(plan)
                if representation.n_auxiliary > 0:
                    active_aux_design_count += 1
                data = statevector_data(
                    polynomial,
                    representation,
                    optimum_original=float(truth["optimum_original"]),
                )
                warm_specs = warm_start_specs(
                    design, moments, clipping_delta=clipping_delta
                )
                for budget in budget_specs(gates_per_layer, qaoa_config):
                    for warm_spec in warm_specs:
                        for restart_id in range(len(optimizer_seeds)):
                            run_rows.append(
                                optimize_warmstart_run(
                                    instance_id=instance_id,
                                    family=family,
                                    design=design,
                                    budget=budget,
                                    data=data,
                                    warm_spec=warm_spec,
                                    moments=moments,
                                    restart_id=restart_id,
                                    optimizer_seed=optimizer_seeds[restart_id],
                                    circuit_seed=circuit_seeds[restart_id],
                                    measurement_seed=measurement_seeds[restart_id],
                                    qaoa_config=qaoa_config,
                                    config_hash=config_hash,
                                    manifest_hash=manifest_hash,
                                    e3_summary_hash=e3_summary_hash,
                                    code_commit=code_commit,
                                )
                            )
            if progress:
                progress(
                    f"E4 INSTANCE {ordinal}/14: {instance_id} / moments=optimal / "
                    f"cumulative_runs={len(run_rows)}"
                )
        audit = warmstart_audit(
            run_rows,
            designs=design_rows,
            qaoa_config=qaoa_config,
            e3_rows=frozen["e3_run_rows"],
        )
        expected_marginals = sum(
            int(row["n"]) * (int(row["n"]) + 1) // 2
            for row in frozen["qaoa_test_rows"]
        )
        missing_marginals = abs(expected_marginals - len(marginal_rows))
        summary_rows = summarise_warmstart_runs(run_rows)
        output_paths = {
            "results/e4_warmstart_runs.csv": staging / "results/e4_warmstart_runs.csv",
            "results/e4_marginal_diagnostics.csv": staging
            / "results/e4_marginal_diagnostics.csv",
            "results/e4_warmstart_summary.csv": staging
            / "results/e4_warmstart_summary.csv",
            "tables/table_e4_warmstart.tex": staging
            / "tables/table_e4_warmstart.tex",
            "figures/figure_e4_marginals.pdf": staging
            / "figures/figure_e4_marginals.pdf",
        }
        _write_csv(output_paths["results/e4_warmstart_runs.csv"], run_rows, RUN_FIELDS)
        _write_csv(
            output_paths["results/e4_marginal_diagnostics.csv"],
            marginal_rows,
            MARGINAL_FIELDS,
        )
        _write_csv(
            output_paths["results/e4_warmstart_summary.csv"],
            summary_rows,
            SUMMARY_FIELDS,
        )
        output_paths["tables/table_e4_warmstart.tex"].parent.mkdir(
            parents=True, exist_ok=True
        )
        output_paths["tables/table_e4_warmstart.tex"].write_text(
            _latex_table(summary_rows), encoding="utf-8", newline="\n"
        )
        reportlab_version = write_marginal_figure_pdf(
            output_paths["figures/figure_e4_marginals.pdf"], marginal_rows
        )
        hashes = {name: _write_hash(path) for name, path in output_paths.items()}
        original_rows = [
            row for row in marginal_rows if row["moment_type"] == "original_variable"
        ]
        pair_rows = [row for row in marginal_rows if row["moment_type"] == "lifted_pair"]
        weak_instances = {
            str(row["instance_id"])
            for row in original_rows
            if row["weak_signal_flag"] is True
        }
        gate_failures = sum(audit.values()) - audit["expected_run_row_count"]
        status = (
            "pass"
            if gate_failures == 0
            and missing_marginals == 0
            and relaxation_count == 14
            and len(design_rows) == 112
            and (
                expected_active_auxiliary_design_count is None
                or active_aux_design_count
                == expected_active_auxiliary_design_count
            )
            else "fail"
        )
        validation = {
            "scope": "formal_step6_e4_warmstart_and_relaxation_ablation",
            "status": status,
            "e5_e6_may_continue": status == "pass",
            "config_hash": config_hash,
            "qaoa_manifest_hash": manifest_hash,
            "ground_truth_hash": frozen["ground_truth_hash"],
            "e3_validation_summary_hash": e3_summary_hash,
            "code_commit": code_commit,
            "frozen_test_instance_count": 14,
            "scheduled_design_count": len(design_rows),
            "active_auxiliary_design_count": active_aux_design_count,
            "expected_active_auxiliary_design_count": (
                expected_active_auxiliary_design_count
            ),
            "relaxation_optimal_instance_count": relaxation_count,
            "marginal_diagnostic_row_count": len(marginal_rows),
            "expected_marginal_diagnostic_row_count": expected_marginals,
            "missing_marginal_count": missing_marginals,
            "original_marginal_row_count": len(original_rows),
            "pair_marginal_row_count": len(pair_rows),
            "weak_signal_instance_count": len(weak_instances),
            "weak_signal_rule": "median_abs_raw_mu_minus_half_le_frozen_clipping_delta",
            "warmstart_run_row_count": len(run_rows),
            "cold_run_row_count": sum(
                row["warm_start_policy"] == "cold_start" for row in run_rows
            ),
            "original_only_run_row_count": sum(
                row["warm_start_policy"] == "original_variables_only"
                for row in run_rows
            ),
            "pair_moment_run_row_count": sum(
                row["pair_closure"] == "sa_rlt_level_2_pair_moments"
                for row in run_rows
            ),
            "independence_ablation_run_row_count": sum(
                row["pair_closure"] == "independence_mu_product_ablation"
                for row in run_rows
            ),
            "summary_row_count": len(summary_rows),
            "optimizer": "COBYLA",
            "objective_evaluations_per_restart": int(
                qaoa_config["optimizer"]["objective_evaluations"]
            ),
            "restarts_per_design_budget_variant": int(
                qaoa_config["optimizer"]["restarts"]
            ),
            "primary_score": "original_family_objective",
            "primary_relaxation": "SA_RLT_level_2_pair_moments",
            "only_relaxation_ablation": "independence_mu_product",
            "zero_auxiliary_variants_deduplicated": True,
            "reportlab_version": reportlab_version,
            **audit,
            "artifact_hashes": hashes,
        }
        validation_path = staging / "results/e4_validation_summary.json"
        _write_json(validation_path, validation)
        _write_hash(validation_path)
        if status != "pass":
            raise E4WarmStartError(f"Formal E4 gate failed; staging retained at {staging}")
        for relative in relative_targets:
            source = staging / relative
            destination = project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            source.with_suffix(".sha256").replace(destination.with_suffix(".sha256"))
        for directory in ("results", "tables", "figures"):
            (staging / directory).rmdir()
        staging.rmdir()
        if assumptions_path is not None:
            path = Path(assumptions_path)
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(
                    "\n## Formal Step 6 / E4 warm-start decisions\n\n"
                    "- The primary relaxation is the frozen SA/RLT level-2 LP with first and lifted pair moments.\n"
                    "- The only closure ablation is `q_ij = mu_i * mu_j`; no additional relaxation was compared.\n"
                    "- Zero-auxiliary designs deduplicate original-only and original-plus-auxiliary warm starts.\n"
                    "- A weak signal is reported, never excluded, when the median raw `|mu_i-0.5|` is at most the frozen clipping delta.\n"
                )
        if run_commands_path is not None:
            path = Path(run_commands_path)
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.write(
                    "\n## Formal Step 6 / E4 warm-start and relaxation ablation\n\n"
                    "```powershell\n"
                    "python .\\run_e4_warmstart.py `\n"
                    "  --config .\\configs\\experiment_config_v1.yaml `\n"
                    "  --config-hash .\\configs\\experiment_config_v1.sha256 `\n"
                    "  --data .\\data --results .\\results `\n"
                    "  --tables .\\tables --figures .\\figures `\n"
                    "  --assumptions .\\assumptions_and_decisions.md `\n"
                    "  --run-commands .\\RUN_COMMANDS.md\n"
                    "```\n"
                )
        if progress:
            progress(
                f"E4 COMPLETE: status=pass / runs={len(run_rows)} / "
                f"marginals={len(marginal_rows)} / summaries={len(summary_rows)}"
            )
        return validation
    except Exception:
        # Retain staging only if formal output construction had begun.  Input
        # verification happens before this directory is created.
        raise
