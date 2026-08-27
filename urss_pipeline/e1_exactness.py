"""Formal Step 3 / E1 pointwise-exactness and penalty-tightness pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import time
from dataclasses import dataclass
from fractions import Fraction
from itertools import product
from numbers import Number
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from .polynomial import Polynomial, Support, canonicalize, cubic_supports, evaluate_pubo
from .reference_compiler import compile_reference
from .representations import minimum_pair_cover


class E1ExactnessError(RuntimeError):
    """Formal E1 cannot proceed or failed a mandatory correctness gate."""


E1_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "penalty_setting",
    "n_original",
    "n_aux",
    "x_assignments_checked",
    "xy_assignments_checked",
    "max_pointwise_error",
    "mismatch_count",
    "tie_count",
    "inconsistent_minimiser_count",
    "witness_id",
    "runtime_sec",
    "status",
    "active_pair_count",
    "design_count",
    "target_pair_trials",
    "below_failure_witness_count",
    "selector_status",
    "selection_objective",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


def _fraction(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E1ExactnessError(f"Expected a JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=E1_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in E1_FIELDS})


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


@dataclass(frozen=True)
class MixedRepresentation:
    """One exact cubic design with an explicit penalty assignment."""

    original_width: int
    actions: tuple[Support | None, ...]
    cubic_order: tuple[Support, ...]
    active_pairs: tuple[Support, ...]
    polynomial: Polynomial
    thresholds: Mapping[Support, Fraction]
    penalties: Mapping[Support, Fraction]

    @property
    def n_auxiliary(self) -> int:
        return len(self.active_pairs)

    @property
    def n_qubits(self) -> int:
        return self.original_width + self.n_auxiliary

    @property
    def auxiliary_indices(self) -> dict[Support, int]:
        return {
            pair: self.original_width + index
            for index, pair in enumerate(self.active_pairs, start=1)
        }


def action_options(cubic: Support) -> tuple[Support | None, ...]:
    if len(cubic) != 3:
        raise ValueError(f"Expected a cubic support, received {cubic}")
    left, middle, right = cubic
    return (None, (left, middle), (left, right), (middle, right))


def build_mixed_representation(
    polynomial: Mapping[Support, Number],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    penalty_values: Mapping[Support, Number] | None = None,
    default_margin: Number = 1,
) -> MixedRepresentation:
    """Build the collected mixed quadratic-cubic objective for one design."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    action_tuple = tuple(actions)
    if len(action_tuple) != len(cubics):
        raise ValueError("Exactly one action is required for every cubic support")
    for cubic, action in zip(cubics, action_tuple):
        if action is not None and (
            len(action) != 2 or not set(action).issubset(cubic)
        ):
            raise ValueError(f"Action {action} is not a constituent pair of {cubic}")

    active_pairs = tuple(sorted({pair for pair in action_tuple if pair is not None}))
    auxiliaries = {
        pair: n_original + index
        for index, pair in enumerate(active_pairs, start=1)
    }
    output: list[tuple[Support, Fraction]] = [
        (support, _fraction(coefficient))
        for support, coefficient in canonical.items()
        if len(support) <= 2
    ]
    assigned: dict[Support, list[Fraction]] = {pair: [] for pair in active_pairs}
    for cubic, action in zip(cubics, action_tuple):
        coefficient = _fraction(canonical[cubic])
        if action is None:
            output.append((cubic, coefficient))
            continue
        remaining = next(variable for variable in cubic if variable not in action)
        output.append(((auxiliaries[action], remaining), coefficient))
        assigned[action].append(coefficient)

    thresholds: dict[Support, Fraction] = {}
    penalties: dict[Support, Fraction] = {}
    margin = _fraction(default_margin)
    for pair in active_pairs:
        positive = sum((value for value in assigned[pair] if value > 0), Fraction(0))
        negative = sum((-value for value in assigned[pair] if value < 0), Fraction(0))
        threshold = max(positive, negative)
        penalty = (
            _fraction(penalty_values[pair])
            if penalty_values is not None and pair in penalty_values
            else threshold + margin
        )
        if penalty < 0:
            raise ValueError(f"Penalty for {pair} cannot be negative")
        thresholds[pair] = threshold
        penalties[pair] = penalty
        left, right = pair
        auxiliary = auxiliaries[pair]
        output.extend(
            (
                ((left, right), penalty),
                ((left, auxiliary), -2 * penalty),
                ((right, auxiliary), -2 * penalty),
                ((auxiliary,), 3 * penalty),
            )
        )

    return MixedRepresentation(
        original_width=n_original,
        actions=action_tuple,
        cubic_order=cubics,
        active_pairs=active_pairs,
        polynomial=canonicalize(output),
        thresholds=thresholds,
        penalties=penalties,
    )


