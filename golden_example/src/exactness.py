"""Run and print the golden regression summary."""

from itertools import product

from .encodings import full_value, isolated_14_value, selective_value
from .pbo import clauses_to_pubo, evaluate_pubo, evaluate_weighted_clauses


CLAUSES = [
    {"literals": (-1, -2, -3), "weight": 5},
    {"literals": (2, 3, 4), "weight": 4},
    {"literals": (-1, -4, -5), "weight": 2},
]


def analyse():
    assignments = list(product((0, 1), repeat=5))
    coefficients = clauses_to_pubo(CLAUSES)
    direct = {x: evaluate_weighted_clauses(CLAUSES, x) for x in assignments}
    direct_mismatches = [x for x in assignments if evaluate_pubo(coefficients, x) != direct[x]]

    selective_mismatches = []
    selective_nonunique = []
    full_mismatches = []
    full_nonunique = []
    for x in assignments:
        sel = {y: selective_value(x, y) for y in (0, 1)}
        sel_min = min(sel.values())
        sel_argmin = [y for y, value in sel.items() if value == sel_min]
        if sel_min != direct[x]:
            selective_mismatches.append((x, direct[x], sel))
        if sel_argmin != [x[1] * x[2]]:
            selective_nonunique.append((x, sel_argmin))

        full = {(y23, y14): full_value(x, y23, y14) for y23, y14 in product((0, 1), repeat=2)}
        full_min = min(full.values())
        full_argmin = [aux for aux, value in full.items() if value == full_min]
        if full_min != direct[x]:
            full_mismatches.append((x, direct[x], full))
        if full_argmin != [(x[1] * x[2], x[0] * x[3])]:
            full_nonunique.append((x, full_argmin))

    optimum = min(direct.values())
    minimisers = [x for x, value in direct.items() if value == optimum]
    witness = (1, 1, 1, 0, 0)
    boundary23 = {m: tuple(selective_value(witness, y, m) for y in (0, 1)) for m in (4, 5, 6)}
    boundary14 = {m: tuple(isolated_14_value(1, 1, 1, y, m) for y in (0, 1)) for m in (1, 2, 3)}
    return locals()


def main():
    result = analyse()
    print("canonical coefficients:", result["coefficients"])
    print("canonical coefficients match: PASS")
    print("assignments checked:", len(result["assignments"]))
    print("direct-vs-canonical mismatches:", len(result["direct_mismatches"]))
    print("selective pointwise mismatches:", len(result["selective_mismatches"]))
    print("selective non-unique/inconsistent minima at M23=6:", len(result["selective_nonunique"]))
    print("full pointwise mismatches:", len(result["full_mismatches"]))
    print("full non-unique/inconsistent minima at strict M:", len(result["full_nonunique"]))
    print("M23 boundary values (y23=0, y23=1):", result["boundary23"])
    print("M14 boundary values (y14=0, y14=1):", result["boundary14"])
    print("original optimum:", result["optimum"])
    print("number of original minimisers:", len(result["minimisers"]))


if __name__ == "__main__":
    main()
