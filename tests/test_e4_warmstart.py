from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.e3_qaoa import QAOABudgetSpec, QAOADesign, statevector_data
from urss_pipeline.e4_warmstart import (
    MARGINAL_FIELDS,
    RUN_FIELDS,
    RelaxationMoments,
    WarmStartSpec,
    _latex_table,
    _simulate,
    marginal_diagnostic_rows,
    optimize_warmstart_run,
    product_state,
    simulate_warm_qaoa,
    solve_sa_rlt_level2,
    summarise_warmstart_runs,
    warm_start_specs,
    write_marginal_figure_pdf,
)
from urss_pipeline.polynomial import evaluate_pubo


ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load(
    (ROOT / "configs/experiment_config_v1.yaml").read_text(encoding="utf-8")
)
POLYNOMIAL = {(1,): -1, (1, 2, 3): 2}


class E4WarmStartTests(unittest.TestCase):
    def _design(self, actions=(None,), label="all_native") -> QAOADesign:
        evaluation = _evaluate_design(
            POLYNOMIAL,
            n_original=3,
            actions=actions,
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=True,
        )
        return QAOADesign(label, None, evaluation)

    def _moments(self) -> RelaxationMoments:
        return RelaxationMoments(
            objective=-1.0,
            singles={1: 0.2, 2: 0.7, 3: 0.4},
            pairs={(1, 2): 0.15, (1, 3): 0.1, (2, 3): 0.3},
            status="optimal",
            solver_message="ok",
            runtime_sec=0.01,
        )

    def _qaoa(self, evaluations: int = 4):
        copied = dict(CONFIG["qaoa"])
        copied["optimizer"] = dict(CONFIG["qaoa"]["optimizer"])
        copied["optimizer"]["objective_evaluations"] = evaluations
        return copied

    def test_required_raw_and_marginal_fields_are_present(self) -> None:
        raw_required = {
            "instance_id",
            "representation",
            "budget_mode",
            "p",
            "warm_start_policy",
            "pair_closure",
            "optimizer_seed",
            "evaluations",
            "original_objective_mean",
            "auxiliary_inconsistency_rate",
            "config_hash",
            "manifest_hash",
            "code_commit",
        }
        marginal_required = {
            "raw_single_moment",
            "clipped_single_moment",
            "abs_single_margin_from_half",
            "raw_pair_moment",
            "independence_pair_moment",
            "solver_status",
        }
        self.assertTrue(raw_required.issubset(RUN_FIELDS))
        self.assertTrue(marginal_required.issubset(MARGINAL_FIELDS))

    def test_sa_rlt_returns_all_first_and_pair_moments(self) -> None:
        moments = solve_sa_rlt_level2(POLYNOMIAL, n_original=3)
        self.assertEqual(moments.status, "optimal")
        self.assertEqual(set(moments.singles), {1, 2, 3})
        self.assertEqual(set(moments.pairs), {(1, 2), (1, 3), (2, 3)})
        self.assertTrue(all(0 <= value <= 1 for value in moments.singles.values()))
        self.assertTrue(all(0 <= value <= 1 for value in moments.pairs.values()))

    def test_sa_rlt_pair_moments_obey_boolean_envelopes(self) -> None:
        moments = solve_sa_rlt_level2(POLYNOMIAL, n_original=3)
        for (i, j), pair in moments.pairs.items():
            self.assertLessEqual(pair, moments.singles[i] + 1e-9)
            self.assertLessEqual(pair, moments.singles[j] + 1e-9)
            self.assertGreaterEqual(
                pair + 1e-9, moments.singles[i] + moments.singles[j] - 1
            )

    def test_sa_rlt_is_a_lower_bound_on_binary_optimum(self) -> None:
        moments = solve_sa_rlt_level2(POLYNOMIAL, n_original=3)
        optimum = min(
            float(evaluate_pubo(POLYNOMIAL, bits))
            for bits in (
                (0, 0, 0),
                (0, 0, 1),
                (0, 1, 0),
                (0, 1, 1),
                (1, 0, 0),
                (1, 0, 1),
                (1, 1, 0),
                (1, 1, 1),
            )
        )
        self.assertLessEqual(moments.objective, optimum + 1e-9)

    def test_product_state_has_declared_bernoulli_marginals(self) -> None:
        probabilities = (0.2, 0.7, 0.4)
        state = product_state(probabilities)
        weights = np.abs(state) ** 2
        self.assertAlmostEqual(float(np.sum(weights)), 1.0)
        for bit, expected in enumerate(probabilities):
            observed = sum(
                weights[index]
                for index in range(len(weights))
                if (index >> bit) & 1
            )
            self.assertAlmostEqual(float(observed), expected)

    def test_matched_mixer_preserves_its_product_ground_state(self) -> None:
        design = self._design()
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        probabilities = (0.2, 0.7, 0.4)
        initial = product_state(probabilities)
        mixed = simulate_warm_qaoa(
            data,
            probabilities=probabilities,
            gammas=(0.0,),
            betas=(0.37,),
        )
        np.testing.assert_allclose(
            np.abs(initial) ** 2, np.abs(mixed) ** 2, atol=1e-12
        )

    def test_zero_auxiliary_design_deduplicates_auxiliary_variant(self) -> None:
        specs = warm_start_specs(
            self._design(), self._moments(), clipping_delta=0.05
        )
        self.assertEqual(len(specs), 2)
        self.assertEqual(
            [spec.policy for spec in specs],
            ["cold_start", "original_variables_only"],
        )

    def test_active_auxiliary_gets_only_pair_and_independence_closures(self) -> None:
        specs = warm_start_specs(
            self._design(actions=((1, 2),), label="fully_quadratized"),
            self._moments(),
            clipping_delta=0.05,
        )
        self.assertEqual(len(specs), 4)
        self.assertEqual(
            {spec.pair_closure for spec in specs},
            {
                "not_applicable",
                "auxiliary_cold_half",
                "sa_rlt_level_2_pair_moments",
                "independence_mu_product_ablation",
            },
        )
        pair = next(
            spec
            for spec in specs
            if spec.pair_closure == "sa_rlt_level_2_pair_moments"
        )
        independent = next(
            spec
            for spec in specs
            if spec.pair_closure == "independence_mu_product_ablation"
        )
        self.assertAlmostEqual(pair.probabilities[-1], 0.15)
        self.assertAlmostEqual(independent.probabilities[-1], 0.2 * 0.7)

    def test_cold_path_is_exactly_the_e3_statevector_path(self) -> None:
        from urss_pipeline.e3_qaoa import simulate_qaoa

        design = self._design()
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        parameters = [0.37, 0.19]
        direct = simulate_qaoa(data, gammas=parameters[:1], betas=parameters[1:])
        e4 = _simulate(
            data,
            WarmStartSpec("cold_start", "not_applicable", None),
            parameters,
            1,
        )
        np.testing.assert_allclose(direct, e4, atol=1e-14)

    def test_optimizer_retains_exact_e3_evaluation_budget(self) -> None:
        design = self._design()
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        row = optimize_warmstart_run(
            instance_id="inst_test",
            family="max3sat",
            design=design,
            budget=QAOABudgetSpec(
                "equal_layer", "equal_layer_p1", 1, None, 8, 8
            ),
            data=data,
            warm_spec=WarmStartSpec("cold_start", "not_applicable", None),
            moments=self._moments(),
            restart_id=0,
            optimizer_seed=11,
            circuit_seed=21,
            measurement_seed=31,
            qaoa_config=self._qaoa(4),
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            e3_summary_hash="c" * 64,
            code_commit="d" * 40,
        )
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["evaluations"], 4)
        self.assertEqual(row["evaluation_budget"], 4)

    def test_marginal_diagnostics_report_every_single_and_pair(self) -> None:
        designs = (
            self._design(),
            self._design(actions=((1, 2),), label="fully_quadratized"),
        )
        rows = marginal_diagnostic_rows(
            instance_id="inst_test",
            family="max3sat",
            moments=self._moments(),
            designs=designs,
            clipping_delta=0.05,
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            code_commit="c" * 40,
            solver_package="scipy.optimize.linprog",
            solver_method="highs",
        )
        self.assertEqual(len(rows), 6)
        pair = next(
            row
            for row in rows
            if row["moment_type"] == "lifted_pair"
            and row["variable_i"] == 1
            and row["variable_j"] == 2
        )
        self.assertEqual(pair["active_auxiliary_design_count"], 1)
        self.assertAlmostEqual(pair["independence_pair_moment"], 0.14)

    def test_summary_table_and_pdf_are_emitted(self) -> None:
        base = {
            "instance_id": "inst_test",
            "family": "max3sat",
            "representation": "all_native",
            "random_rep_seed": "",
            "design_id": "design_test",
            "budget_mode": "equal_layer",
            "budget_key": "equal_layer_p1",
            "p": 1,
            "compiled_2q_budget": "",
            "warm_start_policy": "cold_start",
            "pair_closure": "not_applicable",
            "original_objective_mean": -0.5,
            "optimum_hit_rate": 0.2,
            "encoded_energy_mean": -0.5,
            "auxiliary_inconsistency_rate": 0.0,
            "mean_abs_original_margin": 0.2,
            "weak_signal_flag": False,
            "status": "pass",
            "config_hash": "a" * 64,
            "manifest_hash": "b" * 64,
            "code_commit": "c" * 40,
        }
        rows = [
            {**base, "restart_id": restart}
            for restart in range(3)
        ]
        summary = summarise_warmstart_runs(rows)
        self.assertEqual(len(summary), 1)
        self.assertIn("\\begin{tabular}", _latex_table(summary))
        marginal_rows = marginal_diagnostic_rows(
            instance_id="inst_test",
            family="max3sat",
            moments=self._moments(),
            designs=(self._design(actions=((1, 2),)),),
            clipping_delta=0.05,
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            code_commit="c" * 40,
            solver_package="scipy.optimize.linprog",
            solver_method="highs",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "marginals.pdf"
            version = write_marginal_figure_pdf(path, marginal_rows)
            self.assertEqual(version, "4.4.9")
            self.assertGreater(path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
