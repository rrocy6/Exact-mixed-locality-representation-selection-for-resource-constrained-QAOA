"""Penalty functions and exact threshold calculations."""


def rosenberg(a, b, y):
    return a * b - 2 * a * y - 2 * b * y + 3 * y


def residual_masses(coefficients):
    positive = sum(value for value in coefficients if value > 0)
    negative = -sum(value for value in coefficients if value < 0)
    return positive, negative, max(positive, negative)
