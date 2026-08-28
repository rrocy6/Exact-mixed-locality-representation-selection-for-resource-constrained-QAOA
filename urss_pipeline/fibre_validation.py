"""Formal fibre-aware selector-v2 freeze and validation pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import subprocess
import time
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from .e2_resources import _action_key, _canonical_polynomial
from .fibre_selector import (
    FibreCandidate,
    FibreMoments,
    FibreSearchResult,
    actions_payload,
    beam_select_fibre_design,
    certify_fibre_optimum_from_candidates,
    design_id,
    enumerate_expected_fibre_excess,
    enumerate_fibre_candidates,
    fibre_risk,
    greedy_select_fibre_design,
    matched_random_fibre_designs,
    solve_deterministic_sa_rlt_level2,
)
from .polynomial import Polynomial, Support, cubic_supports


class FibreValidationError(RuntimeError):
    """The fibre-aware v2 freeze or validation gate failed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hash(path: Path, sidecar: Path) -> str:
    if not path.is_file() or not sidecar.is_file():
        raise FibreValidationError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = _sha256(path)
    declared = sidecar.read_text(encoding="utf-8").strip()
    if actual != declared:
        raise FibreValidationError(f"Frozen hash mismatch: {path}")
    return actual


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
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_sidecar(path: Path) -> str:
    digest = _sha256(path)
    path.with_suffix(".sha256").write_text(digest + "\n", encoding="ascii")
    return digest


def _code_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "git_commit_unavailable"


def _validate_config(
    config: Mapping[str, object],
    *,
    config_path: Path,
    config_hash_path: Path,
) -> dict[str, object]:
    config_hash = _verify_hash(config_path, config_hash_path)
    if config.get("config_id") != "experiment_config_v2":
        raise FibreValidationError("Expected experiment_config_v2")
    if config.get("status") != "frozen":
        raise FibreValidationError("Fibre selector v2 requires frozen status")
    parent = config.get("parent_config")
    if not isinstance(parent, dict):
        raise FibreValidationError("Missing v1 parent-config provenance")
    repository_root = config_path.resolve().parent.parent
    parent_path = repository_root / str(parent.get("path", ""))
    if not parent_path.is_file() or _sha256(parent_path) != parent.get("sha256"):
        raise FibreValidationError("Frozen v1 parent config changed")
    freeze = config.get("freeze_gate")
    if not isinstance(freeze, dict) or freeze.get("completed") is not True:
        raise FibreValidationError("V2 freeze gate is not complete")
    if freeze.get("blocked") is not False:
        raise FibreValidationError("V2 freeze gate remains blocked")
    relaxation = config.get("relaxation")
    if not isinstance(relaxation, dict):
        raise FibreValidationError("Missing frozen relaxation settings")
    if relaxation.get("primary_method") != "SA_RLT_level_2":
        raise FibreValidationError("V2 must freeze SA/RLT level-2")
    if relaxation.get("returns") != ["single_moments_mu", "pair_moments_q"]:
        raise FibreValidationError("V2 moment sources are not frozen")
    tie_break = relaxation.get("optimum_face_tie_break")
    if not isinstance(tie_break, dict) or tie_break.get("enabled") is not True:
        raise FibreValidationError("Deterministic relaxation tie-break is missing")
    selector = config.get("selector")
    if not isinstance(selector, dict):
        raise FibreValidationError("Missing selector v2 settings")
    if selector.get("tune_on") != ["train", "validation"]:
        raise FibreValidationError("Selector calibration splits are not frozen")
    if selector.get("retune_on_test") is not False:
        raise FibreValidationError("Test retuning must remain disabled")
    fibre = selector.get("fibre_risk")
    if not isinstance(fibre, dict) or fibre.get("enabled") is not True:
        raise FibreValidationError("Fibre-risk guardrail is not enabled")
    if fibre.get("include_as_pareto_coordinate") is not True:
        raise FibreValidationError("Fibre risk is absent from the Pareto vector")
    tau = float(fibre.get("threshold_tau", math.nan))
    if not math.isfinite(tau) or tau <= 0:
        raise FibreValidationError("tau_fib must be finite and positive")
    weights = selector.get("weights")
    if not isinstance(weights, dict) or any(float(value) <= 0 for value in weights.values()):
        raise FibreValidationError("Every frozen selector weight must be positive")
    if not math.isclose(
        float(weights["two_qubit_gate_count"]),
        float(weights["two_qubit_depth"]),
    ):
        raise FibreValidationError("Gate and depth weights must be symmetric")
    search = selector.get("search_settings")
    if not isinstance(search, dict):
        raise FibreValidationError("Missing frozen search settings")
    required = (
        "action_order",
        "beam_width",
        "beam_allocation",
        "final_tie_break",
        "no_feasible_design_fallback",
        "certification",
    )
    if any(key not in search for key in required):
        raise FibreValidationError("Incomplete beam/certification freeze")
    provenance = config.get("fibre_selector_freeze_provenance")
    if not isinstance(provenance, dict):
        raise FibreValidationError("Missing fibre-selector freeze provenance")
    if provenance.get("test_data_used_for_weight_or_threshold_selection") is not False:
        raise FibreValidationError("V2 provenance does not exclude test calibration")
    return {
        "config_hash": config_hash,
        "selector": selector,
        "relaxation": relaxation,
        "provenance": provenance,
    }


