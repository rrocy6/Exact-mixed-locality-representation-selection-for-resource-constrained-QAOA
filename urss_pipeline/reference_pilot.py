"""End-to-end reference compiler and statevector pilot."""

from __future__ import annotations

import csv
import json
from fractions import Fraction
from pathlib import Path

from .generators import derive_seed, generate_max3sat, generate_spin_glass
from .identity import sha256_bytes
from .metadata import polynomial_for_instance
from .polynomial import cubic_supports
from .qaoa_pilot import (
    run_statevector_probe,
    synthetic_width_polynomial,
)
from .reference_compiler import compile_reference
from .representations import (
    fully_quadratize,
    validate_full_quadratization,
)


def _require_empty_output(output_directory: Path) -> None:
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_directory}. "
            "Use a new path to preserve prior pilot evidence."
        )
    output_directory.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _generate_instance(
    request: dict[str, object],
    *,
    master_seed: int,
    ordinal: int,
) -> dict[str, object]:
    family = request["family"]
    mode = request["generator_mode"]
    instance_seed = derive_seed(
        master_seed,
        "reference_pilot_v1",
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
        return generate_max3sat(
            **common,
            clause_density=request["clause_density"],
        )
    if family == "cubic_spin_glass":
        return generate_spin_glass(
            **common,
            hyperedges_per_variable=request["hyperedges_per_variable"],
        )
    raise ValueError(f"Unsupported reference-pilot family: {family!r}")


def _resource_row(
    *,
    instance: dict[str, object],
    representation: str,
    polynomial,
    n_original: int,
    n_auxiliary: int,
    maximum_penalty: float,
) -> dict[str, object]:
    compilation = compile_reference(
        polynomial, n_qubits=n_original + n_auxiliary
    )
    record = compilation.to_record()
    pubo_coefficients = [
        abs(Fraction(str(coefficient)))
        for coefficient in polynomial.values()
        if coefficient != 0
    ]
    pubo_dynamic_range = (
        float(max(pubo_coefficients) / min(pubo_coefficients))
        if pubo_coefficients
        else 0.0
    )
    return {
        "instance_id": instance["instance_id"],
        "family": instance["family"],
        "representation": representation,
        "n_original": n_original,
        "n_auxiliary": n_auxiliary,
        "n_qubits": n_original + n_auxiliary,
        "retained_cubic_terms": len(cubic_supports(polynomial)),
        "quadratic_couplings": sum(
            len(support) == 2 for support in polynomial
        ),
        "maximum_penalty": maximum_penalty,
        "pauli_weight_1": record["pauli_weight_1"],
        "pauli_weight_2": record["pauli_weight_2"],
        "pauli_weight_3": record["pauli_weight_3"],
        "two_qubit_gate_count": record["two_qubit_gate_count"],
        "two_qubit_depth": record["two_qubit_depth"],
        "swap_count": record["swap_count"],
        "pubo_coefficient_dynamic_range": pubo_dynamic_range,
        "pauli_coefficient_dynamic_range": record[
            "coefficient_dynamic_range"
        ],
        "coefficient_dynamic_range_stage": (
            "both_collected_pubo_and_collected_pauli_pre_synthesis"
        ),
        "pauli_terms_sha256": record["pauli_terms_sha256"],
        "cnot_stream_sha256": record["cnot_stream_sha256"],
        "compiler_id": record["compiler_id"],
    }


def run_reference_pilot(
    *,
    config_path: str | Path,
    output_directory: str | Path,
) -> dict[str, object]:
    """Run the non-formal reference-compiler and statevector pilot."""

    config_path = Path(config_path)
    output_directory = Path(output_directory)
    _require_empty_output(output_directory)
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    config_hash = sha256_bytes(config_bytes)
    resource_rows: list[dict[str, object]] = []
    exactness_rows: list[dict[str, object]] = []
    timing_rows: list[dict[str, object]] = []
    master_seed = config["master_seed"]
    simulator_seed = config["simulator_seed"]
    gammas = config["qaoa_probe"]["gammas"]
    betas = config["qaoa_probe"]["betas"]

    for ordinal, request in enumerate(config["instances"]):
        instance = _generate_instance(
            request, master_seed=master_seed, ordinal=ordinal
        )
        original = polynomial_for_instance(instance)
        n_original = instance["problem"]["n"]
        full = fully_quadratize(
            original,
            n_original=n_original,
            positive_margin=config["positive_penalty_margin"],
            maximum_pair_candidates=config[
                "maximum_exact_pair_candidates"
            ],
        )
        exactness = validate_full_quadratization(original, full)
        exactness_rows.append(
            {
                "instance_id": instance["instance_id"],
                "family": instance["family"],
                "representation": "fully_quadratized",
                **exactness,
            }
        )
        maximum_penalty = max(
            (
                float(item["penalty"])
                for item in full.penalties
            ),
            default=0.0,
        )
        resource_rows.append(
            _resource_row(
                instance=instance,
                representation="all_native",
                polynomial=original,
                n_original=n_original,
                n_auxiliary=0,
                maximum_penalty=0.0,
            )
        )
        resource_rows.append(
            _resource_row(
                instance=instance,
                representation="fully_quadratized",
                polynomial=full.polynomial,
                n_original=n_original,
                n_auxiliary=full.n_auxiliary,
                maximum_penalty=maximum_penalty,
            )
        )
        for representation, encoded, width in [
            ("all_native", original, n_original),
            ("fully_quadratized", full.polynomial, full.n_qubits),
        ]:
            timing_rows.append(
                {
                    "probe_type": "benchmark_instance",
                    "instance_id": instance["instance_id"],
                    "family": instance["family"],
                    "representation": representation,
                    **run_statevector_probe(
                        encoded,
                        n_qubits=width,
                        scoring_polynomial=original,
                        n_original=n_original,
                        gammas=gammas,
                        betas=betas,
                        simulator_seed=derive_seed(
                            simulator_seed,
                            instance["instance_id"],
                            representation,
                        ),
                    ),
                }
            )

    for width in config["qaoa_probe"]["synthetic_widths"]:
        polynomial = synthetic_width_polynomial(width)
        timing_rows.append(
            {
                "probe_type": "synthetic_width",
                "instance_id": f"synthetic_width_{width}",
                "family": "synthetic_not_benchmark",
                "representation": "all_native",
                **run_statevector_probe(
                    polynomial,
                    n_qubits=width,
                    scoring_polynomial=polynomial,
                    n_original=width,
                    gammas=gammas,
                    betas=betas,
                    simulator_seed=derive_seed(
                        simulator_seed, "synthetic_width", width
                    ),
                ),
            }
        )

    _write_csv(
        output_directory / "reference_resources.csv", resource_rows
    )
    _write_csv(
        output_directory / "reference_exactness.csv", exactness_rows
    )
    _write_csv(
        output_directory / "qaoa_statevector_timing.csv", timing_rows
    )
    _write_json(output_directory / "config_snapshot.json", config)
    all_exact = all(row["status"] == "pass" for row in exactness_rows)
    all_statevectors = all(row["status"] == "pass" for row in timing_rows)
    audit = {
        "status": "pass" if all_exact and all_statevectors else "fail",
        "scope": "reference_compiler_pilot_only_not_formal_results",
        "pilot_config_version": config["pilot_config_version"],
        "config_sha256": config_hash,
        "instance_count": len(config["instances"]),
        "representation_resource_row_count": len(resource_rows),
        "statevector_probe_count": len(timing_rows),
        "all_full_quadratization_exactness_checks_pass": all_exact,
        "all_statevector_probes_pass": all_statevectors,
        "formal_manifest_created": False,
        "formal_split_created": False,
        "qmax_frozen": False,
        "selector_weights_frozen": False,
        "output_files": [
            "reference_resources.csv",
            "reference_exactness.csv",
            "qaoa_statevector_timing.csv",
            "config_snapshot.json",
            "reference_pilot_audit.json",
        ],
    }
    _write_json(
        output_directory / "reference_pilot_audit.json", audit
    )
    return audit
