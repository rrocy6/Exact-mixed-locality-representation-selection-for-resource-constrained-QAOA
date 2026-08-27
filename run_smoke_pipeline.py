"""Command-line entry point for the deterministic URSS smoke batch."""

from __future__ import annotations

import argparse
import json

from urss_pipeline.smoke import run_smoke_batch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and validate the non-formal URSS smoke batch."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    audit = run_smoke_batch(
        config_path=arguments.config,
        schema_path=arguments.schema,
        output_directory=arguments.output,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
