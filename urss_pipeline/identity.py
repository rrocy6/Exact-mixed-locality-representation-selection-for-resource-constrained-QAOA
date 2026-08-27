"""Canonical raw-instance serialization and content-derived identifiers."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Mapping


def normalize_problem(instance: Mapping[str, object]) -> dict[str, object]:
    """Return the identity-bearing mathematical payload in canonical order."""

    family = instance["family"]
    problem = instance["problem"]
    if family == "max3sat":
        clauses = []
        for clause in problem["clauses"]:  # type: ignore[index]
            literals = sorted(clause["literals"], key=abs)
            clauses.append(
                {"literals": literals, "weight": clause["weight"]}
            )
        clauses.sort(key=lambda row: (row["literals"], row["weight"]))
        return {"n": problem["n"], "clauses": clauses}  # type: ignore[index]

    if family == "cubic_spin_glass":
        hyperedges = []
        for hyperedge in problem["hyperedges"]:  # type: ignore[index]
            hyperedges.append(
                {
                    "variables": sorted(hyperedge["variables"]),
                    "coefficient": hyperedge["coefficient"],
                }
            )
        hyperedges.sort(
            key=lambda row: (row["variables"], row["coefficient"])
        )
        return {
            "n": problem["n"],  # type: ignore[index]
            "hyperedges": hyperedges,
            "c": problem["c"],  # type: ignore[index]
            "h": deepcopy(problem["h"]),  # type: ignore[index]
            "J": deepcopy(problem["J"]),  # type: ignore[index]
        }

    raise ValueError(f"Unsupported family: {family!r}")


def identity_material(instance: Mapping[str, object]) -> dict[str, object]:
    return {
        "family": instance["family"],
        "generator_version": instance["generation"]["generator_version"],  # type: ignore[index]
        "normalisation_convention": instance["normalisation_convention"],
        "raw_mathematical_instance": normalize_problem(instance),
        "spec_version": instance["spec_version"],
        "variable_convention": deepcopy(instance["conventions"]),
    }


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_instance_id(instance: Mapping[str, object]) -> str:
    encoded = canonical_json(identity_material(instance)).encode("utf-8")
    return "inst_" + hashlib.sha256(encoded).hexdigest()


def stable_instance_json(instance: Mapping[str, object]) -> str:
    return json.dumps(
        instance,
        ensure_ascii=True,
        sort_keys=True,
        indent=2,
    ) + "\n"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
