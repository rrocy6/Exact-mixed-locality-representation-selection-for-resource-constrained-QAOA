from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.e1_exactness import _canonical_polynomial
from urss_pipeline.fibre_rerun import (
    FibreDesignBundle,
    FibreRerunError,
    _e2_designs,
    _qaoa_designs,
    deserialize_actions,
    polynomial_key,
    sha256_file,
    verify_sidecar,
)


class FibreRerunPrimitiveTests(unittest.TestCase):
    def test_deserialise_actions(self) -> None:
        self.assertEqual(
            deserialize_actions([None, [3, 1], [2, 4]]),
            (None, (1, 3), (2, 4)),
        )

    def test_deserialise_actions_rejects_invalid_pair(self) -> None:
        with self.assertRaises(FibreRerunError):
            deserialize_actions([[2, 2]])

    def test_polynomial_key_is_order_independent(self) -> None:
        left = {(1, 2, 3): 2, (1,): -1, (): 4}
        right = {(): 4, (1,): -1, (1, 2, 3): 2}
        self.assertEqual(polynomial_key(left), polynomial_key(right))

    def test_sidecar_gate_accepts_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.json"
            path.write_bytes(b"{}\n")
            path.with_suffix(".sha256").write_text(
                sha256_file(path) + "\n", encoding="utf-8"
            )
            self.assertEqual(verify_sidecar(path), sha256_file(path))

    def test_sidecar_gate_rejects_changed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.csv"
            path.write_bytes(b"a\n")
            path.with_suffix(".sha256").write_text("0" * 64 + "\n", encoding="utf-8")
            with self.assertRaises(FibreRerunError):
                verify_sidecar(path)


class FibreRerunBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        candidates = (
            Path("fibre_selector_v2"),
            Path("tmp_fibre_selector_v2_full_output"),
        )
        directory = next((path for path in candidates if path.is_dir()), None)
        if directory is None:
            raise unittest.SkipTest("Frozen fibre_selector_v2 bundle is not available")
        cls.bundle = FibreDesignBundle(
            directory=directory,
            config_path=directory / "experiment_config_v2.yaml",
            config_hash_path=directory / "experiment_config_v2.sha256",
            data_directory="data",
        )
        cls.config = yaml.safe_load(
            (directory / "experiment_config_v2.yaml").read_text(encoding="utf-8-sig")
        )

    @staticmethod
    def _manifest_row(tier: str, instance_id: str) -> dict[str, str]:
        with Path(f"data/manifests/{tier}_v1.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as stream:
            return next(row for row in csv.DictReader(stream) if row["instance_id"] == instance_id)

    def test_bundle_covers_all_frozen_tiers(self) -> None:
        self.assertEqual(
            {tier: len(rows) for tier, rows in self.bundle.records.items()},
            {"oracle": 60, "qaoa": 72, "compilation": 180},
        )

    def test_compilation_design_injection_has_eight_designs(self) -> None:
        record = next(iter(self.bundle.records["compilation"].values()))
        row = self._manifest_row("compilation", str(record["instance_id"]))
        _, polynomial = _canonical_polynomial(Path("data") / row["canonical_file"])
        designs, design_record = _e2_designs(
            self.bundle,
            polynomial,
            n_original=int(row["n"]),
            instance_id=row["instance_id"],
            config=self.config,
        )
        self.assertEqual(len(designs), 8)
        self.assertEqual(len(design_record["matched_random"]), 5)
        self.assertEqual(designs[2][0], "selective")

    def test_qaoa_design_injection_has_eight_feasible_designs(self) -> None:
        record = next(iter(self.bundle.records["qaoa"].values()))
        row = self._manifest_row("qaoa", str(record["instance_id"]))
        _, polynomial = _canonical_polynomial(Path("data") / row["canonical_file"])
        designs = _qaoa_designs(
            self.bundle,
            polynomial,
            n_original=int(row["n"]),
            instance_id=row["instance_id"],
            config=self.config,
        )
        self.assertEqual(len(designs), 8)
        self.assertTrue(all(design.evaluation.feasible for design in designs))

    def test_selector_validation_conversion_preserves_all_rows(self) -> None:
        rows = self.bundle.selector_validation_rows(
            config_hash=self.bundle.config_hash,
            manifest_hash=self.bundle.manifest_hashes["oracle"],
            code_commit="test",
        )
        self.assertEqual(len(rows), 180)
        self.assertTrue(all(row["test_retuning_used"] is False for row in rows))
        self.assertTrue(all(float(row["regret"]) >= -1e-12 for row in rows))


if __name__ == "__main__":
    unittest.main()
