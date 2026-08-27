"""Derived canonical metadata and exact small-instance ground truth."""

from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations, product
from math import comb
from statistics import mean
from typing import Mapping

from .polynomial import (
    Polynomial,
    Support,
    cubic_supports,
    evaluate_max3sat_direct,
    evaluate_spin_glass_direct,
    max3sat_clause_polynomials,
    max3sat_to_pubo,
    pair_degrees,
    pair_shadow,
    spin_glass_to_pubo,
    spin_hyperedge_polynomials,
)


def polynomial_for_instance(instance: Mapping[str, object]) -> Polynomial:
    if instance["family"] == "max3sat":
        return max3sat_to_pubo(instance)
    if instance["family"] == "cubic_spin_glass":
        return spin_glass_to_pubo(instance)
    raise ValueError(f"Unsupported family: {instance['family']!r}")


def _component_statistics(cubics: set[Support]) -> tuple[int, int, int]:
    nodes = sorted(cubics)
    adjacency = {node: set() for node in nodes}
    for left, right in combinations(nodes, 2):
        if len(set(left).intersection(right)) >= 2:
            adjacency[left].add(right)
            adjacency[right].add(left)

    components = 0
    remaining = set(nodes)
    while remaining:
        components += 1
        queue = deque([remaining.pop()])
        while queue:
            node = queue.popleft()
            for neighbor in adjacency[node]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
    edge_count = sum(len(neighbors) for neighbors in adjacency.values()) // 2
    max_degree = max((len(neighbors) for neighbors in adjacency.values()), default=0)
    return edge_count, components, max_degree


def _minimum_pair_cover(cubics: set[Support]) -> dict[str, object]:
    if not cubics:
        return {
            "tau2": 0,
            "tau2_status": "exact",
            "tau2_lower_bound": 0,
            "tau2_upper_bound": 0,
        }
    pairs = sorted(pair_shadow(cubics))
    if len(pairs) > 20:
        greedy: list[Support] = []
        uncovered = set(cubics)
        while uncovered:
            best = max(
                pairs,
                key=lambda pair: sum(
                    set(pair).issubset(cubic) for cubic in uncovered
                ),
            )
            greedy.append(best)
            uncovered = {
                cubic
                for cubic in uncovered
                if not set(best).issubset(cubic)
            }
        return {
            "tau2": None,
            "tau2_status": "bounded_pair_shadow_too_large",
            "tau2_lower_bound": 1,
            "tau2_upper_bound": len(greedy),
        }

    for size in range(1, len(pairs) + 1):
        for selected in combinations(pairs, size):
            if all(
                any(set(pair).issubset(cubic) for pair in selected)
                for cubic in cubics
            ):
                return {
                    "tau2": size,
                    "tau2_status": "exact",
                    "tau2_lower_bound": size,
                    "tau2_upper_bound": size,
                }
    raise AssertionError("A finite cubic family must have a pair cover")


def _cancellation_metrics(instance: Mapping[str, object]) -> tuple[int, float]:
    if instance["family"] == "max3sat":
        pieces = max3sat_clause_polynomials(instance)
    else:
        pieces = spin_hyperedge_polynomials(instance)
    contributions: defaultdict[Support, list[float]] = defaultdict(list)
    for piece in pieces:
        for support, coefficient in piece.items():
            contributions[support].append(float(coefficient))
    cancellation_masses = []
    for values in contributions.values():
        mass = sum(abs(value) for value in values) - abs(sum(values))
        if mass > 0:
            cancellation_masses.append(mass)
    return len(cancellation_masses), sum(cancellation_masses)


def canonical_metadata(instance: Mapping[str, object]) -> dict[str, object]:
    polynomial = polynomial_for_instance(instance)
    n = instance["problem"]["n"]  # type: ignore[index]
    cubics = cubic_supports(polynomial)
    degrees = pair_degrees(cubics)
    shadow = set(degrees)
    m3 = len(cubics)
    reused_pairs = {pair for pair, degree in degrees.items() if degree >= 2}
    cubics_with_shared_pair = {
        cubic
        for cubic in cubics
        if any(degrees[pair] >= 2 for pair in combinations(cubic, 2))
    }
    overlap_edges, overlap_components, overlap_max_degree = _component_statistics(cubics)
    cancellation_count, cancellation_mass = _cancellation_metrics(instance)
    coefficients = [float(value) for value in polynomial.values()]
    cubic_coefficients = [float(polynomial[support]) for support in cubics]
    raw_count_field = (
        "m_clause" if instance["family"] == "max3sat" else "m_edge"
    )
    result: dict[str, object] = {
        "n": n,
        "raw_term_count": instance["problem"][raw_count_field],  # type: ignore[index]
        "canonical_term_count": len(polynomial),
        "canonical_degree": max((len(support) for support in polynomial), default=0),
        "m3": m3,
        "cubic_density": m3 / comb(n, 3),
        "cubics_per_variable": m3 / n,
        "pair_shadow_size": len(shadow),
        "pair_reuse_score": 0 if m3 == 0 else 1 - len(shadow) / (3 * m3),
        "Delta2": max(degrees.values(), default=0),
        "pair_degree_mean": mean(degrees.values()) if degrees else 0,
        "pair_degree_max": max(degrees.values(), default=0),
        "fraction_reused_pairs": len(reused_pairs) / len(shadow) if shadow else 0,
        "fraction_cubics_with_shared_pair": len(cubics_with_shared_pair) / m3 if m3 else 0,
        "overlap_graph_nodes": m3,
        "overlap_graph_edges": overlap_edges,
        "overlap_graph_components": overlap_components,
        "overlap_graph_max_degree": overlap_max_degree,
        "coefficient_min": min(coefficients, default=0),
        "coefficient_max": max(coefficients, default=0),
        "coefficient_abs_max": max((abs(value) for value in coefficients), default=0),
        "coefficient_l1": sum(abs(value) for value in coefficients),
        "positive_cubic_mass": sum(value for value in cubic_coefficients if value > 0),
        "negative_cubic_mass": sum(abs(value) for value in cubic_coefficients if value < 0),
        "positive_cubic_count": sum(value > 0 for value in cubic_coefficients),
        "negative_cubic_count": sum(value < 0 for value in cubic_coefficients),
        "canonical_cancellation_count": cancellation_count,
        "canonical_cancellation_mass": cancellation_mass,
        "candidate_pair_count": len(shadow),
    }
    result.update(_minimum_pair_cover(cubics))
    return result


def exact_ground_truth(instance: Mapping[str, object]) -> dict[str, object]:
    n = instance["problem"]["n"]  # type: ignore[index]
    if instance["family"] == "max3sat":
        evaluator = evaluate_max3sat_direct
    elif instance["family"] == "cubic_spin_glass":
        evaluator = evaluate_spin_glass_direct
    else:
        raise ValueError(f"Unsupported family: {instance['family']!r}")
    values = [
        evaluator(instance, bits)
        for bits in product((0, 1), repeat=n)
    ]
    ordered = sorted(set(values))
    optimum = ordered[0]
    first_excited = ordered[1] if len(ordered) > 1 else None
    return {
        "instance_id": instance["instance_id"],
        "optimum_original": optimum,
        "number_of_optima": values.count(optimum),
        "first_excited_value": first_excited,
        "first_excited_gap": (
            None if first_excited is None else first_excited - optimum
        ),
        "near_optimal_count_optional": None,
        "solver": "exhaustive_enumeration",
        "solver_version": "stdlib_v1",
        "solver_status": "optimal",
        "optimality_certificate_or_gap": "complete_enumeration",
        "verification_method": f"all_{1 << n}_assignments",
    }
