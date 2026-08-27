"""Evidence-gated finalisation of the formal Step 1 experiment config."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .configuration import validate_experiment_config


class Step1FreezeError(ValueError):
    """Raised when draft configuration or pilot evidence cannot be frozen."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Step1FreezeError(f"Expected a JSON object: {path}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required for Step 1 freeze") from error
    value = yaml.safe_load(path.read_bytes())
    if not isinstance(value, dict):
        raise Step1FreezeError(f"Expected a YAML mapping: {path}")
    return value


def _dump_yaml(value: dict[str, Any]) -> bytes:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required for Step 1 freeze") from error
    return yaml.safe_dump(
        value,
        allow_unicode=False,
        default_flow_style=False,
        sort_keys=False,
        width=100,
    ).encode("utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _require_empty_output(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {path}. "
            "Use a new path to preserve prior evidence."
        )
    path.mkdir(parents=True, exist_ok=True)


def _require_new_file(path: Path) -> None:
    if path.exists():
        raise FileExistsError(
            f"Formal config target already exists: {path}. "
            "Refusing to overwrite a frozen configuration."
        )
    hash_path = path.with_suffix(".sha256")
    if hash_path.exists():
        raise FileExistsError(
            f"Formal config hash target already exists: {hash_path}"
        )


def _check_document_target(path: Path, marker: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Required Step 1 document does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    if marker in content:
        raise Step1FreezeError(
            f"Document already contains the formal Step 1 marker: {path}"
        )
    return content


def _append_markdown(path: Path, original: str, section: str) -> None:
    separator = "" if original.endswith("\n") else "\n"
    path.write_text(
        original + separator + "\n" + section.rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate_topology(decisions: dict[str, Any], qmax: int) -> None:
    edges = decisions["compiler"]["device_sparse_v1"]["coupling_map"]
    normalised = {tuple(edge) for edge in edges}
    if any(
        len(edge) != 2
        or not all(isinstance(vertex, int) for vertex in edge)
        or edge[0] == edge[1]
        for edge in edges
    ):
        raise Step1FreezeError("Sparse coupling map contains an invalid edge")
    vertices = {vertex for edge in normalised for vertex in edge}
    if vertices != set(range(qmax)):
        raise Step1FreezeError(
            "Sparse coupling map must cover exactly the Qmax qubits"
        )
    if any((right, left) not in normalised for left, right in normalised):
        raise Step1FreezeError("Sparse coupling map must be bidirectional")


def _validate_pilot_evidence(
    *,
    pilot_output: Path,
    pilot_config_path: Path,
    decisions: dict[str, Any],
) -> dict[str, Any]:
    audit = _load_json(pilot_output / "reference_pilot_audit.json")
    timing_rows = _read_csv(pilot_output / "qaoa_statevector_timing.csv")
    resource_rows = _read_csv(pilot_output / "reference_resources.csv")
    exactness_rows = _read_csv(pilot_output / "reference_exactness.csv")
    pilot_hash = _sha256(pilot_config_path.read_bytes())

    required_audit = {
        "status": "pass",
        "all_full_quadratization_exactness_checks_pass": True,
        "all_statevector_probes_pass": True,
        "formal_manifest_created": False,
        "formal_split_created": False,
        "qmax_frozen": False,
    }
    for key, expected in required_audit.items():
        if audit.get(key) != expected:
            raise Step1FreezeError(
                f"Pilot audit field {key!r} must be {expected!r}"
            )
    if audit.get("config_sha256") != pilot_hash:
        raise Step1FreezeError("Pilot audit/config SHA-256 mismatch")
    if int(audit.get("statevector_probe_count", -1)) != len(timing_rows):
        raise Step1FreezeError("Pilot timing row count does not match audit")
    if int(audit.get("representation_resource_row_count", -1)) != len(
        resource_rows
    ):
        raise Step1FreezeError("Pilot resource row count does not match audit")
    if not exactness_rows or any(
        row.get("status") != "pass" for row in exactness_rows
    ):
        raise Step1FreezeError("Full quadratization pilot exactness did not pass")
    if not timing_rows or any(row.get("status") != "pass" for row in timing_rows):
        raise Step1FreezeError("At least one statevector pilot row did not pass")

    qmax = int(decisions["qmax"]["value"])
    matching = [
        row
        for row in timing_rows
        if row.get("probe_type") == decisions["qmax"]["required_probe_type"]
        and int(row["n_qubits"]) == qmax
        and row.get("status") == decisions["qmax"]["required_status"]
    ]
    if not matching:
        raise Step1FreezeError(
            f"No passing synthetic statevector probe supports Qmax={qmax}"
        )
    if any(abs(float(row["statevector_norm"]) - 1.0) > 1e-9 for row in matching):
        raise Step1FreezeError("Qmax statevector norm check failed")

    pilot_config = _load_json(pilot_config_path)
    declared_widths = pilot_config.get("qaoa_probe", {}).get(
        "synthetic_widths", []
    )
    if qmax != max(declared_widths, default=-1):
        raise Step1FreezeError(
            "Qmax must equal the largest predeclared synthetic pilot width"
        )
    versions = {
        (row.get("qiskit_version"), row.get("qiskit_aer_version"))
        for row in timing_rows
    }
    if versions != {("2.4.2", "0.17.2")}:
        raise Step1FreezeError(
            f"Unexpected or inconsistent quantum-stack versions: {versions}"
        )
    return {
        "pilot_audit_sha256": _sha256(
            (pilot_output / "reference_pilot_audit.json").read_bytes()
        ),
        "pilot_config_sha256": pilot_hash,
        "timing_sha256": _sha256(
            (pilot_output / "qaoa_statevector_timing.csv").read_bytes()
        ),
        "qmax_supporting_rows": len(matching),
        "qiskit_version": "2.4.2",
        "qiskit_aer_version": "0.17.2",
    }


def _replace_noise_level(
    levels: list[dict[str, Any]], level_id: str, parameters: dict[str, Any]
) -> None:
    matches = [level for level in levels if level.get("id") == level_id]
    if len(matches) != 1:
        raise Step1FreezeError(f"Expected exactly one noise level {level_id!r}")
    matches[0]["parameters"] = copy.deepcopy(parameters)


def _build_formal_config(
    *,
    draft: dict[str, Any],
    decisions: dict[str, Any],
    provenance: dict[str, Any],
    draft_hash: str,
    decisions_hash: str,
) -> dict[str, Any]:
    formal = copy.deepcopy(draft)
    qmax = int(decisions["qmax"]["value"])
    formal["config_version"] = "1.0"
    formal["config_id"] = "experiment_config_v1"
    formal["status"] = "frozen"
    formal["updated_date"] = decisions["created_date"]
    formal["dataset"]["tiers"]["qaoa"][
        "common_width_limit_qmax"
    ] = qmax

    selector = formal["selector"]
    selector["weights"] = copy.deepcopy(decisions["selector"]["weights"])
    selector["scales"] = copy.deepcopy(decisions["selector"]["scales"])
    selector["feasibility_limits"] = copy.deepcopy(
        decisions["selector"]["feasibility_limits"]
    )
    selector["search_settings"]["beam_width"] = decisions["selector"][
        "beam_width"
    ]
    selector["search_settings"]["certification"][
        "max_complete_candidate_evaluations"
    ] = decisions["selector"]["maximum_complete_candidate_evaluations"]

    compiler = formal["compiler"]
    sparse = [
        item
        for item in compiler["architectures"]
        if item.get("id") == "device_sparse_v1"
    ]
    if len(sparse) != 1:
        raise Step1FreezeError(
            "Draft config must contain exactly one device_sparse_v1 architecture"
        )
    sparse[0]["coupling_map"] = copy.deepcopy(
        decisions["compiler"]["device_sparse_v1"]["coupling_map"]
    )
    sparse[0]["topology"] = decisions["compiler"]["device_sparse_v1"][
        "topology"
    ]
    for field in (
        "basis_gates",
        "optimization_level",
        "layout_method",
        "routing_method",
        "translation_method",
        "scheduling_method",
    ):
        compiler[field] = copy.deepcopy(decisions["compiler"][field])

    qaoa = formal["qaoa"]
    qaoa["equal_layer_depths"] = copy.deepcopy(
        decisions["qaoa"]["equal_layer_depths"]
    )
    qaoa["compiled_two_qubit_gate_budgets"] = copy.deepcopy(
        decisions["qaoa"]["compiled_two_qubit_gate_budgets"]
    )
    qaoa["optimizer"].update(copy.deepcopy(decisions["qaoa"]["optimizer"]))
    qaoa["shots"]["sampled_or_noisy_runs"] = decisions["qaoa"][
        "sampled_or_noisy_shots"
    ]
    qaoa["warm_start"]["clipping_delta"] = decisions["qaoa"][
        "warm_start_clipping_delta"
    ]

    formal["noise"]["model_id"] = decisions["noise"]["model_id"]
    _replace_noise_level(
        formal["noise"]["levels"],
        "realistic_low",
        decisions["noise"]["realistic_low"],
    )
    _replace_noise_level(
        formal["noise"]["levels"],
        "realistic_high",
        decisions["noise"]["realistic_high"],
    )

    formal["freeze_gate"] = {
        "blocked": False,
        "required_before_freeze": [],
        "approvals_required": [],
        "pilot_required": False,
        "completed": True,
        "completion_basis": "evidence_gated_step1_freeze_v1",
    }
    formal["freeze_provenance"] = {
        "finalizer": "urss_step1_freeze_v1",
        "draft_config_sha256": draft_hash,
        "decision_file_sha256": decisions_hash,
        **provenance,
        "resolved_blockers": list(decisions["required_draft_blockers"]),
        "decision_basis": copy.deepcopy(decisions["decision_basis"]),
        "formal_step2_started": False,
    }
    return formal


def freeze_step1_config(
    *,
    draft_config_path: str | Path,
    decisions_path: str | Path,
    reference_pilot_config_path: str | Path,
    pilot_output_directory: str | Path,
    formal_config_path: str | Path,
    output_directory: str | Path,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate all evidence, then create the zero-blocker formal config."""

    draft_config_path = Path(draft_config_path)
    decisions_path = Path(decisions_path)
    reference_pilot_config_path = Path(reference_pilot_config_path)
    pilot_output_directory = Path(pilot_output_directory)
    formal_config_path = Path(formal_config_path)
    output_directory = Path(output_directory)
    assumptions_path = Path(assumptions_path) if assumptions_path else None
    run_commands_path = Path(run_commands_path) if run_commands_path else None

    _require_new_file(formal_config_path)
    _require_empty_output(output_directory)
    assumptions_original = (
        _check_document_target(assumptions_path, "## Formal Step 1 freeze (v1)")
        if assumptions_path
        else None
    )
    commands_original = (
        _check_document_target(run_commands_path, "## Formal Step 1 freeze command (v1)")
        if run_commands_path
        else None
    )
    draft_report = validate_experiment_config(draft_config_path)
    decisions = _load_json(decisions_path)
    required = decisions.get("required_draft_blockers")
    draft = _load_yaml(draft_config_path)
    actual = draft["freeze_gate"]["required_before_freeze"]
    if draft_report["remaining_blocker_count"] != len(required):
        raise Step1FreezeError(
            "Draft blocker count does not match the Step 1 decision file"
        )
    if actual != required:
        raise Step1FreezeError(
            "Draft blocker names/order differ from the audited 23-blocker state"
        )
    if not draft_report["freeze_blocked"]:
        raise Step1FreezeError("Input config is not an actively blocked draft")

    for path, expected in [
        (("relaxation", "solver", "scipy_version"), "1.18.1"),
        (("compiler", "software", "qiskit_version"), "2.4.2"),
        (("compiler", "software", "qiskit_aer_version"), "0.17.2"),
    ]:
        value: Any = draft
        for part in path:
            value = value[part]
        if value != expected:
            raise Step1FreezeError(
                f"Draft version {'.'.join(path)} must equal {expected}"
            )

    qmax = int(decisions["qmax"]["value"])
    _validate_topology(decisions, qmax)
    provenance = _validate_pilot_evidence(
        pilot_output=pilot_output_directory,
        pilot_config_path=reference_pilot_config_path,
        decisions=decisions,
    )
    draft_hash = _sha256(draft_config_path.read_bytes())
    decisions_hash = _sha256(decisions_path.read_bytes())
    formal = _build_formal_config(
        draft=draft,
        decisions=decisions,
        provenance=provenance,
        draft_hash=draft_hash,
        decisions_hash=decisions_hash,
    )
    formal_bytes = _dump_yaml(formal)
    formal_hash = _sha256(formal_bytes)

    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / "experiment_config_v1.yaml"
        candidate.write_bytes(formal_bytes)
        final_report = validate_experiment_config(candidate)
    if final_report["freeze_blocked"] or final_report[
        "remaining_blocker_count"
    ] != 0:
        raise AssertionError("Final config unexpectedly retained blockers")
    if final_report["sha256"] != formal_hash:
        raise AssertionError("Final config hash changed during validation")

    formal_config_path.parent.mkdir(parents=True, exist_ok=True)
    formal_config_path.write_bytes(formal_bytes)
    formal_hash_path = formal_config_path.with_suffix(".sha256")
    formal_hash_path.write_text(formal_hash + "\n", encoding="utf-8", newline="\n")
    (output_directory / "config_snapshot_frozen.yaml").write_bytes(formal_bytes)
    (output_directory / "config_snapshot_frozen.sha256").write_text(
        formal_hash + "\n", encoding="utf-8", newline="\n"
    )
    (output_directory / "step1_freeze_decisions_snapshot.json").write_bytes(
        decisions_path.read_bytes()
    )

    if assumptions_path is not None and assumptions_original is not None:
        selector = decisions["selector"]
        qaoa = decisions["qaoa"]
        noise = decisions["noise"]
        assumptions_section = f"""## Formal Step 1 freeze (v1)

- Status: `frozen`; remaining blocker count: `0`.
- Formal config: `configs/experiment_config_v1.yaml`.
- Formal config SHA-256: `{formal_hash}`.
- Evidence-backed common width cap: `Qmax={qmax}`.
- Selector: equal weights `0.25/0.25/0.25/0.25`, beam width `{selector['beam_width']}`, complete oracle budget `{selector['maximum_complete_candidate_evaluations']}`.
- Sparse compiler target: bidirectional 3-by-4 grid, `rz/sx/x/cx`, optimisation level `1`, SABRE layout/routing, deterministic seed bundle already declared.
- QAOA: depths `{qaoa['equal_layer_depths']}`, compiled 2Q budgets `{qaoa['compiled_two_qubit_gate_budgets']}`, COBYLA with `{qaoa['optimizer']['objective_evaluations']}` evaluations and `{qaoa['optimizer']['restarts']}` restarts, `{qaoa['sampled_or_noisy_shots']}` sampled/noisy shots.
- Warm-start clipping delta: `{qaoa['warm_start_clipping_delta']}`.
- Noise model: `{noise['model_id']}` with exactly two frozen nonzero levels.
- Pilot config SHA-256: `{provenance['pilot_config_sha256']}`.
- Pilot audit SHA-256: `{provenance['pilot_audit_sha256']}`.
- Formal manifests/splits have not yet been created; their generation belongs to Step 2.

This section supersedes the earlier draft-status and pending-pilot statements. The complete values and rationales are authoritative in the formal config, its `freeze_provenance`, and `configs/step1_freeze_decisions_v1.json`.
"""
        _append_markdown(
            assumptions_path, assumptions_original, assumptions_section
        )

    if run_commands_path is not None and commands_original is not None:
        commands_section = """## Formal Step 1 freeze command (v1)

The evidence-gated finalizer was added after the reference compiler pilot. Run it from the repository root:

```powershell
python .\\run_finalize_step1.py `
  --draft-config .\\configs\\experiment_config_v1.draft.yaml `
  --decisions .\\configs\\step1_freeze_decisions_v1.json `
  --reference-pilot-config .\\configs\\reference_pilot_v1.json `
  --pilot-output .\\evidence\\reference_pilot_v1_windows `
  --formal-config .\\configs\\experiment_config_v1.yaml `
  --output .\\evidence\\step1_freeze_v1 `
  --assumptions .\\assumptions_and_decisions.md `
  --run-commands .\\RUN_COMMANDS.md
```

Required result: `status=pass`, `formal_step1_complete=true`, `remaining_blocker_count=0`, and `formal_step2_started=false`. Validate the written config and hash before starting Step 2.
"""
        _append_markdown(run_commands_path, commands_original, commands_section)

    audit: dict[str, Any] = {
        "status": "pass",
        "scope": "formal_step1_configuration_freeze",
        "decision_version": decisions["decision_version"],
        "draft_config_sha256": draft_hash,
        "decisions_sha256": decisions_hash,
        "formal_config_sha256": formal_hash,
        "formal_config_path": formal_config_path.as_posix(),
        "remaining_blocker_count": 0,
        "qmax": qmax,
        "resolved_blocker_count": len(required),
        "pilot_evidence": provenance,
        "formal_step1_complete": True,
        "formal_step2_started": False,
        "formal_manifest_created": False,
        "formal_split_created": False,
        "updated_documents": [
            path.as_posix()
            for path in (assumptions_path, run_commands_path)
            if path is not None
        ],
        "output_files": [
            "config_snapshot_frozen.yaml",
            "config_snapshot_frozen.sha256",
            "step1_freeze_decisions_snapshot.json",
            "step1_freeze_audit.json",
        ],
    }
    (output_directory / "step1_freeze_audit.json").write_text(
        json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return audit
