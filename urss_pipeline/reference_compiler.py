"""Deterministic all-to-all reference compiler from the paper appendix.

The compiler operates on a collected Boolean polynomial, applies
'x_i = (I - Z_i) / 2' exactly, and emits the fixed ancilla-free parity
gadgets defined by the paper.  It intentionally performs no cross-gadget
cancellation or commutation-based reordering.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from numbers import Number
from typing import Mapping

from .polynomial import Polynomial, Support, canonicalize


PauliPolynomial = dict[Support, Fraction]
Cnot = tuple[int, int]


def _as_fraction(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def boolean_to_pauli(
    polynomial: Mapping[Support, Number],
) -> PauliPolynomial:
    """Collect the exact Pauli-Z expansion of a Boolean polynomial."""

    totals: dict[Support, Fraction] = {}
    for support, raw_coefficient in canonicalize(polynomial).items():
        coefficient = _as_fraction(raw_coefficient)
        scale = coefficient / (1 << len(support))
        for size in range(len(support) + 1):
            sign = -1 if size % 2 else 1
            for z_support in combinations(support, size):
                totals[z_support] = (
                    totals.get(z_support, Fraction(0)) + sign * scale
                )
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


def emit_cnot_stream(pauli: Mapping[Support, Fraction]) -> tuple[Cnot, ...]:
    """Emit the paper's ordered two-qubit stream without cancellations."""

    stream: list[Cnot] = []
    for support, coefficient in sorted(
        pauli.items(), key=lambda item: (len(item[0]), item[0])
    ):
        if coefficient == 0 or len(support) < 2:
            continue
        target = support[-1]
        controls = support[:-1]
        stream.extend((control, target) for control in controls)
        stream.extend((control, target) for control in reversed(controls))
    return tuple(stream)


def earliest_layer_depth(
    cnot_stream: tuple[Cnot, ...], *, n_qubits: int
) -> int:
    """Apply the deterministic earliest-layer recurrence from the appendix."""

    availability = [0] * (n_qubits + 1)
    maximum = 0
    for control, target in cnot_stream:
        if not (1 <= control <= n_qubits and 1 <= target <= n_qubits):
            raise ValueError(
                f"CNOT ({control}, {target}) exceeds width {n_qubits}"
            )
        layer = 1 + max(availability[control], availability[target])
        availability[control] = layer
        availability[target] = layer
        maximum = max(maximum, layer)
    return maximum


def _fraction_json(value: Fraction) -> dict[str, int]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


@dataclass(frozen=True)
class ReferenceCompilation:
    """Auditable logical resources for one collected polynomial."""

    n_qubits: int
    pauli: PauliPolynomial
    cnot_stream: tuple[Cnot, ...]
    two_qubit_depth: int

    @property
    def two_qubit_gate_count(self) -> int:
        return len(self.cnot_stream)

    @property
    def swap_count(self) -> int:
        return 0

    @property
    def pauli_counts(self) -> dict[int, int]:
        result: dict[int, int] = {}
        for support in self.pauli:
            result[len(support)] = result.get(len(support), 0) + 1
        return result

    @property
    def coefficient_dynamic_range(self) -> float:
        """Non-identity Pauli coefficient ratio; zero for a constant operator.

        The identity contributes only a global phase.  Excluding it makes this
        diagnostic invariant under adding a constant to the objective.
        """
        nonzero = [abs(value) for support, value in self.pauli.items() if support and value]
        if not nonzero:
            return 0.0
        return float(max(nonzero) / min(nonzero))

    def to_record(self) -> dict[str, object]:
        serialised_terms = [
            {
                "support": list(support),
                "coefficient": _fraction_json(coefficient),
            }
            for support, coefficient in self.pauli.items()
        ]
        stream_payload = json.dumps(
            self.cnot_stream, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        pauli_payload = json.dumps(
            serialised_terms,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        counts = self.pauli_counts
        return {
            "compiler_id": "paper_all_to_all_reference_v1",
            "n_qubits": self.n_qubits,
            "pauli_term_count": len(self.pauli),
            "pauli_weight_0": counts.get(0, 0),
            "pauli_weight_1": counts.get(1, 0),
            "pauli_weight_2": counts.get(2, 0),
            "pauli_weight_3": counts.get(3, 0),
            "two_qubit_gate_count": self.two_qubit_gate_count,
            "two_qubit_depth": self.two_qubit_depth,
            "swap_count": self.swap_count,
            "coefficient_dynamic_range": self.coefficient_dynamic_range,
            "pauli_terms_sha256": hashlib.sha256(pauli_payload).hexdigest(),
            "cnot_stream_sha256": hashlib.sha256(stream_payload).hexdigest(),
            "pauli_terms": serialised_terms,
            "cross_gadget_cancellation": False,
            "commutation_reordering": False,
            "approximate_angle_simplification": False,
        }


def compile_reference(
    polynomial: Mapping[Support, Number], *, n_qubits: int
) -> ReferenceCompilation:
    """Compile a degree-at-most-three polynomial to reference resources."""

    if n_qubits < 1:
        raise ValueError("n_qubits must be positive")
    canonical: Polynomial = canonicalize(polynomial)
    for support in canonical:
        if len(support) > 3:
            raise ValueError(
                "Reference pilot supports polynomial degree at most three"
            )
        if support and support[-1] > n_qubits:
            raise ValueError(
                f"Support {support} exceeds declared width {n_qubits}"
            )
    pauli = boolean_to_pauli(canonical)
    stream = emit_cnot_stream(pauli)
    return ReferenceCompilation(
        n_qubits=n_qubits,
        pauli=pauli,
        cnot_stream=stream,
        two_qubit_depth=earliest_layer_depth(
            stream, n_qubits=n_qubits
        ),
    )
