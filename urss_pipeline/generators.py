"""Fixed-seed raw generators for the two V1 benchmark families."""

from __future__ import annotations

import hashlib
import random
from itertools import combinations
from math import comb
from typing import Iterable

from .identity import compute_instance_id


SCHEMA_VERSION = "instance_schema_v1.0-draft"
SPEC_VERSION = "benchmark_spec_v1.0"


def derive_seed(master_seed: int, *parts: object) -> int:
    """Derive a stable nonnegative 63-bit seed from named config parts."""

    material = "|".join([str(master_seed), *(str(part) for part in parts)])
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def _canonical_clause(literals: Iterable[int], weight: int) -> dict[str, object]:
    return {
        "literals": sorted(literals, key=abs),
        "weight": weight,
    }


def _choose_anchor_pairs(rng: random.Random, n: int, count: int) -> list[tuple[int, int]]:
    pairs = list(combinations(range(1, n + 1), 2))
    if not 1 <= count <= len(pairs):
        raise ValueError(f"anchor_pair_count must be in 1..{len(pairs)}")
    return sorted(rng.sample(pairs, count))


def generate_max3sat(
    *,
    n: int,
    clause_density: float,
    generator_mode: str,
    master_seed: int,
    instance_seed: int,
    generator_version: str = "max3sat_smoke_v1",
    anchor_pair_count: int | None = None,
    max_restarts: int = 500,
) -> dict[str, object]:
    """Generate one deterministic, coverage-valid weighted Max-3SAT instance."""

    if n < 3:
        raise ValueError("n must be at least 3")
    if clause_density <= 0:
        raise ValueError("clause_density must be positive")
    if generator_mode not in {"uniform", "anchor_pair"}:
        raise ValueError("generator_mode must be uniform or anchor_pair")

    target = max(1, round(clause_density * n))
    max_signed_clauses = comb(n, 3) * 8
    target = min(target, max_signed_clauses)
    rng = random.Random(instance_seed)
    total_rejections = 0

    for restart in range(max_restarts + 1):
        clauses: dict[tuple[int, int, int], dict[str, object]] = {}
        anchors: list[tuple[int, int]] = []
        if generator_mode == "anchor_pair":
            count = anchor_pair_count or max(1, min(n // 3, comb(n, 2)))
            anchors = _choose_anchor_pairs(rng, n, count)

        proposal_budget = max(1000, target * 100)
        proposals = 0
        while len(clauses) < target and proposals < proposal_budget:
            proposals += 1
            if generator_mode == "uniform":
                variables = sorted(rng.sample(range(1, n + 1), 3))
            else:
                anchor = rng.choice(anchors)
                third_choices = [
                    variable
                    for variable in range(1, n + 1)
                    if variable not in anchor
                ]
                variables = sorted((*anchor, rng.choice(third_choices)))

            literals = tuple(
                variable if rng.random() < 0.5 else -variable
                for variable in variables
            )
            if literals in clauses:
                total_rejections += 1
                continue
            clauses[literals] = _canonical_clause(
                literals, rng.randint(1, 5)
            )

        if len(clauses) < target:
            total_rejections += 1
            continue

        used = {
            abs(literal)
            for clause in clauses.values()
            for literal in clause["literals"]
        }
        if used != set(range(1, n + 1)):
            total_rejections += 1
            continue

        ordered_clauses = sorted(
            clauses.values(),
            key=lambda row: (row["literals"], row["weight"]),
        )
        instance: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "spec_version": SPEC_VERSION,
            "family": "max3sat",
            "normalisation_convention": "none",
            "conventions": {
                "domain": "binary_0_1",
                "indexing": "one_based",
                "literal_encoding": "signed_integer_positive_is_x_negative_is_not_x",
                "objective_sense": "minimize",
            },
            "problem": {
                "n": n,
                "m_clause": target,
                "clauses": ordered_clauses,
                "clause_density": target / n,
            },
            "generation": {
                "generator_mode": generator_mode,
                "generator_parameters": {
                    "requested_clause_density": clause_density,
                    "target_clause_count": target,
                    "anchor_pair_count": len(anchors),
                    "anchor_pairs": [list(pair) for pair in anchors],
                },
                "master_seed": master_seed,
                "instance_seed": instance_seed,
                "generator_version": generator_version,
                "rejection_count": total_rejections,
            },
            "instance_id": "",
        }
        instance["instance_id"] = compute_instance_id(instance)
        return instance

    raise RuntimeError(
        f"Unable to generate coverage-valid Max-3SAT after {max_restarts} restarts"
    )


def generate_spin_glass(
    *,
    n: int,
    hyperedges_per_variable: float,
    generator_mode: str,
    master_seed: int,
    instance_seed: int,
    generator_version: str = "spin_glass_smoke_v1",
    anchor_pair_count: int | None = None,
    max_restarts: int = 500,
) -> dict[str, object]:
    """Generate one deterministic pure cubic spin-glass instance."""

    if n < 3:
        raise ValueError("n must be at least 3")
    if hyperedges_per_variable <= 0:
        raise ValueError("hyperedges_per_variable must be positive")
    if generator_mode not in {"uniform", "anchor_pair"}:
        raise ValueError("generator_mode must be uniform or anchor_pair")

    target = max(1, round(hyperedges_per_variable * n))
    target = min(target, comb(n, 3))
    rng = random.Random(instance_seed)
    total_rejections = 0

    for restart in range(max_restarts + 1):
        hyperedges: dict[tuple[int, int, int], dict[str, object]] = {}
        anchors: list[tuple[int, int]] = []
        if generator_mode == "anchor_pair":
            count = anchor_pair_count or max(1, min(n // 3, comb(n, 2)))
            anchors = _choose_anchor_pairs(rng, n, count)

        proposal_budget = max(1000, target * 100)
        proposals = 0
        while len(hyperedges) < target and proposals < proposal_budget:
            proposals += 1
            if generator_mode == "uniform":
                variables = tuple(sorted(rng.sample(range(1, n + 1), 3)))
            else:
                anchor = rng.choice(anchors)
                third_choices = [
                    variable
                    for variable in range(1, n + 1)
                    if variable not in anchor
                ]
                variables = tuple(sorted((*anchor, rng.choice(third_choices))))
            if variables in hyperedges:
                total_rejections += 1
                continue
            coefficient = 1 if rng.random() < 0.5 else -1
            hyperedges[variables] = {
                "variables": list(variables),
                "coefficient": coefficient,
            }

        if len(hyperedges) < target:
            total_rejections += 1
            continue

        used = {
            variable
            for hyperedge in hyperedges.values()
            for variable in hyperedge["variables"]
        }
        if used != set(range(1, n + 1)):
            total_rejections += 1
            continue

        ordered_hyperedges = sorted(
            hyperedges.values(),
            key=lambda row: (row["variables"], row["coefficient"]),
        )
        instance = {
            "schema_version": SCHEMA_VERSION,
            "spec_version": SPEC_VERSION,
            "family": "cubic_spin_glass",
            "normalisation_convention": "none",
            "conventions": {
                "raw_domain": "spin_minus1_plus1",
                "canonical_domain": "binary_0_1",
                "indexing": "one_based",
                "boolean_conversion": "s=1-2x",
                "objective_sense": "minimize",
            },
            "problem": {
                "n": n,
                "m_edge": target,
                "hyperedges": ordered_hyperedges,
                "c": 0,
                "h": [],
                "J": [],
                "hyperedge_density": target / comb(n, 3),
            },
            "generation": {
                "generator_mode": generator_mode,
                "generator_parameters": {
                    "requested_hyperedges_per_variable": hyperedges_per_variable,
                    "target_hyperedge_count": target,
                    "anchor_pair_count": len(anchors),
                    "anchor_pairs": [list(pair) for pair in anchors],
                },
                "master_seed": master_seed,
                "instance_seed": instance_seed,
                "generator_version": generator_version,
                "rejection_count": total_rejections,
            },
            "instance_id": "",
        }
        instance["instance_id"] = compute_instance_id(instance)
        return instance

    raise RuntimeError(
        f"Unable to generate coverage-valid spin glass after {max_restarts} restarts"
    )
