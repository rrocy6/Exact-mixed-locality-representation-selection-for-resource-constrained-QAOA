from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from urss_pipeline.e5_regime import (
    DIAGNOSTIC_AXES,
    INSTANCE_FIELDS,
    PRIMARY_AXES,
    SUMMARY_FIELDS,
    _latex_table,
    _validate_analysis_config,
    assign_bin,
    classify_effect,
    compiled_instance_rows,
    paired_interval,
    qaoa_instance_rows,
    summarise_regime_rows,
    write_regime_figure_pdf,
)


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = json.loads(
    (ROOT / "configs/e5_analysis_v1.json").read_text(encoding="utf-8")
)
CONFIG_HASH = "a" * 64
MANIFEST_HASH = "b" * 64
ANALYSIS_HASH = "c" * 64
COMMIT = "d" * 40


def metadata(family: str = "max3sat") -> dict[str, str]:
    return {
        "instance_id": "inst_test",
        "family": family,
        "n": "8",
        "cubic_density": "0.2",
        "pair_reuse_score": "0.5",
        "positive_cubic_count": "6",
        "negative_cubic_count": "4",
    }


def qaoa_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for restart, selected in enumerate((0.2, 0.3, 0.4)):
        rows.append(
            {
                "instance_id": "inst_test",
                "family": "max3sat",
                "split": "test",
                "representation": "selective",
                "random_rep_seed": "",
                "budget_mode": "equal_layer",
                "budget_key": "equal_layer_p1",
                "restart_id": str(restart),
                "original_objective_mean": str(selected),
                "status": "pass",
            }
        )
        for random_seed, control in enumerate((0.5, 0.7)):
            rows.append(
                {
                    "instance_id": "inst_test",
                    "family": "max3sat",
                    "split": "test",
                    "representation": "matched_random_selective",
                    "random_rep_seed": str(random_seed),
                    "budget_mode": "equal_layer",
                    "budget_key": "equal_layer_p1",
                    "restart_id": str(restart),
                    "original_objective_mean": str(control),
                    "status": "pass",
                }
            )
    return rows


def compiler_rows(status: str = "pass") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for topology in ("all_to_all_reference", "device_sparse_v1"):
        for seed in (1, 2, 3, 4, 5):
            rows.append(
                {
                    "instance_id": "inst_test",
                    "family": "max3sat",
                    "split": "test",
                    "representation": "selective",
                    "random_rep_seed": "",
                    "topology_id": topology,
                    "transpiler_seed": str(seed),
                    "two_qubit_gates": "80",
                    "two_qubit_depth": "40",
                    "routing_overhead": "20",
                    "status": status,
                }
            )
            for random_seed in (11, 12):
                rows.append(
                    {
                        "instance_id": "inst_test",
                        "family": "max3sat",
                        "split": "test",
                        "representation": "matched_random_selective",
                        "random_rep_seed": str(random_seed),
                        "topology_id": topology,
                        "transpiler_seed": str(seed),
                        "two_qubit_gates": "100",
                        "two_qubit_depth": "50",
                        "routing_overhead": "25",
                        "status": status,
                    }
                )
    return rows


def common_kwargs() -> dict[str, str]:
    return {
        "config_hash": CONFIG_HASH,
        "manifest_hash": MANIFEST_HASH,
        "analysis_config_hash": ANALYSIS_HASH,
        "code_commit": COMMIT,
    }


