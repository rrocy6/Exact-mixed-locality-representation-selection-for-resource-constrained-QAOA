"""End-to-end deterministic smoke batch with machine-readable outputs."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Mapping

from .generators import derive_seed, generate_max3sat, generate_spin_glass
from .identity import canonical_json, sha256_bytes, stable_instance_json
from .metadata import canonical_metadata, exact_ground_truth, polynomial_for_instance
from .validation import validate_direct_vs_canonical, validate_raw_instance


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _polynomial_json(polynomial: Mapping[tuple[int, ...], object]) -> dict[str, object]:
    return {
        "terms": [
            {"support": list(support), "coefficient": coefficient}
            for support, coefficient in polynomial.items()
        ]
    }


def _require_empty_output(output_directory: Path) -> None:
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_directory}. "
            "Use a new path to preserve prior evidence."
        )
    output_directory.mkdir(parents=True, exist_ok=True)


def run_smoke_batch(
    *,
    config_path: str | Path,
    schema_path: str | Path,
    output_directory: str | Path,
) -> dict[str, object]:
    config_path = Path(config_path)
    schema_path = Path(schema_path)
    output_directory = Path(output_directory)
    _require_empty_output(output_directory)

    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    config_hash = sha256_bytes(config_bytes)
    master_seed = config["master_seed"]
    validation_seed = config["validation_seed"]
    manifest_rows: list[dict[str, object]] = []
    metadata_rows: list[dict[str, object]] = []
    validation_rows: list[dict[str, object]] = []

    for ordinal, request in enumerate(config["instances"]):
        family = request["family"]
        mode = request["generator_mode"]
        instance_seed = derive_seed(
            master_seed,
            config["smoke_config_version"],
            ordinal,
            family,
            mode,
            request["n"],
        )
        common = {
            "n": request["n"],
            "generator_mode": mode,
            "master_seed": master_seed,
            "instance_seed": instance_seed,
            "anchor_pair_count": request.get("anchor_pair_count"),
        }
        if family == "max3sat":
            instance = generate_max3sat(
                **common,
                clause_density=request["clause_density"],
            )
            repeat = generate_max3sat(
                **common,
                clause_density=request["clause_density"],
            )
        elif family == "cubic_spin_glass":
            instance = generate_spin_glass(
                **common,
                hyperedges_per_variable=request["hyperedges_per_variable"],
            )
            repeat = generate_spin_glass(
                **common,
                hyperedges_per_variable=request["hyperedges_per_variable"],
            )
        else:
            raise ValueError(f"Unsupported family in smoke config: {family!r}")

        if canonical_json(instance) != canonical_json(repeat):
            raise AssertionError("Fixed-seed generator rerun was not identical")
        validate_raw_instance(instance, schema_path=schema_path)
        validation = validate_direct_vs_canonical(
            instance,
            validation_seed=derive_seed(validation_seed, instance["instance_id"]),
            maximum_assignments=config["maximum_validation_assignments"],
        )

        instance_id = instance["instance_id"]
        raw_relative = Path("raw") / family / f"{instance_id}.json"
        raw_content = stable_instance_json(instance)
        raw_path = output_directory / raw_relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw_content, encoding="utf-8", newline="\n")
        raw_hash = sha256_bytes(raw_content.encode("utf-8"))

        canonical_relative = Path("canonical") / f"{instance_id}.json"
        _write_json(
            output_directory / canonical_relative,
            {
                "instance_id": instance_id,
                "family": family,
                **_polynomial_json(polynomial_for_instance(instance)),
            },
        )
        ground_truth_relative = Path("ground_truth") / f"{instance_id}.json"
        _write_json(
            output_directory / ground_truth_relative,
            exact_ground_truth(instance),
        )

        manifest_rows.append(
            {
                "instance_id": instance_id,
                "family": family,
                "tier": "smoke",
                "split": "smoke_not_formal",
                "generator_mode": mode,
                "instance_seed": instance_seed,
                "raw_file": raw_relative.as_posix(),
                "raw_sha256": raw_hash,
                "config_sha256": config_hash,
                "validation_status": validation["status"],
            }
        )
        metadata_rows.append(
            {
                "instance_id": instance_id,
                "family": family,
                "spec_version": instance["spec_version"],
                "generator_version": instance["generation"]["generator_version"],
                "config_hash": config_hash,
                "master_seed": master_seed,
                "instance_seed": instance_seed,
                "created_at": config["created_at_utc"],
                "raw_file": raw_relative.as_posix(),
                "raw_hash": raw_hash,
                "split": "smoke_not_formal",
                "tier": "smoke",
                **canonical_metadata(instance),
            }
        )
        validation_rows.append(
            {
                "instance_id": instance_id,
                "family": family,
                **validation,
                "fixed_seed_rerun_identical": True,
                "schema_validation": "pass",
            }
        )

    manifest_path = output_directory / "manifests" / "smoke_v1.csv"
    metadata_path = output_directory / "metadata" / "smoke_v1.csv"
    validation_path = output_directory / "audit" / "validation_v1.csv"
    _write_csv(manifest_path, manifest_rows)
    _write_csv(metadata_path, metadata_rows)
    _write_csv(validation_path, validation_rows)
    _write_json(output_directory / "config_snapshot.json", config)

    family_counts = Counter(row["family"] for row in manifest_rows)
    audit = {
        "status": "pass",
        "scope": "smoke_only_not_formal_results",
        "smoke_config_version": config["smoke_config_version"],
        "config_sha256": config_hash,
        "instance_count": len(manifest_rows),
        "family_counts": dict(sorted(family_counts.items())),
        "all_schema_valid": True,
        "all_fixed_seed_reruns_identical": True,
        "all_direct_vs_canonical_checks_pass": True,
        "formal_split_created": False,
        "formal_manifest_created": False,
        "outputs": {
            "manifest": manifest_path.relative_to(output_directory).as_posix(),
            "metadata": metadata_path.relative_to(output_directory).as_posix(),
            "validation": validation_path.relative_to(output_directory).as_posix(),
        },
    }
    _write_json(output_directory / "audit" / "smoke_audit_v1.json", audit)
    return audit
