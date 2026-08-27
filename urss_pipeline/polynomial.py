"""Canonical Boolean-polynomial conversion and independent evaluators."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from numbers import Number
from typing import Iterable, Mapping, Sequence


Support = tuple[int, ...]
Polynomial = dict[Support, Number]


def canonicalize(
    terms: Mapping[Iterable[int], Number]
    | Iterable[tuple[Iterable[int], Number]],
) -> Polynomial:
    """Aggregate equal Boolean supports and remove exact zero coefficients."""

    items = terms.items() if isinstance(terms, Mapping) else terms
    totals: defaultdict[Support, Number] = defaultdict(int)
    for raw_support, coefficient in items:
        support = tuple(sorted(set(raw_support)))
        if any(index < 1 for index in support):
            raise ValueError(f"Variable indices must start at 1: {support}")
        totals[support] += coefficient
    return dict(
        sorted(
            (
                (support, coefficient)
                for support, coefficient in totals.items()
                if coefficient != 0
            ),
            key=lambda item: (len(item[0]), item[0]),
        )
    )


def add_polynomials(*polynomials: Mapping[Support, Number]) -> Polynomial:
    return canonicalize(
        (support, coefficient)
        for polynomial in polynomials
        for support, coefficient in polynomial.items()
    )


def multiply_polynomials(
    left: Mapping[Support, Number],
    right: Mapping[Support, Number],
) -> Polynomial:
    return canonicalize(
        (
            tuple(left_support) + tuple(right_support),
            left_coefficient * right_coefficient,
        )
        for left_support, left_coefficient in left.items()
        for right_support, right_coefficient in right.items()
    )


def scale_polynomial(
    polynomial: Mapping[Support, Number], scalar: Number
) -> Polynomial:
    return canonicalize(
        (support, scalar * coefficient)
        for support, coefficient in polynomial.items()
    )


def literal_false_indicator(literal: int) -> Polynomial:
    if literal == 0:
        raise ValueError("Literal 0 is invalid")
    variable = abs(literal)
    if literal > 0:
        return {(): 1, (variable,): -1}
    return {(variable,): 1}


def max3sat_clause_polynomials(
    instance: Mapping[str, object]
) -> list[Polynomial]:
    clauses = instance["problem"]["clauses"]  # type: ignore[index]
    clause_polynomials: list[Polynomial] = []
    for clause in clauses:
        polynomial: Polynomial = {(): 1}
        for literal in clause["literals"]:
            polynomial = multiply_polynomials(
                polynomial, literal_false_indicator(literal)
            )
        clause_polynomials.append(
            scale_polynomial(polynomial, clause["weight"])
        )
    return clause_polynomials


def max3sat_to_pubo(instance: Mapping[str, object]) -> Polynomial:
    """Expand weighted clause-violation indicators and aggregate them."""

    return add_polynomials(*max3sat_clause_polynomials(instance))


def spin_hyperedge_polynomials(
    instance: Mapping[str, object]
) -> list[Polynomial]:
    problem = instance["problem"]  # type: ignore[index]
    terms: list[Polynomial] = []
    if problem["c"] != 0:
        terms.append({(): problem["c"]})
    for hyperedge in problem["hyperedges"]:
        term: Polynomial = {(): hyperedge["coefficient"]}
        for variable in hyperedge["variables"]:
            term = multiply_polynomials(
                term, {(): 1, (variable,): -2}
            )
        terms.append(term)
    return terms


def spin_glass_to_pubo(instance: Mapping[str, object]) -> Polynomial:
    """Apply s_i=1-2*x_i to every cubic spin interaction."""

    return add_polynomials(*spin_hyperedge_polynomials(instance))


def evaluate_pubo(
    polynomial: Mapping[Support, Number], bits: Sequence[int]
) -> Number:
    total: Number = 0
    for support, coefficient in polynomial.items():
        monomial = 1
        for variable in support:
            monomial *= bits[variable - 1]
        total += coefficient * monomial
    return total


def evaluate_max3sat_direct(
    instance: Mapping[str, object], bits: Sequence[int]
) -> int:
    """Score violated clause weight without using polynomial conversion."""

    total = 0
    for clause in instance["problem"]["clauses"]:  # type: ignore[index]
        truths = []
        for literal in clause["literals"]:
            bit = bits[abs(literal) - 1]
            truths.append(bit if literal > 0 else 1 - bit)
        if all(value == 0 for value in truths):
            total += clause["weight"]
    return total


def evaluate_spin_glass_direct(
    instance: Mapping[str, object], bits: Sequence[int]
) -> int:
    """Evaluate the original spin objective independently of conversion."""

    spins = [1 - 2 * bit for bit in bits]
    problem = instance["problem"]  # type: ignore[index]
    total = problem["c"]
    for hyperedge in problem["hyperedges"]:
        product = hyperedge["coefficient"]
        for variable in hyperedge["variables"]:
            product *= spins[variable - 1]
        total += product
    return total


def cubic_supports(polynomial: Mapping[Support, Number]) -> set[Support]:
    return {support for support in polynomial if len(support) == 3}


def pair_shadow(cubics: Iterable[Support]) -> set[Support]:
    return {
        pair
        for cubic in cubics
        for pair in combinations(cubic, 2)
    }


def pair_degrees(cubics: Iterable[Support]) -> dict[Support, int]:
    counts: defaultdict[Support, int] = defaultdict(int)
    for cubic in cubics:
        for pair in combinations(cubic, 2):
            counts[pair] += 1
    return dict(sorted(counts.items()))
