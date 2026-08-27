"""Validation helpers for the versioned experiment configuration."""

from __future__ import annotations

import hashlib
from pathlib import Path


class ExperimentConfigError(ValueError):
    pass


def validate_experiment_config(path: str | Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError(
            "PyYAML is required; install requirements-smoke.txt"
        ) from error

    path = Path(path)
    content = path.read_bytes()
    config = yaml.safe_load(content)
    if not isinstance(config, dict):
        raise ExperimentConfigError("Experiment config must be a mapping")
    for key in ("config_version", "config_id", "status", "freeze_gate"):
        if key not in config:
            raise ExperimentConfigError(f"Missing required config field: {key}")
    freeze_gate = config["freeze_gate"]
    if not isinstance(freeze_gate, dict):
        raise ExperimentConfigError("freeze_gate must be a mapping")
    blocked = freeze_gate.get("blocked")
    blockers = freeze_gate.get("required_before_freeze")
    if not isinstance(blocked, bool):
        raise ExperimentConfigError("freeze_gate.blocked must be Boolean")
    if not isinstance(blockers, list) or not all(
        isinstance(item, str) and item for item in blockers
    ):
        raise ExperimentConfigError(
            "freeze_gate.required_before_freeze must be a list of names"
        )
    status = str(config["status"])
    if "frozen" in status.lower() and (blocked or blockers):
        raise ExperimentConfigError(
            "A frozen config cannot retain an active freeze gate or blockers"
        )
    if not blocked and blockers:
        raise ExperimentConfigError(
            "freeze_gate.blocked=false conflicts with remaining blockers"
        )
    return {
        "status": "valid",
        "config_id": config["config_id"],
        "config_version": config["config_version"],
        "declared_status": status,
        "freeze_blocked": blocked,
        "remaining_blocker_count": len(blockers),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
