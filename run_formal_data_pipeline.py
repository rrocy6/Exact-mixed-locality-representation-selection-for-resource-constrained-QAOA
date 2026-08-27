from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from urss_pipeline.formal_data import run_formal_data_pipeline


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
            "Formal Step 2 must run from a clean committed source tree"
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
        description="Generate and freeze formal URSS Step 2 data/manifests"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--smoke-config", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assumptions", required=True)
    parser.add_argument("--run-commands", required=True)
    arguments = parser.parse_args()
    audit = run_formal_data_pipeline(
        config_path=arguments.config,
        config_hash_path=arguments.config_hash,
        plan_path=arguments.plan,
        smoke_config_path=arguments.smoke_config,
        schema_path=arguments.schema,
        output_directory=arguments.output,
        code_commit=_clean_code_commit(),
        progress=lambda message: print(message, flush=True),
        assumptions_path=arguments.assumptions,
        run_commands_path=arguments.run_commands,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