def _load_instance(
    row: Mapping[str, str], data_directory: Path
) -> tuple[str, Polynomial]:
    canonical_path = data_directory / row["canonical_file"]
    if _sha256(canonical_path) != row["canonical_sha256"]:
        raise FibreValidationError(
            f"Canonical hash mismatch: {row['instance_id']}"
        )
    family, polynomial = _canonical_polynomial(canonical_path)
    if family != row["family"]:
        raise FibreValidationError(f"Family mismatch: {row['instance_id']}")
    return family, polynomial


def _solve_moments(
    polynomial: Polynomial,
    *,
    n_original: int,
    relaxation: Mapping[str, object],
) -> FibreMoments:
    solver = relaxation["solver"]  # type: ignore[assignment]
    tie_break = relaxation["optimum_face_tie_break"]  # type: ignore[assignment]
    return solve_deterministic_sa_rlt_level2(
        polynomial,
        n_original=n_original,
        method=str(solver["method"]),  # type: ignore[index]
        presolve=bool(solver["presolve"]),  # type: ignore[index]
        primary_optimum_tolerance=float(
            tie_break["primary_optimum_tolerance"]  # type: ignore[index]
        ),
    )


def _risk_payload(risk: object) -> dict[str, object]:
    data = asdict(risk)  # type: ignore[arg-type]
    data["contributions"] = [
        {
            **item,
            "pair": list(item["pair"]),
        }
        for item in data["contributions"]
    ]
    return data


def _representation_class(actions: Sequence[Support | None]) -> str:
    if all(action is None for action in actions):
        return "all_native"
    if all(action is not None for action in actions):
        return "fully_reduced"
    return "mixed_selective"


def _result_payload(result: FibreSearchResult) -> dict[str, object]:
    evaluation = result.evaluation
    maximum_penalty = max(evaluation.representation.penalties.values(), default=0)
    return {
        "design_id": design_id(result.actions),
        "representation_class": _representation_class(result.actions),
        "actions": actions_payload(result.actions),
        "n_auxiliary": evaluation.representation.n_auxiliary,
        "n_qubits": evaluation.representation.n_qubits,
        "two_qubit_gate_count": evaluation.reference.two_qubit_gate_count,
        "two_qubit_depth": evaluation.reference.two_qubit_depth,
        "maximum_penalty": float(maximum_penalty),
        "resource_score": float(evaluation.score),
        "resource_score_exact": f"{evaluation.score.numerator}/{evaluation.score.denominator}",
        "resource_vector": [float(value) for value in evaluation.vector],
        "fibre_risk": _risk_payload(result.risk),
        "status": result.status,
        "candidate_evaluations": result.candidate_evaluations,
        "runtime_sec": result.runtime_sec,
        "certified_optimum_score": (
            float(result.certified_optimum_score)
            if result.certified_optimum_score is not None
            else None
        ),
        "regret": float(result.regret) if result.regret is not None else None,
    }


