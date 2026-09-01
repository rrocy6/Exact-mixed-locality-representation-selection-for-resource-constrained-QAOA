"""Hash-safe post-processing correction for the fibre-aware E1/E4 outputs.

This module never runs an experiment.  It rebuilds the E4 summary and LaTeX
table exclusively from the already-frozen E4 raw-run CSV, corrects the stale
E1 fibre-guardrail provenance, and updates the downstream validation hash
chain required before the final result ZIP is rebuilt.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from .e4_warmstart import SUMMARY_FIELDS, _latex_table, summarise_warmstart_runs
from .fibre_rerun import sha256_file


class FibrePostprocessError(RuntimeError):
    """An input, provenance, or post-processing invariant failed."""


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise FibrePostprocessError(f"Expected JSON object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _verify_sidecar(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise FibrePostprocessError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = sha256_file(path)
    declared = sidecar.read_text(encoding="utf-8-sig").strip().lower()
    if actual != declared:
        raise FibrePostprocessError(f"Frozen hash mismatch: {path}")
    return actual


def _write_json(path: Path, value: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return _write_sidecar(path)


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return _write_sidecar(path)


def _write_text(path: Path, value: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")
    return _write_sidecar(path)


def _write_sidecar(path: Path) -> str:
    digest = sha256_file(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def guardrail_provenance(config: Mapping[str, object]) -> dict[str, object]:
    selector = config.get("selector")
    if not isinstance(selector, Mapping):
        raise FibrePostprocessError("Missing selector configuration")
    fibre_risk = selector.get("fibre_risk")
    if not isinstance(fibre_risk, Mapping) or fibre_risk.get("enabled") is not True:
        raise FibrePostprocessError("Frozen v2 fibre-risk guardrail is not enabled")
    required = (
        "definition",
        "moment_source",
        "threshold_tau",
        "guardrail_operator",
    )
    missing = [field for field in required if field not in fibre_risk]
    if missing:
        raise FibrePostprocessError(
            "Incomplete frozen v2 fibre-risk guardrail: " + ", ".join(missing)
        )
    return {
        "selector_fibre_risk_guardrail": "enabled_in_frozen_v2",
        "selector_fibre_risk_guardrail_definition": fibre_risk["definition"],
        "selector_fibre_risk_guardrail_moment_source": fibre_risk["moment_source"],
        "selector_fibre_risk_guardrail_threshold_tau": fibre_risk["threshold_tau"],
        "selector_fibre_risk_guardrail_operator": fibre_risk["guardrail_operator"],
    }


def _replace_artifact_hash(
    value: object,
    relative_path: str,
    digest: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise FibrePostprocessError("Validation summary lacks artifact_hashes")
    result = {str(key): item for key, item in value.items()}
    wanted = relative_path.replace("\\", "/")
    matching = [key for key in result if key.replace("\\", "/") == wanted]
    if len(matching) != 1:
        raise FibrePostprocessError(
            f"Expected exactly one artifact hash entry for {relative_path}"
        )
    result[matching[0]] = digest
    return result


def _require_pass(summary: Mapping[str, object], continuation: str, label: str) -> None:
    if summary.get("status") != "pass" or summary.get(continuation) is not True:
        raise FibrePostprocessError(f"{label} validation gate is not pass")


def repair_fibre_e1_e4_postprocess(
    *,
    output_root: str | Path,
    config_path: str | Path,
    config_hash_path: str | Path,
    code_commit: str,
) -> dict[str, object]:
    """Apply the E1/E4 post-processing correction without rerunning E1--E6."""

    root = Path(output_root).resolve()
    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    if not root.is_dir():
        raise FibrePostprocessError(f"Missing fibre E1--E6 output root: {root}")
    if (root / "evidence/FIBRE_V2_E1_E4_POSTPROCESS_CORRECTION.json").exists():
        raise FibrePostprocessError("Post-processing correction already exists")

    config_hash = sha256_file(config_path)
    declared_config_hash = config_hash_path.read_text(
        encoding="utf-8-sig"
    ).strip().lower()
    if config_hash != declared_config_hash:
        raise FibrePostprocessError("experiment_config_v2 hash mismatch")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, Mapping):
        raise FibrePostprocessError("experiment_config_v2 is not a mapping")
    guardrail = guardrail_provenance(config)

    paths = {
        "e4_runs": root / "results/e4_warmstart_runs.csv",
        "e4_summary": root / "results/e4_warmstart_summary.csv",
        "e4_table": root / "tables/table_e4_warmstart.tex",
        "e1_validation": root / "results/e1_validation_summary.json",
        "e4_validation": root / "results/e4_validation_summary.json",
        "e5_validation": root / "results/e5_validation_summary.json",
        "e6_validation": root / "results/e6_validation_summary.json",
        "e1_audit": root / "evidence/FIBRE_V2_E1_AUDIT.json",
        "e4_audit": root / "evidence/FIBRE_V2_E4_AUDIT.json",
        "e5_audit": root / "evidence/FIBRE_V2_E5_AUDIT.json",
        "e6_audit": root / "evidence/FIBRE_V2_E6_AUDIT.json",
    }
    before_hashes = {name: _verify_sidecar(path) for name, path in paths.items()}
    raw_hash = before_hashes["e4_runs"]

    run_rows = _read_csv(paths["e4_runs"])
    if not run_rows:
        raise FibrePostprocessError("E4 raw-run CSV is empty")
    summary_rows = summarise_warmstart_runs(run_rows)
    if not summary_rows:
        raise FibrePostprocessError("Corrected E4 summary is empty")
    if any(
        row.get("ci_unit") != "instance"
        or row.get("ci_method") != "instance_cluster_normal_95"
        for row in summary_rows
    ):
        raise FibrePostprocessError("E4 instance-clustered CI invariant failed")
    if any(
        not str(row.get("budget_label", "")).startswith(("p=", "2Q="))
        for row in summary_rows
    ):
        raise FibrePostprocessError("E4 concrete budget label invariant failed")

    staging = root.parent / f"{root.name}_postprocess_building"
    if staging.exists():
        raise FibrePostprocessError(f"Incomplete postprocess staging exists: {staging}")
    staging.mkdir(parents=True)
    correction_id = "fibre_e1_e4_postprocess_v2_instance_clustered_ci"
    try:
        staged_summary = staging / "results/e4_warmstart_summary.csv"
        staged_table = staging / "tables/table_e4_warmstart.tex"
        e4_summary_hash = _write_csv(staged_summary, summary_rows, SUMMARY_FIELDS)
        e4_table_hash = _write_text(staged_table, _latex_table(summary_rows))

        e1 = _read_json(paths["e1_validation"])
        _require_pass(e1, "e2_e6_may_continue", "E1")
        e1.update(guardrail)
        e1.update(
            {
                "postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
                "experimental_rows_recomputed": False,
            }
        )
        e1_path = staging / "results/e1_validation_summary.json"
        e1_hash = _write_json(e1_path, e1)

        e1_audit = _read_json(paths["e1_audit"])
        e1_audit.update(
            {
                "summary_hash": e1_hash,
                "postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
            }
        )
        _write_json(staging / "evidence/FIBRE_V2_E1_AUDIT.json", e1_audit)

        e4 = _read_json(paths["e4_validation"])
        _require_pass(e4, "e5_e6_may_continue", "E4")
        hashes = _replace_artifact_hash(
            e4.get("artifact_hashes"),
            "results/e4_warmstart_summary.csv",
            e4_summary_hash,
        )
        hashes = _replace_artifact_hash(
            hashes,
            "tables/table_e4_warmstart.tex",
            e4_table_hash,
        )
        e4.update(
            {
                "artifact_hashes": hashes,
                "summary_row_count": len(summary_rows),
                "summary_grouping_fields": [
                    "family",
                    "representation",
                    "budget_mode",
                    "budget_key",
                    "budget_value",
                    "warm_start_policy",
                    "pair_closure",
                ],
                "summary_ci_unit": "instance",
                "summary_ci_method": "instance_cluster_normal_95",
                "summary_restart_handling": "averaged_within_design",
                "summary_matched_random_handling": "averaged_within_instance",
                "summary_budget_value_semantics": {
                    "equal_layer": "p",
                    "equal_compiled_two_qubit_gates": "compiled_2q_budget",
                },
                "postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
                "source_e4_raw_runs_sha256": raw_hash,
                "experimental_rows_recomputed": False,
            }
        )
        e4_path = staging / "results/e4_validation_summary.json"
        e4_hash = _write_json(e4_path, e4)

        e4_audit = _read_json(paths["e4_audit"])
        e4_audit.update(
            {
                "summary_hash": e4_hash,
                "postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
                "source_e4_raw_runs_sha256": raw_hash,
            }
        )
        _write_json(staging / "evidence/FIBRE_V2_E4_AUDIT.json", e4_audit)

        e5 = _read_json(paths["e5_validation"])
        _require_pass(e5, "e6_may_continue", "E5")
        e5.update(
            {
                "e4_validation_summary_hash": e4_hash,
                "upstream_postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
            }
        )
        e5_path = staging / "results/e5_validation_summary.json"
        e5_hash = _write_json(e5_path, e5)
        e5_audit = _read_json(paths["e5_audit"])
        e5_audit.update(
            {
                "summary_hash": e5_hash,
                "upstream_postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
            }
        )
        _write_json(staging / "evidence/FIBRE_V2_E5_AUDIT.json", e5_audit)

        e6 = _read_json(paths["e6_validation"])
        _require_pass(e6, "final_result_pack_may_be_built", "E6")
        e6.update(
            {
                "e5_validation_summary_hash": e5_hash,
                "upstream_postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
            }
        )
        e6_path = staging / "results/e6_validation_summary.json"
        e6_hash = _write_json(e6_path, e6)
        e6_audit = _read_json(paths["e6_audit"])
        e6_audit.update(
            {
                "summary_hash": e6_hash,
                "upstream_postprocess_correction": correction_id,
                "postprocess_code_commit": code_commit,
            }
        )
        _write_json(staging / "evidence/FIBRE_V2_E6_AUDIT.json", e6_audit)

        correction = {
            "schema_version": "fibre_e1_e4_postprocess_correction_v2",
            "status": "pass",
            "correction_id": correction_id,
            "config_hash": config_hash,
            "code_commit": code_commit,
            "raw_e4_run_rows_recomputed": False,
            "e1_e6_experiments_rerun": False,
            "source_e4_raw_runs_sha256": raw_hash,
            "source_e4_raw_runs_sha256_after": sha256_file(paths["e4_runs"]),
            "source_e4_raw_runs_unchanged": sha256_file(paths["e4_runs"]) == raw_hash,
            "corrected_e4_summary_row_count": len(summary_rows),
            "summary_ci_unit": "instance",
            "summary_ci_method": "instance_cluster_normal_95",
            "summary_grouping_fields": e4["summary_grouping_fields"],
            "e1_guardrail": guardrail,
            "before_hashes": before_hashes,
            "after_step_summary_hashes": {
                "e1": e1_hash,
                "e4": e4_hash,
                "e5": e5_hash,
                "e6": e6_hash,
            },
            "corrected_artifact_hashes": {
                "results/e4_warmstart_summary.csv": e4_summary_hash,
                "tables/table_e4_warmstart.tex": e4_table_hash,
            },
            "final_result_pack_rebuild_required": True,
        }
        if correction["source_e4_raw_runs_unchanged"] is not True:
            raise FibrePostprocessError("E4 raw-run CSV changed during postprocess")
        correction_path = (
            staging / "evidence/FIBRE_V2_E1_E4_POSTPROCESS_CORRECTION.json"
        )
        _write_json(correction_path, correction)

        staged_files = sorted(path for path in staging.rglob("*") if path.is_file())
        for source in staged_files:
            relative = source.relative_to(staging)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        for directory in sorted(
            (path for path in staging.rglob("*") if path.is_dir()),
            reverse=True,
        ):
            directory.rmdir()
        staging.rmdir()
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    if sha256_file(paths["e4_runs"]) != raw_hash:
        raise FibrePostprocessError("E4 raw-run CSV changed after postprocess")
    return correction
