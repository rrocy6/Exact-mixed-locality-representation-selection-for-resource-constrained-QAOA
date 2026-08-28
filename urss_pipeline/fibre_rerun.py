"""Additive E1--E6 rerun support for the frozen fibre-aware selector v2.

The v1 data freeze remains authoritative.  This module verifies the v2 design
bundle and injects only its precomputed Selected and Matched-random action
vectors into the already-tested formal E1--E6 pipelines.  Outputs are written
to a separate project root by :mod:`run_fibre_e1_e6_v2`.
"""

from __future__ import annotations

import csv
import hashlib
import json
from contextlib import ExitStack, contextmanager
from fractions import Fraction
from pathlib import Path
from typing import Iterator, Mapping, Sequence
from unittest.mock import patch

from .polynomial import Support, canonicalize, cubic_supports


class FibreRerunError(RuntimeError):
    """A frozen selector-v2 input or rerun invariant failed."""


TIER_MANIFESTS = {
    "oracle": "oracle_v1.csv",
    "qaoa": "qaoa_v1.csv",
    "compilation": "compilation_v1.csv",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sidecar(path: str | Path) -> str:
    path = Path(path)
    sidecar = path.with_suffix(".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise FibreRerunError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = sha256_file(path)
    declared = sidecar.read_text(encoding="utf-8-sig").strip().lower()
    if actual != declared:
        raise FibreRerunError(f"Frozen hash mismatch: {path}")
    return actual


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise FibreRerunError(f"Expected JSON object: {path}")
    return value


def deserialize_actions(values: Sequence[object]) -> tuple[Support | None, ...]:
    actions: list[Support | None] = []
    for value in values:
        if value is None:
            actions.append(None)
            continue
        if not isinstance(value, list) or len(value) != 2:
            raise FibreRerunError(f"Invalid representation action: {value!r}")
        pair = tuple(sorted(int(item) for item in value))
        if pair[0] == pair[1]:
            raise FibreRerunError(f"Invalid repeated-variable action: {value!r}")
        actions.append(pair)
    return tuple(actions)


def polynomial_key(polynomial: Mapping[Support, object]) -> tuple[tuple[Support, str], ...]:
    canonical = canonicalize(polynomial)
    return tuple(
        (tuple(support), str(Fraction(coefficient)))
        for support, coefficient in sorted(canonical.items())
    )


class FibreDesignBundle:
    """Verified, indexed view of ``fibre_selector_v2``."""

    def __init__(
        self,
        *,
        directory: str | Path,
        config_path: str | Path,
        config_hash_path: str | Path,
        data_directory: str | Path,
    ) -> None:
        self.directory = Path(directory)
        self.config_path = Path(config_path)
        self.config_hash_path = Path(config_hash_path)
        self.data_directory = Path(data_directory)
        if not self.directory.is_dir():
            raise FibreRerunError(f"Missing selector-v2 directory: {self.directory}")

        self.config_hash = sha256_file(self.config_path)
        declared_config_hash = self.config_hash_path.read_text(
            encoding="utf-8-sig"
        ).strip().lower()
        if self.config_hash != declared_config_hash:
            raise FibreRerunError("experiment_config_v2 hash mismatch")

        audit_path = self.directory / "fibre_selector_v2_audit.json"
        self.audit_hash = verify_sidecar(audit_path)
        self.audit = _read_json(audit_path)
        if not (
            self.audit.get("status") == "pass"
            and self.audit.get("calibration_status") == "pass"
            and self.audit.get("e1_e6_rerun_completed") is False
            and self.audit.get("selected_matched_random_require_e1_e6_rerun") is True
            and self.audit.get("native_full_protocols_changed") is False
            and int(self.audit.get("closed_form_enumeration_failure_count", -1)) == 0
            and str(self.audit.get("config_hash")) == self.config_hash
        ):
            raise FibreRerunError("Selector-v2 audit does not permit E1--E6 rerun")

        self._verify_package_manifest()
        self.records: dict[str, dict[str, dict[str, object]]] = {}
        self.manifest_hashes: dict[str, str] = {}
        self._polynomial_records: dict[
            str, dict[tuple[tuple[Support, str], ...], dict[str, object]]
        ] = {}
        for tier, manifest_name in TIER_MANIFESTS.items():
            self._load_tier(tier, manifest_name)

    def _verify_package_manifest(self) -> None:
        manifest_path = self.directory / "PACKAGE_SHA256_MANIFEST.csv"
        verify_sidecar(manifest_path)
        for row in _read_csv(manifest_path):
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise FibreRerunError(f"Unsafe selector package path: {relative}")
            path = self.directory / relative
            if not path.is_file():
                raise FibreRerunError(f"Missing selector package artifact: {path}")
            if sha256_file(path) != row["sha256"].lower():
                raise FibreRerunError(f"Selector package artifact changed: {path}")
            if path.stat().st_size != int(row["size_bytes"]):
                raise FibreRerunError(f"Selector package size changed: {path}")

    def _load_tier(self, tier: str, manifest_name: str) -> None:
        manifest_path = self.data_directory / "manifests" / manifest_name
        manifest_hash = verify_sidecar(manifest_path)
        self.manifest_hashes[tier] = manifest_hash
        design_path = self.directory / f"{tier}_representation_designs_v2.json"
        verify_sidecar(design_path)
        payload = _read_json(design_path)
        records = payload.get("records")
        if not isinstance(records, list):
            raise FibreRerunError(f"Missing {tier} design records")
        if not (
            payload.get("schema_version") == "fibre_aware_representation_designs_v2"
            and payload.get("tier") == tier
            and payload.get("config_hash") == self.config_hash
            and payload.get("source_instance_manifest_hash") == manifest_hash
            and payload.get("native_and_full_protocols_reused_from_v1") is True
        ):
            raise FibreRerunError(f"Frozen {tier} design provenance mismatch")

        manifest_rows = {row["instance_id"]: row for row in _read_csv(manifest_path)}
        indexed: dict[str, dict[str, object]] = {}
        keys: dict[tuple[tuple[Support, str], ...], dict[str, object]] = {}
        from .e1_exactness import _canonical_polynomial

        for raw in records:
            if not isinstance(raw, dict):
                raise FibreRerunError(f"Invalid {tier} design record")
            instance_id = str(raw.get("instance_id", ""))
            manifest_row = manifest_rows.get(instance_id)
            if manifest_row is None or instance_id in indexed:
                raise FibreRerunError(f"{tier} design/manifest alignment failed: {instance_id}")
            if not (
                raw.get("tier") == tier
                and raw.get("family") == manifest_row["family"]
                and raw.get("split") == manifest_row["split"]
                and int(raw.get("n_original", -1)) == int(manifest_row["n"])
                and raw.get("canonical_sha256") == manifest_row["canonical_sha256"]
            ):
                raise FibreRerunError(f"{tier} design metadata mismatch: {instance_id}")
            selected = raw.get("selected")
            matched = raw.get("matched_random")
            if not isinstance(selected, dict) or not isinstance(matched, list):
                raise FibreRerunError(f"Incomplete {tier} design: {instance_id}")
            selected_actions = deserialize_actions(selected.get("actions", []))
            if len(matched) != 5:
                raise FibreRerunError(f"Wrong matched-random count: {instance_id}")
            if any(
                not isinstance(item, dict)
                or not item.get("matches_selected_auxiliary_count")
                or len(deserialize_actions(item.get("actions", []))) != len(selected_actions)
                for item in matched
            ):
                raise FibreRerunError(f"Invalid matched-random bundle: {instance_id}")
            canonical_path = self.data_directory / manifest_row["canonical_file"]
            if sha256_file(canonical_path) != manifest_row["canonical_sha256"]:
                raise FibreRerunError(f"Canonical hash mismatch: {instance_id}")
            _, polynomial = _canonical_polynomial(canonical_path)
            cubics = tuple(sorted(cubic_supports(polynomial)))
            declared_cubics = tuple(tuple(item) for item in raw.get("cubic_supports", []))
            if cubics != declared_cubics or len(selected_actions) != len(cubics):
                raise FibreRerunError(f"Cubic/action alignment failed: {instance_id}")
            key = polynomial_key(polynomial)
            if key in keys:
                raise FibreRerunError(f"Duplicate canonical polynomial in {tier}: {instance_id}")
            indexed[instance_id] = raw
            keys[key] = raw
        if set(indexed) != set(manifest_rows):
            raise FibreRerunError(f"{tier} design coverage differs from frozen manifest")
        self.records[tier] = indexed
        self._polynomial_records[tier] = keys

    def record(self, tier: str, instance_id: str) -> dict[str, object]:
        try:
            return self.records[tier][instance_id]
        except KeyError as error:
            raise FibreRerunError(f"Missing {tier} v2 design: {instance_id}") from error

    def record_for_polynomial(
        self, tier: str, polynomial: Mapping[Support, object]
    ) -> dict[str, object]:
        try:
            return self._polynomial_records[tier][polynomial_key(polynomial)]
        except KeyError as error:
            raise FibreRerunError(f"No {tier} v2 design matches canonical polynomial") from error

    def selected_actions(self, record: Mapping[str, object]) -> tuple[Support | None, ...]:
        selected = record["selected"]
        if not isinstance(selected, dict):
            raise FibreRerunError("Invalid selected design")
        return deserialize_actions(selected["actions"])

    def matched_actions(
        self, record: Mapping[str, object]
    ) -> list[tuple[int, tuple[Support | None, ...]]]:
        matched = record["matched_random"]
        if not isinstance(matched, list):
            raise FibreRerunError("Invalid matched-random designs")
        return [
            (int(item["random_rep_seed"]), deserialize_actions(item["actions"]))
            for item in matched
            if isinstance(item, dict)
        ]

    def selector_validation_rows(
        self,
        *,
        config_hash: str,
        manifest_hash: str,
        code_commit: str,
    ) -> list[dict[str, object]]:
        rows = _read_csv(self.directory / "oracle_selector_validation_v2.csv")
        converted: list[dict[str, object]] = []
        for row in rows:
            selected = _selected_record_fields(self.record("oracle", row["instance_id"]))
            converted.append(
                {
                    "instance_id": row["instance_id"],
                    "family": row["family"],
                    "split": row["split"],
                    "method": row["method"],
                    "certificate_status": row["certificate_status"],
                    "selected_design_id": row["selected_design_id"],
                    "selected_n_aux": row["selected_n_aux"],
                    "selected_two_qubit_gates": row["selected_two_qubit_gates"],
                    "selected_two_qubit_depth": row["selected_two_qubit_depth"],
                    "selected_M_max": selected["maximum_penalty"],
                    "objective": row["objective"],
                    "certified_optimum_objective": row["certified_optimum_objective"],
                    "regret": row["regret"],
                    "hit_certified_design": row["hit_certified_design"] == "True",
                    "runtime_sec": row["runtime_sec"],
                    "compiler_calls": row["candidate_evaluations"],
                    "weights_tuned_on": row["weights_tuned_on"],
                    "test_retuning_used": row["test_retuning_used"] == "True",
                    "status": row["status"],
                    "config_hash": config_hash,
                    "manifest_hash": manifest_hash,
                    "code_commit": code_commit,
                }
            )
        if len(converted) != 180:
            raise FibreRerunError("Selector-v2 oracle validation must contain 180 rows")
        return converted


def _selected_record_fields(record: Mapping[str, object]) -> dict[str, object]:
    selected = record["selected"]
    if not isinstance(selected, dict):
        raise FibreRerunError("Invalid selected design record")
    return selected


def _e2_designs(bundle: FibreDesignBundle, polynomial, *, n_original, instance_id, config):
    from . import e2_resources as e2

    record = bundle.record("compilation", instance_id)
    selector = config["selector"]
    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    native_actions = (None,) * len(cubics)
    full_actions = e2._full_actions(polynomial)
    selected_actions = bundle.selected_actions(record)
    selected_record = _selected_record_fields(record)
    native = e2._evaluate_design(
        polynomial, n_original=n_original, actions=native_actions,
        selector=selector, apply_qaoa_hard_limits=False,
    )
    full = e2._evaluate_design(
        polynomial, n_original=n_original, actions=full_actions,
        selector=selector, apply_qaoa_hard_limits=False,
    )
    selected = e2._evaluate_design(
        polynomial, n_original=n_original, actions=selected_actions,
        selector=selector, apply_qaoa_hard_limits=False,
    )
    designs = [
        ("all_native", None, native, "endpoint_not_searched", 0),
        ("fully_quadratized", None, full, "deterministic_minimum_pair_cover", 0),
        (
            "selective", None, selected, str(selected_record["status"]),
            int(selected_record["candidate_evaluations"]),
        ),
    ]
    matched_records = record["matched_random"]
    for seed, actions in bundle.matched_actions(record):
        evaluation = e2._evaluate_design(
            polynomial, n_original=n_original, actions=actions,
            selector=selector, apply_qaoa_hard_limits=False,
        )
        designs.append(("matched_random_selective", seed, evaluation, "fibre_v2_matched_auxiliary_count", 0))
    design_record = {
        "instance_id": instance_id,
        "n_original": n_original,
        "selection_scope": "fibre_aware_selector_v2_frozen_design_bundle",
        "selected_search_status": selected_record["status"],
        "selected_runtime_sec": selected_record["runtime_sec"],
        "selected_compiler_calls": selected_record["candidate_evaluations"],
        "selected_actions": [list(action) if action is not None else None for action in selected_actions],
        "selected_design_id": selected_record["design_id"],
        "matched_random": [
            {
                "seed": int(item["random_rep_seed"]),
                "actions": item["actions"],
                "design_id": item["design_id"],
                "degenerate_to_selected": not bool(item["distinct_from_selected"]),
                "normalised_fibre_excess": item["normalised_fibre_excess"],
                "within_selector_tau": item["within_selector_tau"],
            }
            for item in matched_records
        ],
        "fibre_risk": selected_record["fibre_risk"],
        "fibre_selector_config_hash": bundle.config_hash,
    }
    return designs, design_record


def _qaoa_designs(bundle: FibreDesignBundle, polynomial, *, n_original, instance_id, config):
    from . import e2_resources as e2
    from . import e3_qaoa as e3

    record = bundle.record("qaoa", instance_id)
    selector = config["selector"]
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    action_sets = [
        ("all_native", None, (None,) * len(cubics)),
        ("fully_quadratized", None, e2._full_actions(canonical)),
        ("selective", None, bundle.selected_actions(record)),
        *[
            ("matched_random_selective", seed, actions)
            for seed, actions in bundle.matched_actions(record)
        ],
    ]
    designs = [
        e3.QAOADesign(
            representation,
            seed,
            e2._evaluate_design(
                canonical, n_original=n_original, actions=actions,
                selector=selector, apply_qaoa_hard_limits=True,
            ),
        )
        for representation, seed, actions in action_sets
    ]
    if len(designs) != 8 or any(not design.evaluation.feasible for design in designs):
        raise FibreRerunError(f"Selector-v2 QAOA feasibility failed: {instance_id}")
    return designs


@contextmanager
def rerun_overrides(
    *,
    step: str,
    bundle: FibreDesignBundle,
    parent_config_path: str | Path,
    parent_config_hash_path: str | Path,
) -> Iterator[None]:
    """Temporarily bind a formal pipeline to the verified v2 designs."""

    from . import e1_exactness as e1
    from . import e2_resources as e2
    from . import e3_qaoa as e3
    from . import e4_warmstart as e4
    from . import e6_noise as e6

    parent_config_path = Path(parent_config_path)
    parent_config_hash_path = Path(parent_config_hash_path)

    def freeze_wrapper(original):
        def wrapped(*, config_path, config_hash_path, data_directory):
            del config_path, config_hash_path
            frozen = original(
                config_path=parent_config_path,
                config_hash_path=parent_config_hash_path,
                data_directory=data_directory,
            )
            frozen["parent_data_config_hash"] = frozen["config_hash"]
            frozen["config_hash"] = bundle.config_hash
            return frozen

        return wrapped

    active_e1: dict[str, dict[str, object] | None] = {"record": None}

    def select_override(polynomial, *, n_original, selector_config, positive_margin):
        del n_original, selector_config, positive_margin
        record = bundle.record_for_polynomial("oracle", polynomial)
        active_e1["record"] = record
        selected = _selected_record_fields(record)
        return bundle.selected_actions(record), {
            "status": selected["status"],
            "objective": selected["resource_score"],
            "compiler_calls": selected["candidate_evaluations"],
            "runtime_sec": selected["runtime_sec"],
            "fibre_risk": selected["fibre_risk"],
            "design_id": selected["design_id"],
            "source": "fibre_selector_v2",
        }

    def matched_override(
        polynomial, *, target_auxiliary_count, selected_actions, instance_id, seed_bundle
    ):
        del polynomial, target_auxiliary_count
        record = bundle.record("oracle", instance_id)
        if active_e1["record"] is not record:
            raise FibreRerunError(f"E1 selector call order mismatch: {instance_id}")
        if tuple(selected_actions) != bundle.selected_actions(record):
            raise FibreRerunError(f"E1 selected actions changed: {instance_id}")
        matched = bundle.matched_actions(record)
        if [seed for seed, _ in matched] != [int(seed) for seed in seed_bundle]:
            raise FibreRerunError(f"E1 matched-random seed mismatch: {instance_id}")
        return matched

    with ExitStack() as stack:
        if step in {"e1", "e2", "e3", "e4", "e6"}:
            module = {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e6": e3}[step]
            stack.enter_context(
                patch.object(module, "verify_data_freeze", freeze_wrapper(module.verify_data_freeze))
            )
        if step == "e1":
            stack.enter_context(patch.object(e1, "select_resource_optimal_design", select_override))
            stack.enter_context(patch.object(e1, "matched_random_actions", matched_override))
        elif step == "e2":
            stack.enter_context(
                patch.object(e2, "_representation_designs", lambda polynomial, **kwargs: _e2_designs(bundle, polynomial, **kwargs))
            )
            stack.enter_context(
                patch.object(
                    e2,
                    "selector_validation_rows",
                    lambda oracle_rows, *, data_directory, config, config_hash, manifest_hash, code_commit: bundle.selector_validation_rows(
                        config_hash=config_hash,
                        manifest_hash=manifest_hash,
                        code_commit=code_commit,
                    ),
                )
            )
        elif step in {"e3", "e4", "e6"}:
            target = {"e3": e3, "e4": e4, "e6": e6}[step]
            stack.enter_context(
                patch.object(target, "qaoa_designs", lambda polynomial, **kwargs: _qaoa_designs(bundle, polynomial, **kwargs))
            )
        yield
