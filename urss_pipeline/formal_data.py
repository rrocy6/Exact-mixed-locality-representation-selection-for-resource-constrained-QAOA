"""Formal Step 2 data generation and manifest-freeze pipeline."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from fractions import Fraction
from itertools import product
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Sequence

from .configuration import validate_experiment_config
from .generators import derive_seed, generate_max3sat, generate_spin_glass
from .identity import canonical_json, sha256_bytes, stable_instance_json
from .metadata import canonical_metadata, exact_ground_truth, polynomial_for_instance
from .reference_compiler import boolean_to_pauli
from .representations import fully_quadratize
from .smoke import run_smoke_batch
from .validation import validate_direct_vs_canonical, validate_raw_instance


class FormalDataError(ValueError):
    """Raised when the Step 2 data-freeze gate cannot pass."""


MANIFEST_FIELDS = [
    "instance_id",
    "family",
    "tier",
    "split",
    "n",
    "regime",
    "generator_mode",
    "instance_seed",
    "raw_file",
    "raw_sha256",
    "canonical_file",
    "canonical_sha256",
    "validation_status",
    "ground_truth_status",
    "qmax",
    "all_native_width",
    "fully_quadratized_width",
    "selective_width_upper_bound",
    "matched_random_width_upper_bound",
    "all_four_within_qmax",
    "origin",
    "config_sha256",
    "generation_plan_sha256",
    "code_commit",
]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FormalDataError(f"Expected a JSON object: {path}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required for formal Step 2") from error
    value = yaml.safe_load(path.read_bytes())
    if not isinstance(value, dict):
        raise FormalDataError(f"Expected a YAML mapping: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    fieldnames: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames or (list(rows[0]) if rows else []))
    if not names:
        raise ValueError(f"CSV field names are required: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=names,
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_hash_sidecar(path: Path) -> str:
    digest = _sha256_file(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def _require_formal_config(
    config_path: Path, config_hash_path: Path
) -> tuple[dict[str, Any], str]:
    report = validate_experiment_config(config_path)
    if report["declared_status"] != "frozen":
        raise FormalDataError("Step 2 requires status=frozen")
    if report["freeze_blocked"] or report["remaining_blocker_count"] != 0:
        raise FormalDataError("Step 2 requires a zero-blocker formal config")
    declared_hash = config_hash_path.read_text(encoding="utf-8").strip()
    if declared_hash != report["sha256"]:
        raise FormalDataError("Formal config hash sidecar does not match")
    config = _load_yaml(config_path)
    if config.get("config_id") != "experiment_config_v1":
        raise FormalDataError("Unexpected formal config_id")
    return config, declared_hash


def _prepare_staging(output: Path) -> Path:
    if output.exists():
        raise FileExistsError(
            f"Formal data output already exists: {output}. Refusing overwrite."
        )
    staging = output.with_name(output.name + "_step2_building")
    if staging.exists():
        raise FileExistsError(
            f"Previous incomplete Step 2 staging directory exists: {staging}"
        )
    staging.mkdir(parents=True)
    return staging


def _document_before_update(path: Path, marker: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Required project document not found: {path}")
    content = path.read_text(encoding="utf-8")
    if marker in content:
        raise FormalDataError(f"Document already contains Step 2 marker: {path}")
    return content


def _append_document(path: Path, original: str, section: str) -> None:
    separator = "" if original.endswith("\n") else "\n"
    path.write_text(
        original + separator + "\n" + section.rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _regime_values(config: Mapping[str, Any], family: str) -> dict[str, float]:
    families = config["benchmark"]["families"]
    if family == "max3sat":
        return dict(families["weighted_max3sat"]["clause_density_targets"])
    if family == "cubic_spin_glass":
        return dict(
            families["cubic_spin_glass"]["hyperedges_per_variable_targets"]
        )
    raise FormalDataError(f"Unsupported family: {family}")


def _proposal_modes(config: Mapping[str, Any], family: str) -> list[str]:
    key = "weighted_max3sat" if family == "max3sat" else "cubic_spin_glass"
    return list(config["benchmark"]["families"][key]["proposal_modes"])


def _profiles(
    config: Mapping[str, Any], family: str, tier: str
) -> list[dict[str, object]]:
    n_values = list(config["dataset"]["tiers"][tier]["n_values"])
    regimes = _regime_values(config, family)
    result = []
    for n in n_values:
        for regime in ("low", "intermediate", "high"):
            for mode in _proposal_modes(config, family):
                result.append(
                    {
                        "n": int(n),
                        "regime": regime,
                        "level": regimes[regime],
                        "generator_mode": mode,
                    }
                )
    return result


def _anchor_pair_count(family: str, n: int, level: float) -> int | None:
    if family == "max3sat":
        target = max(1, round(level * n))
        count = max(2, math.ceil(target / max(1, 8 * (n - 2))))
    else:
        target = min(max(1, round(level * n)), math.comb(n, 3))
        count = max(2, math.ceil(target / max(1, n - 2)))
    return min(count, math.comb(n, 2))


def _generate(
    *,
    family: str,
    profile: Mapping[str, object],
    master_seed: int,
    instance_seed: int,
    generator_version: str,
) -> dict[str, Any]:
    n = int(profile["n"])
    mode = str(profile["generator_mode"])
    level = float(profile["level"])
    anchor_count = (
        _anchor_pair_count(family, n, level) if mode == "anchor_pair" else None
    )
    common = {
        "n": n,
        "generator_mode": mode,
        "master_seed": master_seed,
        "instance_seed": instance_seed,
        "generator_version": generator_version,
        "anchor_pair_count": anchor_count,
    }
    if family == "max3sat":
        return generate_max3sat(**common, clause_density=level)
    if family == "cubic_spin_glass":
        return generate_spin_glass(**common, hyperedges_per_variable=level)
    raise FormalDataError(f"Unsupported family: {family}")


def _assignment_points(
    n: int, *, maximum: int, seed: int
) -> tuple[Iterable[tuple[int, ...]], str]:
    total = 1 << n
    if total <= maximum:
        return product((0, 1), repeat=n), "exhaustive"
    rng = random.Random(seed)
    indices = rng.sample(range(total), maximum)
    return (
        tuple((index >> shift) & 1 for shift in reversed(range(n)))
        for index in indices
    ), "fixed_seed_spot_check"


def _validate_boolean_vs_ising(
    instance: Mapping[str, Any], *, validation_seed: int, maximum: int
) -> dict[str, object]:
    polynomial = polynomial_for_instance(instance)
    pauli = boolean_to_pauli(polynomial)
    n = int(instance["problem"]["n"])
    assignments, method = _assignment_points(
        n, maximum=maximum, seed=validation_seed
    )
    checked = 0
    maximum_mismatch = Fraction(0)
    for bits in assignments:
        checked += 1
        boolean_energy = Fraction(str(0))
        for support, coefficient in polynomial.items():
            term = Fraction(str(coefficient))
            for variable in support:
                term *= bits[variable - 1]
            boolean_energy += term
        z = tuple(1 - 2 * bit for bit in bits)
        ising_energy = Fraction(0)
        for support, coefficient in pauli.items():
            term = coefficient
            for variable in support:
                term *= z[variable - 1]
            ising_energy += term
        mismatch = abs(boolean_energy - ising_energy)
        maximum_mismatch = max(maximum_mismatch, mismatch)
        if mismatch:
            raise FormalDataError(
                f"Boolean/Ising mismatch for {instance['instance_id']} at {bits}"
            )
    return {
        "status": "pass",
        "method": method,
        "assignments_checked": checked,
        "maximum_pointwise_mismatch": float(maximum_mismatch),
    }


def _split_counts(count: int, fractions: Mapping[str, float]) -> dict[str, int]:
    order = ["train", "validation", "test"]
    raw = {name: count * float(fractions[name]) for name in order}
    result = {name: math.floor(raw[name]) for name in order}
    remaining = count - sum(result.values())
    ranking = sorted(
        order,
        key=lambda name: (-(raw[name] - result[name]), order.index(name)),
    )
    for name in ranking[:remaining]:
        result[name] += 1
    return result


def _assign_splits(
    memberships: Mapping[str, Sequence[str]],
    instances: Mapping[str, Mapping[str, Any]],
    *,
    fractions: Mapping[str, float],
    split_seed: int,
) -> dict[str, str]:
    assigned: dict[str, str] = {}
    for tier in ("oracle", "qaoa", "compilation"):
        for family in ("max3sat", "cubic_spin_glass"):
            ids = sorted(
                instance_id
                for instance_id in memberships[tier]
                if instances[instance_id]["family"] == family
            )
            rng = random.Random(derive_seed(split_seed, tier, family))
            rng.shuffle(ids)
            counts = _split_counts(len(ids), fractions)
            cursor = 0
            for split in ("train", "validation", "test"):
                for instance_id in ids[cursor : cursor + counts[split]]:
                    if instance_id in assigned and assigned[instance_id] != split:
                        raise FormalDataError(
                            f"Split inconsistency for {instance_id}"
                        )
                    assigned[instance_id] = split
                cursor += counts[split]
    return assigned


def _select_noise_subset(
    qaoa_ids: Sequence[str],
    *,
    instances: Mapping[str, Mapping[str, Any]],
    records: Mapping[str, Mapping[str, Any]],
    target_per_family: int,
) -> list[str]:
    selected: list[str] = []
    for family in ("max3sat", "cubic_spin_glass"):
        bins: defaultdict[tuple[object, ...], list[str]] = defaultdict(list)
        for instance_id in qaoa_ids:
            if instances[instance_id]["family"] != family:
                continue
            record = records[instance_id]
            key = (
                record["n"],
                record["regime"],
                record["generator_mode"],
            )
            bins[key].append(instance_id)
        for key in bins:
            bins[key].sort(
                key=lambda item: (
                    float(records[item]["pair_reuse_score"]),
                    item,
                )
            )
        ordered_bins = sorted(bins)
        family_selected: list[str] = []
        round_index = 0
        while len(family_selected) < target_per_family:
            progress = False
            for key in ordered_bins:
                if round_index < len(bins[key]):
                    family_selected.append(bins[key][round_index])
                    progress = True
                    if len(family_selected) == target_per_family:
                        break
            if not progress:
                raise FormalDataError(
                    f"Insufficient QAOA instances for noise subset: {family}"
                )
            round_index += 1
        selected.extend(family_selected)
    return selected


def _canonical_payload(instance: Mapping[str, Any]) -> dict[str, object]:
    polynomial = polynomial_for_instance(instance)
    return {
        "instance_id": instance["instance_id"],
        "family": instance["family"],
        "terms": [
            {"support": list(support), "coefficient": coefficient}
            for support, coefficient in polynomial.items()
        ],
    }


def _manifest_row(
    *,
    instance_id: str,
    tier: str,
    split: str,
    instance: Mapping[str, Any],
    record: Mapping[str, Any],
    ground_truth_status: str,
    qmax: int,
    config_hash: str,
    plan_hash: str,
    code_commit: str,
) -> dict[str, object]:
    qaoa = record.get("qaoa", {})
    return {
        "instance_id": instance_id,
        "family": instance["family"],
        "tier": tier,
        "split": split,
        "n": record["n"],
        "regime": record["regime"],
        "generator_mode": record["generator_mode"],
        "instance_seed": record["instance_seed"],
        "raw_file": record["raw_file"],
        "raw_sha256": record["raw_sha256"],
        "canonical_file": record["canonical_file"],
        "canonical_sha256": record["canonical_sha256"],
        "validation_status": "pass",
        "ground_truth_status": ground_truth_status,
        "qmax": qmax if tier == "qaoa" else "",
        "all_native_width": qaoa.get("all_native_width", ""),
        "fully_quadratized_width": qaoa.get(
            "fully_quadratized_width", ""
        ),
        "selective_width_upper_bound": qaoa.get(
            "selective_width_upper_bound", ""
        ),
        "matched_random_width_upper_bound": qaoa.get(
            "matched_random_width_upper_bound", ""
        ),
        "all_four_within_qmax": qaoa.get("all_four_within_qmax", ""),
        "origin": record["origin"],
        "config_sha256": config_hash,
        "generation_plan_sha256": plan_hash,
        "code_commit": code_commit,
    }


def _coverage_summary(
    ids: Sequence[str], records: Mapping[str, Mapping[str, Any]]
) -> dict[str, object]:
    return {
        "count": len(ids),
        "n_values": sorted({int(records[item]["n"]) for item in ids}),
        "regimes": sorted({str(records[item]["regime"]) for item in ids}),
        "generator_modes": sorted(
            {str(records[item]["generator_mode"]) for item in ids}
        ),
        "m3_zero_count": sum(int(records[item]["m3"]) == 0 for item in ids),
        "pair_reuse_min": min(
            (float(records[item]["pair_reuse_score"]) for item in ids),
            default=0.0,
        ),
        "pair_reuse_max": max(
            (float(records[item]["pair_reuse_score"]) for item in ids),
            default=0.0,
        ),
        "Delta2_min": min(
            (int(records[item]["Delta2"]) for item in ids), default=0
        ),
        "Delta2_max": max(
            (int(records[item]["Delta2"]) for item in ids), default=0
        ),
    }


def _audit_html(audit: Mapping[str, Any]) -> str:
    counts = audit["manifest_counts"]
    rows = []
    for manifest, by_family in counts.items():
        for family, count in by_family.items():
            rows.append(
                f"<tr><td>{html.escape(manifest)}</td>"
                f"<td>{html.escape(family)}</td><td>{count}</td></tr>"
            )
    exclusions = "".join(
        f"<li>{html.escape(str(key))}: {value}</li>"
        for key, value in audit["exclusion_counts"].items()
    ) or "<li>none</li>"
    holes = "".join(
        f"<li>{html.escape(item)}</li>" for item in audit["coverage_notes"]
    ) or "<li>No documented coverage limitation.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>URSS benchmark audit v1</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:2rem auto;line-height:1.45}}table{{border-collapse:collapse}}th,td{{border:1px solid #bbb;padding:.4rem .7rem}}.pass{{color:#087830;font-weight:bold}}code{{background:#f3f3f3;padding:.1rem .25rem}}</style></head>
<body><h1>URSS benchmark audit v1</h1>
<p>Status: <span class="pass">{html.escape(str(audit['status']))}</span></p>
<p>Config SHA-256: <code>{audit['config_sha256']}</code></p>
<p>Manifest bundle SHA-256: <code>{audit['manifest_bundle_sha256']}</code></p>
<h2>Manifest counts</h2><table><tr><th>Manifest</th><th>Family</th><th>Rows</th></tr>{''.join(rows)}</table>
<h2>Freeze checks</h2><ul>
<li>Duplicate raw instances: {audit['duplicate_raw_instance_count']}</li>
<li>Split leakage: {audit['split_leakage_count']}</li>
<li>Validation failures: {audit['validation_failure_count']}</li>
<li>Qmax feasibility failures in QAOA manifest: {audit['qmax_feasibility_failure_count']}</li>
<li>All representations share each instance split: {audit['representation_split_consistent']}</li>
</ul><h2>Excluded candidates</h2><ul>{exclusions}</ul>
<h2>Coverage notes</h2><ul>{holes}</ul>
<p>No selector, QAOA, compilation winner, or noise winner was used to choose these instances.</p>
</body></html>"""


