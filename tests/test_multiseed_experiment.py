from __future__ import annotations

import json
import unittest

import numpy as np

from scripts.multiseed_experiment import (
    FALSE,
    TRUE,
    UNKNOWN,
    G_BUDGETS,
    M_BUDGETS,
    Q_BUDGETS,
    D_BUDGETS,
    budgets_array,
    classify_layer,
    feasible_slice,
    validate_cached_batch,
)


def candidate(candidate_id: str, category: str, *, n_aux: int = 1, reduced: int = 1) -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "category": category,
        "n_aux": str(n_aux),
        "reduced": str(reduced),
        "evidence_json": json.dumps({"applicable": True, "mismatch_count": 0, "inconsistent_minimiser_count": 0}),
    }


def result(task_id: str, resources: dict[str, float] | None = None, status: str = "compiled") -> dict[str, str]:
    return {
        "task_id": task_id,
        "status": status,
        "resources_json": json.dumps(resources or {"Q": 6, "G": 4, "D": 24, "M": 1.1}),
    }


class MultiSeedClassificationTests(unittest.TestCase):
    def test_strict_mixed_requires_all_nonmixed_candidates_to_be_infeasible(self) -> None:
        mixed = candidate("mixed", "strict_mixed")
        native = candidate("native", "native", n_aux=0, reduced=0)
        budgets = budgets_array()
        classes, _ = classify_layer(
            [mixed, native],
            {
                "mixed": [result("mixed", {"Q": 6, "G": 4, "D": 24, "M": 1.1})],
                "native": [result("native", {"Q": 6, "G": 8, "D": 24, "M": 0.0})],
            },
            budgets,
        )
        point = np.flatnonzero(np.all(budgets == np.array([6, 4, 24, 1.1]), axis=1))[0]
        self.assertEqual(int(classes[point]), TRUE)

    def test_unknown_nonmixed_exclusion_blocks_true(self) -> None:
        mixed = candidate("mixed", "strict_mixed")
        native = candidate("native", "native", n_aux=0, reduced=0)
        classes, _ = classify_layer(
            [mixed, native],
            {"mixed": [result("mixed")], "native": [result("native", status="compile_error")]},
            budgets_array(),
        )
        point = np.flatnonzero(np.all(budgets_array() == np.array([6, 4, 24, 1.1]), axis=1))[0]
        self.assertEqual(int(classes[point]), UNKNOWN)

    def test_degenerate_selective_is_nonmixed(self) -> None:
        degenerate = candidate("degenerate", "degenerate_selective", n_aux=0, reduced=0)
        classes, _ = classify_layer([degenerate], {"degenerate": [result("degenerate")]}, budgets_array())
        point = np.flatnonzero(np.all(budgets_array() == np.array([6, 4, 24, 1.1]), axis=1))[0]
        self.assertEqual(int(classes[point]), FALSE)

    def test_one_actual_circuit_is_reused_for_every_budget_cell(self) -> None:
        mask = feasible_slice({"Q": 6, "G": 4, "D": 24, "M": 1.1}, (len(Q_BUDGETS), len(G_BUDGETS), len(D_BUDGETS), len(M_BUDGETS)))
        expected = sum(q >= 6 and g >= 4 and d >= 24 and m + 1e-9 >= 1.1 for q in Q_BUDGETS for g in G_BUDGETS for d in D_BUDGETS for m in M_BUDGETS)
        self.assertEqual(int(mask.sum()), expected)

    def test_cross_seed_intersection_is_set_intersection(self) -> None:
        mixed = candidate("mixed", "strict_mixed")
        layer = [mixed]
        classes_a, _ = classify_layer(layer, {"mixed": [result("mixed", {"Q": 6, "G": 4, "D": 24, "M": 1.1})]}, budgets_array())
        classes_b, _ = classify_layer(layer, {"mixed": [result("mixed", {"Q": 6, "G": 8, "D": 24, "M": 1.1})]}, budgets_array())
        self.assertEqual(int(np.sum((classes_a == TRUE) & (classes_b == TRUE))), int(np.sum(classes_b == TRUE)))

    def test_mismatched_cache_is_rejected(self) -> None:
        config = {"config_hash": "config-a", "implementation_hash": "impl-a"}
        payload = {"config_hash": "config-b", "implementation_hash": "impl-a", "status": "pass", "rows": [result("task")]}
        with self.assertRaisesRegex(RuntimeError, "config_hash"):
            validate_cached_batch(payload, config, expected_row_count=1)


if __name__ == "__main__":
    unittest.main()
