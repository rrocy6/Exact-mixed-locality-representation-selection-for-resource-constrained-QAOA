from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from urss_pipeline.e3_qaoa import qaoa_designs
from urss_pipeline.e6_noise import (
    NOISE_LEVEL_ORDER,
    REPRESENTATION_ORDER,
    RUN_FIELDS,
    SUMMARY_FIELDS,
    _build_compiled_qaoa_circuit,
    _latex_table,
    _noise_row_qmax,
    _validate_protocol_config,
    attach_paired_degradation,
    build_noise_model,
    fairness_audit,
    feasible_full_circuit_spec,
    metrics_from_counts,
    representative_transpiler_seed,
    summarise_noise_rows,
    write_noise_figure_pdf,
    run_e6_noise_pipeline,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load(
    (ROOT / "configs/experiment_config_v1.yaml").read_text(encoding="utf-8")
)
PROTOCOL = json.loads(
    (ROOT / "configs/e6_noise_v1.json").read_text(encoding="utf-8")
)


def run_row(level: str, objective: float) -> dict[str, object]:
    return {
        "instance_id": "inst_test",
        "family": "max3sat",
        "split": "test",
        "representation": "selective",
        "random_rep_seed": "",
        "design_id": "design_test",
        "restart_id": 0,
        "noise_level": level,
        "shots": 4096,
        "topology_id": "device_sparse_v1",
        "transpiler_seed": 11,
        "circuit_seed": 21,
        "measurement_seed": 31,
        "optimized_parameters_sha256": "a" * 64,
        "actual_2q_gates": 200,
        "objective_scoring": "original_family_objective_after_discarding_auxiliaries",
        "original_objective_mean": objective,
        "optimum_hit_rate": 0.25,
        "auxiliary_inconsistency_rate": 0.1,
        "paired_degradation_vs_noiseless": 0.0,
        "status": "pass",
        "config_hash": "b" * 64,
        "noise_manifest_hash": "c" * 64,
        "protocol_config_hash": "d" * 64,
        "code_commit": "e" * 40,
    }


def summary_fixture() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for family in ("cubic_spin_glass", "max3sat"):
        for representation in REPRESENTATION_ORDER:
            for index, level in enumerate(NOISE_LEVEL_ORDER):
                row = run_row(level, 1.0 + index * 0.1)
                row["family"] = family
                row["representation"] = representation
                row["design_id"] = f"{family}-{representation}"
                rows.append(row)
    attach_paired_degradation(rows)
    return summarise_noise_rows(rows)


class E6NoiseTests(unittest.TestCase):
    def test_protocol_matches_frozen_parent(self) -> None:
        _validate_protocol_config(PROTOCOL, CONFIG)
        frozen_qmax = CONFIG["dataset"]["tiers"]["qaoa"][
            "common_width_limit_qmax"
        ]
        self.assertEqual(_noise_row_qmax({"qmax": ""}, frozen_qmax), 12)
        self.assertEqual(_noise_row_qmax({"qmax": "12"}, frozen_qmax), 12)
        with self.assertRaisesRegex(Exception, "differs"):
            _noise_row_qmax({"qmax": "13"}, frozen_qmax)

    def test_protocol_rejects_scope_expansion(self) -> None:
        altered = copy.deepcopy(PROTOCOL)
        altered["noise_level_order"].append("extra_high")
        with self.assertRaisesRegex(Exception, "exactly two"):
            _validate_protocol_config(altered, CONFIG)

    def test_representative_seed_is_smallest_median_attainer(self) -> None:
        self.assertEqual(
            representative_transpiler_seed([15, 11, 14, 12, 13], [9, 7, 8, 8, 10]),
            12,
        )

    def test_metrics_discard_auxiliary_bits_for_primary_score(self) -> None:
        representation = SimpleNamespace(
            n_qubits=3,
            original_width=2,
            polynomial={(1,): 1, (2,): 2, (3,): 5},
            auxiliary_indices={(1, 2): 3},
        )
        metrics = metrics_from_counts(
            {"111": 2, "101": 1, "001": 1},
            original={(1,): 1, (2,): 2},
            representation=representation,
            optimum_original=0.0,
        )
        self.assertAlmostEqual(metrics["original_objective_mean"], 2.0)
        self.assertAlmostEqual(metrics["auxiliary_inconsistency_rate"], 0.25)
        self.assertNotEqual(
            metrics["original_objective_mean"], metrics["encoded_energy_mean"]
        )

    def test_paired_degradation_uses_same_run_baseline(self) -> None:
        rows = [
            run_row("noiseless", 1.0),
            run_row("realistic_low", 1.2),
            run_row("realistic_high", 1.5),
        ]
        attach_paired_degradation(rows)
        self.assertAlmostEqual(float(rows[0]["paired_degradation_vs_noiseless"]), 0.0)
        self.assertAlmostEqual(float(rows[1]["paired_degradation_vs_noiseless"]), 0.2)
        self.assertAlmostEqual(float(rows[2]["paired_degradation_vs_noiseless"]), 0.5)

    def test_paired_degradation_rejects_missing_level(self) -> None:
        with self.assertRaisesRegex(Exception, "Incomplete paired"):
            attach_paired_degradation(
                [run_row("noiseless", 1.0), run_row("realistic_low", 1.1)]
            )

    def test_fairness_audit_accepts_complete_paired_protocol(self) -> None:
        rows = []
        for restart in range(3):
            group = [run_row(level, 1.0) for level in NOISE_LEVEL_ORDER]
            for row in group:
                row["restart_id"] = restart
                row["optimizer_seed"] = 100 + restart
                row["circuit_seed"] = 200 + restart
                row["measurement_seed"] = 300 + restart
                row["optimized_parameters_sha256"] = str(restart) * 64
            rows.extend(group)
        attach_paired_degradation(rows)
        audit = fairness_audit(rows, expected_design_count=1, protocol=PROTOCOL)
        self.assertTrue(all(value == 0 for value in audit.values()))

    def test_fairness_audit_detects_cross_level_seed_change(self) -> None:
        rows = [run_row(level, 1.0) for level in NOISE_LEVEL_ORDER]
        rows[-1]["measurement_seed"] = 999
        audit = fairness_audit(rows, expected_design_count=1, protocol=PROTOCOL)
        self.assertEqual(audit["cross_level_protocol_mismatch_count"], 1)

    def test_summary_has_two_families_four_representations_three_levels(self) -> None:
        summary = summary_fixture()
        self.assertEqual(len(summary), 24)
        self.assertEqual(set(summary[0]), set(SUMMARY_FIELDS))

    def test_latex_table_records_noise_and_auxiliary_diagnostic(self) -> None:
        latex = _latex_table(summary_fixture())
        self.assertIn("Aux. inconsistency", latex)
        self.assertIn("realistic high", latex)
        self.assertTrue(latex.endswith("\n"))

    def test_noiseless_model_is_exactly_absent(self) -> None:
        self.assertIsNone(
            build_noise_model(
                {"id": "noiseless", "parameters": {}},
                measured_qubit_count=3,
                protocol=PROTOCOL,
            )
        )

    def test_nonzero_noise_model_contains_quantum_and_readout_errors(self) -> None:
        level = CONFIG["noise"]["levels"][1]
        model = build_noise_model(level, measured_qubit_count=3, protocol=PROTOCOL)
        self.assertTrue(model.to_dict()["errors"])

    def test_compiled_qaoa_circuit_uses_frozen_sparse_basis(self) -> None:
        designs = qaoa_designs(
            {(1, 2, 3): 1, (1,): -1},
            n_original=3,
            instance_id="inst_compile_test",
            config=CONFIG,
        )
        circuit = _build_compiled_qaoa_circuit(
            designs[0].evaluation,
            gammas=[0.1],
            betas=[0.2],
            compiler_config=CONFIG["compiler"],
            transpiler_seed=CONFIG["compiler"]["transpiler_seed_bundle"][0],
        )
        self.assertEqual(circuit.num_clbits, 3)
        self.assertTrue(
            set(circuit.count_ops()).issubset(
                set(CONFIG["compiler"]["basis_gates"]) | {"measure", "barrier"}
            )
        )

    def test_full_circuit_depth_rule_enforces_actual_budget(self) -> None:
        designs = qaoa_designs(
            {(1, 2, 3): 1, (1,): -1},
            n_original=3,
            instance_id="inst_budget_test",
            config=CONFIG,
        )
        initial = SimpleNamespace(
            mode="equal_compiled_two_qubit_gates",
            key="equal_2q_budget_256",
            p=4,
            compiled_budget=256,
            compiled_two_qubit_gates_per_layer=80,
        )
        spec, actual = feasible_full_circuit_spec(
            designs[0].evaluation,
            initial_spec=initial,
            compiler_config=CONFIG["compiler"],
            transpiler_seed=CONFIG["compiler"]["transpiler_seed_bundle"][0],
        )
        self.assertGreater(spec.p, 0)
        self.assertLessEqual(actual, 256)

    def test_pdf_has_four_declared_panels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "e6.pdf"
            version = write_noise_figure_pdf(path, summary_fixture())
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 1000)
            self.assertTrue(version)

    def test_run_schema_retains_all_traceability_fields(self) -> None:
        required = {
            "instance_id",
            "representation",
            "noise_level",
            "shots",
            "transpiler_seed",
            "optimized_parameters_sha256",
            "paired_degradation_vs_noiseless",
            "auxiliary_inconsistency_rate",
            "config_hash",
            "noise_manifest_hash",
            "code_commit",
        }
        self.assertTrue(required.issubset(RUN_FIELDS))

    def test_reduced_pipeline_emits_all_hashed_artifacts(self) -> None:
        with (ROOT / "data/manifests/noise_subset_v1.csv").open(
            encoding="utf-8"
        ) as stream:
            noise_rows = list(csv.DictReader(stream))
        selected = [
            next(row for row in noise_rows if row["family"] == family)
            for family in ("max3sat", "cubic_spin_glass")
        ]
        with (ROOT / "data/ground_truth/ground_truth_v1.csv").open(
            encoding="utf-8"
        ) as stream:
            truth_rows = {
                row["instance_id"]: row for row in csv.DictReader(stream)
            }
        frozen = {
            "config": CONFIG,
            "protocol": PROTOCOL,
            "config_hash": "a" * 64,
            "protocol_hash": "b" * 64,
            "noise_manifest_hash": "c" * 64,
            "noise_rows": selected,
            "noise_levels": CONFIG["noise"]["levels"],
            "ground_truth_rows": truth_rows,
            "e2_summary_hash": "d" * 64,
            "e3_validation_summary_hash": "e" * 64,
            "e5_validation_summary_hash": "f" * 64,
        }

        def fake_plan(**kwargs):
            design = kwargs["design"]
            return {
                "instance_id": kwargs["instance_id"],
                "design_id": design.design_id,
                "compiled_2q_gates_by_seed_json": "[20,20,20,20,20]",
                "compiled_2q_gates_per_layer": 20,
            }

        def fake_optimize(**kwargs):
            spec = kwargs["spec"]
            parameters = [0.1] * spec.p + [0.2] * spec.p
            return {
                "status": "pass",
                "optimized_parameters_json": json.dumps(parameters),
                "evaluations": 60,
            }

        def fake_simulate(**kwargs):
            level = kwargs["level"]["id"]
            degradation = {
                "noiseless": 0.0,
                "realistic_low": 0.1,
                "realistic_high": 0.2,
            }[level]
            return (
                {
                    "original_objective_mean": 1.0 + degradation,
                    "original_objective_best": 0.0,
                    "optimum_hit_rate": 0.25,
                    "encoded_energy_mean": 1.5 + degradation,
                    "auxiliary_inconsistency_rate": degradation / 2,
                },
                0.01,
            )

        fake_circuit = SimpleNamespace(
            data=[SimpleNamespace(qubits=(0, 1)) for _ in range(20)]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("results", "tables", "figures"):
                (root / name).mkdir()
            assumptions = root / "assumptions.md"
            commands = root / "RUN_COMMANDS.md"
            assumptions.write_text("base\n", encoding="utf-8")
            commands.write_text("base\n", encoding="utf-8")
            with (
                patch("urss_pipeline.e6_noise.verify_e6_inputs", return_value=frozen),
                patch("urss_pipeline.e6_noise.compile_budget_plan", side_effect=fake_plan),
                patch(
                    "urss_pipeline.e6_noise.feasible_full_circuit_spec",
                    side_effect=lambda evaluation, initial_spec, **kwargs: (
                        initial_spec,
                        20,
                    ),
                ),
                patch("urss_pipeline.e6_noise.optimize_qaoa_run", side_effect=fake_optimize),
                patch(
                    "urss_pipeline.e6_noise._build_compiled_qaoa_circuit",
                    return_value=fake_circuit,
                ),
                patch("urss_pipeline.e6_noise.simulate_noise_row", side_effect=fake_simulate),
            ):
                validation = run_e6_noise_pipeline(
                    config_path=ROOT / "configs/experiment_config_v1.yaml",
                    config_hash_path=ROOT / "configs/experiment_config_v1.sha256",
                    protocol_config_path=ROOT / "configs/e6_noise_v1.json",
                    protocol_config_hash_path=ROOT / "configs/e6_noise_v1.sha256",
                    data_directory=ROOT / "data",
                    results_directory=root / "results",
                    tables_directory=root / "tables",
                    figures_directory=root / "figures",
                    code_commit="1" * 40,
                    assumptions_path=assumptions,
                    run_commands_path=commands,
                )
            self.assertEqual(validation["status"], "pass")
            self.assertEqual(validation["run_row_count"], 144)
            self.assertEqual(validation["summary_row_count"], 24)
            for relative in (
                "results/e6_noise_runs.csv",
                "results/e6_noise_summary.csv",
                "results/e6_noise_provenance.json",
                "results/e6_validation_summary.json",
                "tables/table_e6_noise.tex",
                "figures/figure_e6_noise.pdf",
            ):
                path = root / relative
                self.assertTrue(path.is_file())
                self.assertTrue(path.with_suffix(".sha256").is_file())


if __name__ == "__main__":
    unittest.main()
