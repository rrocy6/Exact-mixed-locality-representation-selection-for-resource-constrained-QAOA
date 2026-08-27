"""Validate and summarize the draft/frozen experiment configuration."""

from __future__ import annotations

import argparse
import json

from urss_pipeline.configuration import validate_experiment_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args()
    report = validate_experiment_config(arguments.config)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
