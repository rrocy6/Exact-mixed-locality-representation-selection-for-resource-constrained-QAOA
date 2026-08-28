from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from urss_pipeline.e1_e2_corrections import (
    _evaluate_one_design,
    _method_status,
    common_feasible_ids,
    deterministic_nontrivial_actions,
    e2_capacity_summary,
    matched_nontrivial_actions,
)
from urss_pipeline.e1_exactness import build_mixed_representation
from urss_pipeline.polynomial import cubic_supports


class E1CorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.polynomial = {
            (1, 2, 3): 1,
            (1, 2, 4): -2,
            (1,): 1,
        }

    def test_deterministic_design_is_genuinely_selective(self) -> None:
        actions, reason = deterministic_nontrivial_actions(
            self.polynomial,
            n_original=4,
            positive_margin=1,
        )
        self.assertEqual(reason, "deterministic_first_single_reduction")
        self.assertIsNotNone(actions)
        representation = build_mixed_representation(
            self.polynomial,
            n_original=4,
            actions=actions,
            default_margin=1,
        )
        self.assertGreater(representation.n_auxiliary, 0)
        self.assertGreater(len(cubic_supports(representation.polynomial)), 0)

    def test_one_cubic_is_explicitly_not_constructible(self) -> None:
        actions, reason = deterministic_nontrivial_actions(
            {(1, 2, 3): 1},
            n_original=3,
            positive_margin=1,
        )
        self.assertIsNone(actions)
        self.assertEqual(reason, "fewer_than_two_cubic_terms")

    def test_matched_random_never_uses_zero_auxiliary(self) -> None:
        selected, _ = deterministic_nontrivial_actions(
            self.polynomial,
            n_original=4,
            positive_margin=1,
        )
        assert selected is not None
        sampled = matched_nontrivial_actions(
            self.polynomial,
            n_original=4,
            selected_actions=selected,
            instance_id="example",
            seed_bundle=(11, 12, 13),
            positive_margin=1,
        )
        self.assertEqual([seed for seed, _, _ in sampled], [11, 12, 13])
        for _, actions, _ in sampled:
            representation = build_mixed_representation(
                self.polynomial,
                n_original=4,
                actions=actions,
                default_margin=1,
            )
            self.assertEqual(representation.n_auxiliary, 1)
            self.assertGreater(len(cubic_supports(representation.polynomial)), 0)

    def test_supplement_trials_pass_required_boundary_gates(self) -> None:
        actions, _ = deterministic_nontrivial_actions(
            self.polynomial,
            n_original=4,
            positive_margin=1,
        )
        assert actions is not None
        rows, _, witnesses = _evaluate_one_design(
            self.polynomial,
            n_original=4,
            actions=actions,
            representation_name="supplement",
            random_seed=None,
            below_delta=1,
            above_epsilon=1,
            witness_prefix="example",
        )
        self.assertTrue(all(row["status"] == "pass" for row in rows))
        strict = next(row for row in rows if row["penalty_setting"] == "above_threshold")
        below = next(row for row in rows if row["penalty_setting"] == "below_threshold")
        at = next(row for row in rows if row["penalty_setting"] == "at_threshold")
        self.assertEqual(strict["mismatch_count"], 0)
        self.assertEqual(strict["inconsistent_minimiser_count"], 0)
        self.assertGreater(below["mismatch_count"], 0)
        self.assertEqual(at["mismatch_count"], 0)
        below_witness = next(item for item in witnesses if item["penalty_setting"] == "below_threshold")
        at_witness = next(item for item in witnesses if item["penalty_setting"] == "at_threshold")
        self.assertGreater(below_witness["pointwise_error"], 0)
        self.assertLess(below_witness["minimum_reduced_energy"], below_witness["original_energy"])
        self.assertEqual(at_witness["pointwise_error"], 0)
        self.assertTrue(at_witness["inconsistent_minimising_auxiliary_bits"])


class E2CorrectionTests(unittest.TestCase):
    def _rows(self):
        rows = []
        for instance, family in (("a", "max3sat"), ("b", "max3sat"), ("c", "cubic_spin_glass")):
            for representation in ("all_native", "fully_quadratized", "selective"):
                status = "pass"
                if instance == "b" and representation == "fully_quadratized":
                    status = "infeasible_width_exceeds_topology"
                for seed in (1, 2):
                    rows.append(
                        {
                            "instance_id": instance,
                            "family": family,
                            "representation": representation,
                            "random_rep_seed": "",
                            "design_id": representation,
                            "topology_id": "device_sparse_v1",
                            "transpiler_seed": str(seed),
                            "status": status,
                        }
                    )
        return rows

    def test_common_feasible_intersection_uses_same_ids(self) -> None:
        common, successful = common_feasible_ids(self._rows())
        self.assertEqual(common, {"a", "c"})
        self.assertEqual(successful["all_native"], {"a", "b", "c"})
        self.assertEqual(successful["fully_quadratized"], {"a", "c"})

    def test_capacity_failures_are_separate(self) -> None:
        summary = e2_capacity_summary(
            self._rows(),
            config_hash="c",
            manifest_hash="m",
            code_commit="f" * 40,
        )
        full = next(
            row
            for row in summary
            if row["family"] == "max3sat" and row["representation"] == "fully_quadratized"
        )
        self.assertEqual(full["scheduled_row_count"], 4)
        self.assertEqual(full["success_row_count"], 2)
        self.assertEqual(full["infeasible_width_row_count"], 2)
        self.assertEqual(full["other_failure_row_count"], 0)

    def test_method_status_detects_current_resource_only_e3(self) -> None:
        status = _method_status(
            {"selector": {"weights": {"auxiliary_count": 1}}},
            "selected_search = beam_select_design(polynomial)",
        )
        self.assertEqual(status["method_status"], "resource_only_selector")

    def test_method_status_refuses_unreviewed_fibre_rule(self) -> None:
        with self.assertRaises(Exception):
            _method_status(
                {"selector": {"fibre_risk": "pair_moment"}},
                "selected_search = beam_select_design(polynomial)",
            )


if __name__ == "__main__":
    unittest.main()