def evaluate_pointwise(
    original: Mapping[Support, Number], representation: MixedRepresentation
) -> dict[str, object]:
    """Enumerate every original and auxiliary assignment exactly."""

    started = time.perf_counter()
    mismatch_count = 0
    tie_count = 0
    inconsistent_count = 0
    maximum_error = Fraction(0)
    first_witness: dict[str, object] | None = None
    auxiliary_indices = representation.auxiliary_indices

    for original_bits in product((0, 1), repeat=representation.original_width):
        expected = tuple(
            original_bits[left - 1] * original_bits[right - 1]
            for left, right in representation.active_pairs
        )
        original_energy = _fraction(evaluate_pubo(original, original_bits))
        fibres: list[tuple[Fraction, tuple[int, ...]]] = []
        for auxiliary_bits in product((0, 1), repeat=representation.n_auxiliary):
            energy = _fraction(
                evaluate_pubo(
                    representation.polynomial,
                    original_bits + auxiliary_bits,
                )
            )
            fibres.append((energy, auxiliary_bits))
        minimum = min(energy for energy, _ in fibres)
        minimisers = [bits for energy, bits in fibres if energy == minimum]
        error = abs(original_energy - minimum)
        maximum_error = max(maximum_error, error)
        if error:
            mismatch_count += 1
        if len(minimisers) > 1:
            tie_count += 1
        inconsistent = [bits for bits in minimisers if bits != expected]
        inconsistent_count += len(inconsistent)
        if first_witness is None and (error or inconsistent):
            first_witness = {
                "original_bits": list(original_bits),
                "original_energy": float(original_energy),
                "minimum_reduced_energy": float(minimum),
                "pointwise_error": float(error),
                "expected_auxiliary_bits": list(expected),
                "minimising_auxiliary_bits": [list(bits) for bits in minimisers],
                "inconsistent_minimising_auxiliary_bits": [
                    list(bits) for bits in inconsistent
                ],
                "auxiliary_indices": [
                    {"pair": list(pair), "variable": auxiliary_indices[pair]}
                    for pair in representation.active_pairs
                ],
            }

    return {
        "x_assignments_checked": 1 << representation.original_width,
        "xy_assignments_checked": 1 << representation.n_qubits,
        "max_pointwise_error": float(maximum_error),
        "mismatch_count": mismatch_count,
        "tie_count": tie_count,
        "inconsistent_minimiser_count": inconsistent_count,
        "first_witness": first_witness,
        "runtime_sec": time.perf_counter() - started,
    }


def full_action_vector(polynomial: Mapping[Support, Number]) -> tuple[Support, ...]:
    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    cover = minimum_pair_cover(set(cubics), maximum_pair_candidates=45)
    return tuple(next(pair for pair in cover if set(pair).issubset(cubic)) for cubic in cubics)


def _candidate_vectors(cubics: Sequence[Support]) -> Iterable[tuple[Support | None, ...]]:
    return product(*(action_options(cubic) for cubic in cubics))


def _action_key(
    cubics: Sequence[Support], actions: Sequence[Support | None]
) -> tuple[int, ...]:
    return tuple(
        action_options(cubic).index(action)
        for cubic, action in zip(cubics, actions)
    )


