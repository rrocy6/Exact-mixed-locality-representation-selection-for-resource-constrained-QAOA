"""Command-line entry point for the frozen fibre-aware selector v2."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from urss_pipeline.fibre_validation import run_fibre_selector_v2_pipeline


def _require_clean_commit() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        raise RuntimeError(
            "Fibre selector v2 must run from a clean committed implementation"
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze and validate the fibre-aware representation selector v2"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    _require_clean_commit()
    summary = run_fibre_selector_v2_pipeline(
        config_path=Path(arguments.config),
        config_hash_path=Path(arguments.config_hash),
        data_directory=Path(arguments.data),
        output_directory=Path(arguments.output),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
