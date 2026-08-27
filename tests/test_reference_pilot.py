from __future__ import annotations

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from urss_pipeline.qaoa_pilot import (
    run_statevector_probe,
    statevector_width_from_amplitudes,
)
from urss_pipeline.reference_compiler import (
    boolean_to_pauli,
    compile_reference,
    earliest_layer_depth,
)
from urss_pipeline.reference_pilot import run_reference_pilot
from urss_pipeline.representations import (
    PairCoverTooLargeError,
    fully_quadratize,
    minimum_pair_cover,
    validate_full_quadratization,
)


ROOT = Path(__file__).resolve().parents[1]


class ReferenceCompilerTests(unittest.TestCase):
    def test_boolean_cubic_to_collected_pauli_is_exact(self) -> None:
        pauli = boolean_to_pauli({(1, 2, 3): 8})
        self.assertEqual(pauli[()], Fraction(1))
        self.assertEqual(pauli[(1,)], Fraction(-1))
        self.assertEqual(pauli[(2,)], Fraction(-1))
        self.assertEqual(pauli[(3,)], Fraction(-1))
        self.assertEqual(pauli[(1, 2)], Fraction(1))
        self.assertEqual(pauli[(1, 3)], Fraction(1))
        self.assertEqual(pauli[(2, 3)], Fraction(1))
        self.assertEqual(pauli[(1, 2, 3)], Fraction(-1))

    def test_reference_gate_formula_for_one_boolean_cubic(self) -> None:
        compilation = compile_reference(
            {(1, 2, 3): 8}, n_qubits=3
        )
        self.assertEqual(compilation.pauli_counts[2], 3)
        self.assertEqual(compilation.pauli_counts[3], 1)
        self.assertEqual(compilation.two_qubit_gate_count, 10)
        self.assertEqual(compilation.two_qubit_depth, 10)
        self.assertEqual(compilation.swap_count, 0)

    def test_exact_zero_is_removed_only_after_aggregation(self) -> None:
        pauli = boolean_to_pauli(
            {
                (1, 2): 1,
                (1,): Fraction(-1, 2),
                (2,): Fraction(-1, 2),
            }
        )
        self.assertEqual(pauli[()], Fraction(-1, 4))
        self.assertEqual(pauli[(1, 2)], Fraction(1, 4))
        self.assertNotIn((1,), pauli)
        self.assertNotIn((2,), pauli)

    def test_earliest_layer_schedule_parallelises_disjoint_gates(self) -> None:
        depth = earliest_layer_depth(
            ((1, 2), (1, 2), (3, 4), (3, 4)), n_qubits=4
        )
        self.assertEqual(depth, 2)

    def test_declared_width_is_enforced(self) -> None:
        with self.assertRaises(ValueError):
            compile_reference({(1, 3): 1}, n_qubits=2)


class RepresentationTests(unittest.TestCase):
    def test_lexicographic_minimum_pair_cover(self) -> None:
        cover = minimum_pair_cover({(1, 2, 3), (1, 2, 4)})
        self.assertEqual(cover, ((1, 2),))

    def test_large_pair_cover_uses_exact_milp_and_preserves_tie_break(self) -> None:
        cubics = {
            (start, start + 1, start + 2)
            for start in range(1, 28, 3)
        }
        with self.assertRaises(PairCoverTooLargeError):
            minimum_pair_cover(cubics, maximum_pair_candidates=24)
        cover = minimum_pair_cover(cubics, maximum_pair_candidates=30)
        self.assertEqual(
            cover,
            tuple((start, start + 1) for start in range(1, 28, 3)),
        )

    def test_full_quadratization_is_pointwise_exact_and_unique(self) -> None:
        original = {
            (1, 2, 3): 5,
            (1, 2, 4): -4,
            (1, 4, 5): 2,
        }
        full = fully_quadratize(
            original, n_original=5, positive_margin=1
        )
        report = validate_full_quadratization(original, full)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["maximum_pointwise_mismatch"], 0)
        self.assertEqual(report["inconsistent_minimiser_count"], 0)
        self.assertEqual(
            report["unique_consistency_violation_count"], 0
        )


class StatevectorPilotTests(unittest.TestCase):
    def test_small_statevector_probe(self) -> None:
        polynomial = {(1, 2, 3): 1, (1,): -1}
        report = run_statevector_probe(
            polynomial,
            n_qubits=3,
            scoring_polynomial=polynomial,
            n_original=3,
            gammas=[0.2],
            betas=[0.3],
            simulator_seed=7,
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["statevector_amplitudes"], 8)
        self.assertEqual(
            statevector_width_from_amplitudes(
                report["statevector_amplitudes"]
            ),
            3,
        )

    def test_fixed_statevector_probe_is_numerically_reproducible(self) -> None:
        arguments = {
            "n_qubits": 3,
            "scoring_polynomial": {(1, 2, 3): 1, (1,): -1},
            "n_original": 3,
            "gammas": [0.2],
            "betas": [0.3],
            "simulator_seed": 7,
        }
        first = run_statevector_probe(
            arguments["scoring_polynomial"], **arguments
        )
        second = run_statevector_probe(
            arguments["scoring_polynomial"], **arguments
        )
        self.assertAlmostEqual(
            first["projected_original_expectation"],
            second["projected_original_expectation"],
            places=14,
        )
        self.assertEqual(
            first["two_qubit_gate_count_per_cost_layer"],
            second["two_qubit_gate_count_per_cost_layer"],
        )

    def test_end_to_end_reference_pilot(self) -> None:
        config = ROOT / "configs" / "reference_pilot_v1.json"
        with tempfile.TemporaryDirectory() as output:
            audit = run_reference_pilot(
                config_path=config,
                output_directory=output,
            )
            self.assertEqual(audit["status"], "pass")
            self.assertTrue(
                audit[
                    "all_full_quadratization_exactness_checks_pass"
                ]
            )
            self.assertTrue(audit["all_statevector_probes_pass"])
            self.assertFalse(audit["formal_manifest_created"])
            self.assertFalse(audit["qmax_frozen"])
            root = Path(output)
            resources = (
                root / "reference_resources.csv"
            ).read_text(encoding="utf-8")
            self.assertIn("all_native", resources)
            self.assertIn("fully_quadratized", resources)
            json.loads(
                (root / "reference_pilot_audit.json").read_text(
                    encoding="utf-8"
                )
            )

    def test_nonempty_output_is_rejected(self) -> None:
        config = ROOT / "configs" / "reference_pilot_v1.json"
        with tempfile.TemporaryDirectory() as output:
            marker = Path(output) / "preserve.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_reference_pilot(
                    config_path=config,
                    output_directory=output,
                )
            self.assertEqual(
                marker.read_text(encoding="utf-8"), "keep"
            )


if __name__ == "__main__":
    unittest.main()
