from __future__ import annotations

import importlib.util
import tempfile
import unittest
from itertools import product
from pathlib import Path

import yaml

from urss_pipeline.e2_resources import (
    COMPILED_FIELDS,
    LOGICAL_FIELDS,
    SELECTOR_FIELDS,
    _evaluate_design,
    _fast_evaluate_design,
    _fairness_audit,
    _full_actions,
    beam_select_design,
    compile_sparse_design,
    logical_resource_record,
    matched_random_designs,
    summarise_compiled_rows,
    write_resource_figure_pdf,
)
from urss_pipeline.e1_exactness import action_options
from urss_pipeline.polynomial import canonicalize, cubic_supports


ROOT = Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load(
    (ROOT / "configs" / "experiment_config_v1.yaml").read_text(encoding="utf-8")
)
POLYNOMIAL = {
    (1, 2, 3): 4,
    (1, 2, 4): -2,
    (2, 3, 4): 1,
}


class E2ResourceTests(unittest.TestCase):
    def _native(self):
        return _evaluate_design(
            POLYNOMIAL,
            n_original=4,
            actions=(None, None, None),
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=False,
        )

    def test_logical_metrics_include_every_required_resource(self) -> None:
        evaluation = self._native()
        row = logical_resource_record(
            instance_id="inst_test",
            family="max3sat",
            split="train",
            representation_name="all_native",
            random_rep_seed=None,
            evaluation=evaluation,
            selector_status="endpoint_not_searched",
            selector_compiler_calls=0,
            config_hash="a" * 64,
            manifest_hash="b" * 64,
            code_commit="c" * 40,
        )
        self.assertEqual(row["n_original"], 4)
        self.assertEqual(row["n_aux"], 0)
        self.assertEqual(row["retained_cubic"], 3)
        self.assertEqual(row["M_max"], 0.0)
        self.assertGreater(row["coefficient_dynamic_range"], 0)

    def test_full_actions_reduce_every_cubic_deterministically(self) -> None:
        actions = _full_actions(POLYNOMIAL)
        first = _evaluate_design(
            POLYNOMIAL,
            n_original=4,
            actions=actions,
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=False,
        )
        second = _full_actions(POLYNOMIAL)
        self.assertEqual(actions, second)
        self.assertEqual(
            sum(1 for support in first.representation.polynomial if len(support) == 3),
            0,
        )

    def test_pareto_beam_is_deterministic(self) -> None:
        canonical = canonicalize(POLYNOMIAL)
        cubics = tuple(sorted(cubic_supports(canonical)))
        for actions in product(*(action_options(cubic) for cubic in cubics)):
            fast = _fast_evaluate_design(
                canonical,
                cubics,
                n_original=4,
                actions=actions,
                selector=CONFIG["selector"],
                apply_qaoa_hard_limits=True,
            )
            full = _evaluate_design(
                canonical,
                n_original=4,
                actions=actions,
                selector=CONFIG["selector"],
                apply_qaoa_hard_limits=True,
            )
            self.assertEqual(fast.score, full.score)
            self.assertEqual(
                fast.two_qubit_gate_count,
                full.reference.two_qubit_gate_count,
            )
            self.assertEqual(
                fast.two_qubit_depth,
                full.reference.two_qubit_depth,
            )
        first = beam_select_design(
            POLYNOMIAL,
            n_original=4,
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=True,
        )
        second = beam_select_design(
            POLYNOMIAL,
            n_original=4,
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=True,
        )
        self.assertEqual(first.actions, second.actions)
        self.assertEqual(first.evaluation.score, second.evaluation.score)
        self.assertGreater(first.compiler_calls, 0)

    def test_matched_random_is_reproducible_and_aux_matched(self) -> None:
        selected = ((1, 2), (1, 2), None)
        seeds = [11, 12, 13, 14, 15]
        first = matched_random_designs(
            POLYNOMIAL,
            selected_actions=selected,
            instance_id="inst_test",
            seed_bundle=seeds,
        )
        second = matched_random_designs(
            POLYNOMIAL,
            selected_actions=selected,
            instance_id="inst_test",
            seed_bundle=seeds,
        )
        self.assertEqual(first, second)
        self.assertEqual([seed for seed, _ in first], seeds)
        self.assertTrue(
            all(len({action for action in actions if action is not None}) == 1 for _, actions in first)
        )

    def test_summary_retains_expected_width_failures(self) -> None:
        base = {
            "instance_id": "inst_test",
            "family": "max3sat",
            "split": "test",
            "representation": "all_native",
            "random_rep_seed": "",
            "config_hash": "a" * 64,
            "manifest_hash": "b" * 64,
            "code_commit": "c" * 40,
        }
        rows = [
            {
                **base,
                "topology_id": "all_to_all_reference",
                "transpiler_seed": seed,
                "two_qubit_gates": 20,
                "two_qubit_depth": 10,
                "swap_count": 0,
                "routing_overhead": 0,
                "compile_runtime_sec": 0.1,
                "status": "pass",
                "failure_kind": "",
            }
            for seed in range(5)
        ]
        rows.extend(
            {
                **base,
                "topology_id": "device_sparse_v1",
                "transpiler_seed": seed,
                "two_qubit_gates": "",
                "two_qubit_depth": "",
                "swap_count": "",
                "routing_overhead": "",
                "compile_runtime_sec": 0,
                "status": "infeasible_width_exceeds_topology",
                "failure_kind": "expected_capacity_failure",
            }
            for seed in range(5)
        )
        summary = summarise_compiled_rows(rows)
        self.assertEqual(len(summary), 2)
        sparse = next(row for row in summary if row["topology_id"] == "device_sparse_v1")
        self.assertEqual(sparse["status"], "expected_infeasible_width")
        self.assertEqual(sparse["failure_count"], 5)

    @unittest.skipUnless(
        importlib.util.find_spec("qiskit") is not None,
        "Qiskit is required for the sparse compiler integration test",
    )
    def test_sparse_compiler_uses_frozen_protocol(self) -> None:
        result = compile_sparse_design(
            self._native(),
            compiler_config=CONFIG["compiler"],
            transpiler_seed=CONFIG["compiler"]["transpiler_seed_bundle"][0],
        )
        self.assertEqual(result["status"], "pass")
        self.assertGreaterEqual(result["two_qubit_gates"], 1)
        self.assertGreaterEqual(result["two_qubit_depth"], 1)
        wide = _evaluate_design(
            {(1, 2, 3): 1},
            n_original=13,
            actions=(None,),
            selector=CONFIG["selector"],
            apply_qaoa_hard_limits=False,
        )
        infeasible = compile_sparse_design(
            wide,
            compiler_config=CONFIG["compiler"],
            transpiler_seed=CONFIG["compiler"]["transpiler_seed_bundle"][0],
        )
        self.assertEqual(
            infeasible["status"], "infeasible_width_exceeds_topology"
        )
        self.assertEqual(infeasible["qiskit_version"], "2.4.2")

    def test_fairness_gate_detects_complete_topology_and_seed_bundles(self) -> None:
        seeds = CONFIG["compiler"]["transpiler_seed_bundle"]
        rows = []
        for topology in ("all_to_all_reference", "device_sparse_v1"):
            for seed in seeds:
                rows.append(
                    {
                        "instance_id": "inst_test",
                        "representation": "all_native",
                        "design_id": "design_test",
                        "topology_id": topology,
                        "transpiler_seed": seed,
                        "compiler_protocol_id": "compiler_test",
                    }
                )
        audit = _fairness_audit(
            rows,
            compilation_instance_ids={"inst_test"},
            compiler_config=CONFIG["compiler"],
        )
        self.assertEqual(sum(audit.values()), 0)

    def test_formal_csv_schemas_contain_guide_columns(self) -> None:
        required = {
            "instance_id",
            "family",
            "representation",
            "random_rep_seed",
            "n_original",
            "n_aux",
            "n_qubits",
            "retained_cubic",
            "quadratic_couplings",
            "M_max",
            "coefficient_dynamic_range",
            "topology_id",
            "transpiler_seed",
            "two_qubit_gates",
            "two_qubit_depth",
            "swap_count",
            "routing_overhead",
            "compile_runtime_sec",
            "status",
            "config_hash",
            "manifest_hash",
            "code_commit",
        }
        self.assertTrue(required.issubset(set(COMPILED_FIELDS)))
        self.assertTrue(set(LOGICAL_FIELDS).issuperset(required - {"topology_id", "transpiler_seed", "two_qubit_gates", "two_qubit_depth", "swap_count", "routing_overhead", "compile_runtime_sec", "status"}))
        self.assertIn("regret", SELECTOR_FIELDS)
        self.assertIn("compiler_calls", SELECTOR_FIELDS)

    def test_required_resource_figure_is_a_renderable_pdf(self) -> None:
        representations = (
            "all_native",
            "fully_quadratized",
            "selective",
            "matched_random_selective",
        )
        logical = [
            {
                "family": "max3sat",
                "representation": representation,
                "n_qubits": 4 + index,
                "n_aux": index,
            }
            for index, representation in enumerate(representations)
        ]
        summary = []
        for index, representation in enumerate(representations):
            for topology in ("all_to_all_reference", "device_sparse_v1"):
                summary.append(
                    {
                        "family": "max3sat",
                        "representation": representation,
                        "topology_id": topology,
                        "success_count": 5,
                        "failure_count": 0,
                        "scheduled_row_count": 5,
                        "status": "pass",
                        "two_qubit_gates_median": 10 + index,
                        "two_qubit_depth_median": 5 + index,
                        "swap_count_median": index,
                        "routing_overhead_median": 3 * index,
                    }
                )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "figure.pdf"
            version = write_resource_figure_pdf(path, logical, summary)
            self.assertEqual(version, "4.4.9")
            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            self.assertGreater(path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