def _candidate_key(
    candidate: FibreCandidate, cubics: Sequence[Support]
) -> tuple[Fraction, float, tuple[int, ...]]:
    return (
        candidate.score,
        candidate.risk.normalised_excess,
        _action_key(cubics, candidate.actions),
    )


def _unguarded_winner(
    candidates: Sequence[FibreCandidate], cubics: Sequence[Support]
) -> FibreCandidate:
    feasible = [candidate for candidate in candidates if candidate.resources.feasible]
    if not feasible:
        raise FibreValidationError("No resource-feasible unguarded oracle design")
    return min(feasible, key=lambda item: _candidate_key(item, cubics))


def _calibration_observation(
    records: Sequence[Mapping[str, object]], split: str
) -> dict[str, object]:
    selected = [record for record in records if record["split"] == split]
    counts = {"all_native": 0, "mixed_selective": 0, "fully_reduced": 0}
    for record in selected:
        counts[str(record["representation_class"])] += 1
    return {
        "instance_count": len(selected),
        "selected_native_count": counts["all_native"],
        "selected_mixed_count": counts["mixed_selective"],
        "selected_full_count": counts["fully_reduced"],
        "guardrail_changed_design_count": sum(
            1 for record in selected if record["guardrail_changed_design"] is True
        ),
        "maximum_resource_score_degradation": max(
            (float(record["resource_score_degradation"]) for record in selected),
            default=0.0,
        ),
    }


def _verify_calibration(
    observed: Mapping[str, Mapping[str, object]],
    provenance: Mapping[str, object],
) -> dict[str, object]:
    gates = provenance["calibration_gates"]  # type: ignore[assignment]
    failures: list[str] = []
    for split in ("train", "validation"):
        declared = provenance[f"observed_{split}"]  # type: ignore[index]
        actual = observed[split]
        for key in (
            "instance_count",
            "selected_native_count",
            "selected_mixed_count",
            "selected_full_count",
            "guardrail_changed_design_count",
        ):
            if int(actual[key]) != int(declared[key]):  # type: ignore[index]
                failures.append(f"{split}.{key}")
        if not math.isclose(
            float(actual["maximum_resource_score_degradation"]),
            float(declared["maximum_resource_score_degradation"]),  # type: ignore[index]
            abs_tol=5e-5,
        ):
            failures.append(f"{split}.maximum_resource_score_degradation")
    validation = observed["validation"]
    count = int(validation["instance_count"])
    nonnative = (
        int(validation["selected_mixed_count"])
        + int(validation["selected_full_count"])
    ) / count
    mixed = int(validation["selected_mixed_count"]) / count
    if nonnative < float(gates["validation_nonnative_fraction_minimum"]):  # type: ignore[index]
        failures.append("validation.nonnative_fraction_minimum")
    if nonnative > float(gates["validation_nonnative_fraction_maximum"]):  # type: ignore[index]
        failures.append("validation.nonnative_fraction_maximum")
    if mixed < float(gates["validation_mixed_fraction_minimum"]):  # type: ignore[index]
        failures.append("validation.mixed_fraction_minimum")
    if int(validation["guardrail_changed_design_count"]) < 1:
        failures.append("validation.guardrail_changed_design_count")
    if float(validation["maximum_resource_score_degradation"]) > float(
        gates["validation_max_resource_score_degradation"]  # type: ignore[index]
    ):
        failures.append("validation.maximum_resource_score_degradation")
    if failures:
        raise FibreValidationError(
            "Frozen calibration reproduction failed: " + ", ".join(failures)
        )
    return {
        "status": "pass",
        "observed": observed,
        "validation_nonnative_fraction": nonnative,
        "validation_mixed_fraction": mixed,
        "failed_gates": [],
    }


