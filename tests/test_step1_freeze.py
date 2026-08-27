from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from urss_pipeline.configuration import validate_experiment_config
from urss_pipeline.step1_freeze import Step1FreezeError, freeze_step1_config


ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = ROOT / "configs" / "step1_freeze_decisions_v1.json"
PILOT_CONFIG_PATH = ROOT / "configs" / "reference_pilot_v1.json"


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _draft_config() -> dict[str, object]:
    decisions = json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
    return {
        "config_version": "1.0-draft.2",
        "config_id": "experiment_config_v1_draft_2",
        "status": "draft_pending_pilot_and_approval",
        "created_date": "2026-08-27",
        "updated_date": "2026-08-27",
        "dataset": {
            "tiers": {"qaoa": {"common_width_limit_qmax": None}}
        },
        "relaxation": {"solver": {"scipy_version": "1.18.1"}},
        "selector": {
            "weights": None,
            "feasibility_limits": None,
            "search_settings": {
                "beam_width": None,
                "certification": {
                    "max_complete_candidate_evaluations": None
                },
            },
        },
        "compiler": {
            "software": {
                "qiskit_version": "2.4.2",
                "qiskit_aer_version": "0.17.2",
            },
            "architectures": [
                {"id": "all_to_all_reference", "coupling_map": "all_to_all"},
                {"id": "device_sparse_v1", "coupling_map": None},
            ],
            "basis_gates": None,
            "optimization_level": None,
            "layout_method": None,
            "routing_method": None,
            "translation_method": None,
            "scheduling_method": None,
        },
        "qaoa": {
            "equal_layer_depths": [],
            "compiled_two_qubit_gate_budgets": [],
            "optimizer": {
                "name": None,
                "objective_evaluations": None,
                "restarts": None,
                "tolerance": None,
            },
            "shots": {
                "noiseless_statevector": None,
                "sampled_or_noisy_runs": None,
            },
            "warm_start": {"clipping_delta": None},
        },
        "noise": {
            "model_id": None,
            "levels": [
                {"id": "noiseless", "parameters": {}},
                {"id": "realistic_low", "parameters": None},
                {"id": "realistic_high", "parameters": None},
            ],
        },
        "freeze_gate": {
            "blocked": True,
            "required_before_freeze": decisions["required_draft_blockers"],
            "approvals_required": [
                "benchmark_owner",
                "code_owner",
                "project_lead",
            ],
            "pilot_required": True,
        },
    }


def _create_evidence(root: Path, *, qmax_status: str = "pass") -> Path:
    evidence = root / "pilot"
    evidence.mkdir(parents=True)
    timing_rows: list[dict[str, object]] = []
    for ordinal, width in enumerate([6, 8, 10, 12]):
        timing_rows.append(
            {
                "probe_type": "synthetic_width",
                "instance_id": f"synthetic_width_{width}",
                "family": "synthetic_not_benchmark",
                "representation": "all_native",
                "status": qmax_status if width == 12 else "pass",
                "n_qubits": width,
                "statevector_norm": 1.0,
                "qiskit_version": "2.4.2",
                "qiskit_aer_version": "0.17.2",
            }
        )
    for ordinal in range(4):
        timing_rows.append(
            {
                "probe_type": "benchmark_instance",
                "instance_id": f"instance_{ordinal}",
                "family": "max3sat" if ordinal < 2 else "cubic_spin_glass",
                "representation": "all_native",
                "status": "pass",
                "n_qubits": 6,
                "statevector_norm": 1.0,
                "qiskit_version": "2.4.2",
                "qiskit_aer_version": "0.17.2",
            }
        )
    _write_csv(evidence / "qaoa_statevector_timing.csv", timing_rows)
    _write_csv(
        evidence / "reference_resources.csv",
        [
            {"instance_id": f"instance_{index}", "status": "pass"}
            for index in range(4)
        ],
    )
    _write_csv(
        evidence / "reference_exactness.csv",
        [
            {"instance_id": "instance_0", "status": "pass"},
            {"instance_id": "instance_1", "status": "pass"},
        ],
    )
    config_hash = hashlib.sha256(PILOT_CONFIG_PATH.read_bytes()).hexdigest()
    audit = {
        "status": "pass" if qmax_status == "pass" else "fail",
        "all_full_quadratization_exactness_checks_pass": True,
        "all_statevector_probes_pass": qmax_status == "pass",
        "config_sha256": config_hash,
        "formal_manifest_created": False,
        "formal_split_created": False,
        "qmax_frozen": False,
        "statevector_probe_count": 8,
        "representation_resource_row_count": 4,
    }
    (evidence / "reference_pilot_audit.json").write_text(
        json.dumps(audit), encoding="utf-8"
    )
    return evidence


