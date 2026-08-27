"""Deterministic full quadratization used by the reference pilot."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, product
from numbers import Number
from typing import Mapping, Sequence

from .polynomial import (
    Polynomial,
    Support,
    canonicalize,
    cubic_supports,
    evaluate_pubo,
    pair_shadow,
)


class PairCoverTooLargeError(RuntimeError):
    """The exact pilot pair-cover enumerator exceeded its declared scope."""


def _as_fraction(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def minimum_pair_cover(
    cubics: set[Support], *, maximum_pair_candidates: int = 24
) -> tuple[Support, ...]:
    """Return the lexicographically first minimum-cardinality pair cover."""

    if not cubics:
        return ()
    pairs = sorted(pair_shadow(cubics))
    if len(pairs) > maximum_pair_candidates:
        raise PairCoverTooLargeError(
            "Exact exhaustive pair-cover pilot is limited to "
            f"{maximum_pair_candidates} candidate pairs; received {len(pairs)}"
        )
    ordered_cubics = sorted(cubics)
    for size in range(1, len(pairs) + 1):
        for selected in combinations(pairs, size):
            if all(
                any(set(pair).issubset(cubic) for pair in selected)
                for cubic in ordered_cubics
            ):
                return selected
    raise AssertionError("Every finite family of cubic supports has a pair cover")


@dataclass(frozen=True)
class FullQuadratization:
    """A deterministic, minimum-auxiliary full quadratic representation."""

    original_width: int
    active_pairs: tuple[Support, ...]
    polynomial: Polynomial
    penalties: tuple[dict[str, object], ...]

    @property
    def n_auxiliary(self) -> int:
        return len(self.active_pairs)

    @property
    def n_qubits(self) -> int:
        return self.original_width + self.n_auxiliary

    @property
    def auxiliary_indices(self) -> dict[Support, int]:
        return {
            pair: self.original_width + ordinal
            for ordinal, pair in enumerate(self.active_pairs, start=1)
        }

    def to_record(self) -> dict[str, object]:
        return {
            "representation": "fully_quadratized",
            "pair_assignment_rule": (
                "minimum_cardinality_pair_cover_with_lexicographic_"
                "pair_set_and_assignment_tie_break"
            ),
            "n_original": self.original_width,
            "n_auxiliary": self.n_auxiliary,
            "n_qubits": self.n_qubits,
            "active_pairs": [list(pair) for pair in self.active_pairs],
            "auxiliary_indices": [
                {
                    "pair": list(pair),
                    "variable": self.auxiliary_indices[pair],
                }
                for pair in self.active_pairs
            ],
            "penalties": list(self.penalties),
        }


def fully_quadratize(
    polynomial: Mapping[Support, Number],
    *,
    n_original: int,
    positive_margin: Number = 1,
    maximum_pair_candidates: int = 24,
) -> FullQuadratization:
    """Reduce every cubic using the deterministic minimum pair cover."""

    if n_original < 1:
        raise ValueError("n_original must be positive")
    margin = _as_fraction(positive_margin)
    if margin <= 0:
        raise ValueError("positive_margin must be strictly positive")
    canonical = canonicalize(polynomial)
    if any(len(support) > 3 for support in canonical):
        raise ValueError("Full quadratization pilot supports degree at most three")
    cubics = cubic_supports(canonical)
    active_pairs = minimum_pair_cover(
        cubics, maximum_pair_candidates=maximum_pair_candidates
    )
    auxiliary = {
        pair: n_original + ordinal
        for ordinal, pair in enumerate(active_pairs, start=1)
    }
    output_terms: list[tuple[Support, Fraction]] = [
        (support, _as_fraction(coefficient))
        for support, coefficient in canonical.items()
        if len(support) <= 2
    ]
    assigned: dict[Support, list[Fraction]] = {
        pair: [] for pair in active_pairs
    }

    for cubic in sorted(cubics):
        pair = next(
            pair for pair in active_pairs if set(pair).issubset(cubic)
        )
        remaining = next(variable for variable in cubic if variable not in pair)
        coefficient = _as_fraction(canonical[cubic])
        output_terms.append(((auxiliary[pair], remaining), coefficient))
        assigned[pair].append(coefficient)

    penalties: list[dict[str, object]] = []
    for pair in active_pairs:
        positive_mass = sum(
            (coefficient for coefficient in assigned[pair] if coefficient > 0),
            Fraction(0),
        )
        negative_mass = sum(
            (-coefficient for coefficient in assigned[pair] if coefficient < 0),
            Fraction(0),
        )
        threshold = max(positive_mass, negative_mass)
        penalty = threshold + margin
        left, right = pair
        y = auxiliary[pair]
        output_terms.extend(
            [
                ((left, right), penalty),
                ((left, y), -2 * penalty),
                ((right, y), -2 * penalty),
                ((y,), 3 * penalty),
            ]
        )
        penalties.append(
            {
                "pair": list(pair),
                "auxiliary": y,
                "positive_mass": float(positive_mass),
                "negative_mass": float(negative_mass),
                "threshold": float(threshold),
                "positive_margin": float(margin),
                "penalty": float(penalty),
            }
        )

    return FullQuadratization(
        original_width=n_original,
        active_pairs=active_pairs,
        polynomial=canonicalize(output_terms),
        penalties=tuple(penalties),
    )


def validate_full_quadratization(
    original: Mapping[Support, Number],
    representation: FullQuadratization,
) -> dict[str, object]:
    """Exhaustively check pointwise exactness and unique consistent fibres."""

    n_original = representation.original_width
    n_auxiliary = representation.n_auxiliary
    maximum_mismatch = Fraction(0)
    mismatch_count = 0
    inconsistent_minimiser_count = 0
    unique_consistency_violation_count = 0
    first_witness: dict[str, object] | None = None

    for original_bits in product((0, 1), repeat=n_original):
        original_energy = _as_fraction(evaluate_pubo(original, original_bits))
        energies: list[tuple[Fraction, tuple[int, ...]]] = []
        for auxiliary_bits in product((0, 1), repeat=n_auxiliary):
            bits: Sequence[int] = original_bits + auxiliary_bits
            energy = _as_fraction(
                evaluate_pubo(representation.polynomial, bits)
            )
            energies.append((energy, auxiliary_bits))
        minimum = min(energy for energy, _ in energies)
        minimisers = [
            bits for energy, bits in energies if energy == minimum
        ]
        expected = tuple(
            original_bits[left - 1] * original_bits[right - 1]
            for left, right in representation.active_pairs
        )
        mismatch = abs(original_energy - minimum)
        maximum_mismatch = max(maximum_mismatch, mismatch)
        if mismatch:
            mismatch_count += 1
        inconsistent = [bits for bits in minimisers if bits != expected]
        inconsistent_minimiser_count += len(inconsistent)
        if minimisers != [expected]:
            unique_consistency_violation_count += 1
        if (
            first_witness is None
            and (mismatch or minimisers != [expected])
        ):
            first_witness = {
                "original_bits": list(original_bits),
                "original_energy": float(original_energy),
                "minimum_reduced_energy": float(minimum),
                "expected_auxiliary_bits": list(expected),
                "minimising_auxiliary_bits": [
                    list(bits) for bits in minimisers
                ],
            }

    return {
        "status": (
            "pass"
            if mismatch_count == 0
            and unique_consistency_violation_count == 0
            else "fail"
        ),
        "original_assignment_count": 1 << n_original,
        "auxiliary_assignment_count_per_original": 1 << n_auxiliary,
        "maximum_pointwise_mismatch": float(maximum_mismatch),
        "mismatch_count": mismatch_count,
        "inconsistent_minimiser_count": inconsistent_minimiser_count,
        "unique_consistency_violation_count": (
            unique_consistency_violation_count
        ),
        "first_witness": first_witness,
    }
