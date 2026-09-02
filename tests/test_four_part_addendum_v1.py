from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.fibre_selector import (
    certify_fibre_optimum,
    solve_deterministic_sa_rlt_level2,
)
from urss_pipeline.four_part_addendum import (
    FourPartAddendumError,
    _phase_finish,
    _phase_start,
    branch_and_bound_fibre_optimum,
    build_result_pack,
    load_addendum_config,
    max_reuse_actions,
    rank_strong_bias_candidates,
    prepare_output_provenance,
    selector_ablation_variants,
    topology_definitions,
)


ROOT = Path(__file__).resolve().parents[1]


class FourPartAddendumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config, cls.config_hash = load_addendum_config(
            ROOT / "configs" / "four_part_addendum_v1.json"
        )
        cls.parent = yaml.safe_load(
            (ROOT / "configs" / "experiment_config_v2.yaml").read_text(
                encoding="utf-8-sig"
            )
        )

    def test_frozen_main_selector_is_unchanged(self) -> None:
        main = self.config["selector_ablation"]["main"]
        self.assertEqual(main["weights"], self.parent["selector"]["weights"])
        self.assertEqual(main["beam_width"], 64)
        self.assertEqual(main["fibre_threshold"], 0.02)
        self.assertEqual(main["penalty_margin"], 1.0)

    def test_ablation_is_one_factor_at_a_time_and_deduplicated(self) -> None:
        variants = selector_ablation_variants(self.config)
        identifiers = [row["variant_id"] for row in variants]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        main = variants[0]
        for variant in variants[1:]:
            changed = sum(
                variant[key] != main[key]
                for key in ("weights", "beam_width", "fibre_threshold", "penalty_margin")
            )
            self.assertEqual(changed, 1, variant["variant_id"])

    def test_topology_definitions_are_symmetric_and_connected(self) -> None:
        definitions = topology_definitions(self.config)
        self.assertEqual(set(definitions), {"line_12", "ring_12", "heavy_hex_d3_19"})
        self.assertEqual(definitions["heavy_hex_d3_19"]["capacity"], 19)
        self.assertEqual(len(definitions["heavy_hex_d3_19"]["coupling_map"]), 40)
        for topology in definitions.values():
            edges = set(topology["coupling_map"])
            self.assertTrue(all((right, left) in edges for left, right in edges))
            visited = {0}
            while True:
                expanded = visited | {
                    right for left, right in edges if left in visited
                }
                if expanded == visited:
                    break
                visited = expanded
            self.assertEqual(visited, set(range(int(topology["capacity"]))))

    def test_branch_and_bound_matches_complete_enumeration(self) -> None:
        polynomial = {
            (1, 2, 3): 2,
            (1, 2, 4): -1,
            (2, 3): 1,
            (4,): -2,
        }
        selector = copy.deepcopy(self.parent["selector"])
        moments = solve_deterministic_sa_rlt_level2(polynomial, n_original=4)
        expected = certify_fibre_optimum(
            polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
            apply_qaoa_hard_limits=True,
        )
        actual = branch_and_bound_fibre_optimum(
            polynomial,
            n_original=4,
            selector=selector,
            moments=moments,
            trace_interval_nodes=1,
        )
        self.assertEqual(actual.result.actions, expected.actions)
        self.assertEqual(actual.final_lower_bound, actual.final_upper_bound)
        self.assertTrue(actual.proof_complete)
        self.assertEqual(actual.trace[-1]["event"], "proof_complete")
        self.assertEqual(actual.trace[-1]["gap"], 0.0)

    def test_penalty_margin_changes_selector_resources(self) -> None:
        polynomial = {(1, 2, 3): 2}
        actions = ((1, 2),)
        low = copy.deepcopy(self.parent["selector"])
        high = copy.deepcopy(self.parent["selector"])
        low["fibre_risk"]["positive_penalty_margin"] = 0.5
        high["fibre_risk"]["positive_penalty_margin"] = 2.0
        low_eval = _evaluate_design(
            polynomial,
            n_original=3,
            actions=actions,
            selector=low,
            apply_qaoa_hard_limits=False,
        )
        high_eval = _evaluate_design(
            polynomial,
            n_original=3,
            actions=actions,
            selector=high,
            apply_qaoa_hard_limits=False,
        )
        self.assertEqual(float(max(low_eval.representation.penalties.values())), 2.5)
        self.assertEqual(float(max(high_eval.representation.penalties.values())), 4.0)
        self.assertLess(low_eval.score, high_eval.score)

    def test_maximum_reuse_baseline_is_deterministic(self) -> None:
        polynomial = {
            (1, 2, 3): 1,
            (1, 2, 4): 1,
            (1, 3, 4): 1,
        }
        first = max_reuse_actions(polynomial)
        second = max_reuse_actions(dict(reversed(list(polynomial.items()))))
        self.assertEqual(first, second)
        self.assertEqual(first[0], (1, 2))
        self.assertEqual(first[1], (1, 2))

    def test_strong_bias_ranking_uses_relaxation_signals_only(self) -> None:
        rows = [
            {
                "instance_id": "b",
                "family": "f",
                "active_auxiliary_count": 1,
                "median_abs_single_margin": 0.3,
                "mean_active_pair_dependence": 0.1,
            },
            {
                "instance_id": "a",
                "family": "f",
                "active_auxiliary_count": 1,
                "median_abs_single_margin": 0.3,
                "mean_active_pair_dependence": 0.2,
            },
        ]
        selected = rank_strong_bias_candidates(rows, 1)
        self.assertEqual(selected[0]["instance_id"], "a")
        contaminated = [dict(rows[0], qaoa_score=0.2)]
        with self.assertRaises(FourPartAddendumError):
            rank_strong_bias_candidates(contaminated, 1)

    def test_completed_phase_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            phase = _phase_start(root, "certification", "abc", False)
            _phase_finish(
                phase,
                {
                    "status": "pass",
                    "config_hash": "abc",
                    "old_e1_e6_overwritten": False,
                },
            )
            with self.assertRaises(FourPartAddendumError):
                _phase_start(root, "certification", "abc", True)

    def test_incomplete_phase_requires_explicit_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _phase_start(root, "topologies", "abc", False)
            with self.assertRaises(FourPartAddendumError):
                _phase_start(root, "topologies", "abc", False)
            resumed = _phase_start(root, "topologies", "abc", True)
            self.assertEqual(resumed.name, "topologies")

    def test_output_provenance_is_stable_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "result"
            config_path = ROOT / "configs" / "four_part_addendum_v1.json"
            parent_path = ROOT / "configs" / "experiment_config_v2.yaml"
            prepare_output_provenance(
                output_root=root,
                config_path=config_path,
                config_hash=self.config_hash,
                parent_config_path=parent_path,
                code_commit="update123",
                parent_commit="1a4f866",
            )
            self.assertTrue((root / "provenance" / "source_checkpoint.json.sha256").is_file())
            prepare_output_provenance(
                output_root=root,
                config_path=config_path,
                config_hash=self.config_hash,
                parent_config_path=parent_path,
                code_commit="update123",
                parent_commit="1a4f866",
            )
            with self.assertRaises(FourPartAddendumError):
                prepare_output_provenance(
                    output_root=root,
                    config_path=config_path,
                    config_hash=self.config_hash,
                    parent_config_path=parent_path,
                    code_commit="changed",
                    parent_commit="1a4f866",
                )

    def test_final_builder_requires_and_packages_all_four_audits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "four_part_addendum_v1"
            for phase_name in ("certification", "topologies", "selector_ablation", "strong_bias"):
                phase = _phase_start(root, phase_name, "abc", False)
                _phase_finish(
                    phase,
                    {
                        "status": "pass",
                        "config_hash": "abc",
                        "old_e1_e6_overwritten": False,
                    },
                )
            zip_path, sidecar = build_result_pack(output_root=root, config_hash="abc")
            self.assertTrue(zip_path.is_file())
            self.assertTrue(sidecar.is_file())
            self.assertEqual(sidecar.read_text().strip(), __import__("hashlib").sha256(zip_path.read_bytes()).hexdigest())
            with self.assertRaises(FourPartAddendumError):
                build_result_pack(output_root=root, config_hash="abc")

    def test_strong_bias_protocol_excludes_p0_and_old_reruns(self) -> None:
        settings = self.config["strong_bias"]
        self.assertEqual(settings["equal_layer_depths"], [1, 2])
        self.assertTrue(settings["exclude_p0"])
        self.assertFalse(settings["screening_uses_qaoa_outcomes"])
        self.assertFalse(settings["old_qaoa_noise_rerun"])


if __name__ == "__main__":
    unittest.main()
