from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from urss_pipeline.e6_noise import run_e6_noise_pipeline


def _clean_code_commit() -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    if status.strip():
        raise RuntimeError(
            "Formal E6 must run from the clean committed Step 8 implementation"
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path.cwd(),
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run formal Step 8 / E6 limited-noise study"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--protocol-config", required=True)
    parser.add_argument("--protocol-config-hash", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--figures", required=True)
    parser.add_argument("--assumptions", required=True)
    parser.add_argument("--run-commands", required=True)
    arguments = parser.parse_args()
    summary = run_e6_noise_pipeline(
        config_path=arguments.config,
        config_hash_path=arguments.config_hash,
        protocol_config_path=arguments.protocol_config,
        protocol_config_hash_path=arguments.protocol_config_hash,
        data_directory=arguments.data,
        results_directory=arguments.results,
        tables_directory=arguments.tables,
        figures_directory=arguments.figures,
        code_commit=_clean_code_commit(),
        assumptions_path=arguments.assumptions,
        run_commands_path=arguments.run_commands,
        progress=print,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
