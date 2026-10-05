"""Independent exact checks of the static and compiled representation claims.

Pure standard-library Python. Uses exact rational Pauli expansion and actual
ordered CNOT streams, rather than the closed-form counts, for compiled checks.
Exhaustive static checks enumerate native/three-pair choices for every term.
Run: python revision/theory/verify_theory.py
"""
from collections import defaultdict
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path
import json


def star_forest(sizes):
    terms = []
    offset = 0
    for size in sizes:
        terms.extend((offset, offset + 1, offset + 2 + j) for j in range(size))
        offset += size + 2
    return terms, offset


def polynomial(terms, n, assignment, margin=Fraction(1, 4)):
    poly = defaultdict(Fraction)
    buckets = defaultdict(list)
    for term, pair in zip(terms, assignment):
        if pair is None:
            poly[tuple(term)] += 1
        else:
            buckets[pair].append(term)
    for k, (pair, bucket) in enumerate(sorted(buckets.items())):
        y = n + k
        a, b = pair
        M = len(bucket) + margin
        for term in bucket:
            leaf = next(q for q in term if q not in pair)
            poly[tuple(sorted((leaf, y)))] += 1
        poly[pair] += M
        poly[(a, y)] -= 2 * M
        poly[(b, y)] -= 2 * M
        poly[(y,)] += 3 * M
    return {k: v for k, v in poly.items() if v}, n + len(buckets)


def pauli(poly):
    result = defaultdict(Fraction)
    for support, coefficient in poly.items():
        for weight in range(len(support) + 1):
            for chosen in combinations(support, weight):
                result[chosen] += coefficient * Fraction((-1) ** weight, 2 ** len(support))
    return {k: v for k, v in result.items() if k and v}


def compile_reference(poly, width):
    gates = []
    supports = sorted(pauli(poly), key=lambda t: (len(t), t))
    for support in supports:
        compute = [(q, support[-1]) for q in support[:-1]]
        gates.extend(compute)
        gates.extend(reversed(compute))
    last = [0] * width
    for a, b in gates:
        layer = max(last[a], last[b]) + 1
        last[a] = last[b] = layer
    return len(gates), max(last, default=0)


def static_checks():
    checked = 0
    families = [(1,), (2,), (3,), (4,), (1, 1), (2, 2), (3, 2),
                (3, 3), (2, 1, 1), (4, 2), (2, 2, 2)]
    for sizes in families:
        terms, _ = star_forest(sizes)
        possibilities = [[None, *combinations(term, 2)] for term in terms]
        observed = set()
        for assignment in product(*possibilities):
            buckets = defaultdict(int)
            for pair in assignment:
                if pair is not None:
                    buckets[pair] += 1
            observed.add((len(buckets), max(buckets.values(), default=0), sum(buckets.values())))
        for r0 in range(len(terms) + 2):
            for C in range(max(sizes) + 2):
                actual = max(reduced for r, q, reduced in observed if r <= r0 and q <= C)
                gains = sorted((min(size, C) - 1 for size in sizes), reverse=True)
                predicted = 0 if r0 == 0 or C == 0 else min(len(terms), r0 + sum(gains[:r0]))
                assert actual == predicted, (sizes, r0, C, actual, predicted)
                # Exhaustive assignment set also verifies all five phase classes.
                for h0 in range(len(terms) + 2):
                    feasible = any(r <= r0 and q <= C and len(terms) - d <= h0
                                   for r, q, d in observed)
                    assert feasible == (predicted + h0 >= len(terms))
                checked += 1
    return checked


def evaluate(poly, bits):
    return sum(c for term, c in poly.items() if all(bits[q] for q in term))


def exactness_check(L, H):
    terms, n = star_forest([L] + [1] * H)
    original = {term: Fraction(1) for term in terms}
    assignment = [(0, 1)] * L + [None] * H
    reduced, width = polynomial(terms, n, assignment)
    for x in product((0, 1), repeat=n):
        values = [evaluate(reduced, x + y) for y in product((0, 1), repeat=width - n)]
        truth = evaluate(original, x)
        assert min(values) == truth
        assert values.count(truth) == 1
        assert values[x[0] * x[1]] == truth
    return 2 ** n


def compiled_checks():
    rows = []
    for L in range(2, 33):
        for H in range(1, 9):
            terms, n = star_forest([L] + [1] * H)
            native = [None] * len(terms)
            mixed = [(0, 1)] * L + [None] * H
            full = [(0, 1)] * L + [tuple(term[:2]) for term in terms[L:]]
            measured = {}
            for label, assignment in (("native", native), ("mixed", mixed), ("full_core", full)):
                poly, width = polynomial(terms, n, assignment)
                gates, depth = compile_reference(poly, width)
                measured[label] = {"width": width, "gates": gates, "depth": depth}
            assert measured["native"] == {"width": n, "gates": 8 * L + 2 + 10 * H,
                                           "depth": 6 * L + 3}
            assert measured["mixed"] == {"width": n + 1, "gates": 2 * L + 6 + 10 * H,
                                          "depth": 2 * L + 6}
            assert measured["full_core"] == {"width": n + H + 1, "gates": 2 * L + 6 + 8 * H,
                                              "depth": 2 * L + 6}
            rows.append({"L": L, "H": H, **measured})
    return rows


if __name__ == "__main__":
    static_count = static_checks()
    rows = compiled_checks()
    exactness_count = sum(exactness_check(L, H) for L in range(2, 6) for H in range(1, 3))
    summary = {"static_budget_cases": static_count, "compiled_family_instances": len(rows),
               "exhaustive_original_assignments_for_exactness": exactness_count,
               "all_assertions_passed": True, "compiler": "collected exact Pauli expansion; weight/lex ordering; largest-index parity target; CNOT ASAP",
               "compiled_results": rows}
    destination = Path(__file__).with_name("verification_results.json")
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "compiled_results"}, indent=2))
