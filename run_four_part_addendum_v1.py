"""Command-line driver for the append-only four-part URSS addendum."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from urss_pipeline.four_part_addendum import (
    FourPartAddendumError,
    build_result_pack,
    load_addendum_config,
    prepare_output_provenance,
    run_certification,
    run_selector_ablation,
    run_strong_bias,
    run_topologies,
    verify_parent_config,
)


def _commit(repo: Path, supplied: str | None) -> str:
    if supplied:
        return supplied
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True,
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise FourPartAddendumError(
            "Git commit unavailable; pass --code-commit with the committed update hash"
        )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one append-only four-part addendum phase"
    )
    parser.add_argument(
        "--phase",
        required=True,
        choices=("certification", "topologies", "selector-ablation", "strong-bias", "build"),
    )
    parser.add_argument(
        "--config", type=Path, default=Path("configs/four_part_addendum_v1.json")
    )
    parser.add_argument("--output-root", type=Path, default=Path("four_part_addendum_v1"))
    parser.add_argument("--code-commit")
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()

    repo = Path.cwd().resolve()
    config_path = (repo / arguments.config).resolve()
    output_root = (repo / arguments.output_root).resolve()
    config, config_hash = load_addendum_config(config_path)
    parent_spec = config["parent_config"]
    parent_path = repo / str(parent_spec["path"])
    parent = verify_parent_config(
        parent_path,
        parent_path.with_suffix(".sha256"),
        str(parent_spec["sha256"]),
    )
    code_commit = _commit(repo, arguments.code_commit)
    if not code_commit.startswith(str(config["parent_commit"])):
        print(
            "NOTICE: running from an additive implementation commit whose parent "
            f"checkpoint is declared as {config['parent_commit']}"
        )

    prepare_output_provenance(
        output_root=output_root,
        config_path=config_path,
        config_hash=config_hash,
        parent_config_path=parent_path,
        code_commit=code_commit,
        parent_commit=str(config["parent_commit"]),
    )

    common = {
        "repo": repo,
        "output_root": output_root,
        "config": config,
        "config_hash": config_hash,
        "parent": parent,
        "code_commit": code_commit,
        "resume": arguments.resume,
    }
    if arguments.phase == "certification":
        run_certification(**common)
    elif arguments.phase == "topologies":
        run_topologies(**common)
    elif arguments.phase == "selector-ablation":
        run_selector_ablation(**common)
    elif arguments.phase == "strong-bias":
        run_strong_bias(**common)
    else:
        zip_path, sidecar = build_result_pack(
            output_root=output_root, config_hash=config_hash
        )
        print(f"FINAL ZIP: {zip_path}")
        print(f"SHA256 SIDECAR: {sidecar}")
    print(f"FOUR-PART ADDENDUM {arguments.phase.upper()}: PASS")


if __name__ == "__main__":
    main()