def run_formal_data_pipeline(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    plan_path: str | Path,
    smoke_config_path: str | Path,
    schema_path: str | Path,
    output_directory: str | Path,
    code_commit: str,
    progress: Callable[[str], None] | None = None,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run smoke gate, generate formal data, and atomically freeze manifests."""

    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    plan_path = Path(plan_path)
    smoke_config_path = Path(smoke_config_path)
    schema_path = Path(schema_path)
    output_directory = Path(output_directory)
    assumptions_path = Path(assumptions_path) if assumptions_path else None
    run_commands_path = Path(run_commands_path) if run_commands_path else None
    assumptions_original = (
        _document_before_update(
            assumptions_path, "## Formal Step 2 data freeze (v1)"
        )
        if assumptions_path
        else None
    )
    commands_original = (
        _document_before_update(
            run_commands_path, "## Formal Step 2 data-freeze command (v1)"
        )
        if run_commands_path
        else None
    )
    config, config_hash = _require_formal_config(
        config_path, config_hash_path
    )
    plan = _load_json(plan_path)
    plan_hash = _sha256_file(plan_path)
    if plan.get("generation_plan_version") != "formal_data_generation_v1":
        raise FormalDataError("Unexpected formal data generation plan")
    expected_schema_hash = config.get("sources", {}).get(
        "instance_schema", {}
    ).get("sha256")
    if expected_schema_hash and _sha256_file(schema_path) != expected_schema_hash:
        raise FormalDataError("Instance schema hash differs from formal config")
    if not code_commit or code_commit == "unknown":
        raise FormalDataError("A concrete code commit is required")

    staging = _prepare_staging(output_directory)
    smoke_audit = run_smoke_batch(
        config_path=smoke_config_path,
        schema_path=schema_path,
        output_directory=staging / "audit" / "smoke_gate",
    )
    if smoke_audit["status"] != "pass":
        raise FormalDataError("Internal smoke gate failed")
    if progress:
        progress("SMOKE GATE: pass")

    master_seed = int(config["dataset"]["generation"]["master_seed"])
    validation_seed = int(config["dataset"]["generation"]["validation_seed"])
    maximum_validation = int(
        config["dataset"]["generation"]["large_instance_spot_checks"]
    )
    split_seed = int(config["dataset"]["split"]["assignment_seed"])
    qmax = int(
        config["dataset"]["tiers"]["qaoa"][
            "common_width_limit_qmax"
        ]
    )
    maximum_pair_candidates = int(
        plan["qaoa_full_pair_cover"]["maximum_pair_candidates"]
    )
    maximum_attempt_multiplier = int(plan["maximum_attempt_multiplier"])
    generator_version = str(plan["generator_version"])

    instances: dict[str, dict[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    validations: dict[str, dict[str, Any]] = {}
    memberships: dict[str, list[str]] = {
        "oracle": [],
        "qaoa": [],
        "compilation": [],
    }
    rejections: list[dict[str, object]] = []

    def reject(
        *,
        tier: str,
        family: str,
        attempt: int,
        profile: Mapping[str, object],
        seed: int,
        reason: str,
        instance_id: str = "",
        retained_for: str = "audit_only",
    ) -> None:
        rejections.append(
            {
                "candidate_tier": tier,
                "family": family,
                "attempt": attempt,
                "n": profile["n"],
                "regime": profile["regime"],
                "generator_mode": profile["generator_mode"],
                "instance_seed": seed,
                "instance_id": instance_id,
                "reason": reason,
                "retained_for": retained_for,
            }
        )

    def validate_candidate(
        instance: dict[str, Any], instance_seed: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        validate_raw_instance(instance, schema_path=schema_path)
        repeat_validation_seed = derive_seed(
            validation_seed, instance["instance_id"]
        )
        direct = validate_direct_vs_canonical(
            instance,
            validation_seed=repeat_validation_seed,
            maximum_assignments=maximum_validation,
        )
        ising = _validate_boolean_vs_ising(
            instance,
            validation_seed=repeat_validation_seed,
            maximum=maximum_validation,
        )
        metadata = canonical_metadata(instance)
        return metadata, {
            "instance_id": instance["instance_id"],
            "family": instance["family"],
            "schema_validation": "pass",
            "fixed_seed_rerun_identical": True,
            "direct_vs_canonical_status": direct["status"],
            "direct_vs_canonical_method": direct["method"],
            "direct_vs_canonical_assignments": direct["assignments_checked"],
            "direct_vs_canonical_maximum_mismatch": direct[
                "maximum_pointwise_mismatch"
            ],
            "boolean_vs_ising_status": ising["status"],
            "boolean_vs_ising_method": ising["method"],
            "boolean_vs_ising_assignments": ising["assignments_checked"],
            "boolean_vs_ising_maximum_mismatch": ising[
                "maximum_pointwise_mismatch"
            ],
            "validation_seed": repeat_validation_seed,
            "instance_seed": instance_seed,
        }

    def store(
        instance: dict[str, Any],
        *,
        tier: str,
        profile: Mapping[str, object],
        instance_seed: int,
        metadata: Mapping[str, Any],
        validation: Mapping[str, Any],
        origin: str,
        qaoa_record: Mapping[str, Any] | None = None,
    ) -> None:
        instance_id = str(instance["instance_id"])
        if instance_id in instances:
            raise FormalDataError(f"Duplicate raw instance accepted: {instance_id}")
        instances[instance_id] = instance
        memberships[tier].append(instance_id)
        validations[instance_id] = dict(validation)
        records[instance_id] = {
            "instance_id": instance_id,
            "family": instance["family"],
            "n": int(profile["n"]),
            "regime": profile["regime"],
            "level": profile["level"],
            "generator_mode": profile["generator_mode"],
            "instance_seed": instance_seed,
            "origin": origin,
            "qaoa": dict(qaoa_record or {}),
            **metadata,
        }

    for tier in ("oracle", "qaoa"):
        tier_config = config["dataset"]["tiers"][tier]
        target = int(tier_config["target_instances_per_family"])
        for family in ("max3sat", "cubic_spin_glass"):
            profiles = _profiles(config, family, tier)
            accepted = 0
            attempt = 0
            maximum_attempts = target * maximum_attempt_multiplier
            while accepted < target and attempt < maximum_attempts:
                profile = profiles[attempt % len(profiles)]
                seed = derive_seed(
                    master_seed,
                    "formal_data_v1",
                    tier,
                    family,
                    attempt,
                )
                try:
                    instance = _generate(
                        family=family,
                        profile=profile,
                        master_seed=master_seed,
                        instance_seed=seed,
                        generator_version=generator_version,
                    )
                    repeat = _generate(
                        family=family,
                        profile=profile,
                        master_seed=master_seed,
                        instance_seed=seed,
                        generator_version=generator_version,
                    )
                except (RuntimeError, ValueError) as error:
                    reject(
                        tier=tier,
                        family=family,
                        attempt=attempt,
                        profile=profile,
                        seed=seed,
                        reason="generator_failure:" + type(error).__name__,
                    )
                    attempt += 1
                    continue
                instance_id = str(instance["instance_id"])
                if canonical_json(instance) != canonical_json(repeat):
                    raise FormalDataError(
                        f"Fixed-seed rerun mismatch: {instance_id}"
                    )
                if instance_id in instances:
                    reject(
                        tier=tier,
                        family=family,
                        attempt=attempt,
                        profile=profile,
                        seed=seed,
                        reason="duplicate_existing_instance",
                        instance_id=instance_id,
                    )
                    attempt += 1
                    continue
                metadata, validation = validate_candidate(instance, seed)
                if plan["reject_zero_canonical_cubics"] and int(
                    metadata["m3"]
                ) == 0:
                    reject(
                        tier=tier,
                        family=family,
                        attempt=attempt,
                        profile=profile,
                        seed=seed,
                        reason="zero_canonical_cubic_terms",
                        instance_id=instance_id,
                    )
                    attempt += 1
                    continue
                if tier == "oracle" and int(metadata["m3"]) > int(
                    tier_config["max_canonical_cubic_terms"]
                ):
                    reject(
                        tier=tier,
                        family=family,
                        attempt=attempt,
                        profile=profile,
                        seed=seed,
                        reason="oracle_m3_limit",
                        instance_id=instance_id,
                    )
                    attempt += 1
                    continue
                qaoa_record: dict[str, Any] = {}
                if tier == "qaoa":
                    full = fully_quadratize(
                        polynomial_for_instance(instance),
                        n_original=int(profile["n"]),
                        positive_margin=config["penalty_tightness"][
                            "above_threshold_epsilon"
                        ],
                        maximum_pair_candidates=maximum_pair_candidates,
                    )
                    qaoa_record = {
                        "all_native_width": int(profile["n"]),
                        "fully_quadratized_width": full.n_qubits,
                        "selective_width_upper_bound": full.n_qubits,
                        "matched_random_width_upper_bound": full.n_qubits,
                        "all_four_within_qmax": full.n_qubits <= qmax,
                    }
                    if full.n_qubits > qmax:
                        compilation_target = int(
                            config["dataset"]["tiers"]["compilation"][
                                "target_instances_per_family"
                            ]
                        )
                        compilation_n_values = set(
                            config["dataset"]["tiers"]["compilation"][
                                "n_values"
                            ]
                        )
                        current_promoted = sum(
                            instances[item]["family"] == family
                            for item in memberships["compilation"]
                        )
                        retained = (
                            int(profile["n"]) in compilation_n_values
                            and current_promoted < compilation_target
                        )
                        reject(
                            tier=tier,
                            family=family,
                            attempt=attempt,
                            profile=profile,
                            seed=seed,
                            reason="qmax_exceeded",
                            instance_id=instance_id,
                            retained_for=(
                                "compilation" if retained else "audit_only"
                            ),
                        )
                        if retained:
                            store(
                                instance,
                                tier="compilation",
                                profile=profile,
                                instance_seed=seed,
                                metadata=metadata,
                                validation=validation,
                                origin="qaoa_qmax_exclusion_promoted",
                                qaoa_record=qaoa_record,
                            )
                        attempt += 1
                        continue
                store(
                    instance,
                    tier=tier,
                    profile=profile,
                    instance_seed=seed,
                    metadata=metadata,
                    validation=validation,
                    origin=f"formal_{tier}_generation",
                    qaoa_record=qaoa_record,
                )
                accepted += 1
                attempt += 1
            if accepted != target:
                raise FormalDataError(
                    f"Unable to fill {tier}/{family}: {accepted}/{target}"
                )
            if progress:
                progress(
                    f"GENERATED {tier}/{family}: {accepted}/{target} accepted"
                )

    tier = "compilation"
    target = int(
        config["dataset"]["tiers"][tier]["target_instances_per_family"]
    )
    for family in ("max3sat", "cubic_spin_glass"):
        profiles = _profiles(config, family, tier)
        accepted = sum(
            instances[item]["family"] == family
            for item in memberships[tier]
        )
        attempt = 0
        maximum_attempts = target * maximum_attempt_multiplier
        while accepted < target and attempt < maximum_attempts:
            profile = profiles[attempt % len(profiles)]
            seed = derive_seed(
                master_seed, "formal_data_v1", tier, family, attempt
            )
            try:
                instance = _generate(
                    family=family,
                    profile=profile,
                    master_seed=master_seed,
                    instance_seed=seed,
                    generator_version=generator_version,
                )
                repeat = _generate(
                    family=family,
                    profile=profile,
                    master_seed=master_seed,
                    instance_seed=seed,
                    generator_version=generator_version,
                )
            except (RuntimeError, ValueError) as error:
                reject(
                    tier=tier,
                    family=family,
                    attempt=attempt,
                    profile=profile,
                    seed=seed,
                    reason="generator_failure:" + type(error).__name__,
                )
                attempt += 1
                continue
            instance_id = str(instance["instance_id"])
            if canonical_json(instance) != canonical_json(repeat):
                raise FormalDataError(f"Fixed-seed rerun mismatch: {instance_id}")
            if instance_id in instances:
                reject(
                    tier=tier,
                    family=family,
                    attempt=attempt,
                    profile=profile,
                    seed=seed,
                    reason="duplicate_existing_instance",
                    instance_id=instance_id,
                )
                attempt += 1
                continue
            metadata, validation = validate_candidate(instance, seed)
            if plan["reject_zero_canonical_cubics"] and int(metadata["m3"]) == 0:
                reject(
                    tier=tier,
                    family=family,
                    attempt=attempt,
                    profile=profile,
                    seed=seed,
                    reason="zero_canonical_cubic_terms",
                    instance_id=instance_id,
                )
                attempt += 1
                continue
            store(
                instance,
                tier=tier,
                profile=profile,
                instance_seed=seed,
                metadata=metadata,
                validation=validation,
                origin="formal_compilation_generation",
            )
            accepted += 1
            attempt += 1
        if accepted != target:
            raise FormalDataError(
                f"Unable to fill compilation/{family}: {accepted}/{target}"
            )
        if progress:
            progress(
                f"GENERATED compilation/{family}: {accepted}/{target} accepted"
            )

    expected_total = sum(len(values) for values in memberships.values())
    if len(instances) != expected_total:
        raise FormalDataError("Formal tier memberships contain duplicate instances")

    split_map = _assign_splits(
        memberships,
        instances,
        fractions=config["dataset"]["split"],
        split_seed=split_seed,
    )
    noise_target = int(
        config["dataset"]["tiers"]["limited_noise"][
            "target_instances_per_family"
        ]
    )
    noise_ids = _select_noise_subset(
        memberships["qaoa"],
        instances=instances,
        records=records,
        target_per_family=noise_target,
    )
    if progress:
        progress("SPLITS AND NOISE SUBSET: frozen")

    metadata_rows: list[dict[str, object]] = []
    validation_rows = []
    for instance_id in sorted(instances):
        instance = instances[instance_id]
        record = records[instance_id]
        raw_relative = (
            Path("raw") / str(instance["family"]) / f"{instance_id}.json"
        )
        raw_content = stable_instance_json(instance)
        raw_path = staging / raw_relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw_content, encoding="utf-8", newline="\n")
        canonical_relative = Path("canonical") / f"{instance_id}.json"
        _write_json(staging / canonical_relative, _canonical_payload(instance))
        record["raw_file"] = raw_relative.as_posix()
        record["raw_sha256"] = sha256_bytes(raw_content.encode("utf-8"))
        record["canonical_file"] = canonical_relative.as_posix()
        record["canonical_sha256"] = _sha256_file(staging / canonical_relative)
        tier = next(
            name for name, ids in memberships.items() if instance_id in ids
        )
        metadata_rows.append(
            {
                "instance_id": instance_id,
                "family": instance["family"],
                "tier": tier,
                "split": split_map[instance_id],
                "spec_version": instance["spec_version"],
                "generator_version": instance["generation"]["generator_version"],
                "master_seed": master_seed,
                "instance_seed": record["instance_seed"],
                "regime": record["regime"],
                "generator_mode": record["generator_mode"],
                "origin": record["origin"],
                "raw_file": record["raw_file"],
                "raw_sha256": record["raw_sha256"],
                "canonical_file": record["canonical_file"],
                "canonical_sha256": record["canonical_sha256"],
                "config_sha256": config_hash,
                "generation_plan_sha256": plan_hash,
                "code_commit": code_commit,
                **{
                    key: value
                    for key, value in record.items()
                    if key
                    not in {
                        "instance_id",
                        "family",
                        "regime",
                        "generator_mode",
                        "instance_seed",
                        "origin",
                        "qaoa",
                        "raw_file",
                        "raw_sha256",
                        "canonical_file",
                        "canonical_sha256",
                    }
                },
            }
        )
        validation_rows.append(validations[instance_id])

    _write_csv(staging / "metadata" / "metadata_v1.csv", metadata_rows)
    _write_csv(staging / "metadata" / "validation_v1.csv", validation_rows)
    rejection_fields = [
        "candidate_tier",
        "family",
        "attempt",
        "n",
        "regime",
        "generator_mode",
        "instance_seed",
        "instance_id",
        "reason",
        "retained_for",
    ]
    _write_csv(
        staging / "metadata" / "candidate_exclusions_v1.csv",
        rejections,
        fieldnames=rejection_fields,
    )

    exact_maximum_n = int(plan["ground_truth"]["exact_maximum_n"])
    ground_truth_rows: list[dict[str, object]] = []
    ground_truth_status: dict[str, str] = {}
    for tier in ("oracle", "qaoa", "compilation"):
        for instance_id in sorted(memberships[tier]):
            instance = instances[instance_id]
            n = int(instance["problem"]["n"])
            if n <= exact_maximum_n:
                started = perf_counter()
                result = exact_ground_truth(instance)
                runtime = perf_counter() - started
                status = str(result["solver_status"])
                row = {
                    "instance_id": instance_id,
                    "family": instance["family"],
                    "tier": tier,
                    "split": split_map[instance_id],
                    "n": n,
                    "status": status,
                    "optimum_original": result["optimum_original"],
                    "number_of_optima": result["number_of_optima"],
                    "first_excited_value": result["first_excited_value"],
                    "first_excited_gap": result["first_excited_gap"],
                    "lower_bound": result["optimum_original"],
                    "upper_bound": result["optimum_original"],
                    "optimality_gap": 0,
                    "solver": result["solver"],
                    "solver_version": result["solver_version"],
                    "verification_method": result["verification_method"],
                    "runtime_sec": runtime,
                    "exact_truth": True,
                    "config_sha256": config_hash,
                    "generation_plan_sha256": plan_hash,
                    "code_commit": code_commit,
                }
            else:
                status = str(plan["ground_truth"]["larger_instance_status"])
                row = {
                    "instance_id": instance_id,
                    "family": instance["family"],
                    "tier": tier,
                    "split": split_map[instance_id],
                    "n": n,
                    "status": status,
                    "optimum_original": "",
                    "number_of_optima": "",
                    "first_excited_value": "",
                    "first_excited_gap": "",
                    "lower_bound": "",
                    "upper_bound": "",
                    "optimality_gap": "",
                    "solver": "not_run",
                    "solver_version": "",
                    "verification_method": "none",
                    "runtime_sec": 0,
                    "exact_truth": False,
                    "config_sha256": config_hash,
                    "generation_plan_sha256": plan_hash,
                    "code_commit": code_commit,
                }
            ground_truth_status[instance_id] = status
            ground_truth_rows.append(row)
    _write_csv(
        staging / "ground_truth" / "ground_truth_v1.csv",
        ground_truth_rows,
    )
    if progress:
        progress("GROUND TRUTH: complete for declared affordable widths")

    manifest_rows: dict[str, list[dict[str, object]]] = {}
    for tier in ("oracle", "qaoa", "compilation"):
        manifest_rows[tier] = [
            _manifest_row(
                instance_id=instance_id,
                tier=tier,
                split=split_map[instance_id],
                instance=instances[instance_id],
                record=records[instance_id],
                ground_truth_status=ground_truth_status[instance_id],
                qmax=qmax,
                config_hash=config_hash,
                plan_hash=plan_hash,
                code_commit=code_commit,
            )
            for instance_id in sorted(memberships[tier])
        ]
    manifest_rows["noise_subset"] = [
        _manifest_row(
            instance_id=instance_id,
            tier="noise_subset",
            split=split_map[instance_id],
            instance=instances[instance_id],
            record=records[instance_id],
            ground_truth_status=ground_truth_status[instance_id],
            qmax=qmax,
            config_hash=config_hash,
            plan_hash=plan_hash,
            code_commit=code_commit,
        )
        for instance_id in noise_ids
    ]

    manifest_hashes: dict[str, str] = {}
    manifest_filenames = {
        "oracle": "oracle_v1.csv",
        "qaoa": "qaoa_v1.csv",
        "compilation": "compilation_v1.csv",
        "noise_subset": "noise_subset_v1.csv",
    }
    for key, filename in manifest_filenames.items():
        path = staging / "manifests" / filename
        _write_csv(path, manifest_rows[key], fieldnames=MANIFEST_FIELDS)
        manifest_hashes[filename] = _write_hash_sidecar(path)

    bundle = {
        "manifest_bundle_version": "manifest_bundle_v1",
        "config_sha256": config_hash,
        "generation_plan_sha256": plan_hash,
        "code_commit": code_commit,
        "manifests": [
            {
                "file": filename,
                "rows": len(manifest_rows[key]),
                "sha256": manifest_hashes[filename],
            }
            for key, filename in manifest_filenames.items()
        ],
    }
    bundle_path = staging / "manifests" / "manifest_bundle_v1.json"
    _write_json(bundle_path, bundle)
    bundle_hash = _write_hash_sidecar(bundle_path)

    shutil.copyfile(config_path, staging / "config_snapshot_frozen.yaml")
    (staging / "config_snapshot_frozen.sha256").write_text(
        config_hash + "\n", encoding="utf-8", newline="\n"
    )
    shutil.copyfile(plan_path, staging / "formal_data_generation_v1.json")
    (staging / "formal_data_generation_v1.sha256").write_text(
        plan_hash + "\n", encoding="utf-8", newline="\n"
    )

    manifest_counts = {
        key: dict(
            sorted(Counter(row["family"] for row in rows).items())
        )
        for key, rows in manifest_rows.items()
    }
    split_counts = {
        key: dict(sorted(Counter(row["split"] for row in rows).items()))
        for key, rows in manifest_rows.items()
    }
    exclusion_counts = dict(
        sorted(Counter(str(row["reason"]) for row in rejections).items())
    )
    validation_failure_count = sum(
        row["direct_vs_canonical_status"] != "pass"
        or row["boolean_vs_ising_status"] != "pass"
        or row["schema_validation"] != "pass"
        or row["fixed_seed_rerun_identical"] is not True
        for row in validation_rows
    )
    qmax_failures = sum(
        str(row["all_four_within_qmax"]).lower() != "true"
        for row in manifest_rows["qaoa"]
    )
    leakage = defaultdict(set)
    for rows in manifest_rows.values():
        for row in rows:
            leakage[str(row["instance_id"])].add(str(row["split"]))
    split_leakage_count = sum(len(values) > 1 for values in leakage.values())
    coverage: dict[str, dict[str, object]] = {}
    coverage_notes: list[str] = []
    for tier in ("oracle", "qaoa", "compilation"):
        for family in ("max3sat", "cubic_spin_glass"):
            ids = [
                item
                for item in memberships[tier]
                if instances[item]["family"] == family
            ]
            coverage[f"{tier}:{family}"] = _coverage_summary(ids, records)
            expected_n = set(config["dataset"]["tiers"][tier]["n_values"])
            observed_n = {int(records[item]["n"]) for item in ids}
            missing_n = sorted(expected_n - observed_n)
            if missing_n:
                coverage_notes.append(
                    f"{tier}/{family} lacks n={missing_n}; deterministic structural "
                    "eligibility filters excluded those widths."
                )
            expected_regimes = {"low", "intermediate", "high"}
            observed_regimes = {
                str(records[item]["regime"]) for item in ids
            }
            missing_regimes = sorted(expected_regimes - observed_regimes)
            if missing_regimes:
                coverage_notes.append(
                    f"{tier}/{family} lacks regimes={missing_regimes}; the frozen "
                    "structural eligibility rule removed those candidates."
                )
            expected_modes = set(_proposal_modes(config, family))
            observed_modes = {
                str(records[item]["generator_mode"]) for item in ids
            }
            missing_modes = sorted(expected_modes - observed_modes)
            if missing_modes:
                coverage_notes.append(
                    f"{tier}/{family} lacks generator_modes={missing_modes}; "
                    "the omission is structural and pre-result."
                )
    if exclusion_counts.get("qmax_exceeded", 0):
        coverage_notes.append(
            "QAOA candidates exceeding Qmax=12 were excluded before any QAOA "
            "or representation-winner result and retained for compilation when capacity allowed."
        )

    expected_counts = {
        "oracle": int(
            config["dataset"]["tiers"]["oracle"][
                "target_instances_per_family"
            ]
        ),
        "qaoa": int(
            config["dataset"]["tiers"]["qaoa"][
                "target_instances_per_family"
            ]
        ),
        "compilation": int(
            config["dataset"]["tiers"]["compilation"][
                "target_instances_per_family"
            ]
        ),
        "noise_subset": noise_target,
    }
    counts_ok = all(
        manifest_counts[tier].get(family) == expected_counts[tier]
        for tier in expected_counts
        for family in ("max3sat", "cubic_spin_glass")
    )
    all_checks = (
        counts_ok
        and len(instances) == expected_total
        and validation_failure_count == 0
        and qmax_failures == 0
        and split_leakage_count == 0
    )
    audit: dict[str, Any] = {
        "status": "pass" if all_checks else "fail",
        "scope": "formal_step2_data_and_manifest_freeze",
        "config_sha256": config_hash,
        "generation_plan_sha256": plan_hash,
        "code_commit": code_commit,
        "manifest_bundle_sha256": bundle_hash,
        "manifest_hashes": manifest_hashes,
        "manifest_counts": manifest_counts,
        "split_counts": split_counts,
        "formal_instance_count": len(instances),
        "duplicate_raw_instance_count": len(instances) - expected_total,
        "split_leakage_count": split_leakage_count,
        "representation_split_consistent": split_leakage_count == 0,
        "validation_failure_count": validation_failure_count,
        "all_schema_checks_pass": validation_failure_count == 0,
        "all_seed_repeat_checks_pass": validation_failure_count == 0,
        "all_direct_vs_canonical_checks_pass": validation_failure_count == 0,
        "all_boolean_vs_ising_checks_pass": validation_failure_count == 0,
        "qmax": qmax,
        "qmax_feasibility_failure_count": qmax_failures,
        "all_qaoa_instances_four_representations_within_qmax": qmax_failures
        == 0,
        "exclusion_counts": exclusion_counts,
        "coverage": coverage,
        "coverage_notes": coverage_notes,
        "ground_truth_status_counts": dict(
            sorted(Counter(ground_truth_status.values()).items())
        ),
        "formal_manifests_created": all_checks,
        "formal_split_created": all_checks,
        "test_split_frozen_before_results": all_checks,
        "selector_or_qaoa_results_used_for_selection": False,
        "formal_results_created": False,
        "output_files": [
            "manifests/oracle_v1.csv",
            "manifests/qaoa_v1.csv",
            "manifests/compilation_v1.csv",
            "manifests/noise_subset_v1.csv",
            "manifests/manifest_bundle_v1.json",
            "ground_truth/ground_truth_v1.csv",
            "metadata/metadata_v1.csv",
            "metadata/validation_v1.csv",
            "metadata/candidate_exclusions_v1.csv",
            "benchmark_audit_v1.json",
            "benchmark_audit_v1.html",
        ],
    }
    _write_json(staging / "benchmark_audit_v1.json", audit)
    audit_html_path = staging / "benchmark_audit_v1.html"
    audit_html_path.write_text(
        _audit_html(audit), encoding="utf-8", newline="\n"
    )
    _write_hash_sidecar(staging / "benchmark_audit_v1.json")
    html_hash = _sha256_file(audit_html_path)
    (staging / "benchmark_audit_v1.html.sha256").write_text(
        html_hash + "\n", encoding="utf-8", newline="\n"
    )
    if audit["status"] != "pass":
        raise FormalDataError(
            f"Formal data-freeze audit failed; staging retained at {staging}"
        )
    staging.rename(output_directory)
    if assumptions_path is not None and assumptions_original is not None:
        assumptions_section = f"""## Formal Step 2 data freeze (v1)

- Status: `pass`; formal manifests and the fixed split are frozen.
- Formal instance count: `{audit['formal_instance_count']}`.
- Oracle: `30` instances per family; QAOA: `36` per family; compilation: `90` per family; noise subset: `9` per family.
- QAOA common width cap: `Qmax={qmax}`; accepted-manifest feasibility failures: `0`.
- Split counts: oracle `{audit['split_counts']['oracle']}`, QAOA `{audit['split_counts']['qaoa']}`, compilation `{audit['split_counts']['compilation']}`.
- Manifest bundle SHA-256: `{bundle_hash}`.
- Config SHA-256: `{config_hash}`.
- Generation-plan SHA-256: `{plan_hash}`.
- Code commit: `{code_commit}`.
- Direct-vs-canonical, Boolean-vs-Ising, schema, fixed-seed rerun, duplicate, and split-leakage gates all passed.
- Ground truth is exact only where `status=optimal`; larger unaffordable instances remain explicitly `not_run_width_above_declared_exact_limit` and are not presented as exact.
- No selector, representation-winner, QAOA, or noise-winner result was used for data selection.
- E1-E6 formal result files have not yet been created.

The machine-readable authority is `data/benchmark_audit_v1.json` together with `data/manifests/manifest_bundle_v1.json` and their SHA-256 sidecars.
"""
        _append_document(
            assumptions_path, assumptions_original, assumptions_section
        )
    if run_commands_path is not None and commands_original is not None:
        commands_section = """## Formal Step 2 data-freeze command (v1)

Run only from the clean committed Step 2 implementation checkpoint:

```powershell
python .\\run_formal_data_pipeline.py `
  --config .\\configs\\experiment_config_v1.yaml `
  --config-hash .\\configs\\experiment_config_v1.sha256 `
  --plan .\\configs\\formal_data_generation_v1.json `
  --smoke-config .\\configs\\smoke_config_v1.json `
  --schema .\\instance_schema\\instance_schema_v1.json `
  --output .\\data `
  --assumptions .\\assumptions_and_decisions.md `
  --run-commands .\\RUN_COMMANDS.md
```

Required result: `DATA FREEZE GATE: pass`, `status=pass`, `formal_manifests_created=true`, `formal_split_created=true`, `split_leakage_count=0`, and `qmax_feasibility_failure_count=0`.
"""
        _append_document(run_commands_path, commands_original, commands_section)
    if progress:
        progress("DATA FREEZE GATE: pass")
    return audit
