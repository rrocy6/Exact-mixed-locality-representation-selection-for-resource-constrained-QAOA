from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from urss_pipeline.fibre_postprocess_v2 import (
    FibrePostprocessError,
    repair_fibre_e1_e4_postprocess,
)


def _require_clean_worktree() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    if status.strip():
        raise FibrePostprocessError(
            "Worktree is not clean; commit the implementation before postprocessing"
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild only the E4 summary/table and correct E1 guardrail provenance; "
            "never rerun E1--E6 experiments"
        )
    )
    parser.add_argument("--output", default="fibre_e1_e6_v2")
    parser.add_argument("--config", default="configs/experiment_config_v2.yaml")
    parser.add_argument(
        "--config-hash", default="configs/experiment_config_v2.sha256"
    )
    args = parser.parse_args()
    commit = _require_clean_worktree()
    result = repair_fibre_e1_e4_postprocess(
        output_root=Path(args.output),
        config_path=Path(args.config),
        config_hash_path=Path(args.config_hash),
        code_commit=commit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    print("FIBRE V2 E1/E4 POSTPROCESS GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
