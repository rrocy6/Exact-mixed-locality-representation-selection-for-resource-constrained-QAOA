from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.formal_data import FormalDataError, run_formal_data_pipeline


ROOT = Path(__file__).resolve().parents[1]
FORMAL_CONFIG = ROOT / "configs" / "experiment_config_v1.yaml"
PLAN = ROOT / "configs" / "formal_data_generation_v1.json"
SMOKE_CONFIG = ROOT / "configs" / "smoke_config_v1.json"
SCHEMA = ROOT / "instance_schema" / "instance_schema_v1.json"


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _reduced_config(root: Path) -> tuple[Path, Path]:
    config = yaml.safe_load(FORMAL_CONFIG.read_text(encoding="utf-8"))
    config["dataset"]["tiers"]["oracle"]["n_values"] = [5]
    config["dataset"]["tiers"]["oracle"][
        "target_instances_per_family"
    ] = 2
    config["dataset"]["tiers"]["qaoa"]["n_values"] = [6]
    config["dataset"]["tiers"]["qaoa"][
        "target_instances_per_family"
    ] = 3
    config["dataset"]["tiers"]["compilation"]["n_values"] = [8]
    config["dataset"]["tiers"]["compilation"][
        "target_instances_per_family"
    ] = 4
    config["dataset"]["tiers"]["limited_noise"][
        "target_instances_per_family"
    ] = 1
    config["sources"]["instance_schema"]["sha256"] = hashlib.sha256(
        SCHEMA.read_bytes()
    ).hexdigest()
    path = root / "experiment_config_v1.yaml"
    content = yaml.safe_dump(
        config,
        allow_unicode=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")
    path.write_bytes(content)
    hash_path = root / "experiment_config_v1.sha256"
    hash_path.write_text(
        hashlib.sha256(content).hexdigest() + "\n", encoding="utf-8"
    )
    return path, hash_path


class FormalDataPipelineTests(unittest.TestCase):
    def _run(self, root: Path, output_name: str = "data"):
        config, config_hash = _reduced_config(root)
        return run_formal_data_pipeline(
            config_path=config,
            config_hash_path=config_hash,
            plan_path=PLAN,
            smoke_config_path=SMOKE_CONFIG,
            schema_path=SCHEMA,
            output_directory=root / output_name,
            code_commit="0123456789abcdef0123456789abcdef01234567",
        )

    def test_reduced_formal_pipeline_passes_all_freeze_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = self._run(root)
            data = root / "data"
            self.assertEqual(audit["status"], "pass")
            self.assertTrue(audit["formal_manifests_created"])
            self.assertTrue(audit["formal_split_created"])
            self.assertTrue(audit["test_split_frozen_before_results"])
            self.assertFalse(audit["formal_results_created"])
            self.assertEqual(audit["formal_instance_count"], 18)
            self.assertEqual(audit["duplicate_raw_instance_count"], 0)
            self.assertEqual(audit["split_leakage_count"], 0)
            self.assertEqual(audit["validation_failure_count"], 0)
            self.assertEqual(audit["qmax_feasibility_failure_count"], 0)
            self.assertEqual(
                audit["manifest_counts"]["oracle"],
                {"cubic_spin_glass": 2, "max3sat": 2},
            )
            self.assertEqual(
                audit["manifest_counts"]["qaoa"],
                {"cubic_spin_glass": 3, "max3sat": 3},
            )
            self.assertEqual(
                audit["manifest_counts"]["compilation"],
                {"cubic_spin_glass": 4, "max3sat": 4},
            )
            self.assertEqual(
                audit["manifest_counts"]["noise_subset"],
                {"cubic_spin_glass": 1, "max3sat": 1},
            )
            self.assertEqual(len(list((data / "raw").rglob("*.json"))), 18)
            self.assertEqual(len(list((data / "canonical").glob("*.json"))), 18)
            for filename in (
                "oracle_v1.csv",
                "qaoa_v1.csv",
                "compilation_v1.csv",
                "noise_subset_v1.csv",
            ):
                manifest = data / "manifests" / filename
                declared = manifest.with_suffix(".sha256").read_text(
                    encoding="utf-8"
                ).strip()
                self.assertEqual(
                    declared, hashlib.sha256(manifest.read_bytes()).hexdigest()
                )
            for artifact_name, sidecar_name in (
                ("benchmark_audit_v1.json", "benchmark_audit_v1.sha256"),
                ("benchmark_audit_v1.html", "benchmark_audit_v1.html.sha256"),
            ):
                artifact = data / artifact_name
                declared = (data / sidecar_name).read_text(
                    encoding="utf-8"
                ).strip()
                self.assertEqual(
                    declared, hashlib.sha256(artifact.read_bytes()).hexdigest()
                )

    def test_qaoa_manifest_has_one_consistent_split_and_qmax_per_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root)
            rows = _csv_rows(root / "data" / "manifests" / "qaoa_v1.csv")
            seen: dict[str, str] = {}
            for row in rows:
                self.assertEqual(row["qmax"], "12")
                self.assertEqual(row["all_four_within_qmax"], "True")
                self.assertLessEqual(int(row["fully_quadratized_width"]), 12)
                previous = seen.setdefault(row["instance_id"], row["split"])
                self.assertEqual(previous, row["split"])

    def test_manifest_bundle_is_reproducible_across_fresh_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, config_hash = _reduced_config(root)
            first = run_formal_data_pipeline(
                config_path=config,
                config_hash_path=config_hash,
                plan_path=PLAN,
                smoke_config_path=SMOKE_CONFIG,
                schema_path=SCHEMA,
                output_directory=root / "first",
                code_commit="0123456789abcdef0123456789abcdef01234567",
            )
            second = run_formal_data_pipeline(
                config_path=config,
                config_hash_path=config_hash,
                plan_path=PLAN,
                smoke_config_path=SMOKE_CONFIG,
                schema_path=SCHEMA,
                output_directory=root / "second",
                code_commit="0123456789abcdef0123456789abcdef01234567",
            )
            self.assertEqual(
                first["manifest_bundle_sha256"],
                second["manifest_bundle_sha256"],
            )
            for filename in (
                "oracle_v1.csv",
                "qaoa_v1.csv",
                "compilation_v1.csv",
                "noise_subset_v1.csv",
            ):
                self.assertEqual(
                    (root / "first" / "manifests" / filename).read_bytes(),
                    (root / "second" / "manifests" / filename).read_bytes(),
                )

    def test_rejects_tampered_formal_config_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, config_hash = _reduced_config(root)
            config_hash.write_text("0" * 64 + "\n", encoding="utf-8")
            with self.assertRaises(FormalDataError):
                run_formal_data_pipeline(
                    config_path=config,
                    config_hash_path=config_hash,
                    plan_path=PLAN,
                    smoke_config_path=SMOKE_CONFIG,
                    schema_path=SCHEMA,
                    output_directory=root / "data",
                    code_commit="0123456789abcdef0123456789abcdef01234567",
                )

    def test_refuses_to_overwrite_formal_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root)
            with self.assertRaises(FileExistsError):
                self._run(root)

    def test_success_appends_audited_project_document_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, config_hash = _reduced_config(root)
            assumptions = root / "assumptions_and_decisions.md"
            commands = root / "RUN_COMMANDS.md"
            assumptions.write_text("# Existing assumptions\n", encoding="utf-8")
            commands.write_text("# Existing commands\n", encoding="utf-8")
            run_formal_data_pipeline(
                config_path=config,
                config_hash_path=config_hash,
                plan_path=PLAN,
                smoke_config_path=SMOKE_CONFIG,
                schema_path=SCHEMA,
                output_directory=root / "data",
                code_commit="0123456789abcdef0123456789abcdef01234567",
                assumptions_path=assumptions,
                run_commands_path=commands,
            )
            self.assertIn(
                "## Formal Step 2 data freeze (v1)",
                assumptions.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "## Formal Step 2 data-freeze command (v1)",
                commands.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
