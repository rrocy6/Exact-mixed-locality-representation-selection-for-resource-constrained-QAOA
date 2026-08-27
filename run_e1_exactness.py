from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from urss_pipeline.e1_exactness import run_e1_exactness_pipeline


def _clean_code_commit() -> str:
    root = Path.cwd()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    if status.strip():
        raise RuntimeError(
            "Formal E1 must run from the clean committed Step 3 implementation"
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run formal Step 3 / E1 exactness and penalty tightness"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--assumptions", required=True)
    parser.add_argument("--run-commands", required=True)
    arguments = parser.parse_args()
    summary = run_e1_exactness_pipeline(
        config_path=arguments.config,
        config_hash_path=arguments.config_hash,
        data_directory=arguments.data,
        results_directory=arguments.results,
        tables_directory=arguments.tables,
        code_commit=_clean_code_commit(),
        assumptions_path=arguments.assumptions,
        run_commands_path=arguments.run_commands,
        progress=lambda message: print(message, flush=True),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
