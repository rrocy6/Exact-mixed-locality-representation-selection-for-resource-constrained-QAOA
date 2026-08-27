from __future__ import annotations

import argparse
import json

from urss_pipeline.reference_pilot import run_reference_pilot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the non-formal URSS reference compiler pilot"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    audit = run_reference_pilot(
        config_path=arguments.config,
        output_directory=arguments.output,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
