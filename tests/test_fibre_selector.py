from __future__ import annotations

import unittest
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from urss_pipeline.fibre_selector import (
    _pareto_rank_and_crowding,
    FibreMoments,
    beam_select_fibre_design,
    certify_fibre_optimum,
    enumerate_fibre_candidates,
    enumerate_expected_fibre_excess,
    fibre_risk,
    greedy_select_fibre_design,
    matched_random_fibre_designs,
    solve_deterministic_sa_rlt_level2,
)
from urss_pipeline.fibre_validation import _newline_normalized_sha256


class FibreFormulaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.polynomial = {
            (1, 2, 3): Fraction(2),
            (1, 2, 4): Fraction(-1),
            (1,): Fraction(1),
        }
        self.moments = FibreMoments(
            objective=0.0,
            singles={1: 0.2, 2: 0.7, 3: 0.4, 4: 0.8},
            pairs={
                (1, 2): 0.18,
                (1, 3): 0.11,
                (1, 4): 0.17,
                (2, 3): 0.31,
                (2, 4): 0.52,
                (3, 4): 0.29,
            },
            status="fixture",
            solver_message="fixture",
            primary_runtime_sec=0.0,
            secondary_runtime_sec=0.0,
            moment_sha256="fixture",
        )

    def test_closed_form_matches_direct_product_enumeration(self) -> None:
        actions = ((1, 2), (1, 2))
        closed = fibre_risk(
            self.polynomial,
            n_original=4,
            actions=actions,
            moments=self.moments,
            positive_margin=1,
        )
        enumerated = enumerate_expected_fibre_excess(
            self.polynomial,
            n_original=4,
            actions=actions,
            moments=self.moments,
            positive_margin=1,
        )
        self.assertAlmostEqual(closed.excess, enumerated, places=11)
        self.assertGreater(closed.normalised_excess, 0)
        self.assertEqual(len(closed.contributions), 1)

    def test_native_design_has_zero_fibre_excess(self) -> None:
        risk = fibre_risk(
            self.polynomial,
            n_original=4,
            actions=(None, None),
            moments=self.moments,
            positive_margin=1,
        )
        self.assertEqual(risk.excess, 0)
        self.assertEqual(risk.normalised_excess, 0)
        self.assertEqual(risk.contributions, ())

    def test_parent_config_hash_is_invariant_to_git_crlf_checkout(self) -> None:
        lf_bytes = b"config_id: experiment_config_v1\nstatus: frozen\n"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "experiment_config_v1.yaml"
            path.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))
            self.assertEqual(
                _newline_normalized_sha256(path),
                sha256(lf_bytes).hexdigest(),
            )


class FibreRelaxationAndSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.polynomial = {
            (1, 2, 3): Fraction(1),
            (1, 2, 4): Fraction(-2),
            (1,): Fraction(1),
        }
        with open("configs/experiment_config_v1.yaml", encoding="utf-8") as stream:
            cls.config = yaml.safe_load(stream)
        cls.config["selector"]["fibre_risk"] = {
            "enabled": True,
            "threshold_tau": 0.25,
            "positive_penalty_margin": 1,
            "numeric_tolerance": 1e-9,
        }

    def test_deterministic_relaxation_repeats_exact_moment_hash(self) -> None:
        first = solve_deterministic_sa_rlt_level2(
            self.polynomial,
            n_original=4,
        )
        second = solve_deterministic_sa_rlt_level2(
            self.polynomial,
            n_original=4,
        )
        self.assertEqual(first.status, "optimal_primary_then_deterministic_secondary")
        self.assertEqual(first.moment_sha256, second.moment_sha256)
        self.assertEqual(first.singles, second.singles)
        self.assertEqual(first.pairs, second.pairs)

    def test_certified_and_beam_results_are_fibre_feasible(self) -> None:
        moments = solve_deterministic_sa_rlt_level2(
            self.polynomial,
            n_original=4,
        )
        selector = self.config["selector"]
        certified = certify_fibre_optimum(
            self.polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
        )
        beam = beam_select_fibre_design(
            self.polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
            apply_qaoa_hard_limits=True,
            certified=certified,
        )
        self.assertLessEqual(certified.risk.normalised_excess, 0.25 + 1e-9)
        self.assertLessEqual(beam.risk.normalised_excess, 0.25 + 1e-9)
        self.assertGreaterEqual(beam.regret, 0)

    def test_greedy_reports_nonnegative_certified_regret(self) -> None:
        moments = solve_deterministic_sa_rlt_level2(
            self.polynomial,
            n_original=4,
        )
        selector = self.config["selector"]
        certified = certify_fibre_optimum(
            self.polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
        )
        greedy = greedy_select_fibre_design(
            self.polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
            apply_qaoa_hard_limits=True,
            certified=certified,
        )
        self.assertLessEqual(greedy.risk.normalised_excess, 0.25 + 1e-9)
        self.assertGreaterEqual(greedy.regret, 0)

    def test_pareto_crowding_uses_all_five_coordinates_deterministically(self) -> None:
        moments = solve_deterministic_sa_rlt_level2(
            self.polynomial,
            n_original=4,
        )
        candidates = enumerate_fibre_candidates(
            self.polynomial,
            n_original=4,
            selector=self.config["selector"],
            moments=moments,
        )
        first = _pareto_rank_and_crowding(candidates)
        second = _pareto_rank_and_crowding(tuple(reversed(candidates)))
        self.assertEqual(first, second)
        self.assertEqual(set(first), {candidate.actions for candidate in candidates})
        self.assertTrue(any(value[1] == float("inf") for value in first.values()))

    def test_bounded_matched_random_is_deterministic_and_exactly_matched(self) -> None:
        selected = ((1, 2), (1, 2))
        first = matched_random_fibre_designs(
            self.polynomial,
            selected_actions=selected,
            instance_id="fixture_instance",
            seed_bundle=(11, 12, 13),
            maximum_pair_set_attempts=16,
        )
        second = matched_random_fibre_designs(
            self.polynomial,
            selected_actions=selected,
            instance_id="fixture_instance",
            seed_bundle=(11, 12, 13),
            maximum_pair_set_attempts=16,
        )
        self.assertEqual(first, second)
        self.assertEqual([seed for seed, _ in first], [11, 12, 13])
        self.assertTrue(
            all(
                len({action for action in actions if action is not None}) == 1
                for _, actions in first
            )
        )


if __name__ == "__main__":
    unittest.main()
