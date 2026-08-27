from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.e1_exactness import (
    E1_FIELDS,
    E1ExactnessError,
    action_options,
    build_mixed_representation,
    evaluate_design_settings,
    evaluate_pointwise,
    full_action_vector,
    matched_random_actions,
    select_resource_optimal_design,
    verify_data_freeze,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_with_hash(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8"
    )
    return digest


class E1CoreTests(unittest.TestCase):
    def test_action_order_is_native_then_lexicographic_pairs(self) -> None:
        self.assertEqual(
            action_options((1, 3, 4)),
            (None, (1, 3), (1, 4), (3, 4)),
        )

    def test_sharp_threshold_has_failure_tie_and_strict_uniqueness(self) -> None:
        original = {(1, 2, 3): 2}
        below = build_mixed_representation(
            original,
            n_original=3,
            actions=((1, 2),),
            penalty_values={(1, 2): 1},
        )
        at = build_mixed_representation(
            original,
            n_original=3,
            actions=((1, 2),),
            penalty_values={(1, 2): 2},
        )
        above = build_mixed_representation(
            original,
            n_original=3,
            actions=((1, 2),),
            penalty_values={(1, 2): 3},
        )
        below_result = evaluate_pointwise(original, below)
        at_result = evaluate_pointwise(original, at)
        above_result = evaluate_pointwise(original, above)
        self.assertGreater(below_result["mismatch_count"], 0)
        self.assertEqual(at_result["mismatch_count"], 0)
        self.assertGreater(at_result["tie_count"], 0)
        self.assertEqual(above_result["mismatch_count"], 0)
        self.assertEqual(above_result["inconsistent_minimiser_count"], 0)

    def test_mixed_sign_shared_pair_threshold_is_maximum_signed_mass(self) -> None:
        original = {(1, 2, 3): 3, (1, 2, 4): -5}
        representation = build_mixed_representation(
            original,
            n_original=4,
            actions=((1, 2), (1, 2)),
            default_margin=1,
        )
        self.assertEqual(representation.thresholds[(1, 2)], 5)
        self.assertEqual(representation.penalties[(1, 2)], 6)
        result = evaluate_pointwise(original, representation)
        self.assertEqual(result["mismatch_count"], 0)
        self.assertEqual(result["inconsistent_minimiser_count"], 0)

    def test_pairwise_setting_protocol_aggregates_required_rows(self) -> None:
        rows, witnesses, trials = evaluate_design_settings(
            {(1, 2, 3): 2},
            n_original=3,
            actions_by_seed=[(None, ((1, 2),))],
            representation_name="selective",
            below_delta=1,
            above_epsilon=1,
            witness_prefix="fixture",
        )
        by_setting = {row["penalty_setting"]: row for row in rows}
        self.assertEqual(
            set(by_setting),
            {"below_threshold", "at_threshold", "above_threshold"},
        )
        self.assertGreater(by_setting["below_threshold"]["mismatch_count"], 0)
        self.assertGreater(by_setting["at_threshold"]["tie_count"], 0)
        self.assertEqual(by_setting["above_threshold"]["mismatch_count"], 0)
        self.assertEqual(
            by_setting["above_threshold"]["inconsistent_minimiser_count"], 0
        )
        self.assertTrue(witnesses)
        self.assertEqual(len(trials), 3)

    def test_full_reference_reduces_every_cubic_with_minimum_pair_cover(self) -> None:
        original = {(1, 2, 3): 2, (1, 2, 4): -1}
        actions = full_action_vector(original)
        self.assertEqual(actions, ((1, 2), (1, 2)))
        representation = build_mixed_representation(
            original, n_original=4, actions=actions
        )
        self.assertEqual(representation.n_auxiliary, 1)
        self.assertFalse(any(len(support) == 3 for support in representation.polynomial))

    def test_oracle_resource_selector_is_complete_and_deterministic(self) -> None:
        config = yaml.safe_load(
            (ROOT / "configs" / "experiment_config_v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        original = {(1, 2, 3): 2, (1, 2, 4): -1}
        first = select_resource_optimal_design(
            original,
            n_original=4,
            selector_config=config["selector"],
            positive_margin=1,
        )
        second = select_resource_optimal_design(
            original,
            n_original=4,
            selector_config=config["selector"],
            positive_margin=1,
        )
        self.assertEqual(first, second)
        self.assertEqual(first[1]["design_count"], 16)
        self.assertEqual(first[1]["status"], "certified_complete_resource_objective")

    def test_matched_random_is_reproducible_and_matches_auxiliary_count(self) -> None:
        original = {(1, 2, 3): 2, (1, 2, 4): -1}
        selected = ((1, 2), None)
        first = matched_random_actions(
            original,
            target_auxiliary_count=1,
            selected_actions=selected,
            instance_id="inst_fixture",
            seed_bundle=[11, 12, 13],
        )
        second = matched_random_actions(
            original,
            target_auxiliary_count=1,
            selected_actions=selected,
            instance_id="inst_fixture",
            seed_bundle=[11, 12, 13],
        )
        self.assertEqual(first, second)
        for _, actions in first:
            self.assertEqual(
                len({action for action in actions if action is not None}), 1
            )

    def test_data_freeze_gate_accepts_signed_formal_shape_and_rejects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "experiment_config_v1.yaml"
            config.write_bytes(b"status: frozen\n")
            config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
            config.with_suffix(".sha256").write_text(
                config_hash + "\n", encoding="utf-8"
            )
            data = root / "data"
            snapshot = data / "config_snapshot_frozen.yaml"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(config.read_bytes())
            snapshot.with_suffix(".sha256").write_text(
                config_hash + "\n", encoding="utf-8"
            )
            manifest = data / "manifests" / "oracle_v1.csv"
            manifest.parent.mkdir(parents=True)
            with manifest.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=("instance_id", "family", "split", "ground_truth_status"),
                    lineterminator="\n",
                )
                writer.writeheader()
                for family in ("cubic_spin_glass", "max3sat"):
                    for index in range(30):
                        writer.writerow(
                            {
                                "instance_id": f"{family}_{index}",
                                "family": family,
                                "split": ("train", "validation", "test")[index % 3],
                                "ground_truth_status": "optimal",
                            }
                        )
            manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            manifest.with_suffix(".sha256").write_text(
                manifest_digest + "\n", encoding="utf-8"
            )
            bundle_digest = _write_with_hash(
                data / "manifests" / "manifest_bundle_v1.json", b"{}\n"
            )
            audit = {
                "status": "pass",
                "formal_instance_count": 312,
                "formal_manifests_created": True,
                "formal_split_created": True,
                "split_leakage_count": 0,
                "representation_split_consistent": True,
                "validation_failure_count": 0,
                "qmax_feasibility_failure_count": 0,
                "test_split_frozen_before_results": True,
                "formal_results_created": False,
                "qmax": 12,
                "manifest_bundle_sha256": bundle_digest,
            }
            _write_with_hash(
                data / "benchmark_audit_v1.json",
                (json.dumps(audit, sort_keys=True) + "\n").encode("utf-8"),
            )
            gate = verify_data_freeze(
                config_path=config,
                config_hash_path=config.with_suffix(".sha256"),
                data_directory=data,
            )
            self.assertEqual(gate["config_hash"], config_hash)
            manifest.write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(E1ExactnessError):
                verify_data_freeze(
                    config_path=config,
                    config_hash_path=config.with_suffix(".sha256"),
                    data_directory=data,
                )

    def test_formal_csv_schema_contains_every_required_guide_column(self) -> None:
        required = {
            "instance_id",
            "family",
            "representation",
            "penalty_setting",
            "n_original",
            "n_aux",
            "x_assignments_checked",
            "xy_assignments_checked",
            "max_pointwise_error",
            "mismatch_count",
            "tie_count",
            "inconsistent_minimiser_count",
            "witness_id",
            "runtime_sec",
            "status",
            "config_hash",
            "manifest_hash",
            "code_commit",
        }
        self.assertTrue(required.issubset(E1_FIELDS))


if __name__ == "__main__":
    unittest.main()