class Step1FreezeTests(unittest.TestCase):
    def _run(self, root: Path, draft: dict[str, object], evidence: Path):
        draft_path = root / "experiment_config_v1.draft.yaml"
        draft_path.write_text(
            yaml.safe_dump(draft, sort_keys=False), encoding="utf-8"
        )
        assumptions = root / "assumptions_and_decisions.md"
        commands = root / "RUN_COMMANDS.md"
        assumptions.write_text("# Existing assumptions\n", encoding="utf-8")
        commands.write_text("# Existing commands\n", encoding="utf-8")
        return freeze_step1_config(
            draft_config_path=draft_path,
            decisions_path=DECISIONS_PATH,
            reference_pilot_config_path=PILOT_CONFIG_PATH,
            pilot_output_directory=evidence,
            formal_config_path=root / "configs" / "experiment_config_v1.yaml",
            output_directory=root / "freeze_evidence",
            assumptions_path=assumptions,
            run_commands_path=commands,
        )

    def test_pass_creates_zero_blocker_config_and_matching_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = self._run(root, _draft_config(), _create_evidence(root))
            formal_path = root / "configs" / "experiment_config_v1.yaml"
            hash_path = root / "configs" / "experiment_config_v1.sha256"
            report = validate_experiment_config(formal_path)
            self.assertEqual(audit["status"], "pass")
            self.assertTrue(audit["formal_step1_complete"])
            self.assertFalse(audit["formal_step2_started"])
            self.assertEqual(audit["qmax"], 12)
            self.assertEqual(audit["resolved_blocker_count"], 23)
            self.assertEqual(report["remaining_blocker_count"], 0)
            self.assertFalse(report["freeze_blocked"])
            self.assertEqual(
                hash_path.read_text(encoding="utf-8").strip(),
                hashlib.sha256(formal_path.read_bytes()).hexdigest(),
            )
            self.assertIn(
                "## Formal Step 1 freeze (v1)",
                (root / "assumptions_and_decisions.md").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertIn(
                "## Formal Step 1 freeze command (v1)",
                (root / "RUN_COMMANDS.md").read_text(encoding="utf-8"),
            )
            formal = yaml.safe_load(formal_path.read_text(encoding="utf-8"))
            self.assertEqual(formal["status"], "frozen")
            self.assertEqual(
                formal["dataset"]["tiers"]["qaoa"][
                    "common_width_limit_qmax"
                ],
                12,
            )

    def test_fails_if_qmax_probe_did_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(Step1FreezeError):
                self._run(
                    root,
                    _draft_config(),
                    _create_evidence(root, qmax_status="fail"),
                )

    def test_fails_if_draft_blocker_list_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = _draft_config()
            draft["freeze_gate"]["required_before_freeze"].pop()  # type: ignore[index]
            with self.assertRaises(Step1FreezeError):
                self._run(root, draft, _create_evidence(root))

    def test_refuses_to_overwrite_formal_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "configs" / "experiment_config_v1.yaml"
            target.parent.mkdir(parents=True)
            target.write_text("preserve: true\n", encoding="utf-8")
            draft_path = root / "draft.yaml"
            draft_path.write_text(
                yaml.safe_dump(_draft_config(), sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaises(FileExistsError):
                freeze_step1_config(
                    draft_config_path=draft_path,
                    decisions_path=DECISIONS_PATH,
                    reference_pilot_config_path=PILOT_CONFIG_PATH,
                    pilot_output_directory=_create_evidence(root),
                    formal_config_path=target,
                    output_directory=root / "freeze_evidence",
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "preserve: true\n")


if __name__ == "__main__":
    unittest.main()