def select_resource_optimal_design(
    polynomial: Mapping[Support, Number],
    *,
    n_original: int,
    selector_config: Mapping[str, object],
    positive_margin: Number,
) -> tuple[tuple[Support | None, ...], dict[str, object]]:
    """Exhaustively select the frozen resource objective on the oracle tier."""

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    certification = selector_config["search_settings"]["certification"]  # type: ignore[index]
    maximum = int(certification["max_complete_candidate_evaluations"])  # type: ignore[index]
    design_count = 4 ** len(cubics)
    if design_count > maximum:
        raise E1ExactnessError(
            f"Oracle selector requires {design_count} complete candidates; frozen budget is {maximum}"
        )
    weights = selector_config["weights"]  # type: ignore[assignment]
    scales = selector_config["scales"]  # type: ignore[assignment]
    limits = selector_config["feasibility_limits"]  # type: ignore[assignment]
    best_actions: tuple[Support | None, ...] | None = None
    best_score: Fraction | None = None
    best_metrics: dict[str, object] | None = None
    feasible_count = 0

    for actions in _candidate_vectors(cubics):
        representation = build_mixed_representation(
            polynomial,
            n_original=n_original,
            actions=actions,
            default_margin=positive_margin,
        )
        compilation = compile_reference(
            representation.polynomial, n_qubits=representation.n_qubits
        )
        maximum_penalty = max(representation.penalties.values(), default=Fraction(0))
        feasible = (
            representation.n_qubits <= int(limits["maximum_qubits"])  # type: ignore[index]
            and compilation.two_qubit_gate_count
            <= int(limits["maximum_two_qubit_gates_per_cost_layer"])  # type: ignore[index]
            and compilation.two_qubit_depth
            <= int(limits["maximum_two_qubit_depth_per_cost_layer"])  # type: ignore[index]
            and maximum_penalty <= _fraction(limits["maximum_penalty"])  # type: ignore[index]
        )
        if not feasible:
            continue
        feasible_count += 1
        score = (
            _fraction(weights["auxiliary_count"])  # type: ignore[index]
            * representation.n_auxiliary
            / _fraction(scales["auxiliary_count"])  # type: ignore[index]
            + _fraction(weights["two_qubit_gate_count"])  # type: ignore[index]
            * compilation.two_qubit_gate_count
            / _fraction(scales["two_qubit_gate_count"])  # type: ignore[index]
            + _fraction(weights["two_qubit_depth"])  # type: ignore[index]
            * compilation.two_qubit_depth
            / _fraction(scales["two_qubit_depth"])  # type: ignore[index]
            + _fraction(weights["maximum_penalty"])  # type: ignore[index]
            * maximum_penalty
            / _fraction(scales["maximum_penalty"])  # type: ignore[index]
        )
        if best_score is None or (score, _action_key(cubics, actions)) < (
            best_score,
            _action_key(cubics, best_actions or ()),
        ):
            best_score = score
            best_actions = tuple(actions)
            best_metrics = {
                "n_auxiliary": representation.n_auxiliary,
                "n_qubits": representation.n_qubits,
                "two_qubit_gate_count": compilation.two_qubit_gate_count,
                "two_qubit_depth": compilation.two_qubit_depth,
                "maximum_penalty": float(maximum_penalty),
            }

    if best_actions is None or best_score is None or best_metrics is None:
        raise E1ExactnessError("Frozen selector found no feasible oracle design")
    return best_actions, {
        "status": "certified_complete_resource_objective",
        "design_count": design_count,
        "feasible_design_count": feasible_count,
        "objective": float(best_score),
        "objective_exact": f"{best_score.numerator}/{best_score.denominator}",
        "metrics": best_metrics,
        "fibre_risk_guardrail": "not_configured_in_frozen_v1",
    }


def matched_random_actions(
    polynomial: Mapping[Support, Number],
    *,
    target_auxiliary_count: int,
    selected_actions: Sequence[Support | None],
    instance_id: str,
    seed_bundle: Sequence[int],
) -> list[tuple[int, tuple[Support | None, ...]]]:
    """Sample action vectors matched exactly on distinct auxiliary count."""

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    eligible = [
        tuple(actions)
        for actions in _candidate_vectors(cubics)
        if len({action for action in actions if action is not None})
        == target_auxiliary_count
    ]
    selected_tuple = tuple(selected_actions)
    alternatives = [actions for actions in eligible if actions != selected_tuple]
    population = alternatives or eligible
    if not population:
        raise E1ExactnessError("No matched-random design satisfies auxiliary-count matching")
    sampled: list[tuple[int, tuple[Support | None, ...]]] = []
    for base_seed in seed_bundle:
        digest = hashlib.sha256(f"{instance_id}:{base_seed}".encode("ascii")).digest()
        derived_seed = int.from_bytes(digest[:8], "big")
        sampled.append((base_seed, random.Random(derived_seed).choice(population)))
    return sampled