def _validation_rows(
    row: Mapping[str, str],
    *,
    certified: FibreSearchResult,
    beam: FibreSearchResult,
    greedy: FibreSearchResult,
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
    tau: float,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for method, result, certificate in (
        ("full_space_optimum", certified, "certified_complete_fibre_aware_optimum"),
        ("pareto_beam", beam, "beam_incumbent_not_certified"),
        ("greedy_native_completion", greedy, "heuristic_result_not_certified"),
    ):
        regret = result.regret if result.regret is not None else Fraction(0)
        output.append(
            {
                "instance_id": row["instance_id"],
                "family": row["family"],
                "split": row["split"],
                "method": method,
                "certificate_status": certificate,
                "selected_design_id": design_id(result.actions),
                "selected_n_aux": result.evaluation.representation.n_auxiliary,
                "selected_two_qubit_gates": result.evaluation.reference.two_qubit_gate_count,
                "selected_two_qubit_depth": result.evaluation.reference.two_qubit_depth,
                "objective": float(result.evaluation.score),
                "fibre_excess": result.risk.excess,
                "normalised_fibre_excess": result.risk.normalised_excess,
                "fibre_feasible": result.risk.normalised_excess <= tau + 1e-9,
                "certified_optimum_objective": float(certified.evaluation.score),
                "regret": float(regret),
                "hit_certified_design": result.actions == certified.actions,
                "runtime_sec": result.runtime_sec,
                "candidate_evaluations": result.candidate_evaluations,
                "weights_tuned_on": "train+validation_structural_only",
                "test_retuning_used": False,
                "status": "pass",
                "config_hash": config_hash,
                "manifest_hash": manifest_hash,
                "code_commit": code_commit,
            }
        )
    return output


def _matched_payloads(
    polynomial: Polynomial,
    *,
    n_original: int,
    selected: FibreSearchResult,
    moments: FibreMoments,
    instance_id: str,
    seeds: Sequence[int],
    positive_margin: float,
    tau: float,
    maximum_pair_set_attempts: int,
) -> list[dict[str, object]]:
    target = selected.evaluation.representation.n_auxiliary
    outputs: list[dict[str, object]] = []
    for seed, actions in matched_random_fibre_designs(
        polynomial,
        selected_actions=selected.actions,
        instance_id=instance_id,
        seed_bundle=seeds,
        maximum_pair_set_attempts=maximum_pair_set_attempts,
    ):
        active = len({action for action in actions if action is not None})
        if active != target:
            raise FibreValidationError(
                f"Matched-random auxiliary count mismatch: {instance_id}"
            )
        risk = fibre_risk(
            polynomial,
            n_original=n_original,
            actions=actions,
            moments=moments,
            positive_margin=positive_margin,
        )
        outputs.append(
            {
                "random_rep_seed": seed,
                "design_id": design_id(actions),
                "actions": actions_payload(actions),
                "n_auxiliary": active,
                "matches_selected_auxiliary_count": True,
                "distinct_from_selected": tuple(actions) != selected.actions,
                "normalised_fibre_excess": risk.normalised_excess,
                "within_selector_tau": risk.normalised_excess <= tau + 1e-9,
            }
        )
    return outputs


def _moment_record(
    row: Mapping[str, str], moments: FibreMoments
) -> dict[str, object]:
    return {
        "instance_id": row["instance_id"],
        "family": row["family"],
        "tier": row["tier"],
        "split": row["split"],
        "n_original": int(row["n"]),
        "objective": moments.objective,
        "status": moments.status,
        "moment_sha256": moments.moment_sha256,
        "singles": {str(key): value for key, value in sorted(moments.singles.items())},
        "pairs": {
            f"{pair[0]},{pair[1]}": value
            for pair, value in sorted(moments.pairs.items())
        },
        "primary_runtime_sec": moments.primary_runtime_sec,
        "secondary_runtime_sec": moments.secondary_runtime_sec,
    }


def run_fibre_selector_v2_pipeline(
    *,
    config_path: Path,
    config_hash_path: Path,
    data_directory: Path,
    output_directory: Path,
) -> dict[str, object]:
    """Freeze and validate fibre-aware v2 designs without overwriting v1."""

    started = time.perf_counter()
    if output_directory.exists():
        raise FibreValidationError(f"Output already exists: {output_directory}")
    staging = output_directory.with_name(output_directory.name + "_building")
    if staging.exists():
        raise FibreValidationError(f"Incomplete v2 staging directory exists: {staging}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    frozen = _validate_config(
        config,
        config_path=config_path,
        config_hash_path=config_hash_path,
    )
    config_hash = str(frozen["config_hash"])
    selector = frozen["selector"]  # type: ignore[assignment]
    relaxation = frozen["relaxation"]  # type: ignore[assignment]
    provenance = frozen["provenance"]  # type: ignore[assignment]
    tau = float(selector["fibre_risk"]["threshold_tau"])  # type: ignore[index]
    margin = float(selector["fibre_risk"]["positive_penalty_margin"])  # type: ignore[index]
    random_seeds = [int(seed) for seed in config["representations"]["matched_random"]["seed_bundle"]]  # type: ignore[index]
    matched_attempts = int(
        config["representations"]["matched_random"]["maximum_pair_set_attempts"]  # type: ignore[index]
    )
    code_commit = _code_commit()
    staging.mkdir(parents=True)
    produced: list[Path] = []
    moment_records: list[dict[str, object]] = []
    design_manifests: dict[str, list[dict[str, object]]] = {
        "oracle": [],
        "qaoa": [],
        "compilation": [],
    }
    validation_rows: list[dict[str, object]] = []
    formula_rows: list[dict[str, object]] = []
    calibration_records: list[dict[str, object]] = []
    manifest_hashes: dict[str, str] = {}

    try:
        snapshot = staging / "experiment_config_v2.yaml"
        shutil.copy2(config_path, snapshot)
        produced.append(snapshot)

        oracle_path = data_directory / "manifests" / "oracle_v1.csv"
        oracle_hash = _verify_hash(
            oracle_path, data_directory / "manifests" / "oracle_v1.sha256"
        )
        if oracle_hash != provenance["calibration_manifest_sha256"]:
            raise FibreValidationError("Oracle calibration manifest hash changed")
        manifest_hashes["oracle"] = oracle_hash
        oracle_rows = _read_csv(oracle_path)
        if len(oracle_rows) != 60:
            raise FibreValidationError("Oracle manifest must contain 60 instances")
        calibration_rows = [
            row for row in oracle_rows if row["split"] in ("train", "validation")
        ]
        held_out_rows = [row for row in oracle_rows if row["split"] == "test"]
        if len(calibration_rows) != 48 or len(held_out_rows) != 12:
            raise FibreValidationError("Oracle calibration/test split counts changed")

        oracle_cache: dict[str, tuple[Polynomial, FibreMoments, FibreSearchResult]] = {}
        for ordinal, row in enumerate(
            sorted(calibration_rows, key=lambda item: item["instance_id"]), start=1
        ):
            _, polynomial = _load_instance(row, data_directory)
            n_original = int(row["n"])
            moments = _solve_moments(
                polynomial, n_original=n_original, relaxation=relaxation
            )
            enumerated_at = time.perf_counter()
            candidates = enumerate_fibre_candidates(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
            )
            certified = certify_fibre_optimum_from_candidates(
                polynomial,
                n_original=n_original,
                selector=selector,
                candidates=candidates,
                apply_qaoa_hard_limits=True,
                runtime_sec=time.perf_counter() - enumerated_at,
            )
            cubics = tuple(sorted(cubic_supports(polynomial)))
            unguarded = _unguarded_winner(candidates, cubics)
            degradation = certified.evaluation.score - unguarded.score
            if degradation < 0:
                raise FibreValidationError("Fibre guardrail improved below unguarded optimum")
            calibration_records.append(
                {
                    "instance_id": row["instance_id"],
                    "family": row["family"],
                    "split": row["split"],
                    "representation_class": _representation_class(certified.actions),
                    "selected_design_id": design_id(certified.actions),
                    "unguarded_design_id": design_id(unguarded.actions),
                    "guardrail_changed_design": certified.actions != unguarded.actions,
                    "selected_normalised_fibre_excess": certified.risk.normalised_excess,
                    "unguarded_normalised_fibre_excess": unguarded.risk.normalised_excess,
                    "resource_score_degradation": float(degradation),
                    "candidate_count": len(candidates),
                    "moment_sha256": moments.moment_sha256,
                }
            )
            beam = beam_select_fibre_design(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
                certified=certified,
            )
            greedy = greedy_select_fibre_design(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
                certified=certified,
            )
            validation_rows.extend(
                _validation_rows(
                    row,
                    certified=certified,
                    beam=beam,
                    greedy=greedy,
                    config_hash=config_hash,
                    manifest_hash=oracle_hash,
                    code_commit=code_commit,
                    tau=tau,
                )
            )
            direct = enumerate_expected_fibre_excess(
                polynomial,
                n_original=n_original,
                actions=certified.actions,
                moments=moments,
                positive_margin=margin,
            )
            error = abs(direct - certified.risk.excess)
            formula_rows.append(
                {
                    "instance_id": row["instance_id"],
                    "split": row["split"],
                    "closed_form_excess": certified.risk.excess,
                    "direct_enumeration_excess": direct,
                    "absolute_error": error,
                    "status": "pass" if error <= 1e-9 else "fail",
                }
            )
            moment_records.append(_moment_record(row, moments))
            oracle_cache[row["instance_id"]] = (polynomial, moments, certified)
            print(
                f"calibration_oracle={ordinal}/48 instance={row['instance_id']} status=pass",
                flush=True,
            )

        observed = {
            split: _calibration_observation(calibration_records, split)
            for split in ("train", "validation")
        }
        calibration_report = _verify_calibration(observed, provenance)
        calibration_report.update(
            {
                "config_hash_frozen_before_test_read": config_hash,
                "test_instance_files_read_during_calibration": 0,
                "calibration_instance_count": 48,
            }
        )
        print("calibration_gate=pass test_files_read=0", flush=True)

        # The held-out files are opened only after the frozen calibration gate.
        for ordinal, row in enumerate(
            sorted(held_out_rows, key=lambda item: item["instance_id"]), start=1
        ):
            _, polynomial = _load_instance(row, data_directory)
            n_original = int(row["n"])
            moments = _solve_moments(
                polynomial, n_original=n_original, relaxation=relaxation
            )
            enumerated_at = time.perf_counter()
            candidates = enumerate_fibre_candidates(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
            )
            certified = certify_fibre_optimum_from_candidates(
                polynomial,
                n_original=n_original,
                selector=selector,
                candidates=candidates,
                apply_qaoa_hard_limits=True,
                runtime_sec=time.perf_counter() - enumerated_at,
            )
            beam = beam_select_fibre_design(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
                certified=certified,
            )
            greedy = greedy_select_fibre_design(
                polynomial,
                n_original=n_original,
                selector=selector,
                moments=moments,
                apply_qaoa_hard_limits=True,
                certified=certified,
            )
            validation_rows.extend(
                _validation_rows(
                    row,
                    certified=certified,
                    beam=beam,
                    greedy=greedy,
                    config_hash=config_hash,
                    manifest_hash=oracle_hash,
                    code_commit=code_commit,
                    tau=tau,
                )
            )
            direct = enumerate_expected_fibre_excess(
                polynomial,
                n_original=n_original,
                actions=certified.actions,
                moments=moments,
                positive_margin=margin,
            )
            error = abs(direct - certified.risk.excess)
            formula_rows.append(
                {
                    "instance_id": row["instance_id"],
                    "split": row["split"],
                    "closed_form_excess": certified.risk.excess,
                    "direct_enumeration_excess": direct,
                    "absolute_error": error,
                    "status": "pass" if error <= 1e-9 else "fail",
                }
            )
            moment_records.append(_moment_record(row, moments))
            oracle_cache[row["instance_id"]] = (polynomial, moments, certified)
            print(
                f"heldout_oracle={ordinal}/12 instance={row['instance_id']} status=pass",
                flush=True,
            )

        for row in sorted(oracle_rows, key=lambda item: item["instance_id"]):
            polynomial, moments, selected = oracle_cache[row["instance_id"]]
            design_manifests["oracle"].append(
                {
                    "instance_id": row["instance_id"],
                    "family": row["family"],
                    "tier": "oracle",
                    "split": row["split"],
                    "n_original": int(row["n"]),
                    "canonical_sha256": row["canonical_sha256"],
                    "moment_sha256": moments.moment_sha256,
                    "cubic_supports": [list(item) for item in sorted(cubic_supports(polynomial))],
                    "selected": _result_payload(selected),
                    "matched_random": _matched_payloads(
                        polynomial,
                        n_original=int(row["n"]),
                        selected=selected,
                        moments=moments,
                        instance_id=row["instance_id"],
                        seeds=random_seeds,
                        positive_margin=margin,
                        tau=tau,
                        maximum_pair_set_attempts=matched_attempts,
                    ),
                }
            )

        for tier in ("qaoa", "compilation"):
            manifest_path = data_directory / "manifests" / f"{tier}_v1.csv"
            manifest_hash = _verify_hash(
                manifest_path,
                data_directory / "manifests" / f"{tier}_v1.sha256",
            )
            manifest_hashes[tier] = manifest_hash
            rows = _read_csv(manifest_path)
            expected_count = 72 if tier == "qaoa" else 180
            if len(rows) != expected_count:
                raise FibreValidationError(
                    f"{tier} manifest has {len(rows)} rows, expected {expected_count}"
                )
            for ordinal, row in enumerate(
                sorted(rows, key=lambda item: item["instance_id"]), start=1
            ):
                _, polynomial = _load_instance(row, data_directory)
                n_original = int(row["n"])
                moments = _solve_moments(
                    polynomial, n_original=n_original, relaxation=relaxation
                )
                selected = beam_select_fibre_design(
                    polynomial,
                    n_original=n_original,
                    selector=selector,
                    moments=moments,
                    apply_qaoa_hard_limits=tier == "qaoa",
                )
                if selected.risk.normalised_excess > tau + 1e-9:
                    raise FibreValidationError(
                        f"Selected {tier} design violates tau: {row['instance_id']}"
                    )
                moment_records.append(_moment_record(row, moments))
                design_manifests[tier].append(
                    {
                        "instance_id": row["instance_id"],
                        "family": row["family"],
                        "tier": tier,
                        "split": row["split"],
                        "n_original": n_original,
                        "canonical_sha256": row["canonical_sha256"],
                        "moment_sha256": moments.moment_sha256,
                        "cubic_supports": [list(item) for item in sorted(cubic_supports(polynomial))],
                        "selected": _result_payload(selected),
                        "matched_random": _matched_payloads(
                            polynomial,
                            n_original=n_original,
                            selected=selected,
                            moments=moments,
                            instance_id=row["instance_id"],
                            seeds=random_seeds,
                            positive_margin=margin,
                            tau=tau,
                            maximum_pair_set_attempts=matched_attempts,
                        ),
                    }
                )
                print(
                    f"{tier}_design={ordinal}/{expected_count} instance={row['instance_id']} status=pass",
                    flush=True,
                )

        if len(validation_rows) != 180:
            raise FibreValidationError("Oracle selector validation must contain 180 rows")
        if any(float(row["regret"]) < -1e-12 for row in validation_rows):
            raise FibreValidationError("Negative oracle selector regret detected")
        if any(row["status"] != "pass" for row in formula_rows):
            raise FibreValidationError("Closed-form fibre validation failed")

        calibration_csv = staging / "fibre_calibration_instances_v2.csv"
        _write_csv(
            calibration_csv,
            calibration_records,
            (
                "instance_id",
                "family",
                "split",
                "representation_class",
                "selected_design_id",
                "unguarded_design_id",
                "guardrail_changed_design",
                "selected_normalised_fibre_excess",
                "unguarded_normalised_fibre_excess",
                "resource_score_degradation",
                "candidate_count",
                "moment_sha256",
            ),
        )
        produced.append(calibration_csv)
        calibration_json = staging / "fibre_calibration_validation_v2.json"
        _write_json(calibration_json, calibration_report)
        produced.append(calibration_json)

        formula_path = staging / "fibre_formula_validation_v2.csv"
        _write_csv(
            formula_path,
            formula_rows,
            (
                "instance_id",
                "split",
                "closed_form_excess",
                "direct_enumeration_excess",
                "absolute_error",
                "status",
            ),
        )
        produced.append(formula_path)

        validation_path = staging / "oracle_selector_validation_v2.csv"
        _write_csv(
            validation_path,
            validation_rows,
            tuple(validation_rows[0]),
        )
        produced.append(validation_path)

        moments_path = staging / "sa_rlt_moments_v2.json"
        _write_json(
            moments_path,
            {
                "schema_version": "sa_rlt_moments_v2",
                "config_hash": config_hash,
                "records": sorted(moment_records, key=lambda item: (item["tier"], item["instance_id"])),
            },
        )
        produced.append(moments_path)

        for tier, records in design_manifests.items():
            path = staging / f"{tier}_representation_designs_v2.json"
            _write_json(
                path,
                {
                    "schema_version": "fibre_aware_representation_designs_v2",
                    "tier": tier,
                    "config_hash": config_hash,
                    "source_instance_manifest_hash": manifest_hashes[tier],
                    "selected_method": (
                        "certified_complete_fibre_aware_optimum"
                        if tier == "oracle"
                        else "fibre_aware_pareto_beam"
                    ),
                    "native_and_full_protocols_reused_from_v1": True,
                    "records": records,
                },
            )
            produced.append(path)

        audit = {
            "schema_version": "fibre_selector_v2_audit",
            "status": "pass",
            "config_hash": config_hash,
            "source_manifest_hashes": manifest_hashes,
            "calibration_status": "pass",
            "test_instance_files_read_during_calibration": 0,
            "closed_form_enumeration_check_count": len(formula_rows),
            "closed_form_enumeration_failure_count": 0,
            "oracle_validation_row_count": len(validation_rows),
            "oracle_negative_regret_count": 0,
            "oracle_beam_hit_count": sum(
                1
                for row in validation_rows
                if row["method"] == "pareto_beam" and row["hit_certified_design"] is True
            ),
            "oracle_greedy_hit_count": sum(
                1
                for row in validation_rows
                if row["method"] == "greedy_native_completion"
                and row["hit_certified_design"] is True
            ),
            "representation_design_counts": {
                tier: len(records) for tier, records in design_manifests.items()
            },
            "matched_random_rows_per_instance": len(random_seeds),
            "raw_canonical_ground_truth_rebuilt": False,
            "native_full_protocols_changed": False,
            "selected_matched_random_require_e1_e6_rerun": True,
            "e1_e6_rerun_completed": False,
            "code_commit": code_commit,
            "runtime_sec": time.perf_counter() - started,
        }
        audit_path = staging / "fibre_selector_v2_audit.json"
        _write_json(audit_path, audit)
        produced.append(audit_path)

        manifest_rows: list[dict[str, object]] = []
        for path in produced:
            relative = path.relative_to(staging).as_posix()
            digest = _write_sidecar(path)
            manifest_rows.append(
                {"path": relative, "sha256": digest, "size_bytes": path.stat().st_size}
            )
        package_manifest = staging / "PACKAGE_SHA256_MANIFEST.csv"
        _write_csv(package_manifest, manifest_rows, ("path", "sha256", "size_bytes"))
        _write_sidecar(package_manifest)
        shutil.move(str(staging), str(output_directory))
        print("FIBRE SELECTOR V2 GATE: pass", flush=True)
        return audit
    except Exception:
        # Preserve the staging tree as forensic evidence; the apply guide gives
        # an explicit recoverable move command before a rerun.
        raise
