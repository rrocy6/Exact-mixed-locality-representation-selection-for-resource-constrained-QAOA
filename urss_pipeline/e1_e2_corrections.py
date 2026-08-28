"""Post-review corrections for formal E1 and E2.

The correction pipeline is intentionally additive.  It verifies the frozen
inputs and the original E1/E2 artifacts, writes a separate correction bundle,
and never overwrites the already reported formal results.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import statistics
from collections import defaultdict
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from .e1_exactness import (
    E1ExactnessError,
    MixedRepresentation,
    action_options,
    build_mixed_representation,
    evaluate_pointwise,
    full_action_vector,
    verify_data_freeze,
)
from .polynomial import Polynomial, Support, canonicalize, cubic_supports


class E1E2CorrectionError(RuntimeError):
    """A review correction could not be produced without violating a gate."""


E1_SUPPLEMENT_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "random_rep_seed",
    "design_id",
    "n_original",
    "n_aux",
    "retained_cubic",
    "active_pair_count",
    "penalty_setting",
    "target_pair",
    "x_assignments_checked",
    "xy_assignments_checked",
    "max_pointwise_error",
    "mismatch_count",
    "tie_count",
    "inconsistent_minimiser_count",
    "witness_id",
    "constructible",
    "constructibility_reason",
    "status",
    "config_hash",
    "manifest_hash",
    "code_commit",
)

E2_INSTANCE_FIELDS = (
    "instance_id",
    "family",
    "representation",
    "common_feasible_cohort_id",
    "transpiler_seed_count",
    "two_qubit_gates_mean",
    "two_qubit_depth_mean",
    "swap_count_mean",
    "routing_overhead_mean",
    "compile_runtime_sec_mean",
    "config_hash",
    "manifest_hash",
    "code_commit",
)

E2_PAIRED_SUMMARY_FIELDS = (
    "family",
    "representation",
    "common_feasible_cohort_id",
    "common_instance_count",
    "two_qubit_gates_mean",
    "two_qubit_gates_ci95_low",
    "two_qubit_gates_ci95_high",
    "two_qubit_gates_paired_delta_vs_native_mean",
    "two_qubit_depth_mean",
    "two_qubit_depth_ci95_low",
    "two_qubit_depth_ci95_high",
    "two_qubit_depth_paired_delta_vs_native_mean",
    "swap_count_mean",
    "swap_count_ci95_low",
    "swap_count_ci95_high",
    "swap_count_paired_delta_vs_native_mean",
    "config_hash",
    "manifest_hash",
    "code_commit",
)

E2_CAPACITY_FIELDS = (
    "family",
    "representation",
    "topology_id",
    "scheduled_row_count",
    "success_row_count",
    "infeasible_width_row_count",
    "other_failure_row_count",
    "success_rate",
    "infeasible_width_rate",
    "scheduled_design_count",
    "successful_design_count",
    "scheduled_instance_count",
    "successful_instance_count",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hash(path: Path, sidecar: Path | None = None) -> str:
    sidecar = sidecar or path.with_suffix(".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise E1E2CorrectionError(f"Missing file/hash: {path} / {sidecar}")
    actual = _sha256(path)
    declared = sidecar.read_text(encoding="utf-8").strip()
    if actual != declared:
        raise E1E2CorrectionError(f"Hash mismatch: {path}")
    return actual


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E1E2CorrectionError(f"Expected JSON object: {path}")
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


def _write_sidecar(path: Path) -> str:
    digest = _sha256(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def _canonical_polynomial(path: Path) -> tuple[str, Polynomial]:
    payload = _load_json(path)
    terms = payload.get("terms")
    if not isinstance(terms, list):
        raise E1E2CorrectionError(f"Malformed canonical instance: {path}")
    polynomial = canonicalize(
        (tuple(item["support"]), item["coefficient"])  # type: ignore[index]
        for item in terms
    )
    return str(payload["family"]), polynomial


def _action_payload(actions: Sequence[Support | None]) -> list[list[int] | None]:
    return [list(action) if action is not None else None for action in actions]


def _design_id(actions: Sequence[Support | None]) -> str:
    encoded = json.dumps(_action_payload(actions), separators=(",", ":"))
    return "design_" + hashlib.sha256(encoded.encode("ascii")).hexdigest()[:16]


def _retained_cubic(representation: MixedRepresentation) -> int:
    return len(cubic_supports(representation.polynomial))


def deterministic_nontrivial_actions(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    positive_margin: object,
) -> tuple[tuple[Support | None, ...] | None, str]:
    """Choose the first one-reduction design that remains genuinely mixed."""

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    if len(cubics) < 2:
        return None, "fewer_than_two_cubic_terms"
    for cubic_index, cubic in enumerate(cubics):
        for pair in action_options(cubic)[1:]:
            actions: list[Support | None] = [None] * len(cubics)
            actions[cubic_index] = pair
            representation = build_mixed_representation(
                polynomial,
                n_original=n_original,
                actions=actions,
                default_margin=positive_margin,
            )
            if representation.n_auxiliary > 0 and _retained_cubic(representation) > 0:
                return tuple(actions), "deterministic_first_single_reduction"
    return None, "no_design_with_auxiliary_and_retained_cubic"


def _candidate_vectors(cubics: Sequence[Support]) -> Iterable[tuple[Support | None, ...]]:
    return product(*(action_options(cubic) for cubic in cubics))


def matched_nontrivial_actions(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selected_actions: Sequence[Support | None],
    instance_id: str,
    seed_bundle: Sequence[int],
    positive_margin: object,
) -> list[tuple[int, tuple[Support | None, ...], bool]]:
    """Sample aux-count-matched designs while keeping the representation mixed."""

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    selected = tuple(selected_actions)
    target = build_mixed_representation(
        polynomial,
        n_original=n_original,
        actions=selected,
        default_margin=positive_margin,
    ).n_auxiliary
    eligible: list[tuple[Support | None, ...]] = []
    for actions in _candidate_vectors(cubics):
        actions = tuple(actions)
        representation = build_mixed_representation(
            polynomial,
            n_original=n_original,
            actions=actions,
            default_margin=positive_margin,
        )
        if (
            representation.n_auxiliary == target
            and representation.n_auxiliary > 0
            and _retained_cubic(representation) > 0
        ):
            eligible.append(actions)
    alternatives = [actions for actions in eligible if actions != selected]
    population = alternatives or eligible
    if not population:
        raise E1E2CorrectionError(
            f"No nontrivial aux-count-matched baseline: {instance_id}"
        )
    output: list[tuple[int, tuple[Support | None, ...], bool]] = []
    for base_seed in seed_bundle:
        digest = hashlib.sha256(f"{instance_id}:{base_seed}:correction-v1".encode("ascii")).digest()
        chosen = random.Random(int.from_bytes(digest[:8], "big")).choice(population)
        output.append((base_seed, chosen, chosen == selected))
    return output


def _evaluate_one_design(
    original: Mapping[Support, object],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    representation_name: str,
    random_seed: int | None,
    below_delta: object,
    above_epsilon: object,
    witness_prefix: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    strict = build_mixed_representation(
        original,
        n_original=n_original,
        actions=actions,
        default_margin=above_epsilon,
    )
    if strict.n_auxiliary <= 0 or _retained_cubic(strict) <= 0:
        raise E1E2CorrectionError("Supplement design is not genuinely selective")
    rows: list[dict[str, object]] = []
    trials: list[dict[str, object]] = []
    witnesses: list[dict[str, object]] = []

    settings: list[tuple[str, Support | None, MixedRepresentation]] = [
        ("above_threshold", None, strict)
    ]
    for pair in strict.active_pairs:
        for setting in ("below_threshold", "at_threshold"):
            penalties = dict(strict.penalties)
            penalties[pair] = strict.thresholds[pair]
            if setting == "below_threshold":
                penalties[pair] -= Fraction(str(below_delta))
            settings.append(
                (
                    setting,
                    pair,
                    build_mixed_representation(
                        original,
                        n_original=n_original,
                        actions=actions,
                        penalty_values=penalties,
                        default_margin=above_epsilon,
                    ),
                )
            )

    for setting, target_pair, representation in settings:
        result = evaluate_pointwise(original, representation)
        witness_id = ""
        witness = result.get("first_witness")
        if witness is not None:
            pair_label = (
                "strict" if target_pair is None else f"{target_pair[0]}_{target_pair[1]}"
            )
            seed_label = "selected" if random_seed is None else str(random_seed)
            witness_id = f"{witness_prefix}_{setting}_{pair_label}_{seed_label}"
            witnesses.append(
                {
                    "witness_id": witness_id,
                    "representation": representation_name,
                    "penalty_setting": setting,
                    "target_pair": list(target_pair) if target_pair else None,
                    "threshold": (
                        float(strict.thresholds[target_pair]) if target_pair else None
                    ),
                    "penalty": (
                        float(representation.penalties[target_pair]) if target_pair else None
                    ),
                    "random_seed": random_seed,
                    **witness,  # type: ignore[arg-type]
                }
            )
        trial = {
            "representation": representation_name,
            "random_seed": random_seed,
            "design_id": _design_id(actions),
            "actions": _action_payload(actions),
            "n_aux": representation.n_auxiliary,
            "retained_cubic": _retained_cubic(representation),
            "penalty_setting": setting,
            "target_pair": list(target_pair) if target_pair else None,
            "threshold": float(strict.thresholds[target_pair]) if target_pair else None,
            "penalty": (
                float(representation.penalties[target_pair]) if target_pair else None
            ),
            "witness_id": witness_id,
            **{key: value for key, value in result.items() if key != "first_witness"},
        }
        strict_bad = setting == "above_threshold" and (
            int(result["mismatch_count"]) != 0
            or int(result["inconsistent_minimiser_count"]) != 0
        )
        threshold_bad = setting == "at_threshold" and (
            int(result["mismatch_count"]) != 0
            or witness is None
            or float(witness["pointwise_error"]) != 0.0  # type: ignore[index]
            or not witness["inconsistent_minimising_auxiliary_bits"]  # type: ignore[index]
        )
        below_bad = setting == "below_threshold" and (
            int(result["mismatch_count"]) <= 0
            or witness is None
            or float(witness["pointwise_error"]) <= 0.0  # type: ignore[index]
            or float(witness["minimum_reduced_energy"])  # type: ignore[index]
            >= float(witness["original_energy"])  # type: ignore[index]
        )
        trial["status"] = "fail" if strict_bad or threshold_bad or below_bad else "pass"
        trials.append(trial)
        rows.append(dict(trial))
    return rows, trials, witnesses


def _actions_for_existing_trial(
    trial: Mapping[str, object],
    *,
    polynomial: Polynomial,
    n_original: int,
    selected_record: Mapping[str, object],
    random_seed_bundle: Sequence[int],
    above_epsilon: object,
) -> tuple[Support | None, ...]:
    representation = str(trial["representation"])
    cubics = tuple(sorted(cubic_supports(polynomial)))
    if representation == "all_native":
        return (None,) * len(cubics)
    if representation == "fully_quadratized":
        return tuple(full_action_vector(polynomial))
    selected = tuple(
        tuple(item) if item is not None else None
        for item in selected_record["actions"]  # type: ignore[index]
    )
    if representation == "selective":
        return selected
    if representation == "matched_random_selective":
        target_aux = build_mixed_representation(
            polynomial,
            n_original=n_original,
            actions=selected,
            default_margin=above_epsilon,
        ).n_auxiliary
        eligible = []
        for actions in _candidate_vectors(cubics):
            if len({item for item in actions if item is not None}) == target_aux:
                eligible.append(tuple(actions))
        alternatives = [actions for actions in eligible if actions != selected]
        population = alternatives or eligible
        seed = int(trial["random_seed"])
        if seed not in random_seed_bundle:
            raise E1E2CorrectionError(f"Unknown matched-random seed: {seed}")
        instance_id = str(trial["instance_id"])
        digest = hashlib.sha256(f"{instance_id}:{seed}".encode("ascii")).digest()
        return random.Random(int.from_bytes(digest[:8], "big")).choice(population)
    raise E1E2CorrectionError(f"Unknown E1 representation: {representation}")


def corrected_existing_witnesses(
    *,
    data_directory: Path,
    results_directory: Path,
    oracle_rows: Sequence[Mapping[str, str]],
    config: Mapping[str, object],
) -> tuple[list[dict[str, object]], int]:
    """Replace tie-only below witnesses with positive pointwise-error witnesses."""

    witness_payload = _load_json(results_directory / "e1_penalty_witnesses.json")
    trial_payload = _load_json(results_directory / "e1_penalty_trials.json")
    design_payload = _load_json(results_directory / "e1_selected_designs.json")
    witnesses = [dict(item) for item in witness_payload["witnesses"]]  # type: ignore[index]
    trials = list(trial_payload["trials"])  # type: ignore[index]
    trial_by_witness = {
        str(item["witness_id"]): item for item in trials if item.get("witness_id")
    }
    selected_by_instance = {
        str(item["instance_id"]): item
        for item in design_payload["designs"]  # type: ignore[index]
    }
    oracle_by_instance = {row["instance_id"]: row for row in oracle_rows}
    below_delta = config["penalty_tightness"]["below_threshold_delta"]  # type: ignore[index]
    above_epsilon = config["penalty_tightness"]["above_threshold_epsilon"]  # type: ignore[index]
    seed_bundle = [
        int(value)
        for value in config["representations"]["matched_random"]["seed_bundle"]  # type: ignore[index]
    ]
    corrected = 0
    for index, witness in enumerate(witnesses):
        if witness["penalty_setting"] != "below_threshold":
            continue
        if float(witness["pointwise_error"]) > 0.0:
            continue
        witness_id = str(witness["witness_id"])
        trial = trial_by_witness.get(witness_id)
        if trial is None or int(trial["mismatch_count"]) <= 0:
            raise E1E2CorrectionError(f"Bad below witness lacks mismatching parent: {witness_id}")
        instance_id = str(witness["instance_id"])
        manifest = oracle_by_instance[instance_id]
        canonical_path = data_directory / manifest["canonical_file"]
        if _sha256(canonical_path) != manifest["canonical_sha256"]:
            raise E1E2CorrectionError(f"Canonical hash mismatch: {instance_id}")
        _, polynomial = _canonical_polynomial(canonical_path)
        n_original = int(manifest["n"])
        actions = _actions_for_existing_trial(
            trial,
            polynomial=polynomial,
            n_original=n_original,
            selected_record=selected_by_instance[instance_id],
            random_seed_bundle=seed_bundle,
            above_epsilon=above_epsilon,
        )
        strict = build_mixed_representation(
            polynomial,
            n_original=n_original,
            actions=actions,
            default_margin=above_epsilon,
        )
        target_pair = tuple(int(value) for value in witness["target_pair"])
        penalties = dict(strict.penalties)
        penalties[target_pair] = strict.thresholds[target_pair] - Fraction(str(below_delta))
        representation = build_mixed_representation(
            polynomial,
            n_original=n_original,
            actions=actions,
            penalty_values=penalties,
            default_margin=above_epsilon,
        )
        result = evaluate_pointwise(polynomial, representation)
        replacement = result["first_witness"]
        if (
            replacement is None
            or float(replacement["pointwise_error"]) <= 0.0  # type: ignore[index]
            or float(replacement["minimum_reduced_energy"])  # type: ignore[index]
            >= float(replacement["original_energy"])  # type: ignore[index]
        ):
            raise E1E2CorrectionError(f"Could not repair below witness: {witness_id}")
        witnesses[index] = {
            **witness,
            **replacement,  # type: ignore[arg-type]
            "threshold": float(strict.thresholds[target_pair]),
            "penalty": float(penalties[target_pair]),
        }
        corrected += 1

    below = [item for item in witnesses if item["penalty_setting"] == "below_threshold"]
    at = [item for item in witnesses if item["penalty_setting"] == "at_threshold"]
    if any(float(item["pointwise_error"]) <= 0.0 for item in below):
        raise E1E2CorrectionError("Below-threshold witness correction is incomplete")
    if any(
        float(item["pointwise_error"]) != 0.0
        or not item["inconsistent_minimising_auxiliary_bits"]
        for item in at
    ):
        raise E1E2CorrectionError("At-threshold witness tie evidence changed")
    return witnesses, corrected


def common_feasible_ids(
    rows: Sequence[Mapping[str, str]],
    *,
    representations: Sequence[str] = ("all_native", "fully_quadratized", "selective"),
    topology_id: str = "device_sparse_v1",
) -> tuple[set[str], dict[str, set[str]]]:
    sparse = [row for row in rows if row["topology_id"] == topology_id]
    successful: dict[str, set[str]] = {}
    for representation in representations:
        groups: dict[str, list[Mapping[str, str]]] = defaultdict(list)
        for row in sparse:
            if row["representation"] == representation:
                groups[row["instance_id"]].append(row)
        successful[representation] = {
            instance_id
            for instance_id, group in groups.items()
            if group and all(row["status"] == "pass" for row in group)
        }
    return set.intersection(*(successful[name] for name in representations)), successful


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else math.nan


def _mean_ci(values: Sequence[float]) -> tuple[float, float, float]:
    mean = _mean(values)
    if len(values) < 2:
        return mean, mean, mean
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half, mean + half


def e2_common_feasible_outputs(
    rows: Sequence[Mapping[str, str]],
    *,
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    representations = ("all_native", "fully_quadratized", "selective")
    common, successful = common_feasible_ids(rows, representations=representations)
    cohort_id = "sparse_common_feasible_" + hashlib.sha256(
        "\n".join(sorted(common)).encode("ascii")
    ).hexdigest()[:16]
    sparse = [
        row
        for row in rows
        if row["topology_id"] == "device_sparse_v1"
        and row["representation"] in representations
        and row["instance_id"] in common
    ]
    by_seed: list[dict[str, object]] = []
    for row in sparse:
        by_seed.append({**row, "common_feasible_cohort_id": cohort_id})

    grouped: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in sparse:
        grouped[(row["instance_id"], row["representation"])].append(row)
    instance_rows: list[dict[str, object]] = []
    metrics = (
        "two_qubit_gates",
        "two_qubit_depth",
        "swap_count",
        "routing_overhead",
        "compile_runtime_sec",
    )
    for (instance_id, representation), group in sorted(grouped.items()):
        if len(group) != 5 or any(row["status"] != "pass" for row in group):
            raise E1E2CorrectionError(
                f"Common-feasible group is not a complete five-seed bundle: {instance_id}/{representation}"
            )
        item: dict[str, object] = {
            "instance_id": instance_id,
            "family": group[0]["family"],
            "representation": representation,
            "common_feasible_cohort_id": cohort_id,
            "transpiler_seed_count": len(group),
            "config_hash": config_hash,
            "manifest_hash": manifest_hash,
            "code_commit": code_commit,
        }
        for metric in metrics:
            item[f"{metric}_mean"] = _mean([float(row[metric]) for row in group])
        instance_rows.append(item)

    by_instance = {
        (str(row["instance_id"]), str(row["representation"])): row
        for row in instance_rows
    }
    summary_rows: list[dict[str, object]] = []
    for family in sorted({str(row["family"]) for row in instance_rows}):
        family_ids = sorted(
            {
                str(row["instance_id"])
                for row in instance_rows
                if row["family"] == family
            }
        )
        for representation in representations:
            output: dict[str, object] = {
                "family": family,
                "representation": representation,
                "common_feasible_cohort_id": cohort_id,
                "common_instance_count": len(family_ids),
                "config_hash": config_hash,
                "manifest_hash": manifest_hash,
                "code_commit": code_commit,
            }
            for metric in ("two_qubit_gates", "two_qubit_depth", "swap_count"):
                values = [
                    float(by_instance[(instance_id, representation)][f"{metric}_mean"])
                    for instance_id in family_ids
                ]
                native = [
                    float(by_instance[(instance_id, "all_native")][f"{metric}_mean"])
                    for instance_id in family_ids
                ]
                mean, low, high = _mean_ci(values)
                output[f"{metric}_mean"] = mean
                output[f"{metric}_ci95_low"] = low
                output[f"{metric}_ci95_high"] = high
                output[f"{metric}_paired_delta_vs_native_mean"] = _mean(
                    [value - base for value, base in zip(values, native)]
                )
            summary_rows.append(output)

    capacity_rows = e2_capacity_summary(
        rows,
        config_hash=config_hash,
        manifest_hash=manifest_hash,
        code_commit=code_commit,
    )
    family_counts = defaultdict(int)
    for instance_id in common:
        family_counts[next(row["family"] for row in sparse if row["instance_id"] == instance_id)] += 1
    audit = {
        "common_feasible_cohort_id": cohort_id,
        "common_feasible_instance_count": len(common),
        "common_feasible_family_counts": dict(sorted(family_counts.items())),
        "successful_instance_counts": {
            key: len(value) for key, value in sorted(successful.items())
        },
        "same_instance_ids_for_all_main_representations": all(
            {
                row["instance_id"]
                for row in instance_rows
                if row["representation"] == representation
            }
            == common
            for representation in representations
        ),
    }
    return by_seed, instance_rows, summary_rows, capacity_rows, audit


def e2_capacity_summary(
    rows: Sequence[Mapping[str, str]],
    *,
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
) -> list[dict[str, object]]:
    sparse = [row for row in rows if row["topology_id"] == "device_sparse_v1"]
    groups: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in sparse:
        groups[(row["family"], row["representation"])].append(row)
    output: list[dict[str, object]] = []
    for (family, representation), group in sorted(groups.items()):
        successful = [row for row in group if row["status"] == "pass"]
        infeasible = [
            row for row in group if row["status"] == "infeasible_width_exceeds_topology"
        ]
        designs: dict[tuple[str, str, str], list[Mapping[str, str]]] = defaultdict(list)
        for row in group:
            designs[(row["instance_id"], row["random_rep_seed"], row["design_id"])].append(row)
        successful_designs = {
            key for key, value in designs.items() if value and all(row["status"] == "pass" for row in value)
        }
        instance_ids = {row["instance_id"] for row in group}
        successful_instances = {
            instance_id
            for instance_id in instance_ids
            if any(key[0] == instance_id for key in successful_designs)
        }
        output.append(
            {
                "family": family,
                "representation": representation,
                "topology_id": "device_sparse_v1",
                "scheduled_row_count": len(group),
                "success_row_count": len(successful),
                "infeasible_width_row_count": len(infeasible),
                "other_failure_row_count": len(group) - len(successful) - len(infeasible),
                "success_rate": len(successful) / len(group),
                "infeasible_width_rate": len(infeasible) / len(group),
                "scheduled_design_count": len(designs),
                "successful_design_count": len(successful_designs),
                "scheduled_instance_count": len(instance_ids),
                "successful_instance_count": len(successful_instances),
                "config_hash": config_hash,
                "manifest_hash": manifest_hash,
                "code_commit": code_commit,
            }
        )
    return output


def _latex_e1(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated E1 nontrivial-selective correction.",
        "\\begin{tabular}{lllrrrrr}",
        "\\toprule",
        "Family & Representation & Setting & Instances & Aux. & Retained cubic & Mismatch & Inconsistent \\\\",
        "\\midrule",
    ]
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if row["constructible"] is True:
            groups[(str(row["family"]), str(row["representation"]), str(row["penalty_setting"]))].append(row)
    for key, group in sorted(groups.items()):
        family, representation, setting = (value.replace("_", "\\_") for value in key)
        lines.append(
            f"{family} & {representation} & {setting} & {len(group)} & "
            f"{sum(int(row['n_aux']) for row in group)} & "
            f"{sum(int(row['retained_cubic']) for row in group)} & "
            f"{sum(int(row['mismatch_count']) for row in group)} & "
            f"{sum(int(row['inconsistent_minimiser_count']) for row in group)} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _latex_e2(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated E2 common-feasible sparse comparison.",
        "\\begin{tabular}{llrrrrrr}",
        "\\toprule",
        "Family & Representation & $N$ & 2Q gates & $\\Delta$ gates & 2Q depth & $\\Delta$ depth & SWAP \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{str(row['family']).replace('_', '\\_')} & "
            f"{str(row['representation']).replace('_', '\\_')} & "
            f"{row['common_instance_count']} & {float(row['two_qubit_gates_mean']):.2f} & "
            f"{float(row['two_qubit_gates_paired_delta_vs_native_mean']):.2f} & "
            f"{float(row['two_qubit_depth_mean']):.2f} & "
            f"{float(row['two_qubit_depth_paired_delta_vs_native_mean']):.2f} & "
            f"{float(row['swap_count_mean']):.2f} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _write_e2_figure(path: Path, rows: Sequence[Mapping[str, object]]) -> str:
    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E1E2CorrectionError("reportlab is required for the correction figure") from error

    path.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = landscape(letter)
    pdf = canvas.Canvas(str(path), pagesize=(page_width, page_height))
    pdf.setTitle("E2 sparse common-feasible paired resources")
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(28, page_height - 28, "E2 sparse-device common-feasible paired comparison")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(
        28,
        page_height - 42,
        "Each family panel uses the same instance IDs for Native, Full, and Selected; means are over per-instance five-seed averages.",
    )
    families = sorted({str(row["family"]) for row in rows})
    metrics = (
        ("two_qubit_gates", "2Q gates"),
        ("two_qubit_depth", "2Q depth"),
        ("swap_count", "SWAP count"),
    )
    representations = ("all_native", "fully_quadratized", "selective")
    palette = (colors.HexColor("#33779B"), colors.HexColor("#7B6FB5"), colors.HexColor("#2A9D78"))
    panel_width = (page_width - 76) / 3
    panel_height = (page_height - 104) / 2
    for family_index, family in enumerate(families):
        for metric_index, (metric, label) in enumerate(metrics):
            x0 = 28 + metric_index * (panel_width + 10)
            y0 = page_height - 70 - (family_index + 1) * panel_height - family_index * 8
            pdf.setStrokeColor(colors.HexColor("#CAD7E4"))
            pdf.rect(x0, y0, panel_width, panel_height - 8, stroke=1, fill=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica-Bold", 8)
            selected = {
                str(row["representation"]): row
                for row in rows
                if row["family"] == family
            }
            sample_size = int(selected["all_native"]["common_instance_count"])
            pdf.drawString(
                x0 + 8,
                y0 + panel_height - 22,
                f"{family.replace('_', ' ')}: {label} (N={sample_size})",
            )
            values = [float(selected[rep][f"{metric}_mean"]) for rep in representations]
            highs = [float(selected[rep][f"{metric}_ci95_high"]) for rep in representations]
            maximum = max(highs + [1.0]) * 1.15
            baseline = y0 + 30
            plot_height = panel_height - 68
            bar_width = 28
            gap = (panel_width - 3 * bar_width) / 4
            for rep_index, rep in enumerate(representations):
                item = selected[rep]
                value = float(item[f"{metric}_mean"])
                low = float(item[f"{metric}_ci95_low"])
                high = float(item[f"{metric}_ci95_high"])
                left = x0 + gap + rep_index * (bar_width + gap)
                height = plot_height * value / maximum
                pdf.setFillColor(palette[rep_index])
                pdf.rect(left, baseline, bar_width, height, stroke=0, fill=1)
                center = left + bar_width / 2
                pdf.setStrokeColor(colors.black)
                pdf.line(center, baseline + plot_height * low / maximum, center, baseline + plot_height * high / maximum)
                pdf.line(center - 3, baseline + plot_height * low / maximum, center + 3, baseline + plot_height * low / maximum)
                pdf.line(center - 3, baseline + plot_height * high / maximum, center + 3, baseline + plot_height * high / maximum)
                pdf.setFillColor(colors.black)
                pdf.setFont("Helvetica", 6.5)
                pdf.drawCentredString(center, y0 + 17, ("Native", "Full", "Selected")[rep_index])
                pdf.drawCentredString(center, baseline + height + 4, f"{value:.1f}")
    pdf.setFont("Helvetica-Oblique", 7)
    pdf.drawRightString(page_width - 28, 14, "Main comparison: common-feasible cohort only; capacity failures are reported separately.")
    pdf.save()
    return reportlab.Version


def _manifest(path: Path, root: Path, files: Sequence[Path]) -> None:
    rows = [
        {
            "path": file.relative_to(root).as_posix(),
            "size_bytes": file.stat().st_size,
            "sha256": _sha256(file),
        }
        for file in sorted(files)
    ]
    _write_csv(path, rows, ("path", "size_bytes", "sha256"))
    _write_sidecar(path)


def _method_status(config: Mapping[str, object], e3_source: str) -> dict[str, object]:
    selector_text = json.dumps(config.get("selector", {}), sort_keys=True).lower()
    explicit = any(
        token in selector_text
        for token in ("fibre", "fiber", "pair_moment", "pair-moment", "sa_rlt")
    )
    e3_uses_resource_beam = "beam_select_design(" in e3_source
    e3_uses_pair_moments = any(
        token in e3_source.lower()
        for token in ("fibre_risk", "fiber_risk", "pair_moment", "sa_rlt")
    )
    if explicit or e3_uses_pair_moments:
        raise E1E2CorrectionError(
            "Selector appears to contain a fibre-risk method; this resource-only correction package cannot certify it"
        )
    if not e3_uses_resource_beam:
        raise E1E2CorrectionError("Could not audit the current E3 selector call")
    return {
        "method_status": "resource_only_selector",
        "e1_e2_label_required": "resource-only",
        "e3_selected_representation_status": "resource-only selector; no SA/RLT pair-moment fibre-risk guardrail",
        "e4_pair_moments_scope": "warm-start initialization only; does not retroactively change E3 selection",
        "current_e3_e6_results_may_be_retained_if": "manuscript explicitly labels the selector and resulting selective comparisons as resource-only",
        "full_proposed_selector_claim_requires": "freeze a mathematically specified SA/RLT pair-moment fibre-risk rule and rerun every selected/matched-random dependent branch of E2-E6",
        "reusable_without_rerun": [
            "E1 native/full exactness",
            "E2 all-to-all native/full rows",
            "native/full downstream controls when their protocol is otherwise unchanged",
        ],
    }


def run_e1_e2_corrections(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    data_directory: str | Path,
    results_directory: str | Path,
    output_directory: str | Path,
    code_commit: str,
    e3_source_path: str | Path = "urss_pipeline/e3_qaoa.py",
    progress=None,
) -> dict[str, object]:
    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    output_directory = Path(output_directory)
    e3_source_path = Path(e3_source_path)
    if output_directory.exists():
        raise FileExistsError(f"Correction output already exists: {output_directory}")
    staging = output_directory.parent / (output_directory.name + "_building")
    if staging.exists():
        raise E1E2CorrectionError(f"Incomplete correction staging exists: {staging}")

    freeze = verify_data_freeze(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["status"] != "frozen" or config["freeze_gate"]["blocked"]:
        raise E1E2CorrectionError("Corrections require the frozen formal config")
    config_hash = str(freeze["config_hash"])
    oracle_hash = str(freeze["oracle_manifest_hash"])
    oracle_rows = freeze["oracle_rows"]  # type: ignore[assignment]

    required_e1 = (
        "e1_exactness.csv",
        "e1_penalty_witnesses.json",
        "e1_penalty_trials.json",
        "e1_selected_designs.json",
        "e1_validation_summary.json",
    )
    for name in required_e1:
        _verify_hash(results_directory / name)
    required_e2 = (
        "e2_compiled_resources_by_seed.csv",
        "e2_validation_summary.json",
    )
    for name in required_e2:
        _verify_hash(results_directory / name)

    selector_path = results_directory / "selector_validation.csv"
    selector_hash = _sha256(selector_path) if selector_path.is_file() else ""
    e2_summary = _load_json(results_directory / "e2_validation_summary.json")
    expected_selector_hash = str(
        e2_summary.get("artifact_hashes", {}).get("results/selector_validation.csv", "")  # type: ignore[union-attr]
    )
    if not selector_path.is_file() or not expected_selector_hash:
        raise E1E2CorrectionError(
            "selector_validation.csv is absent from the repository or from the E2 artifact hash map"
        )
    if selector_hash != expected_selector_hash:
        raise E1E2CorrectionError("selector_validation.csv disagrees with E2 validation summary")
    if selector_path.with_suffix(".sha256").is_file():
        _verify_hash(selector_path)
    selector_rows = _read_csv(selector_path)
    if len(selector_rows) != 180:
        raise E1E2CorrectionError(f"Expected 180 selector rows, found {len(selector_rows)}")

    method = _method_status(
        config,
        e3_source_path.read_text(encoding="utf-8"),
    )
    below_delta = config["penalty_tightness"]["below_threshold_delta"]
    above_epsilon = config["penalty_tightness"]["above_threshold_epsilon"]
    seed_bundle = [
        int(value)
        for value in config["representations"]["matched_random"]["seed_bundle"]
    ]

    staging.mkdir(parents=True)
    try:
        e1_rows: list[dict[str, object]] = []
        e1_trials: list[dict[str, object]] = []
        e1_witnesses: list[dict[str, object]] = []
        construction: list[dict[str, object]] = []
        random_degenerate = 0
        for ordinal, manifest in enumerate(oracle_rows, start=1):
            instance_id = manifest["instance_id"]
            canonical_path = data_directory / manifest["canonical_file"]
            if _sha256(canonical_path) != manifest["canonical_sha256"]:
                raise E1E2CorrectionError(f"Canonical hash mismatch: {instance_id}")
            family, polynomial = _canonical_polynomial(canonical_path)
            n_original = int(manifest["n"])
            selected, reason = deterministic_nontrivial_actions(
                polynomial,
                n_original=n_original,
                positive_margin=above_epsilon,
            )
            construction.append(
                {
                    "instance_id": instance_id,
                    "family": family,
                    "split": manifest["split"],
                    "constructible": selected is not None,
                    "reason": reason,
                }
            )
            if selected is None:
                e1_rows.append(
                    {
                        "instance_id": instance_id,
                        "family": family,
                        "split": manifest["split"],
                        "representation": "nontrivial_selective_supplement",
                        "constructible": False,
                        "constructibility_reason": reason,
                        "status": "not_constructible",
                        "config_hash": config_hash,
                        "manifest_hash": oracle_hash,
                        "code_commit": code_commit,
                    }
                )
                continue
            designs: list[tuple[str, int | None, tuple[Support | None, ...]]] = [
                ("nontrivial_selective_supplement", None, selected)
            ]
            for seed, actions, degenerate in matched_nontrivial_actions(
                polynomial,
                n_original=n_original,
                selected_actions=selected,
                instance_id=instance_id,
                seed_bundle=seed_bundle,
                positive_margin=above_epsilon,
            ):
                random_degenerate += int(degenerate)
                designs.append(("matched_random_nontrivial_selective", seed, actions))
            for representation_name, random_seed, actions in designs:
                rows, trials, witnesses = _evaluate_one_design(
                    polynomial,
                    n_original=n_original,
                    actions=actions,
                    representation_name=representation_name,
                    random_seed=random_seed,
                    below_delta=below_delta,
                    above_epsilon=above_epsilon,
                    witness_prefix=f"{instance_id}_{representation_name}",
                )
                for collection in (rows, trials, witnesses):
                    for item in collection:
                        item.update(
                            {
                                "instance_id": instance_id,
                                "family": family,
                                "split": manifest["split"],
                            }
                        )
                for row in rows:
                    row.update(
                        {
                            "constructible": True,
                            "constructibility_reason": reason,
                            "config_hash": config_hash,
                            "manifest_hash": oracle_hash,
                            "code_commit": code_commit,
                        }
                    )
                e1_rows.extend(rows)
                e1_trials.extend(trials)
                e1_witnesses.extend(witnesses)
            if progress and (ordinal % 10 == 0 or ordinal == len(oracle_rows)):
                progress(f"E1 CORRECTION: {ordinal}/{len(oracle_rows)} oracle instances")

        corrected_witnesses, corrected_count = corrected_existing_witnesses(
            data_directory=data_directory,
            results_directory=results_directory,
            oracle_rows=oracle_rows,
            config=config,
        )
        constructible_by_family = {
            family: sum(
                1
                for item in construction
                if item["family"] == family and item["constructible"] is True
            )
            for family in ("cubic_spin_glass", "max3sat")
        }
        strict_rows = [row for row in e1_rows if row.get("penalty_setting") == "above_threshold"]
        below_rows = [row for row in e1_rows if row.get("penalty_setting") == "below_threshold"]
        at_rows = [row for row in e1_rows if row.get("penalty_setting") == "at_threshold"]
        e1_gate = (
            all(value > 0 for value in constructible_by_family.values())
            and all(int(row["n_aux"]) > 0 and int(row["retained_cubic"]) > 0 for row in strict_rows)
            and sum(int(row["mismatch_count"]) for row in strict_rows) == 0
            and sum(int(row["inconsistent_minimiser_count"]) for row in strict_rows) == 0
            and all(int(row["mismatch_count"]) > 0 and row["witness_id"] for row in below_rows)
            and all(int(row["mismatch_count"]) == 0 and row["witness_id"] for row in at_rows)
            and corrected_count == 23
        )

        compiled_path = results_directory / "e2_compiled_resources_by_seed.csv"
        compiled_rows = _read_csv(compiled_path)
        e2_manifest_hash = str(e2_summary["compilation_manifest_hash"])
        by_seed, instance_rows, paired_rows, capacity_rows, e2_audit = e2_common_feasible_outputs(
            compiled_rows,
            config_hash=config_hash,
            manifest_hash=e2_manifest_hash,
            code_commit=code_commit,
        )
        sparse_rows = [row for row in compiled_rows if row["topology_id"] == "device_sparse_v1"]
        sparse_infeasible = sum(
            row["status"] == "infeasible_width_exceeds_topology" for row in sparse_rows
        )
        e2_gate = (
            len(compiled_rows) == 14400
            and len(sparse_rows) == 7200
            and sparse_infeasible == 3705
            and e2_audit["successful_instance_counts"]
            == {"all_native": 108, "fully_quadratized": 21, "selective": 95}
            and e2_audit["common_feasible_instance_count"] == 21
            and e2_audit["same_instance_ids_for_all_main_representations"] is True
            and all(value > 0 for value in e2_audit["common_feasible_family_counts"].values())  # type: ignore[union-attr]
        )

        e1_dir = staging / "01_E1_CORRECTION"
        e2_dir = staging / "02_E2_CORRECTION"
        method_dir = staging / "03_METHOD_STATUS"
        audit_dir = staging / "04_AUDIT"
        reproducibility_dir = staging / "00_REPRODUCIBILITY"
        reproducibility_dir.mkdir(parents=True)
        e1_dir.mkdir(parents=True)
        e2_dir.mkdir(parents=True)
        method_dir.mkdir(parents=True)
        audit_dir.mkdir(parents=True)

        e1_summary_path = e1_dir / "e1_nontrivial_selective_summary.csv"
        e1_trials_path = e1_dir / "e1_nontrivial_selective_penalty_trials.json"
        e1_witness_path = e1_dir / "e1_nontrivial_selective_witnesses.json"
        corrected_path = e1_dir / "e1_corrected_penalty_witnesses.json"
        e1_validation_path = e1_dir / "e1_correction_validation_summary.json"
        e1_table_path = e1_dir / "table_e1_nontrivial_selective.tex"
        construction_path = e1_dir / "e1_nontrivial_constructibility.json"
        _write_csv(e1_summary_path, e1_rows, E1_SUPPLEMENT_FIELDS)
        _write_json(e1_trials_path, {"schema_version": "e1_nontrivial_trials_v1", "trials": e1_trials})
        _write_json(e1_witness_path, {"schema_version": "e1_nontrivial_witnesses_v1", "witnesses": e1_witnesses})
        _write_json(corrected_path, {"schema_version": "e1_penalty_witnesses_corrected_v2", "witnesses": corrected_witnesses})
        _write_json(construction_path, {"schema_version": "e1_nontrivial_constructibility_v1", "instances": construction})
        e1_validation = {
            "status": "pass" if e1_gate else "fail",
            "scope": "E1 additive nontrivial-selective supplement and witness re-export",
            "original_native_full_results_retained": True,
            "oracle_instance_count": len(oracle_rows),
            "constructible_instance_count_by_family": constructible_by_family,
            "strict_row_count": len(strict_rows),
            "strict_mismatch_count": sum(int(row["mismatch_count"]) for row in strict_rows),
            "strict_inconsistent_minimiser_count": sum(int(row["inconsistent_minimiser_count"]) for row in strict_rows),
            "below_trial_row_count": len(below_rows),
            "below_trials_with_positive_error_witness_count": sum(bool(row["witness_id"]) for row in below_rows),
            "at_threshold_trial_row_count": len(at_rows),
            "at_threshold_tie_witness_count": sum(bool(row["witness_id"]) for row in at_rows),
            "existing_below_witnesses_reexported_count": corrected_count,
            "matched_random_degenerate_to_supplement_count": random_degenerate,
            "config_hash": config_hash,
            "oracle_manifest_hash": oracle_hash,
            "code_commit": code_commit,
        }
        _write_json(e1_validation_path, e1_validation)
        e1_table_path.write_text(_latex_e1(e1_rows), encoding="utf-8", newline="\n")

        selector_copy = e2_dir / "selector_validation.csv"
        shutil.copyfile(selector_path, selector_copy)
        by_seed_path = e2_dir / "e2_sparse_common_feasible_by_seed.csv"
        instance_path = e2_dir / "e2_sparse_common_feasible_instance_metrics.csv"
        paired_path = e2_dir / "e2_sparse_common_feasible_paired_summary.csv"
        capacity_path = e2_dir / "e2_sparse_capacity_summary.csv"
        e2_validation_path = e2_dir / "e2_correction_validation_summary.json"
        e2_table_path = e2_dir / "table_e2_sparse_common_feasible.tex"
        e2_figure_path = e2_dir / "figure_e2_sparse_common_feasible.pdf"
        by_seed_fields = tuple(by_seed[0].keys())
        _write_csv(by_seed_path, by_seed, by_seed_fields)
        _write_csv(instance_path, instance_rows, E2_INSTANCE_FIELDS)
        _write_csv(paired_path, paired_rows, E2_PAIRED_SUMMARY_FIELDS)
        _write_csv(capacity_path, capacity_rows, E2_CAPACITY_FIELDS)
        e2_table_path.write_text(_latex_e2(paired_rows), encoding="utf-8", newline="\n")
        reportlab_version = _write_e2_figure(e2_figure_path, paired_rows)
        e2_validation = {
            "status": "pass" if e2_gate else "fail",
            "scope": "E2 sparse-device common-feasible paired correction",
            "no_recompilation_performed": True,
            "source_compiled_row_count": len(compiled_rows),
            "sparse_scheduled_row_count": len(sparse_rows),
            "sparse_infeasible_width_row_count": sparse_infeasible,
            "selector_validation_row_count": len(selector_rows),
            "selector_validation_sha256": selector_hash,
            "reportlab_version": reportlab_version,
            **e2_audit,
            "success_only_original_figure_status": "appendix_only_conditional_on_representation_specific_successful_subsets",
            "config_hash": config_hash,
            "compilation_manifest_hash": e2_manifest_hash,
            "code_commit": code_commit,
        }
        _write_json(e2_validation_path, e2_validation)

        config_copy = reproducibility_dir / "experiment_config_v1.yaml"
        shutil.copyfile(config_path, config_copy)
        frozen_hashes_path = reproducibility_dir / "frozen_hashes.json"
        _write_json(
            frozen_hashes_path,
            {
                "config_sha256": config_hash,
                "oracle_manifest_sha256": oracle_hash,
                "compilation_manifest_sha256": e2_manifest_hash,
                "selector_validation_sha256": selector_hash,
                "source_e1_validation_summary_sha256": _sha256(
                    results_directory / "e1_validation_summary.json"
                ),
                "source_e2_validation_summary_sha256": _sha256(
                    results_directory / "e2_validation_summary.json"
                ),
                "code_commit": code_commit,
            },
        )
        exact_command_path = reproducibility_dir / "RUN_COMMANDS_E1_E2_CORRECTIONS.md"
        exact_command_path.write_text(
            "# Exact correction command\n\n"
            "```powershell\n"
            "python .\\run_e1_e2_corrections.py `\n"
            "  --config .\\configs\\experiment_config_v1.yaml `\n"
            "  --config-hash .\\configs\\experiment_config_v1.sha256 `\n"
            "  --data .\\data `\n"
            "  --results .\\results `\n"
            "  --output .\\corrections\\e1_e2_v1 `\n"
            "  --e3-source .\\urss_pipeline\\e3_qaoa.py\n"
            "```\n",
            encoding="utf-8",
            newline="\n",
        )

        method_json = method_dir / "method_status_e3_e6.json"
        method_md = method_dir / "METHOD_STATUS_E3_E6.md"
        _write_json(method_json, {**method, "config_hash": config_hash, "code_commit": code_commit})
        method_md.write_text(
            "# Method status after E1/E2 review\n\n"
            "The frozen E1/E2 selector and the E3 selected representation are **resource-only**. "
            "They do not use an SA/RLT level-2 pair-moment fibre-risk guardrail. The SA/RLT pair moments "
            "implemented in E4 are used for warm-start initialization only.\n\n"
            "Existing E3-E6 numerical outputs may be retained only when the manuscript explicitly labels "
            "the selected/matched-random comparisons as resource-only. They cannot support a claim that the "
            "complete proposed fibre-aware selector was tested.\n\n"
            "If the complete proposed selector is required, first freeze its mathematical fibre-risk score, "
            "threshold, tie-break, and SA/RLT moment source. Then rerun selected/matched-random-dependent E2 "
            "sparse resources and E3-E6. Native/full controls remain reusable when their protocols are unchanged.\n",
            encoding="utf-8",
            newline="\n",
        )

        audit_path = audit_dir / "E1_E2_CORRECTION_AUDIT.json"
        overall_gate = e1_gate and e2_gate
        audit = {
            "status": "pass" if overall_gate else "fail",
            "e1_correction_pass": e1_gate,
            "e2_correction_pass": e2_gate,
            "method_status": method["method_status"],
            "final_manuscript_gate": "conditional_on_explicit_resource_only_label",
            "final_pack_must_not_claim_fibre_aware_selector": True,
            "config_hash": config_hash,
            "oracle_manifest_hash": oracle_hash,
            "compilation_manifest_hash": e2_manifest_hash,
            "code_commit": code_commit,
        }
        _write_json(audit_path, audit)

        readme_path = staging / "README_E1_E2_CORRECTION.md"
        readme_path.write_text(
            "# E1/E2 review correction bundle\n\n"
            f"- Overall computational correction status: `{audit['status']}`.\n"
            f"- E1 constructible instances: {sum(constructible_by_family.values())}/60; "
            f"re-exported below-threshold witnesses: {corrected_count}.\n"
            f"- E2 sparse scheduled rows: {len(sparse_rows)}; capacity failures: "
            f"{sparse_infeasible}; common-feasible instances: "
            f"{e2_audit['common_feasible_instance_count']}.\n"
            "- The main sparse table and figure use the same common-feasible instance IDs "
            "for Native, Full, and Selected. Capacity failures are reported separately.\n"
            "- The original representation-specific success-only sparse figure is appendix-only "
            "and conditional on representation-specific successful subsets.\n"
            "- Current selector status: `resource-only`. Existing E3-E6 results may be retained "
            "only under that explicit label; they do not certify a fibre-aware selector.\n\n"
            "See `03_METHOD_STATUS/METHOD_STATUS_E3_E6.md` before building a final manuscript pack.\n",
            encoding="utf-8",
            newline="\n",
        )

        generated = [
            path
            for path in staging.rglob("*")
            if path.is_file() and path.name not in {"PACKAGE_SHA256_MANIFEST.csv", "PACKAGE_SHA256_MANIFEST.sha256"}
        ]
        for path in generated:
            _write_sidecar(path)
        manifest_path = staging / "PACKAGE_SHA256_MANIFEST.csv"
        _manifest(manifest_path, staging, generated + [path.with_suffix(".sha256") for path in generated])
        if not overall_gate:
            raise E1E2CorrectionError(f"Correction gate failed; staging retained: {staging}")
        staging.rename(output_directory)
    except Exception:
        raise

    return audit
