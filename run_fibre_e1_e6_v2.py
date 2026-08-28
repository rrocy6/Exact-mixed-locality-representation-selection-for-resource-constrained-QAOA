from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import zipfile
from collections import Counter
from pathlib import Path

from urss_pipeline.fibre_rerun import (
    FibreDesignBundle,
    FibreRerunError,
    rerun_overrides,
    sha256_file,
)


STEPS = ("e1", "e2", "e3", "e4", "e5", "e6")
SUMMARY_FILES = {
    "e1": "e1_validation_summary.json",
    "e2": "e2_validation_summary.json",
    "e3": "e3_validation_summary.json",
    "e4": "e4_validation_summary.json",
    "e5": "e5_validation_summary.json",
    "e6": "e6_validation_summary.json",
}
COUNT_FILES = {
    "e1": "e1_exactness.csv",
    "e2": "e2_logical_resources.csv",
    "e3": "e3_budget_plan.csv",
    "e4": "e4_warmstart_runs.csv",
    "e5": "e5_regime_instance_level.csv",
    "e6": "e6_noise_runs.csv",
}
CONTINUATION_FIELDS = {
    "e1": "e2_e6_may_continue",
    "e2": "e3_e6_may_continue",
    "e3": "e4_e6_may_continue",
    "e4": "e5_e6_may_continue",
    "e5": "e6_may_continue",
    "e6": "final_result_pack_may_be_built",
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_hash(path: Path) -> str:
    digest = sha256_file(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _require_clean_implementation(output_root: Path) -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        check=True,
        text=True,
        capture_output=True,
    )
    allowed_prefix = output_root.as_posix().rstrip("/") + "/"
    allowed_zip = f"URSS_{output_root.name.upper()}_RESULT_PACK"
    unexpected: list[str] = []
    for line in result.stdout.splitlines():
        relative = line[3:].replace("\\", "/")
        if not (relative.startswith(allowed_prefix) or relative.startswith(allowed_zip)):
            unexpected.append(line)
    if unexpected:
        raise FibreRerunError(
            "Implementation worktree is not clean; commit the update before rerun:\n"
            + "\n".join(unexpected)
        )


def _initialise_output(
    output_root: Path,
    *,
    selector_directory: Path,
    parent_config_path: Path,
    parent_config_hash_path: Path,
) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    assumptions = output_root / "assumptions_and_decisions_v2.md"
    commands = output_root / "RUN_COMMANDS_FIBRE_E1_E6_V2.md"
    if not assumptions.exists():
        assumptions.write_text(
            "# Fibre-aware selector v2 E1--E6 decisions\n\n"
            "- The v1 raw, canonical, metadata, split, ground-truth, Native, and Full protocols remain frozen.\n"
            "- Selected and Matched-random actions come only from the verified `fibre_selector_v2` bundle.\n"
            "- Formal outputs are additive under `fibre_e1_e6_v2`; v1 results are never overwritten.\n"
            "- Native and Full are recomputed as invariant controls under unchanged depth, budget, compiler, QAOA, warm-start, and noise settings.\n",
            encoding="utf-8",
            newline="\n",
        )
    if not commands.exists():
        command_lines = [
            "# Fibre-aware selector v2 E1--E6 commands",
            "",
            "Run only from the clean committed implementation checkpoint:",
            "",
        ]
        for step in STEPS:
            command_lines.extend(
                (
                    "```powershell",
                    f'python ".\\run_fibre_e1_e6_v2.py" --step {step}',
                    "```",
                    "",
                )
            )
        command_lines.extend(
            (
                "After E6 passes:",
                "",
                "```powershell",
                'python ".\\run_fibre_e1_e6_v2.py" --step final',
                "```",
                "",
            )
        )
        commands.write_text(
            "\n".join(command_lines),
            encoding="utf-8",
            newline="\n",
        )

    frozen_copy = output_root / "frozen_selector_v2"
    if not frozen_copy.exists():
        shutil.copytree(selector_directory, frozen_copy)
    provenance = output_root / "provenance"
    provenance.mkdir(exist_ok=True)
    for source in (parent_config_path, parent_config_hash_path):
        target = provenance / source.name
        if not target.exists():
            shutil.copy2(source, target)
    return assumptions, commands


def _read_representation_counts(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        return dict(sorted(Counter(row.get("representation", "") for row in rows).items()))


def _stamp_step(
    step: str,
    *,
    output_root: Path,
    bundle: FibreDesignBundle,
    parent_config_hash: str,
    code_commit: str,
) -> dict[str, object]:
    summary_path = output_root / "results" / SUMMARY_FILES[step]
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary.update(
        {
            "rerun_schema_version": "fibre_selected_matched_e1_e6_v2",
            "rerun_branch_scope": ["selective", "matched_random_selective"],
            "parent_data_config_hash": parent_config_hash,
            "fibre_selector_config_hash": bundle.config_hash,
            "fibre_selector_audit_hash": bundle.audit_hash,
            "native_full_policy": "recomputed_as_invariant_controls_under_unchanged_protocol",
            "v1_results_overwritten": False,
        }
    )
    _write_json(summary_path, summary)
    summary_hash = _write_hash(summary_path)
    counts = _read_representation_counts(output_root / "results" / COUNT_FILES[step])
    audit = {
        "schema_version": "fibre_v2_step_audit",
        "step": step,
        "status": summary.get("status"),
        "continuation_field": CONTINUATION_FIELDS[step],
        "continuation_allowed": summary.get(CONTINUATION_FIELDS[step]),
        "config_hash": bundle.config_hash,
        "parent_data_config_hash": parent_config_hash,
        "fibre_selector_audit_hash": bundle.audit_hash,
        "summary_hash": summary_hash,
        "representation_row_counts": counts,
        "code_commit": code_commit,
        "v1_results_overwritten": False,
    }
    audit_path = output_root / "evidence" / f"FIBRE_V2_{step.upper()}_AUDIT.json"
    _write_json(audit_path, audit)
    _write_hash(audit_path)
    if not (
        summary.get("status") == "pass"
        and summary.get(CONTINUATION_FIELDS[step]) is True
    ):
        raise FibreRerunError(f"{step.upper()} v2 continuation gate failed")
    return summary


def run_step(
    step: str,
    *,
    bundle: FibreDesignBundle,
    parent_config_path: Path,
    parent_config_hash_path: Path,
    data_directory: Path,
    output_root: Path,
    assumptions_path: Path,
    run_commands_path: Path,
    analysis_config_path: Path,
    analysis_config_hash_path: Path,
    noise_config_path: Path,
    noise_config_hash_path: Path,
    code_commit: str,
) -> dict[str, object]:
    from urss_pipeline.e1_exactness import run_e1_exactness_pipeline
    from urss_pipeline.e2_resources import run_e2_resources_pipeline
    from urss_pipeline.e3_qaoa import run_e3_qaoa_pipeline
    from urss_pipeline.e4_warmstart import run_e4_warmstart_pipeline
    from urss_pipeline.e5_regime import run_e5_regime_pipeline
    from urss_pipeline.e6_noise import run_e6_noise_pipeline

    results = output_root / "results"
    tables = output_root / "tables"
    figures = output_root / "figures"
    common = {
        "config_path": bundle.config_path,
        "config_hash_path": bundle.config_hash_path,
        "data_directory": data_directory,
        "results_directory": results,
        "tables_directory": tables,
        "code_commit": code_commit,
        # The legacy formal functions append v1 prose.  The v2 orchestrator
        # owns separate, accurate decision and command records instead.
        "assumptions_path": None,
        "run_commands_path": None,
    }
    progress = lambda message: print(message, flush=True)
    with rerun_overrides(
        step=step,
        bundle=bundle,
        parent_config_path=parent_config_path,
        parent_config_hash_path=parent_config_hash_path,
    ):
        if step == "e1":
            run_e1_exactness_pipeline(**common, progress=progress)
        elif step == "e2":
            run_e2_resources_pipeline(
                **common, figures_directory=figures, progress=progress
            )
            selector_source = bundle.directory / "oracle_selector_validation_v2.csv"
            selector_target = results / "selector_validation_fibre_v2.csv"
            shutil.copy2(selector_source, selector_target)
            _write_hash(selector_target)
        elif step == "e3":
            run_e3_qaoa_pipeline(
                **common, figures_directory=figures, progress=progress
            )
        elif step == "e4":
            run_e4_warmstart_pipeline(
                **common, figures_directory=figures, progress=progress
            )
        elif step == "e5":
            run_e5_regime_pipeline(
                **common,
                figures_directory=figures,
                analysis_config_path=analysis_config_path,
                analysis_config_hash_path=analysis_config_hash_path,
            )
        elif step == "e6":
            run_e6_noise_pipeline(
                **common,
                figures_directory=figures,
                protocol_config_path=noise_config_path,
                protocol_config_hash_path=noise_config_hash_path,
                progress=progress,
            )
        else:
            raise FibreRerunError(f"Unknown rerun step: {step}")
    parent_hash = parent_config_hash_path.read_text(encoding="utf-8-sig").strip()
    return _stamp_step(
        step,
        output_root=output_root,
        bundle=bundle,
        parent_config_hash=parent_hash,
        code_commit=code_commit,
    )


def _build_result_pack(output_root: Path, bundle: FibreDesignBundle, code_commit: str) -> dict[str, object]:
    step_hashes: dict[str, str] = {}
    for step in STEPS:
        summary_path = output_root / "results" / SUMMARY_FILES[step]
        sidecar = summary_path.with_suffix(".sha256")
        if not summary_path.is_file() or not sidecar.is_file():
            raise FibreRerunError(f"Missing completed {step.upper()} summary")
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        if not (
            summary.get("status") == "pass"
            and summary.get(CONTINUATION_FIELDS[step]) is True
        ):
            raise FibreRerunError(f"{step.upper()} completion gate is not pass")
        actual = sha256_file(summary_path)
        if actual != sidecar.read_text(encoding="utf-8-sig").strip():
            raise FibreRerunError(f"{step.upper()} summary sidecar mismatch")
        step_hashes[step] = actual

    audit = {
        "schema_version": "fibre_selected_matched_e1_e6_v2_completion",
        "status": "pass",
        "e1_e6_rerun_completed": True,
        "config_hash": bundle.config_hash,
        "parent_data_config_hash": (output_root / "provenance/experiment_config_v1.sha256").read_text(encoding="utf-8-sig").strip(),
        "fibre_selector_audit_hash": bundle.audit_hash,
        "source_manifest_hashes": bundle.manifest_hashes,
        "rerun_branch_scope": ["selective", "matched_random_selective"],
        "native_full_policy": "recomputed_as_invariant_controls_under_unchanged_protocol",
        "raw_canonical_ground_truth_rebuilt": False,
        "v1_results_overwritten": False,
        "step_summary_hashes": step_hashes,
        "code_commit": code_commit,
        "final_result_pack_may_be_built": True,
    }
    audit_path = output_root / "FIBRE_E1_E6_V2_COMPLETION_AUDIT.json"
    _write_json(audit_path, audit)
    _write_hash(audit_path)

    package_manifest = output_root / "PACKAGE_SHA256_MANIFEST.csv"
    package_sidecar = package_manifest.with_suffix(".sha256")
    files = sorted(
        path for path in output_root.rglob("*")
        if path.is_file() and path not in {package_manifest, package_sidecar}
    )
    with package_manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("path", "sha256", "size_bytes"))
        for path in files:
            writer.writerow((path.relative_to(output_root).as_posix(), sha256_file(path), path.stat().st_size))
    _write_hash(package_manifest)

    zip_path = output_root.parent / f"URSS_{output_root.name.upper()}_RESULT_PACK.zip"
    if zip_path.exists():
        raise FibreRerunError(f"Result pack already exists; refusing overwrite: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in output_root.rglob("*") if item.is_file()):
            info = zipfile.ZipInfo(
                f"{output_root.name}/{path.relative_to(output_root).as_posix()}",
                date_time=(2026, 8, 28, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    zip_hash = sha256_file(zip_path)
    zip_path.with_suffix(".zip.sha256").write_text(zip_hash + "\n", encoding="utf-8", newline="\n")
    audit["result_pack"] = zip_path.name
    audit["result_pack_sha256"] = zip_hash
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rerun E1--E6 with the frozen fibre-aware Selected/Matched-random designs"
    )
    parser.add_argument("--step", choices=(*STEPS, "all", "final"), required=True)
    parser.add_argument("--config", default="configs/experiment_config_v2.yaml")
    parser.add_argument("--config-hash", default="configs/experiment_config_v2.sha256")
    parser.add_argument("--parent-config", default="configs/experiment_config_v1.yaml")
    parser.add_argument("--parent-config-hash", default="configs/experiment_config_v1.sha256")
    parser.add_argument("--selector", default="fibre_selector_v2")
    parser.add_argument("--data", default="data")
    parser.add_argument("--output", default="fibre_e1_e6_v2")
    parser.add_argument("--e5-analysis", default="configs/e5_analysis_v1.json")
    parser.add_argument("--e5-analysis-hash", default="configs/e5_analysis_v1.sha256")
    parser.add_argument("--e6-protocol", default="configs/e6_noise_v1.json")
    parser.add_argument("--e6-protocol-hash", default="configs/e6_noise_v1.sha256")
    args = parser.parse_args()

    output_root = Path(args.output)
    _require_clean_implementation(output_root)
    bundle = FibreDesignBundle(
        directory=args.selector,
        config_path=args.config,
        config_hash_path=args.config_hash,
        data_directory=args.data,
    )
    assumptions, commands = _initialise_output(
        output_root,
        selector_directory=Path(args.selector),
        parent_config_path=Path(args.parent_config),
        parent_config_hash_path=Path(args.parent_config_hash),
    )
    code_commit = _git_commit()
    if args.step == "final":
        result = _build_result_pack(output_root, bundle, code_commit)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    requested = STEPS if args.step == "all" else (args.step,)
    for step in requested:
        print(f"FIBRE V2 {step.upper()}: START", flush=True)
        summary = run_step(
            step,
            bundle=bundle,
            parent_config_path=Path(args.parent_config),
            parent_config_hash_path=Path(args.parent_config_hash),
            data_directory=Path(args.data),
            output_root=output_root,
            assumptions_path=assumptions,
            run_commands_path=commands,
            analysis_config_path=Path(args.e5_analysis),
            analysis_config_hash_path=Path(args.e5_analysis_hash),
            noise_config_path=Path(args.e6_protocol),
            noise_config_hash_path=Path(args.e6_protocol_hash),
            code_commit=code_commit,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(f"FIBRE V2 {step.upper()} GATE: PASS", flush=True)
    if args.step == "all":
        result = _build_result_pack(output_root, bundle, code_commit)
        print(json.dumps(result, indent=2, sort_keys=True))
        print("FIBRE V2 E1-E6 COMPLETION GATE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
