from itertools import product

from src.encodings import encoding_metrics, full_value, isolated_14_value, selective_value
from src.exactness import CLAUSES
from src.pbo import (canonicalize, clause_polynomial, clauses_to_pubo, cubic_supports,
                     evaluate_pubo, evaluate_weighted_clauses, minimum_pair_cover_size,
                     pair_degrees, pair_shadow, polynomial_degree)
from src.penalties import residual_masses, rosenberg


EXPECTED = {
    (): 4, (2,): -4, (3,): -4, (4,): -4,
    (2, 3): 4, (2, 4): 4, (3, 4): 4,
    (1, 2, 3): 5, (2, 3, 4): -4, (1, 4, 5): 2,
}
ALL_X = list(product((0, 1), repeat=5))


def test_direct_easy_assignments():
    assert evaluate_weighted_clauses(CLAUSES, (0, 0, 0, 0, 0)) == 4
    assert evaluate_weighted_clauses(CLAUSES, (1, 1, 1, 0, 0)) == 5
    assert evaluate_weighted_clauses(CLAUSES, (1, 1, 1, 1, 1)) == 7


def test_clause_expansion_and_canonical_pubo():
    assert clause_polynomial(CLAUSES[0]) == {(1, 2, 3): 5}
    assert clause_polynomial(CLAUSES[1]) == {(): 4, (2,): -4, (3,): -4, (4,): -4,
        (2, 3): 4, (2, 4): 4, (3, 4): 4, (2, 3, 4): -4}
    assert clause_polynomial(CLAUSES[2]) == {(1, 4, 5): 2}
    actual = clauses_to_pubo(CLAUSES)
    assert actual == EXPECTED
    assert len(actual) == 10 and polynomial_degree(actual) == 3
    assert canonicalize(actual) == actual
    assert canonicalize([((3, 2, 3), 2), ((2, 3), -2), ((1,), 3)]) == {(1,): 3}


def test_all_32_direct_vs_canonical():
    actual = clauses_to_pubo(CLAUSES)
    for x in ALL_X:
        direct, pubo = evaluate_weighted_clauses(CLAUSES, x), evaluate_pubo(actual, x)
        assert pubo == direct, {"x": x, "direct": direct, "pubo": pubo}


def test_cubic_shadow_reuse_and_pair_cover():
    cubics = cubic_supports(EXPECTED)
    assert cubics == {(1, 2, 3), (2, 3, 4), (1, 4, 5)}
    assert len(pair_shadow(cubics)) == 8
    degrees = pair_degrees(cubics)
    assert degrees[(2, 3)] == 2
    assert all(degree == 1 for pair, degree in degrees.items() if pair != (2, 3))
    assert max(degrees.values()) == 2
    assert minimum_pair_cover_size(cubics) == 2


def test_rosenberg_truth_table_and_thresholds():
    expected = [0, 3, 0, 1, 0, 1, 1, 0]
    for (a, b, y), value in zip(product((0, 1), repeat=3), expected):
        actual = rosenberg(a, b, y)
        assert actual == value, {"a": a, "b": b, "y": y, "actual": actual}
        assert actual >= 0 and ((actual == 0) == (y == a*b))
    assert residual_masses((5, -4)) == (5, 4, 5)
    assert residual_masses((2,)) == (2, 0, 2)


def test_selective_pointwise_exactness_and_unique_consistency():
    for x in ALL_X:
        expected = evaluate_weighted_clauses(CLAUSES, x)
        values = {y: selective_value(x, y, 6) for y in (0, 1)}
        minimum = min(values.values())
        minimisers = [y for y, value in values.items() if value == minimum]
        assert minimum == expected, {"x": x, "expected": expected, "actual": values}
        assert minimisers == [x[1]*x[2]], {"x": x, "minimisers": minimisers}


def test_selective_sharp_boundary_witness():
    x = (1, 1, 1, 0, 0)
    assert tuple(selective_value(x, y, 4) for y in (0, 1)) == (4, 5)
    assert tuple(selective_value(x, y, 5) for y in (0, 1)) == (5, 5)
    assert tuple(selective_value(x, y, 6) for y in (0, 1)) == (6, 5)
    for m, exact, tie in ((4, False, True), (5, True, True), (6, True, False)):
        mismatches, ties = [], []
        for assignment in ALL_X:
            values = [selective_value(assignment, y, m) for y in (0, 1)]
            target = evaluate_weighted_clauses(CLAUSES, assignment)
            if min(values) != target: mismatches.append((assignment, target, values))
            if values[0] == values[1]: ties.append((assignment, values))
        assert (not mismatches) == exact
        assert bool(ties) == tie


def test_full_pointwise_exactness_and_unique_consistency():
    for x in ALL_X:
        expected = evaluate_weighted_clauses(CLAUSES, x)
        values = {(y23, y14): full_value(x, y23, y14) for y23, y14 in product((0, 1), repeat=2)}
        minimum = min(values.values())
        minimisers = [aux for aux, value in values.items() if value == minimum]
        assert minimum == expected, {"x": x, "expected": expected, "actual": values}
        assert minimisers == [(x[1]*x[2], x[0]*x[3])], {"x": x, "minimisers": minimisers}


def test_isolated_14_sharp_boundary():
    assert tuple(isolated_14_value(1, 1, 1, y, 1) for y in (0, 1)) == (1, 2)
    assert tuple(isolated_14_value(1, 1, 1, y, 2) for y in (0, 1)) == (2, 2)
    assert tuple(isolated_14_value(1, 1, 1, y, 3) for y in (0, 1)) == (3, 2)
    for m, exact, tie in ((1, False, False), (2, True, True), (3, True, False)):
        mismatches, ties = [], []
        for x1, x4, x5 in product((0, 1), repeat=3):
            values = [isolated_14_value(x1, x4, x5, y, m) for y in (0, 1)]
            target = 2*x1*x4*x5
            if min(values) != target: mismatches.append(((x1, x4, x5), target, values))
            if values[0] == values[1]: ties.append(((x1, x4, x5), values))
        assert (not mismatches) == exact
        assert bool(ties) == tie


def test_metrics_optimum_and_minimiser_count():
    assert encoding_metrics() == {
        "native": {"variables": 5, "auxiliaries": 0, "retained_cubics": 3, "quadratic_couplings": 3, "penalties": ()},
        "selective": {"variables": 6, "auxiliaries": 1, "retained_cubics": 1, "quadratic_couplings": 7, "penalties": (6,)},
        "full": {"variables": 7, "auxiliaries": 2, "retained_cubics": 0, "quadratic_couplings": 11, "penalties": (6, 3)},
    }
    values = [evaluate_weighted_clauses(CLAUSES, x) for x in ALL_X]
    assert min(values) == 0
    assert values.count(0) == 21
