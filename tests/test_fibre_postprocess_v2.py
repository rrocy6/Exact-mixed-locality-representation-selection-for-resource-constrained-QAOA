from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.e4_warmstart import _latex_table, summarise_warmstart_runs
from urss_pipeline.fibre_postprocess_v2 import (
    guardrail_provenance,
    repair_fibre_e1_e4_postprocess,
)


def _run_row(
    *,
    instance: str,
    design: str,
    restart: int,
    policy: str,
    objective: float,
    mode: str = "equal_layer",
) -> dict[str, object]:
    return {
        "instance_id": instance,
        "family": "max3sat",
        "representation": "matched_random_selective",
        "design_id": design,
        "budget_mode": mode,
        "budget_key": "equal_layer_p1" if mode == "equal_layer" else "equal_2q_128",
        "p": 1,
        "compiled_2q_budget": "" if mode == "equal_layer" else 128,
        "warm_start_policy": policy,
        "pair_closure": (
            "not_applicable" if policy == "cold_start" else "auxiliary_cold_half"
        ),
        "restart_id": restart,
        "original_objective_mean": objective,
        "optimum_hit_rate": objective / 10,
        "encoded_energy_mean": objective,
        "auxiliary_inconsistency_rate": 0.0,
        "mean_abs_original_margin": 0.2,
        "weak_signal_flag": False,
        "status": "pass",
        "config_hash": "a" * 64,
        "manifest_hash": "b" * 64,
        "code_commit": "c" * 40,
    }


