"""Boolean multilinear polynomial helpers and weighted-clause conversion."""

from collections import defaultdict
from itertools import combinations
from math import prod


def canonicalize(terms):
    """Aggregate terms in Boolean multilinear form (x_i**2 == x_i)."""
    result = defaultdict(int)
    items = terms.items() if hasattr(terms, "items") else terms
    for support, coefficient in items:
        result[tuple(sorted(set(support)))] += coefficient
    return dict(sorted(
        ((support, coefficient) for support, coefficient in result.items() if coefficient),
        key=lambda item: (len(item[0]), item[0]),
    ))


def add_polynomials(*polynomials):
    return canonicalize(
        (term for polynomial in polynomials for term in polynomial.items())
    )


def multiply_polynomials(left, right):
    return canonicalize(
        (tuple(left_support) + tuple(right_support), left_coefficient * right_coefficient)
        for left_support, left_coefficient in left.items()
        for right_support, right_coefficient in right.items()
    )


def scale_polynomial(polynomial, scalar):
    return canonicalize((support, scalar * coefficient) for support, coefficient in polynomial.items())


def literal_false_indicator(literal):
    variable = abs(literal)
    return {(): 1, (variable,): -1} if literal > 0 else {(variable,): 1}


def clause_polynomial(clause):
    polynomial = {(): 1}
    for literal in clause["literals"]:
        polynomial = multiply_polynomials(polynomial, literal_false_indicator(literal))
    return scale_polynomial(polynomial, clause["weight"])


def clauses_to_pubo(clauses):
    return add_polynomials(*(clause_polynomial(clause) for clause in clauses))


def literal_truth(literal, bits):
    value = bits[abs(literal) - 1]
    return value if literal > 0 else 1 - value


def evaluate_weighted_clauses(clauses, bits):
    # Deliberately independent of the polynomial evaluator.
    return sum(
        clause["weight"]
        for clause in clauses
        if all(literal_truth(literal, bits) == 0 for literal in clause["literals"])
    )


def evaluate_pubo(coefficients, bits):
    return sum(
        coefficient * prod(bits[index - 1] for index in support)
        for support, coefficient in coefficients.items()
    )


def cubic_supports(coefficients):
    return {support for support, coefficient in coefficients.items() if len(support) == 3 and coefficient}


def pair_shadow(cubics):
    return {pair for cubic in cubics for pair in combinations(cubic, 2)}


def pair_degrees(cubics):
    return {pair: sum(pair[0] in cubic and pair[1] in cubic for cubic in cubics) for pair in pair_shadow(cubics)}


def minimum_pair_cover_size(cubics):
    shadow = sorted(pair_shadow(cubics))
    for size in range(len(shadow) + 1):
        for selected in combinations(shadow, size):
            if all(any(set(pair).issubset(cubic) for pair in selected) for cubic in cubics):
                return size
    raise ValueError("No pair cover exists")


def polynomial_degree(coefficients):
    return max((len(support) for support in coefficients), default=0)
