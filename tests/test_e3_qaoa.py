from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.qaoa_pilot import build_cold_qaoa_circuit
from urss_pipeline.e3_qaoa import (
    RUN_FIELDS,
    QAOABudgetSpec,
    QAOADesign,
    _initial_parameters,
    budget_specs,
    fairness_audit,
    optimize_qaoa_run,
    qaoa_designs,
    simulate_qaoa,
    statevector_data,
    statevector_metrics,
    summarise_runs,
    write_qaoa_figure_pdf,
    E3QAOAError,
)
from urss_pipeline.polynomial import evaluate_pubo


ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load(
    (ROOT / "configs/experiment_config_v1.yaml").read_text(encoding="utf-8")
)
POLYNOMIAL = {(1,): -1, (1, 2, 3): 2}


class E3QAOATests(unittest.TestCase):
    def _design(self, actions=(None,)) -> QAOADesign:
        evaluation = _evaluate_design(
            POLYNOMIAL,
            n_original=3,
            actions=actions,
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=True,
        )
        return QAOADesign("all_native", None, evaluation)

    def _qaoa(self, evaluations: int = 60):
        copied = dict(CONFIG["qaoa"])
        copied["optimizer"] = dict(CONFIG["qaoa"]["optimizer"])
        copied["optimizer"]["objective_evaluations"] = evaluations
        return copied

    def test_raw_fields_include_every_guide_requirement(self) -> None:
        required = {
            "instance_id",
            "family",
            "representation",
            "budget_mode",
            "p",
            "compiled_2q_budget",
            "actual_2q_gates",
            "optimizer",
            "optimizer_seed",
            "restart_id",
            "evaluations",
            "shots",
            "circuit_seed",
            "measurement_seed",
            "original_objective_mean",
            "original_objective_best",
            "optimum_hit_rate",
            "encoded_energy_mean",
            "auxiliary_inconsistency_rate",
            "status",
            "config_hash",
            "manifest_hash",
            "code_commit",
        }
        self.assertTrue(required.issubset(set(RUN_FIELDS)))

    def test_stable_initialisation_is_independent_and_reproducible(self) -> None:
        arguments = dict(
            instance_id="inst_test",
            design_id="design_a",
            representation="all_native",
            random_rep_seed=None,
            budget_key="equal_layer_p1",
            restart_id=0,
            optimizer_seed=11,
            p=1,
            qaoa_config=CONFIG["qaoa"],
        )
        first = _initial_parameters(**arguments)
        second = _initial_parameters(**arguments)
        changed = _initial_parameters(
            **{**arguments, "representation": "selective"}
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_four_representation_families_and_five_random_seeds(self) -> None:
        designs = qaoa_designs(
            POLYNOMIAL,
            n_original=3,
            instance_id="inst_test",
            config=CONFIG,
        )
        self.assertEqual(len(designs), 8)
        self.assertEqual(
            {design.representation for design in designs},
            {
                "all_native",
                "fully_quadratized",
                "selective",
                "matched_random_selective",
            },
        )
        self.assertEqual(
            len(
                {
                    design.random_rep_seed
                    for design in designs
                    if design.representation == "matched_random_selective"
                }
            ),
            5,
        )

    def test_budget_specs_obey_equal_layer_and_compiled_caps(self) -> None:
        specs = budget_specs(20, CONFIG["qaoa"])
        self.assertEqual([spec.p for spec in specs[:2]], [1, 2])
        self.assertEqual([spec.compiled_budget for spec in specs[2:]], [128, 256])
        self.assertEqual([spec.p for spec in specs[2:]], [6, 12])
        self.assertTrue(
            all(
                spec.actual_two_qubit_gates <= int(spec.compiled_budget)
                for spec in specs[2:]
            )
        )

    def test_budget_below_one_layer_is_retained_as_zero_layer(self) -> None:
        specs = budget_specs(300, CONFIG["qaoa"])
        self.assertEqual([spec.p for spec in specs[2:]], [0, 0])
        self.assertEqual(
            [spec.actual_two_qubit_gates for spec in specs[2:]], [0, 0]
        )
        design = self._design()
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        row = optimize_qaoa_run(
            instance_id="inst_zero",
            family="max3sat",
            design=design,
            spec=specs[2],
            data=data,
            restart_id=0,
            optimizer_seed=11,
            circuit_seed=21,
            measurement_seed=31,
            qaoa_config=self._qaoa(evaluations=4),
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            e2_summary_hash="c" * 64,
            code_commit="d" * 40,
        )
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["p"], 0)
        self.assertEqual(row["actual_2q_gates"], 0)
        self.assertEqual(row["evaluations"], 4)

    def test_exact_statevector_preserves_norm_and_original_mean(self) -> None:
        design = self._design()
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
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=optimum,
        )
        state = simulate_qaoa(data, gammas=(), betas=())
        metrics = statevector_metrics(state, data)
        self.assertAlmostEqual(metrics["statevector_norm"], 1.0)
        self.assertAlmostEqual(
            metrics["original_objective_mean"],
            float(np.mean(data.original_energies)),
        )
        from qiskit.quantum_info import Statevector

        gammas = (0.37,)
        betas = (0.19,)
        reference_circuit = build_cold_qaoa_circuit(
            design.evaluation.reference,
            gammas=gammas,
            betas=betas,
        )
        qiskit_state = np.asarray(Statevector.from_instruction(reference_circuit))
        direct_state = simulate_qaoa(data, gammas=gammas, betas=betas)
        np.testing.assert_allclose(
            np.abs(direct_state) ** 2,
            np.abs(qiskit_state) ** 2,
            atol=1e-12,
        )

    def test_auxiliary_inconsistency_is_diagnostic_only(self) -> None:
        design = self._design(actions=((1, 2),))
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        consistent = np.zeros(len(data.encoded_energies), dtype=np.complex128)
        consistent[0b1011] = 1.0  # x=(1,1,0), auxiliary=1
        inconsistent = np.zeros_like(consistent)
        inconsistent[0b0011] = 1.0  # same x, auxiliary=0
        self.assertEqual(
            statevector_metrics(consistent, data)["auxiliary_inconsistency_rate"],
            0.0,
        )
        self.assertEqual(
            statevector_metrics(inconsistent, data)["auxiliary_inconsistency_rate"],
            1.0,
        )

    def test_optimizer_consumes_exact_frozen_evaluation_budget(self) -> None:
        design = self._design()
        data = statevector_data(
            POLYNOMIAL,
            design.evaluation.representation,
            optimum_original=-1,
        )
        row = optimize_qaoa_run(
            instance_id="inst_test",
            family="max3sat",
            design=design,
            spec=QAOABudgetSpec("equal_layer", "equal_layer_p1", 1, None, 8, 8),
            data=data,
            restart_id=0,
            optimizer_seed=11,
            circuit_seed=21,
            measurement_seed=31,
            qaoa_config=self._qaoa(evaluations=8),
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            e2_summary_hash="c" * 64,
            code_commit="d" * 40,
        )
        self.assertEqual(row["status"], "pass")
        self.assertEqual(row["evaluation_budget"], 8)
        self.assertEqual(row["evaluations"], 8)
        self.assertEqual(
            row["objective_scoring"],
            "original_family_objective_projected_from_statevector",
        )

    def _fair_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for design_index in range(2):
            for budget_index in range(4):
                for restart in range(3):
                    rows.append(
                        {
                            "instance_id": "inst_test",
                            "representation": (
                                "all_native" if design_index == 0 else "selective"
                            ),
                            "random_rep_seed": "",
                            "design_id": f"design_{design_index}",
                            "budget_key": f"budget_{budget_index}",
                            "restart_id": restart,
                            "p": 1,
                            "evaluation_budget": 60,
                            "evaluations": 60,
                            "optimizer_seed": CONFIG["qaoa"]["optimizer"]["seed_bundle"][restart],
                            "circuit_seed": CONFIG["qaoa"]["circuit_seed_bundle"][restart],
                            "measurement_seed": CONFIG["qaoa"]["measurement_seed_bundle"][restart],
                            "budget_mode": (
                                "equal_layer"
                                if budget_index < 2
                                else "equal_compiled_two_qubit_gates"
                            ),
                            "actual_2q_gates": 100,
                            "compiled_2q_budget": 128,
                            "objective_scoring": "original_family_objective_projected_from_statevector",
                            "initial_parameters_sha256": f"{design_index}-{budget_index}-{restart}",
                        }
                    )
        return rows

    def test_fairness_audit_accepts_all_restarts_and_equal_budgets(self) -> None:
        report = fairness_audit(
            self._fair_rows(),
            expected_design_count=2,
            qaoa_config=CONFIG["qaoa"],
        )
        self.assertTrue(all(value == 0 for value in report.values()))

    def test_fairness_audit_detects_evaluation_mismatch(self) -> None:
        rows = self._fair_rows()
        rows[0]["evaluations"] = 59
        report = fairness_audit(
            rows,
            expected_design_count=2,
            qaoa_config=CONFIG["qaoa"],
        )
        self.assertEqual(report["evaluation_budget_mismatch_count"], 1)

    def test_summary_reports_paired_difference_against_native(self) -> None:
        rows: list[dict[str, object]] = []
        for instance, native, selected in (("a", 2.0, 1.0), ("b", 4.0, 3.0)):
            for representation, value in (
                ("all_native", native),
                ("selective", selected),
            ):
                rows.append(
                    {
                        "instance_id": instance,
                        "family": "max3sat",
                        "representation": representation,
                        "budget_mode": "equal_layer",
                        "budget_key": "equal_layer_p1",
                        "p": 1,
                        "compiled_2q_budget": "",
                        "original_objective_mean": value,
                        "optimum_hit_rate": 0.25,
                        "encoded_energy_mean": value + 1,
                        "auxiliary_inconsistency_rate": 0.0,
                        "status": "pass",
                        "config_hash": "a" * 64,
                        "manifest_hash": "b" * 64,
                        "code_commit": "c" * 40,
                    }
                )
        summary = summarise_runs(rows)
        selected = next(
            row for row in summary if row["representation"] == "selective"
        )
        self.assertEqual(selected["paired_difference_vs_native_mean"], -1.0)
        self.assertEqual(selected["instance_count"], 2)

    def test_required_figures_are_single_page_pdfs(self) -> None:
        rows: list[dict[str, object]] = []
        for mode, values in (
            ("equal_layer", (1, 2)),
            ("equal_compiled_two_qubit_gates", (128, 256)),
        ):
            for family in ("max3sat", "cubic_spin_glass"):
                for representation in (
                    "all_native",
                    "fully_quadratized",
                    "selective",
                    "matched_random_selective",
                ):
                    for value in values:
                        rows.append(
                            {
                                "family": family,
                                "representation": representation,
                                "budget_mode": mode,
                                "budget_value": value,
                                "paired_difference_vs_native_mean": (
                                    0.0 if representation == "all_native" else -0.1
                                ),
                            }
                        )
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "equal_layer.pdf"
            second = Path(directory) / "equal_budget.pdf"
            write_qaoa_figure_pdf(first, rows, budget_mode="equal_layer")
            write_qaoa_figure_pdf(
                second,
                rows,
                budget_mode="equal_compiled_two_qubit_gates",
            )
            for path in (first, second):
                self.assertTrue(path.read_bytes().startswith(b"%PDF"))
                self.assertGreater(path.stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
