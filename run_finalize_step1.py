from __future__ import annotations

import argparse
import json

from urss_pipeline.step1_freeze import freeze_step1_config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze the formal URSS Step 1 config from audited pilot evidence"
    )
    parser.add_argument("--draft-config", required=True)
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--reference-pilot-config", required=True)
    parser.add_argument("--pilot-output", required=True)
    parser.add_argument("--formal-config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--assumptions", required=True)
    parser.add_argument("--run-commands", required=True)
    arguments = parser.parse_args()
    audit = freeze_step1_config(
        draft_config_path=arguments.draft_config,
        decisions_path=arguments.decisions,
        reference_pilot_config_path=arguments.reference_pilot_config,
        pilot_output_directory=arguments.pilot_output,
        formal_config_path=arguments.formal_config,
        output_directory=arguments.output,
        assumptions_path=arguments.assumptions,
        run_commands_path=arguments.run_commands,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
