"""Structural, semantic, identity, and mathematical validation."""

from __future__ import annotations

import json
import math
import random
from itertools import product
from pathlib import Path
from typing import Mapping

from .identity import compute_instance_id
from .polynomial import (
    evaluate_max3sat_direct,
    evaluate_pubo,
    evaluate_spin_glass_direct,
    max3sat_to_pubo,
    spin_glass_to_pubo,
)


class InstanceValidationError(ValueError):
    """Raised when a raw instance violates the V1 draft contract."""


def validate_json_schema(
    instance: Mapping[str, object], schema_path: str | Path
) -> None:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise RuntimeError(
            "jsonschema is required for structural validation; "
            "install requirements-smoke.txt"
        ) from error

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise InstanceValidationError(f"JSON Schema validation failed: {details}")


def _validate_common(instance: Mapping[str, object]) -> None:
    if instance.get("schema_version") != "instance_schema_v1.0-draft":
        raise InstanceValidationError("Unexpected schema_version")
    if instance.get("spec_version") != "benchmark_spec_v1.0":
        raise InstanceValidationError("Unexpected spec_version")
    if instance.get("normalisation_convention") != "none":
        raise InstanceValidationError("V1 requires no raw normalisation")

    generation = instance.get("generation")
    if not isinstance(generation, Mapping):
        raise InstanceValidationError("generation must be an object")
    mode = generation.get("generator_mode")
    if mode not in {"uniform", "anchor_pair", "manual_golden"}:
        raise InstanceValidationError("Unsupported generator_mode")
    if mode != "manual_golden":
        for name in ("master_seed", "instance_seed"):
            value = generation.get(name)
            if not isinstance(value, int) or value < 0:
                raise InstanceValidationError(
                    f"Generated instances require nonnegative {name}"
                )


def _validate_max3sat(instance: Mapping[str, object]) -> None:
    problem = instance["problem"]
    n = problem["n"]
    clauses = problem["clauses"]
    if not isinstance(n, int) or n < 3:
        raise InstanceValidationError("Max-3SAT n must be an integer >= 3")
    if problem["m_clause"] != len(clauses):
        raise InstanceValidationError("m_clause does not match clauses")
    if not math.isclose(
        problem["clause_density"], len(clauses) / n, rel_tol=0, abs_tol=1e-15
    ):
        raise InstanceValidationError("Incorrect clause_density")

    seen: set[tuple[int, int, int]] = set()
    used: set[int] = set()
    for clause in clauses:
        literals = clause["literals"]
        if len(literals) != 3 or not all(
            isinstance(literal, int) and literal != 0
            for literal in literals
        ):
            raise InstanceValidationError("Every clause needs three nonzero literals")
        absolute = [abs(literal) for literal in literals]
        if len(set(absolute)) != 3:
            raise InstanceValidationError("Clause variables must be distinct")
        if absolute != sorted(absolute):
            raise InstanceValidationError("Clause literals are not canonically ordered")
        if any(variable < 1 or variable > n for variable in absolute):
            raise InstanceValidationError("Clause variable is out of range")
        if not isinstance(clause["weight"], int) or clause["weight"] not in range(1, 6):
            raise InstanceValidationError("Clause weight must be in {1,2,3,4,5}")
        key = tuple(literals)
        if key in seen:
            raise InstanceValidationError("Duplicate signed clause")
        seen.add(key)
        used.update(absolute)
    if used != set(range(1, n + 1)):
        raise InstanceValidationError("Every variable must occur in a clause")


def _validate_spin_glass(instance: Mapping[str, object]) -> None:
    problem = instance["problem"]
    n = problem["n"]
    hyperedges = problem["hyperedges"]
    if not isinstance(n, int) or n < 3:
        raise InstanceValidationError("Spin-glass n must be an integer >= 3")
    if problem["m_edge"] != len(hyperedges):
        raise InstanceValidationError("m_edge does not match hyperedges")
    if not math.isclose(
        problem["hyperedge_density"],
        len(hyperedges) / math.comb(n, 3),
        rel_tol=0,
        abs_tol=1e-15,
    ):
        raise InstanceValidationError("Incorrect hyperedge_density")
    if problem["c"] != 0 or problem["h"] != [] or problem["J"] != []:
        raise InstanceValidationError("V1 spin glass requires c=0, h=[], J=[]")

    seen: set[tuple[int, int, int]] = set()
    used: set[int] = set()
    for hyperedge in hyperedges:
        variables = hyperedge["variables"]
        if (
            len(variables) != 3
            or not all(isinstance(variable, int) for variable in variables)
            or variables != sorted(variables)
            or len(set(variables)) != 3
        ):
            raise InstanceValidationError("Hyperedge variables must satisfy i<j<k")
        if any(variable < 1 or variable > n for variable in variables):
            raise InstanceValidationError("Hyperedge variable is out of range")
        if hyperedge["coefficient"] not in {-1, 1}:
            raise InstanceValidationError("Spin coefficient must be -1 or +1")
        key = tuple(variables)
        if key in seen:
            raise InstanceValidationError("Duplicate hyperedge")
        seen.add(key)
        used.update(variables)
    if used != set(range(1, n + 1)):
        raise InstanceValidationError("Every variable must occur in a hyperedge")


def validate_raw_instance(
    instance: Mapping[str, object], schema_path: str | Path | None = None
) -> None:
    if schema_path is not None:
        validate_json_schema(instance, schema_path)
    _validate_common(instance)
    family = instance.get("family")
    if family == "max3sat":
        _validate_max3sat(instance)
    elif family == "cubic_spin_glass":
        _validate_spin_glass(instance)
    else:
        raise InstanceValidationError(f"Unsupported family: {family!r}")
    expected = compute_instance_id(instance)
    if instance.get("instance_id") != expected:
        raise InstanceValidationError(
            f"instance_id mismatch: expected {expected}"
        )


def validate_direct_vs_canonical(
    instance: Mapping[str, object],
    *,
    validation_seed: int = 0,
    maximum_assignments: int = 1024,
) -> dict[str, object]:
    """Exhaustively validate small instances or sample fixed distinct points."""

    family = instance["family"]
    n = instance["problem"]["n"]  # type: ignore[index]
    if family == "max3sat":
        polynomial = max3sat_to_pubo(instance)
        direct = evaluate_max3sat_direct
    elif family == "cubic_spin_glass":
        polynomial = spin_glass_to_pubo(instance)
        direct = evaluate_spin_glass_direct
    else:
        raise InstanceValidationError(f"Unsupported family: {family!r}")

    total_assignments = 1 << n
    if total_assignments <= maximum_assignments:
        assignments = list(product((0, 1), repeat=n))
        method = "exhaustive"
    else:
        rng = random.Random(validation_seed)
        indices = rng.sample(range(total_assignments), maximum_assignments)
        assignments = [
            tuple((index >> shift) & 1 for shift in reversed(range(n)))
            for index in indices
        ]
        method = "fixed_seed_spot_check"

    maximum_mismatch = 0
    for bits in assignments:
        direct_value = direct(instance, bits)
        canonical_value = evaluate_pubo(polynomial, bits)
        mismatch = abs(direct_value - canonical_value)
        maximum_mismatch = max(maximum_mismatch, mismatch)
        if mismatch != 0:
            raise InstanceValidationError(
                f"Direct/canonical mismatch for {bits}: "
                f"{direct_value} != {canonical_value}"
            )

    return {
        "status": "pass",
        "method": method,
        "assignments_checked": len(assignments),
        "maximum_pointwise_mismatch": maximum_mismatch,
    }