class E5RegimeTests(unittest.TestCase):
    def test_analysis_config_freezes_only_declared_primary_axes(self) -> None:
        _validate_analysis_config(ANALYSIS)
        self.assertEqual(tuple(ANALYSIS["primary_axes"]), PRIMARY_AXES)
        self.assertEqual(tuple(ANALYSIS["diagnostic_only_axes"]), DIAGNOSTIC_AXES)
        self.assertNotIn("sign_balance", PRIMARY_AXES)

    def test_predeclared_bins_have_deterministic_boundaries(self) -> None:
        spec = ANALYSIS["coverage_bins"]["canonical_cubic_sparsity"]
        self.assertEqual(assign_bin(0.0, spec), "low")
        self.assertEqual(assign_bin(0.074999, spec), "low")
        self.assertEqual(assign_bin(0.075, spec), "intermediate")
        self.assertEqual(assign_bin(0.2, spec), "high")
        self.assertEqual(assign_bin(1.0, spec), "high")

    def test_help_requires_interval_above_positive_tolerance(self) -> None:
        self.assertEqual(classify_effect(0.051, 0.08, 0.05), "help")

    def test_hurt_requires_interval_below_negative_tolerance(self) -> None:
        self.assertEqual(classify_effect(-0.09, -0.051, 0.05), "hurt")

    def test_uncertain_or_small_effect_is_little_effect(self) -> None:
        self.assertEqual(classify_effect(-0.2, 0.2, 0.05), "little_effect")
        self.assertEqual(classify_effect(0.01, 0.04, 0.05), "little_effect")

    def test_paired_interval_retains_all_observations(self) -> None:
        mean, low, high = paired_interval((0.1, 0.2, 0.3))
        self.assertAlmostEqual(mean, 0.2)
        self.assertLess(low, mean)
        self.assertGreater(high, mean)

    def test_qaoa_pairs_selected_with_matched_random_by_restart(self) -> None:
        rows = qaoa_instance_rows(
            qaoa_rows(),
            {"inst_test": metadata()},
            {"inst_test": 1.0},
            ANALYSIS,
            **common_kwargs(),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["paired_observation_count"], 3)
        self.assertEqual(rows[0]["control_observation_count"], 6)
        self.assertAlmostEqual(float(rows[0]["effect"]), 0.3)
        self.assertEqual(rows[0]["classification"], "help")

    def test_compiler_pairs_every_transpiler_seed(self) -> None:
        rows = compiled_instance_rows(
            compiler_rows(),
            ["inst_test"],
            {"inst_test": metadata()},
            ANALYSIS,
            **common_kwargs(),
        )
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["paired_observation_count"] == 5 for row in rows))
        gates = next(
            row
            for row in rows
            if row["metric"] == "compiled_two_qubit_gates"
            and row["topology_id"] == "all_to_all_reference"
        )
        self.assertAlmostEqual(float(gates["effect"]), 0.2)
        self.assertEqual(gates["classification"], "help")

    def test_expected_sparse_width_failure_is_retained_not_imputed(self) -> None:
        rows = compiled_instance_rows(
            compiler_rows("infeasible_width_exceeds_topology"),
            ["inst_test"],
            {"inst_test": metadata()},
            ANALYSIS,
            **common_kwargs(),
        )
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["status"] == "expected_infeasible" for row in rows))
        self.assertTrue(all(row["classification"] == "not_estimable" for row in rows))

    def test_summary_reports_family_and_family_balanced_views(self) -> None:
        first = qaoa_instance_rows(
            qaoa_rows(),
            {"inst_test": metadata()},
            {"inst_test": 1.0},
            ANALYSIS,
            **common_kwargs(),
        )[0]
        second = {
            **first,
            "instance_id": "inst_spin",
            "family": "cubic_spin_glass",
            "effect": -0.1,
            "effect_ci95_low": -0.2,
            "effect_ci95_high": 0.0,
            "classification": "little_effect",
        }
        summary = summarise_regime_rows((first, second))
        self.assertEqual({row["view"] for row in summary}, {"family", "combined_family_balanced"})
        combined = next(row for row in summary if row["view"] == "combined_family_balanced")
        self.assertEqual(combined["instance_count"], 2)
        self.assertEqual(combined["uncertainty_unit_count"], 2)

    def test_output_schemas_include_provenance_and_status(self) -> None:
        required = {"instance_id", "status", "config_hash", "manifest_hash", "analysis_config_hash"}
        self.assertTrue(required.issubset(INSTANCE_FIELDS))
        self.assertTrue({"status", "config_hash", "manifest_hash"}.issubset(SUMMARY_FIELDS))

    def test_latex_table_retains_help_little_and_hurt_counts(self) -> None:
        row = qaoa_instance_rows(
            qaoa_rows(),
            {"inst_test": metadata()},
            {"inst_test": 1.0},
            ANALYSIS,
            **common_kwargs(),
        )[0]
        table = _latex_table((row,))
        self.assertIn("Help & Little & Hurt", table)
        self.assertIn("\\begin{tabular}", table)

    def test_vector_pdf_contains_all_six_panels(self) -> None:
        qaoa = qaoa_instance_rows(
            qaoa_rows(),
            {"inst_test": metadata()},
            {"inst_test": 1.0},
            ANALYSIS,
            **common_kwargs(),
        )
        compiled = compiled_instance_rows(
            compiler_rows(),
            ["inst_test"],
            {"inst_test": metadata()},
            ANALYSIS,
            **common_kwargs(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "e5_regime.pdf"
            version = write_regime_figure_pdf(path, qaoa + compiled)
            self.assertEqual(version, "4.4.9")
            self.assertGreater(path.stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