class FibrePostprocessV2Tests(unittest.TestCase):
    def test_matched_random_ci_uses_instances_not_designs_or_restarts(self) -> None:
        rows: list[dict[str, object]] = []
        warm_values = {
            ("instance_a", "design_1"): 1.0,
            ("instance_a", "design_2"): 3.0,
            ("instance_b", "design_1"): 5.0,
            ("instance_b", "design_2"): 7.0,
        }
        for instance, design in warm_values:
            for restart in range(2):
                rows.append(
                    _run_row(
                        instance=instance,
                        design=design,
                        restart=restart,
                        policy="cold_start",
                        objective=0.0,
                    )
                )
                rows.append(
                    _run_row(
                        instance=instance,
                        design=design,
                        restart=restart,
                        policy="original_variables_only",
                        objective=warm_values[(instance, design)],
                    )
                )
        summary = summarise_warmstart_runs(rows)
        warm = next(
            row
            for row in summary
            if row["warm_start_policy"] == "original_variables_only"
        )
        self.assertEqual(warm["instance_count"], 2)
        self.assertEqual(warm["design_count"], 4)
        self.assertEqual(warm["run_count"], 8)
        self.assertEqual(warm["ci_unit"], "instance")
        self.assertAlmostEqual(float(warm["original_objective_mean"]), 4.0)
        self.assertAlmostEqual(float(warm["original_objective_ci95_low"]), 0.08)
        self.assertAlmostEqual(float(warm["original_objective_ci95_high"]), 7.92)

    def test_budget_labels_and_latex_are_explicit(self) -> None:
        layer = summarise_warmstart_runs(
            [
                _run_row(
                    instance="a",
                    design="d",
                    restart=0,
                    policy="cold_start",
                    objective=0.0,
                )
            ]
        )
        compiled = summarise_warmstart_runs(
            [
                _run_row(
                    instance="a",
                    design="d",
                    restart=0,
                    policy="cold_start",
                    objective=0.0,
                    mode="equal_compiled_two_qubit_gates",
                )
            ]
        )
        self.assertEqual(layer[0]["budget_label"], "p=1")
        self.assertEqual(compiled[0]["budget_label"], "2Q=128")
        table = _latex_table([*layer, *compiled])
        self.assertIn("p=1", table)
        self.assertIn("2Q=128", table)
        self.assertIn("95\\% CI", table)

    def test_guardrail_provenance_comes_from_frozen_v2(self) -> None:
        value = guardrail_provenance(
            {
                "selector": {
                    "fibre_risk": {
                        "enabled": True,
                        "definition": "fibre_excess",
                        "moment_source": "SA_RLT_level_2",
                        "threshold_tau": 0.02,
                        "guardrail_operator": "less_than_or_equal",
                    }
                }
            }
        )
        self.assertEqual(value["selector_fibre_risk_guardrail"], "enabled_in_frozen_v2")
        self.assertEqual(value["selector_fibre_risk_guardrail_threshold_tau"], 0.02)

    def test_postprocess_preserves_raw_and_cascades_summary_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "fibre_e1_e6_v2"
            (root / "results").mkdir(parents=True)
            (root / "tables").mkdir()
            (root / "evidence").mkdir()

            config = {
                "selector": {
                    "fibre_risk": {
                        "enabled": True,
                        "definition": "fibre_excess",
                        "moment_source": "SA_RLT_level_2",
                        "threshold_tau": 0.02,
                        "guardrail_operator": "less_than_or_equal",
                    }
                }
            }
            config_path = base / "experiment_config_v2.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            config_hash_path = base / "experiment_config_v2.sha256"
            config_hash_path.write_text(
                hashlib.sha256(config_path.read_bytes()).hexdigest() + "\n",
                encoding="utf-8",
            )

            raw_path = root / "results/e4_warmstart_runs.csv"
            raw = _run_row(
                instance="a",
                design="d",
                restart=0,
                policy="cold_start",
                objective=1.0,
            )
            with raw_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(raw))
                writer.writeheader()
                writer.writerow(raw)

            def sidecar(path: Path) -> str:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                path.with_suffix(".sha256").write_text(digest + "\n", encoding="utf-8")
                return digest

            raw_hash = sidecar(raw_path)
            summary_path = root / "results/e4_warmstart_summary.csv"
            summary_path.write_text("old\n", encoding="utf-8")
            sidecar(summary_path)
            table_path = root / "tables/table_e4_warmstart.tex"
            table_path.write_text("old\n", encoding="utf-8")
            sidecar(table_path)

            validations = {
                "e1": {"status": "pass", "e2_e6_may_continue": True},
                "e4": {
                    "status": "pass",
                    "e5_e6_may_continue": True,
                    "artifact_hashes": {
                        "results/e4_warmstart_summary.csv": "0" * 64,
                        "tables/table_e4_warmstart.tex": "1" * 64,
                    },
                },
                "e5": {"status": "pass", "e6_may_continue": True},
                "e6": {"status": "pass", "final_result_pack_may_be_built": True},
            }
            for step, value in validations.items():
                path = root / f"results/{step}_validation_summary.json"
                path.write_text(json.dumps(value) + "\n", encoding="utf-8")
                sidecar(path)
                audit_path = root / f"evidence/FIBRE_V2_{step.upper()}_AUDIT.json"
                audit_path.write_text(
                    json.dumps({"status": "pass", "summary_hash": "old"}) + "\n",
                    encoding="utf-8",
                )
                sidecar(audit_path)

            result = repair_fibre_e1_e4_postprocess(
                output_root=root,
                config_path=config_path,
                config_hash_path=config_hash_path,
                code_commit="d" * 40,
            )
            self.assertEqual(hashlib.sha256(raw_path.read_bytes()).hexdigest(), raw_hash)
            self.assertTrue(result["source_e4_raw_runs_unchanged"])
            e1 = json.loads(
                (root / "results/e1_validation_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(e1["selector_fibre_risk_guardrail"], "enabled_in_frozen_v2")
            e5 = json.loads(
                (root / "results/e5_validation_summary.json").read_text(encoding="utf-8")
            )
            e4_hash = hashlib.sha256(
                (root / "results/e4_validation_summary.json").read_bytes()
            ).hexdigest()
            self.assertEqual(e5["e4_validation_summary_hash"], e4_hash)


if __name__ == "__main__":
    unittest.main()
