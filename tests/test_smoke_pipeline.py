from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from itertools import product
from pathlib import Path

from urss_pipeline.configuration import (
    ExperimentConfigError,
    validate_experiment_config,
)
from urss_pipeline.generators import (
    derive_seed,
    generate_max3sat,
    generate_spin_glass,
)
from urss_pipeline.identity import compute_instance_id
from urss_pipeline.polynomial import (
    evaluate_max3sat_direct,
    evaluate_pubo,
    max3sat_to_pubo,
)
from urss_pipeline.smoke import run_smoke_batch
from urss_pipeline.validation import (
    InstanceValidationError,
    validate_direct_vs_canonical,
    validate_raw_instance,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(
    os.environ.get(
        "URSS_SCHEMA_PATH",
        ROOT / "instance_schema" / "instance_schema_v1.json",
    )
)
MAX3SAT_EXAMPLE_PATH = Path(
    os.environ.get(
        "URSS_MAX3SAT_EXAMPLE",
        ROOT / "instance_schema" / "max3sat_golden.json",
    )
)
SPIN_EXAMPLE_PATH = Path(
    os.environ.get(
        "URSS_SPIN_EXAMPLE",
        ROOT / "instance_schema" / "cubic_spin_glass_manual.json",
    )
)


def manual_max3sat(literals: list[int], weight: int = 1) -> dict[str, object]:
    instance: dict[str, object] = {
        "schema_version": "instance_schema_v1.0-draft",
        "spec_version": "benchmark_spec_v1.0",
        "family": "max3sat",
        "normalisation_convention": "none",
        "conventions": {
            "domain": "binary_0_1",
            "indexing": "one_based",
            "literal_encoding": "signed_integer_positive_is_x_negative_is_not_x",
            "objective_sense": "minimize",
        },
        "problem": {
            "n": 3,
            "m_clause": 1,
            "clauses": [{"literals": literals, "weight": weight}],
            "clause_density": 1 / 3,
        },
        "generation": {
            "generator_mode": "manual_golden",
            "generator_parameters": {"source": "test"},
            "master_seed": None,
            "instance_seed": None,
            "generator_version": "manual_test_v1",
            "rejection_count": 0,
        },
        "instance_id": "",
    }
    instance["instance_id"] = compute_instance_id(instance)
    return instance


def manual_spin(
    n: int, hyperedges: list[dict[str, object]]
) -> dict[str, object]:
    instance: dict[str, object] = {
        "schema_version": "instance_schema_v1.0-draft",
        "spec_version": "benchmark_spec_v1.0",
        "family": "cubic_spin_glass",
        "normalisation_convention": "none",
        "conventions": {
            "raw_domain": "spin_minus1_plus1",
            "canonical_domain": "binary_0_1",
            "indexing": "one_based",
            "boolean_conversion": "s=1-2x",
            "objective_sense": "minimize",
        },
        "problem": {
            "n": n,
            "m_edge": len(hyperedges),
            "hyperedges": hyperedges,
            "c": 0,
            "h": [],
            "J": [],
            "hyperedge_density": len(hyperedges) / __import__("math").comb(n, 3),
        },
        "generation": {
            "generator_mode": "manual_golden",
            "generator_parameters": {"source": "test"},
            "master_seed": None,
            "instance_seed": None,
            "generator_version": "manual_test_v1",
            "rejection_count": 0,
        },
        "instance_id": "",
    }
    instance["instance_id"] = compute_instance_id(instance)
    return instance


class IdentityTests(unittest.TestCase):
    def test_known_max3sat_example_id(self) -> None:
        instance = json.loads(MAX3SAT_EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(compute_instance_id(instance), instance["instance_id"])

    def test_known_spin_example_id(self) -> None:
        instance = json.loads(SPIN_EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(compute_instance_id(instance), instance["instance_id"])

    def test_reordering_does_not_change_id(self) -> None:
        instance = generate_max3sat(
            n=6,
            clause_density=2,
            generator_mode="uniform",
            master_seed=7,
            instance_seed=11,
        )
        reordered = copy.deepcopy(instance)
        reordered["problem"]["clauses"].reverse()
        for clause in reordered["problem"]["clauses"]:
            clause["literals"].reverse()
        self.assertEqual(compute_instance_id(instance), compute_instance_id(reordered))

    def test_changing_weight_changes_id(self) -> None:
        instance = manual_max3sat([1, 2, 3], weight=1)
        changed = copy.deepcopy(instance)
        changed["problem"]["clauses"][0]["weight"] = 2
        self.assertNotEqual(compute_instance_id(instance), compute_instance_id(changed))


class ConversionTests(unittest.TestCase):
    def test_all_eight_max3sat_sign_patterns(self) -> None:
        for signs in product((-1, 1), repeat=3):
            literals = [sign * index for index, sign in enumerate(signs, start=1)]
            instance = manual_max3sat(literals, weight=5)
            polynomial = max3sat_to_pubo(instance)
            for bits in product((0, 1), repeat=3):
                self.assertEqual(
                    evaluate_max3sat_direct(instance, bits),
                    evaluate_pubo(polynomial, bits),
                )

    def test_three_manual_spin_conversions(self) -> None:
        examples = [
            manual_spin(3, [{"variables": [1, 2, 3], "coefficient": 1}]),
            manual_spin(3, [{"variables": [1, 2, 3], "coefficient": -1}]),
            manual_spin(
                4,
                [
                    {"variables": [1, 2, 3], "coefficient": 1},
                    {"variables": [1, 2, 4], "coefficient": -1},
                ],
            ),
        ]
        for instance in examples:
            report = validate_direct_vs_canonical(instance)
            self.assertEqual(report["status"], "pass")
            self.assertEqual(report["maximum_pointwise_mismatch"], 0)


class GeneratorAndValidationTests(unittest.TestCase):
    def test_fixed_seed_max3sat_is_identical(self) -> None:
        arguments = dict(
            n=6,
            clause_density=2,
            generator_mode="anchor_pair",
            master_seed=20260827,
            instance_seed=derive_seed(20260827, "max3sat", 0),
            anchor_pair_count=2,
        )
        self.assertEqual(generate_max3sat(**arguments), generate_max3sat(**arguments))

    def test_fixed_seed_spin_is_identical(self) -> None:
        arguments = dict(
            n=6,
            hyperedges_per_variable=1,
            generator_mode="anchor_pair",
            master_seed=20260827,
            instance_seed=derive_seed(20260827, "spin", 0),
            anchor_pair_count=2,
        )
        self.assertEqual(generate_spin_glass(**arguments), generate_spin_glass(**arguments))

    def test_generated_instances_pass_schema_and_semantics(self) -> None:
        instances = [
            generate_max3sat(
                n=6,
                clause_density=2,
                generator_mode="uniform",
                master_seed=1,
                instance_seed=2,
            ),
            generate_spin_glass(
                n=6,
                hyperedges_per_variable=1,
                generator_mode="uniform",
                master_seed=1,
                instance_seed=3,
            ),
        ]
        for instance in instances:
            validate_raw_instance(instance, schema_path=SCHEMA_PATH)
            self.assertEqual(validate_direct_vs_canonical(instance)["status"], "pass")

    def test_duplicate_clause_is_rejected(self) -> None:
        instance = manual_max3sat([1, 2, 3])
        duplicate = copy.deepcopy(instance["problem"]["clauses"][0])
        instance["problem"]["clauses"].append(duplicate)
        instance["problem"]["m_clause"] = 2
        instance["problem"]["clause_density"] = 2 / 3
        instance["instance_id"] = compute_instance_id(instance)
        with self.assertRaises(InstanceValidationError):
            validate_raw_instance(instance)


class SmokeBatchTests(unittest.TestCase):
    def test_smoke_batch_is_reproducible_and_complete(self) -> None:
        config_path = ROOT / "configs" / "smoke_config_v1.json"
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_audit = run_smoke_batch(
                config_path=config_path,
                schema_path=SCHEMA_PATH,
                output_directory=first,
            )
            second_audit = run_smoke_batch(
                config_path=config_path,
                schema_path=SCHEMA_PATH,
                output_directory=second,
            )
            self.assertEqual(first_audit, second_audit)
            self.assertEqual(first_audit["status"], "pass")
            self.assertEqual(first_audit["instance_count"], 4)
            first_root, second_root = Path(first), Path(second)
            first_files = sorted(
                path.relative_to(first_root)
                for path in first_root.rglob("*")
                if path.is_file()
            )
            second_files = sorted(
                path.relative_to(second_root)
                for path in second_root.rglob("*")
                if path.is_file()
            )
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual(
                    (first_root / relative).read_bytes(),
                    (second_root / relative).read_bytes(),
                    relative.as_posix(),
                )

    def test_nonempty_output_directory_is_rejected(self) -> None:
        config_path = ROOT / "configs" / "smoke_config_v1.json"
        with tempfile.TemporaryDirectory() as output:
            marker = Path(output) / "existing_evidence.txt"
            marker.write_text("preserve me", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                run_smoke_batch(
                    config_path=config_path,
                    schema_path=SCHEMA_PATH,
                    output_directory=output,
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve me")


class ExperimentConfigTests(unittest.TestCase):
    def test_blocked_draft_config_is_valid_and_auditable(self) -> None:
        config = {
            "config_version": "1.0-draft",
            "config_id": "test_draft",
            "status": "draft_pending_approval",
            "freeze_gate": {
                "blocked": True,
                "required_before_freeze": ["qmax", "noise.model"],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            report = validate_experiment_config(path)
        self.assertEqual(report["status"], "valid")
        self.assertTrue(report["freeze_blocked"])
        self.assertEqual(report["remaining_blocker_count"], 2)

    def test_frozen_config_with_blockers_is_rejected(self) -> None:
        config = {
            "config_version": "1.0",
            "config_id": "invalid_frozen",
            "status": "frozen",
            "freeze_gate": {
                "blocked": True,
                "required_before_freeze": ["qmax"],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ExperimentConfigError):
                validate_experiment_config(path)


if __name__ == "__main__":
    unittest.main()
