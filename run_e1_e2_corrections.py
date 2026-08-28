"""Command-line entry point for the additive E1/E2 review corrections."""

from __future__ import annotations

import argparse
import json
import subprocess

from urss_pipeline.e1_e2_corrections import run_e1_e2_corrections


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--e3-source", default="urss_pipeline/e3_qaoa.py")
    args = parser.parse_args()
    summary = run_e1_e2_corrections(
        config_path=args.config,
        config_hash_path=args.config_hash,
        data_directory=args.data,
        results_directory=args.results,
        output_directory=args.output,
        code_commit=_commit(),
        e3_source_path=args.e3_source,
        progress=print,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"E1/E2 CORRECTION GATE: {summary['status']}")
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