def _aggregate_trials(
    trials: Sequence[dict[str, object]],
    *,
    status: str,
) -> dict[str, object]:
    witnesses = [trial.get("witness_id") for trial in trials if trial.get("witness_id")]
    return {
        "x_assignments_checked": sum(int(trial["x_assignments_checked"]) for trial in trials),
        "xy_assignments_checked": sum(int(trial["xy_assignments_checked"]) for trial in trials),
        "max_pointwise_error": max(float(trial["max_pointwise_error"]) for trial in trials),
        "mismatch_count": sum(int(trial["mismatch_count"]) for trial in trials),
        "tie_count": sum(int(trial["tie_count"]) for trial in trials),
        "inconsistent_minimiser_count": sum(
            int(trial["inconsistent_minimiser_count"]) for trial in trials
        ),
        "witness_id": witnesses[0] if witnesses else "",
        "runtime_sec": sum(float(trial["runtime_sec"]) for trial in trials),
        "target_pair_trials": len(trials),
        "below_failure_witness_count": sum(
            1 for trial in trials if trial.get("penalty_setting") == "below_threshold" and trial.get("witness_id")
        ),
        "status": status,
    }


def evaluate_design_settings(
    original: Mapping[Support, Number],
    *,
    n_original: int,
    actions_by_seed: Sequence[tuple[int | None, Sequence[Support | None]]],
    representation_name: str,
    below_delta: Number,
    above_epsilon: Number,
    witness_prefix: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Run below/at per active pair and one strict run per design."""

    rows: list[dict[str, object]] = []
    witnesses: list[dict[str, object]] = []
    trial_records: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, object]]] = {
        "below_threshold": [],
        "at_threshold": [],
        "above_threshold": [],
        "not_applicable": [],
    }

    for seed, actions in actions_by_seed:
        strict = build_mixed_representation(
            original,
            n_original=n_original,
            actions=actions,
            default_margin=above_epsilon,
        )
        if not strict.active_pairs:
            result = evaluate_pointwise(original, strict)
            trial = {
                **result,
                "penalty_setting": "not_applicable",
                "target_pair": None,
                "random_seed": seed,
                "witness_id": "",
            }
            grouped["not_applicable"].append(trial)
            trial_records.append(trial)
            continue

        strict_result = evaluate_pointwise(original, strict)
        strict_witness_id = ""
        if strict_result["first_witness"] is not None:
            strict_witness_id = f"{witness_prefix}_above_{seed if seed is not None else 'selected'}"
            witnesses.append(
                {
                    "witness_id": strict_witness_id,
                    "representation": representation_name,
                    "penalty_setting": "above_threshold",
                    "target_pair": None,
                    "random_seed": seed,
                    **strict_result["first_witness"],  # type: ignore[arg-type]
                }
            )
        strict_trial = {
            **strict_result,
            "penalty_setting": "above_threshold",
            "target_pair": None,
            "random_seed": seed,
            "witness_id": strict_witness_id,
        }
        grouped["above_threshold"].append(strict_trial)
        trial_records.append(strict_trial)

        for setting in ("below_threshold", "at_threshold"):
            for pair in strict.active_pairs:
                penalty_values = dict(strict.penalties)
                penalty_values[pair] = strict.thresholds[pair]
                if setting == "below_threshold":
                    penalty_values[pair] -= _fraction(below_delta)
                representation = build_mixed_representation(
                    original,
                    n_original=n_original,
                    actions=actions,
                    penalty_values=penalty_values,
                    default_margin=above_epsilon,
                )
                result = evaluate_pointwise(original, representation)
                witness_id = ""
                if result["first_witness"] is not None:
                    pair_label = f"{pair[0]}_{pair[1]}"
                    witness_id = (
                        f"{witness_prefix}_{setting}_{pair_label}_"
                        f"{seed if seed is not None else 'selected'}"
                    )
                    witnesses.append(
                        {
                            "witness_id": witness_id,
                            "representation": representation_name,
                            "penalty_setting": setting,
                            "target_pair": list(pair),
                            "threshold": float(strict.thresholds[pair]),
                            "penalty": float(penalty_values[pair]),
                            "random_seed": seed,
                            **result["first_witness"],  # type: ignore[arg-type]
                        }
                    )
                trial = {
                    **result,
                    "penalty_setting": setting,
                    "target_pair": list(pair),
                    "threshold": float(strict.thresholds[pair]),
                    "penalty": float(penalty_values[pair]),
                    "random_seed": seed,
                    "witness_id": witness_id,
                }
                grouped[setting].append(trial)
                trial_records.append(trial)

    for setting in ("not_applicable", "below_threshold", "at_threshold", "above_threshold"):
        trials = grouped[setting]
        if not trials:
            continue
        strict_failure = setting == "above_threshold" and any(
            int(trial["mismatch_count"]) != 0
            or int(trial["inconsistent_minimiser_count"]) != 0
            for trial in trials
        )
        threshold_failure = setting == "at_threshold" and any(
            int(trial["mismatch_count"]) != 0 for trial in trials
        )
        rows.append(
            {
                "penalty_setting": setting,
                **_aggregate_trials(
                    trials,
                    status="fail" if strict_failure or threshold_failure else "pass",
                ),
            }
        )
    return rows, witnesses, trial_records


def _verify_hash(path: Path, sidecar: Path) -> str:
    if not path.is_file() or not sidecar.is_file():
        raise E1ExactnessError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = _sha256(path)
    declared = sidecar.read_text(encoding="utf-8").strip()
    if actual != declared:
        raise E1ExactnessError(f"Frozen hash mismatch: {path}")
    return actual


def verify_data_freeze(
    *, config_path: Path, config_hash_path: Path, data_directory: Path
) -> dict[str, object]:
    """Re-run the non-negotiable Step 2 data-freeze gate before E1."""

    config_hash = _verify_hash(config_path, config_hash_path)
    snapshot = data_directory / "config_snapshot_frozen.yaml"
    snapshot_hash = data_directory / "config_snapshot_frozen.sha256"
    if _verify_hash(snapshot, snapshot_hash) != config_hash:
        raise E1ExactnessError("Frozen data config snapshot differs from formal config")
    manifest_dir = data_directory / "manifests"
    oracle_path = manifest_dir / "oracle_v1.csv"
    oracle_hash = _verify_hash(oracle_path, manifest_dir / "oracle_v1.sha256")
    bundle_path = manifest_dir / "manifest_bundle_v1.json"
    bundle_hash = _verify_hash(bundle_path, manifest_dir / "manifest_bundle_v1.sha256")
    audit_path = data_directory / "benchmark_audit_v1.json"
    _verify_hash(audit_path, data_directory / "benchmark_audit_v1.sha256")
    audit = _load_json(audit_path)
    required = (
        audit.get("status") == "pass"
        and int(audit.get("formal_instance_count", -1)) == 312
        and audit.get("formal_manifests_created") is True
        and audit.get("formal_split_created") is True
        and int(audit.get("split_leakage_count", -1)) == 0
        and audit.get("representation_split_consistent") is True
        and int(audit.get("validation_failure_count", -1)) == 0
        and int(audit.get("qmax_feasibility_failure_count", -1)) == 0
        and audit.get("test_split_frozen_before_results") is True
        and audit.get("formal_results_created") is False
        and int(audit.get("qmax", -1)) == 12
        and audit.get("manifest_bundle_sha256") == bundle_hash
    )
    if not required:
        raise E1ExactnessError("Formal Step 2 audit does not pass the E1 data-freeze gate")
    oracle_rows = _read_csv(oracle_path)
    counts: dict[str, int] = {}
    splits: dict[str, str] = {}
    for row in oracle_rows:
        counts[row["family"]] = counts.get(row["family"], 0) + 1
        if row["ground_truth_status"] != "optimal":
            raise E1ExactnessError(f"Oracle ground truth is not exact: {row['instance_id']}")
        previous = splits.setdefault(row["instance_id"], row["split"])
        if previous != row["split"]:
            raise E1ExactnessError(f"Instance crosses splits: {row['instance_id']}")
    if counts != {"cubic_spin_glass": 30, "max3sat": 30}:
        raise E1ExactnessError(f"Wrong frozen oracle counts: {counts}")
    return {
        "config_hash": config_hash,
        "oracle_manifest_hash": oracle_hash,
        "manifest_bundle_hash": bundle_hash,
        "oracle_rows": oracle_rows,
    }


def _canonical_polynomial(path: Path) -> tuple[str, Polynomial]:
    record = _load_json(path)
    terms = record.get("terms")
    if not isinstance(terms, list):
        raise E1ExactnessError(f"Malformed canonical record: {path}")
    polynomial = canonicalize(
        (tuple(item["support"]), item["coefficient"])  # type: ignore[index]
        for item in terms
    )
    return str(record["family"]), polynomial


def _latex_table(rows: Sequence[Mapping[str, object]]) -> str:
    totals: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in rows:
        key = (str(row["family"]), str(row["representation"]), str(row["penalty_setting"]))
        item = totals.setdefault(
            key,
            {"instances": 0, "x": 0, "xy": 0, "mismatch": 0, "ties": 0, "inconsistent": 0, "witnesses": 0, "runtime": 0.0},
        )
        item["instances"] += 1
        item["x"] += int(row["x_assignments_checked"])
        item["xy"] += int(row["xy_assignments_checked"])
        item["mismatch"] += int(row["mismatch_count"])
        item["ties"] += int(row["tie_count"])
        item["inconsistent"] += int(row["inconsistent_minimiser_count"])
        item["witnesses"] += int(row["below_failure_witness_count"])
        item["runtime"] += float(row["runtime_sec"])
    lines = [
        "% Auto-generated formal E1 summary; do not edit by hand.",
        "\\begin{tabular}{lllrrrrrrr}",
        "\\toprule",
        "Family & Representation & Setting & Instances & $x$ checks & $(x,y)$ checks & Mismatch & Ties & Inconsistent & Witnesses \\\\",
        "\\midrule",
    ]
    for (family, representation, setting), item in sorted(totals.items()):
        family_tex = family.replace("_", "\\_")
        representation_tex = representation.replace("_", "\\_")
        setting_tex = setting.replace("_", "\\_")
        lines.append(
            f"{family_tex} & {representation_tex} & {setting_tex} & "
            f"{int(item['instances'])} & {int(item['x'])} & "
            f"{int(item['xy'])} & {int(item['mismatch'])} & {int(item['ties'])} & "
            f"{int(item['inconsistent'])} & {int(item['witnesses'])} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def run_e1_exactness_pipeline(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    data_directory: str | Path,
    results_directory: str | Path,
    tables_directory: str | Path,
    code_commit: str,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
    progress=None,
) -> dict[str, object]:
    """Run formal E1 against the immutable frozen oracle manifest."""

    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    targets = (
        results_directory / "e1_exactness.csv",
        results_directory / "e1_penalty_witnesses.json",
        results_directory / "e1_validation_summary.json",
        tables_directory / "table_e1_exactness.tex",
    )
    if any(path.exists() for path in targets):
        raise FileExistsError("Formal E1 output already exists; refusing overwrite")
    staging = results_directory.parent / "e1_step3_building"
    if staging.exists():
        raise E1ExactnessError(f"Incomplete E1 staging directory exists: {staging}")

    freeze = verify_data_freeze(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["status"] != "frozen" or config["freeze_gate"]["blocked"]:
        raise E1ExactnessError("E1 requires the formal frozen configuration")
    below_delta = config["penalty_tightness"]["below_threshold_delta"]
    above_epsilon = config["penalty_tightness"]["above_threshold_epsilon"]
    selector_config = config["selector"]
    random_config = config["representations"]["matched_random"]
    if random_config["match_on"] != "auxiliary_count":
        raise E1ExactnessError("Formal E1 v1 requires auxiliary-count matched random designs")

    staging.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    witnesses: list[dict[str, object]] = []
    trial_records: list[dict[str, object]] = []
    selector_records: list[dict[str, object]] = []
    try:
        oracle_rows = freeze["oracle_rows"]
        for index, manifest_row in enumerate(oracle_rows, start=1):  # type: ignore[assignment]
            instance_id = manifest_row["instance_id"]
            canonical_path = data_directory / manifest_row["canonical_file"]
            if _sha256(canonical_path) != manifest_row["canonical_sha256"]:
                raise E1ExactnessError(f"Canonical coefficient hash mismatch: {instance_id}")
            family, polynomial = _canonical_polynomial(canonical_path)
            if family != manifest_row["family"]:
                raise E1ExactnessError(f"Canonical family mismatch: {instance_id}")
            n_original = int(manifest_row["n"])
            cubics = tuple(sorted(cubic_supports(polynomial)))
            selected_actions, selector_record = select_resource_optimal_design(
                polynomial,
                n_original=n_original,
                selector_config=selector_config,
                positive_margin=above_epsilon,
            )
            selected_strict = build_mixed_representation(
                polynomial,
                n_original=n_original,
                actions=selected_actions,
                default_margin=above_epsilon,
            )
            if all(action is None for action in selected_actions):
                selected_classification = "all_native_endpoint"
            elif all(action is not None for action in selected_actions):
                selected_classification = "fully_reduced_endpoint"
            else:
                selected_classification = "strictly_mixed_selective"
            selector_records.append(
                {
                    "instance_id": instance_id,
                    "family": family,
                    "split": manifest_row["split"],
                    "actions": [list(action) if action is not None else None for action in selected_actions],
                    "active_pairs": [list(pair) for pair in selected_strict.active_pairs],
                    "classification": selected_classification,
                    **selector_record,
                }
            )
            designs: list[tuple[str, list[tuple[int | None, Sequence[Support | None]]], str, float]] = [
                ("all_native", [(None, (None,) * len(cubics))], "endpoint", 0.0),
                ("fully_quadratized", [(None, full_action_vector(polynomial))], "endpoint", 0.0),
                (
                    "selective",
                    [(None, selected_actions)],
                    str(selector_record["status"]),
                    float(selector_record["objective"]),
                ),
            ]
            matched = matched_random_actions(
                polynomial,
                target_auxiliary_count=selected_strict.n_auxiliary,
                selected_actions=selected_actions,
                instance_id=instance_id,
                seed_bundle=[int(seed) for seed in random_config["seed_bundle"]],
            )
            designs.append(("matched_random_selective", matched, "matched_auxiliary_count", float(selector_record["objective"])))

            for representation_name, actions_by_seed, selector_status, objective in designs:
                design_rows, design_witnesses, design_trials = evaluate_design_settings(
                    polynomial,
                    n_original=n_original,
                    actions_by_seed=actions_by_seed,
                    representation_name=representation_name,
                    below_delta=below_delta,
                    above_epsilon=above_epsilon,
                    witness_prefix=f"{instance_id}_{representation_name}",
                )
                n_aux_values = {
                    build_mixed_representation(
                        polynomial,
                        n_original=n_original,
                        actions=actions,
                        default_margin=above_epsilon,
                    ).n_auxiliary
                    for _, actions in actions_by_seed
                }
                if len(n_aux_values) != 1:
                    raise E1ExactnessError("Matched-random auxiliary count is inconsistent")
                n_aux = next(iter(n_aux_values))
                for row in design_rows:
                    rows.append(
                        {
                            "instance_id": instance_id,
                            "family": family,
                            "split": manifest_row["split"],
                            "representation": representation_name,
                            "n_original": n_original,
                            "n_aux": n_aux,
                            "active_pair_count": n_aux,
                            "design_count": len(actions_by_seed),
                            "selector_status": selector_status,
                            "selection_objective": objective,
                            "config_hash": freeze["config_hash"],
                            "manifest_hash": freeze["oracle_manifest_hash"],
                            "code_commit": code_commit,
                            **row,
                        }
                    )
                for witness in design_witnesses:
                    witness["instance_id"] = instance_id
                    witness["family"] = family
                    witness["split"] = manifest_row["split"]
                for trial in design_trials:
                    trial_records.append(
                        {
                            "instance_id": instance_id,
                            "family": family,
                            "split": manifest_row["split"],
                            "representation": representation_name,
                            **trial,
                        }
                    )
                witnesses.extend(design_witnesses)
            if progress:
                progress(f"E1 {index}/{len(oracle_rows)}: {family} {instance_id} pass")

        strict_rows = [row for row in rows if row["penalty_setting"] == "above_threshold"]
        threshold_rows = [row for row in rows if row["penalty_setting"] == "at_threshold"]
        strict_mismatches = sum(int(row["mismatch_count"]) for row in strict_rows)
        strict_inconsistent = sum(int(row["inconsistent_minimiser_count"]) for row in strict_rows)
        threshold_mismatches = sum(int(row["mismatch_count"]) for row in threshold_rows)
        if strict_mismatches or strict_inconsistent or threshold_mismatches:
            raise E1ExactnessError(
                "Mandatory E1 exactness gate failed; E2-E6 must not continue"
            )
        summary = {
            "status": "pass",
            "scope": "formal_step3_e1_pointwise_exactness_and_penalty_tightness",
            "oracle_instance_count": len(oracle_rows),
            "family_counts": {
                family: sum(1 for row in oracle_rows if row["family"] == family)
                for family in ("max3sat", "cubic_spin_glass")
            },
            "summary_row_count": len(rows),
            "trial_count": len(trial_records),
            "x_assignments_checked": sum(int(row["x_assignments_checked"]) for row in rows),
            "xy_assignments_checked": sum(int(row["xy_assignments_checked"]) for row in rows),
            "strict_mismatch_count": strict_mismatches,
            "strict_inconsistent_minimiser_count": strict_inconsistent,
            "threshold_mismatch_count": threshold_mismatches,
            "threshold_tie_count": sum(int(row["tie_count"]) for row in threshold_rows),
            "below_threshold_mismatch_count": sum(
                int(row["mismatch_count"])
                for row in rows
                if row["penalty_setting"] == "below_threshold"
            ),
            "below_threshold_failure_witness_count": sum(
                int(row["below_failure_witness_count"])
                for row in rows
            ),
            "witness_count": len(witnesses),
            "selected_design_classification_counts": {
                classification: sum(
                    1
                    for record in selector_records
                    if record["classification"] == classification
                )
                for classification in (
                    "all_native_endpoint",
                    "strictly_mixed_selective",
                    "fully_reduced_endpoint",
                )
            },
            "matched_random_degenerate_to_native_count": sum(
                1
                for record in selector_records
                if record["classification"] == "all_native_endpoint"
            ),
            "canonical_coefficient_hash_mismatch_count": 0,
            "all_above_threshold_pointwise_exact": True,
            "all_above_threshold_unique_consistent": True,
            "all_at_threshold_pointwise_exact": True,
            "e2_e6_may_continue": True,
            "selector_fibre_risk_guardrail": "not_configured_in_frozen_v1",
            "config_hash": freeze["config_hash"],
            "oracle_manifest_hash": freeze["oracle_manifest_hash"],
            "manifest_bundle_hash": freeze["manifest_bundle_hash"],
            "code_commit": code_commit,
        }
        staged_results = staging / "results"
        staged_tables = staging / "tables"
        exactness_path = staged_results / "e1_exactness.csv"
        witnesses_path = staged_results / "e1_penalty_witnesses.json"
        summary_path = staged_results / "e1_validation_summary.json"
        trials_path = staged_results / "e1_penalty_trials.json"
        selector_path = staged_results / "e1_selected_designs.json"
        table_path = staged_tables / "table_e1_exactness.tex"
        _write_csv(exactness_path, rows)
        _write_json(
            witnesses_path,
            {
                "schema_version": "e1_penalty_witnesses_v1",
                "witnesses": witnesses,
            },
        )
        _write_json(summary_path, summary)
        _write_json(trials_path, {"schema_version": "e1_penalty_trials_v1", "trials": trial_records})
        _write_json(selector_path, {"schema_version": "e1_selected_designs_v1", "designs": selector_records})
        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(_latex_table(rows), encoding="utf-8", newline="\n")
        for path in (exactness_path, witnesses_path, summary_path, trials_path, selector_path, table_path):
            _write_hash(path)

        results_directory.mkdir(parents=True, exist_ok=True)
        tables_directory.mkdir(parents=True, exist_ok=True)
        for path in staged_results.iterdir():
            shutil.move(str(path), results_directory / path.name)
        for path in staged_tables.iterdir():
            shutil.move(str(path), tables_directory / path.name)

        if assumptions_path is not None:
            assumptions = Path(assumptions_path)
            with assumptions.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    "\n## Formal Step 3 / E1 exactness (v1)\n\n"
                    "- Data-freeze gate revalidated before E1; config and oracle manifest hashes were locked.\n"
                    "- Oracle selection used complete deterministic enumeration under the frozen 65,536-candidate budget and frozen resource objective.\n"
                    "- The frozen v1 selector config does not declare a fibre-risk threshold; E1 records this transparently and does not invent one.\n"
                    "- Below/at threshold trials perturb one active pair at a time while all other penalties remain strict.\n"
                    "- E2-E6 may continue only because every strict trial was pointwise exact with a unique consistent auxiliary fibre.\n"
                )
        if run_commands_path is not None:
            commands = Path(run_commands_path)
            with commands.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(
                    "\n## Formal Step 3 / E1 command (v1)\n\n"
                    "See `RUN_COMMANDS_FORMAL_STEP3_E1.md`; the result rows record the exact committed implementation hash.\n"
                )
        if progress:
            progress("E1 EXACTNESS GATE: pass")
        return summary
    except Exception:
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
