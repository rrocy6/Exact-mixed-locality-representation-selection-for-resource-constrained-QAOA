"""Selective and fully quadratized objectives for the worked example."""

from .penalties import rosenberg


def degree_at_most_two(bits):
    _, x2, x3, x4, _ = bits
    return 4 - 4*x2 - 4*x3 - 4*x4 + 4*x2*x3 + 4*x2*x4 + 4*x3*x4


def selective_value(bits, y23, m23=6):
    x1, x2, x3, x4, x5 = bits
    return (degree_at_most_two(bits) + 5*x1*y23 - 4*y23*x4
            + 2*x1*x4*x5 + m23*rosenberg(x2, x3, y23))


def full_value(bits, y23, y14, m23=6, m14=3):
    x1, x2, x3, x4, x5 = bits
    return (degree_at_most_two(bits) + 5*x1*y23 - 4*y23*x4 + 2*y14*x5
            + m23*rosenberg(x2, x3, y23) + m14*rosenberg(x1, x4, y14))


def isolated_14_value(x1, x4, x5, y14, m14):
    return 2*y14*x5 + m14*rosenberg(x1, x4, y14)


def encoding_metrics():
    # Degree-two supports after coefficient aggregation. Auxiliary indices: 6=y23, 7=y14.
    return {
        "native": {"variables": 5, "auxiliaries": 0, "retained_cubics": 3,
                   "quadratic_couplings": 3, "penalties": ()},
        "selective": {"variables": 6, "auxiliaries": 1, "retained_cubics": 1,
                      "quadratic_couplings": 7, "penalties": (6,)},
        "full": {"variables": 7, "auxiliaries": 2, "retained_cubics": 0,
                 "quadratic_couplings": 11, "penalties": (6, 3)},
    }
