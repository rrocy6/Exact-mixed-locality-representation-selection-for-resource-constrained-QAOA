"""Finite multi-transpiler-seed compilation robustness experiment.

This runner is intentionally append-only.  It consumes the already frozen
compiled-study input snapshot, makes a new ``results/multiseed_*`` directory,
and keeps the compilation, classification, and reporting stages separate so a
completed batch can be resumed or re-analysed without recompilation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import os
import platform
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
try:
    from .multiseed_validation import (validate_config, validate_rows, validate_resources, capacity_excluded, task_id, natural_key, retention_metrics, selector_metrics)
except ImportError:
    from multiseed_validation import (validate_config, validate_rows, validate_resources, capacity_excluded, task_id, natural_key, retention_metrics, selector_metrics)
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SEEDS = (1729, 2718, 31415, 57721, 65537)
TOPOLOGIES = ("line12", "ring12", "grid12")
SYNTHESIS = ("canonical", "reuse")
FAMILIES = ("max3sat", "pair_star_isolated")
FAMILY_LABELS = {"max3sat": "max3sat", "pair_star_isolated": "constructed"}
Q_BUDGETS = tuple(range(6, 13))
G_BUDGETS = tuple(range(0, 241, 4))
D_BUDGETS = (24, 48, 72, 96, 120, 160, 240)
M_BUDGETS = (0.0, 1.1, 2.2, 3.3, 4.4, 6.6, 8.8)
DIMENSIONS = ("Q", "G", "D", "M")
STATES = {"compiled", "width_exceeded", "timeout", "compile_error"}
TRUE, FALSE, UNKNOWN = 1, 0, 2


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def atomic_write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if isinstance(content, bytes):
        temporary.write_bytes(content)
    else:
        temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def latest_input_run() -> Path:
    candidates = sorted(
        (ROOT / "results").glob("multiseed_*/inputs/experiments/compiled_study.py"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No prior frozen multiseed input snapshot is available")
    return candidates[0].parents[2]


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_paths(source_run: Path) -> list[Path]:
    experiments = source_run / "inputs" / "experiments"
    paths = [
        experiments / "compiled_study.py",
        experiments / "compiled_study_frozen_v1.py",
        experiments / "COMPILED_PROTOCOL.md",
        experiments / "COMPILED_PROTOCOL_frozen_v1.md",
        experiments / "COMPILED_RESULTS_README.md",
        experiments / "audit_compiled_results.py",
        experiments / "analyse_compiled_study.py",
        experiments / "compiled_results" / "freeze.json",
        experiments / "compiled_results" / "instances_frozen.json",
        experiments / "compiled_results" / "generation_audit.json",
        experiments / "compiled_results" / "summary.json",
        experiments / "compiled_results" / "audit.json",
    ]
    paths.extend(sorted((experiments / "compiled_results" / "instances").glob("*.json")))
    return [path for path in paths if path.is_file()]


def copy_input_snapshot(run: Path, source_run: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for source in source_paths(source_run):
        relative = source.relative_to(source_run / "inputs")
        target = run / "inputs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        records[relative.as_posix()] = sha256_file(target)
    task = ROOT / "URSS_CODEX_TASK_MULTISEED.md"
    if task.is_file():
        target = run / "inputs" / "task.md"
        shutil.copy2(task, target)
        records["task.md"] = sha256_file(target)
    return records


def family_instance_payloads(run: Path) -> dict[str, dict[str, dict[str, Any]]]:
    directory = run / "inputs" / "experiments" / "compiled_results" / "instances"
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for path in sorted(directory.glob("*.json")):
        payload = read_json(path)
        instance = payload["instance"]
        if instance["family"] in FAMILIES:
            output[instance["family"]][instance["id"]] = {
                "payload": payload,
                "source_path": path,
                "source_sha256": sha256_file(path),
            }
    return output


def sample_manifest(run: Path) -> list[dict[str, Any]]:
    payloads = family_instance_payloads(run)
    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        qualified = []
        for instance_id, record in payloads[family].items():
            instance_hash = stable_digest(record["payload"]["instance"])
            ranking_hash = sha256_bytes(
                f"URSS_MULTISEED_V1|{FAMILY_LABELS[family]}|{instance_id}".encode("utf-8")
            )
            qualified.append((ranking_hash, instance_id, instance_hash, record))
        qualified.sort(key=lambda item: (item[0], item[1]))
        if len(qualified) < 30:
            raise RuntimeError(f"Only {len(qualified)} qualified {family} instances; target is 30")
        for rank, (ranking_hash, instance_id, instance_hash, record) in enumerate(qualified):
            selected = rank < 30
            rows.append(
                {
                    "family": family,
                    "family_label": FAMILY_LABELS[family],
                    "instance_id": instance_id,
                    "rank": rank,
                    "selected": selected,
                    "restricted": selected and rank < 10,
                    "selection_hash": ranking_hash,
                    "instance_sha256": instance_hash,
                    "source_sha256": record["source_sha256"],
                    "qualification": "readable_and_frozen_exactness_traceable",
                }
            )
    selected = [row for row in rows if row["selected"]]
    if len(selected) != 60:
        raise RuntimeError("Expected 60 selected instances")
    return rows


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fieldnames: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_actions(value: str | Iterable[int]) -> tuple[int, ...]:
    if isinstance(value, str):
        return tuple(int(part) for part in value.split(",") if part != "")
    return tuple(int(item) for item in value)


def exactness_evidence(compiler: Any, instance: Mapping[str, Any], actions: tuple[int, ...]) -> dict[str, Any]:
    """Exhaustively verify a candidate's pointwise exactness and lift consistency."""
    polynomial, logical = compiler.representation(instance, actions)
    n = int(instance["n"])
    width = int(logical["Q"])
    if width > 12:
        return {"applicable": False, "reason": "logical_width_exceeds_12"}

    original = compiler.original(instance)
    cubic_terms = compiler.cubic_terms(instance)
    active_pairs = []
    for (edge, _coefficient), action in zip(cubic_terms, actions):
        if action >= 0:
            active_pairs.append(tuple(sorted(compiler.pairs(edge)[action])))
    active_pairs = sorted(set(active_pairs))
    encoded_indices = np.arange(1 << width, dtype=np.uint64)
    encoded_values = np.zeros(len(encoded_indices), dtype=float)
    for support, coefficient in polynomial.items():
        mask = sum(1 << index for index in support)
        encoded_values += float(coefficient) * ((encoded_indices & mask) == mask)
    original_indices = np.arange(1 << n, dtype=np.uint64)
    original_values = np.zeros(len(original_indices), dtype=float)
    for support, coefficient in original.items():
        mask = sum(1 << index for index in support)
        original_values += float(coefficient) * ((original_indices & mask) == mask)
    auxiliary_width = width - n
    table = encoded_values.reshape((1 << auxiliary_width, 1 << n))
    minima = table.min(axis=0)
    mismatch = int(np.count_nonzero(np.abs(minima - original_values) > 1e-9))
    expected_aux = np.zeros(1 << n, dtype=np.uint64)
    for aux_index, pair in enumerate(active_pairs):
        expected_aux |= (((original_indices >> pair[0]) & 1) * ((original_indices >> pair[1]) & 1)) << aux_index
    minimisers = np.abs(table - minima[None, :]) <= 1e-9
    auxiliary_indices = np.arange(1 << auxiliary_width, dtype=np.uint64)[:, None]
    inconsistent = int(np.count_nonzero(minimisers & (auxiliary_indices != expected_aux[None, :])))
    return {
        "applicable": True,
        "method": "exhaustive_all_x_y_unique_consistent_lift",
        "assignments_checked": int(1 << width),
        "mismatch_count": mismatch,
        "inconsistent_minimiser_count": inconsistent,
        "encoded_polynomial_sha256": stable_digest(sorted((list(key), value) for key, value in polynomial.items())),
    }


def candidate_category(candidate: Mapping[str, Any], cubic_count: int, evidence: Mapping[str, Any]) -> str:
    actions = parse_actions(candidate["actions"])
    reduced = int(candidate["reduced"])
    if all(action < 0 for action in actions):
        return "native"
    if reduced == cubic_count:
        return "full"
    if 0 < reduced < cubic_count and evidence.get("applicable") and evidence.get("mismatch_count") == 0 and evidence.get("inconsistent_minimiser_count") == 0:
        return "strict_mixed"
    return "degenerate_selective"


def build_candidate_rows(run: Path, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compiler = import_module(run / "inputs/experiments/compiled_study.py", "multiseed_compiler_manifest")
    payloads = family_instance_payloads(run)
    rows: list[dict[str, Any]] = []
    evidence_cache: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
    for sample in samples:
        if not sample["selected"]:
            continue
        payload = payloads[sample["family"]][sample["instance_id"]]["payload"]
        instance = payload["instance"]
        cubic_count = len(compiler.cubic_terms(instance))
        for target in payload["results"]:
            topology = target["topology"]
            synthesis = target["strategy"]
            keys = list(dict.fromkeys(target["full_keys"] + target["mixed_keys"]))
            for key in keys:
                candidate = target["candidates"][key]
                actions = parse_actions(candidate["actions"])
                evidence_key = (sample["instance_id"], actions)
                evidence = evidence_cache.get(evidence_key)
                if evidence is None:
                    evidence = exactness_evidence(compiler, instance, actions)
                    evidence_cache[evidence_key] = evidence
                category = candidate_category(candidate, cubic_count, evidence)
                candidate_id = stable_digest({
                    "instance_id": sample["instance_id"],
                    "topology": topology,
                    "synthesis": synthesis,
                    "actions": actions,
                })[:24]
                input_hash = stable_digest({
                    "instance_sha256": sample["source_sha256"],
                    "candidate_id": candidate_id,
                    "actions": actions,
                    "topology": topology,
                    "synthesis": synthesis,
                })
                rows.append({
                    "candidate_id": candidate_id,
                    "instance_id": sample["instance_id"],
                    "family": sample["family"],
                    "family_label": sample["family_label"],
                    "restricted": sample["restricted"],
                    "topology": topology,
                    "synthesis": synthesis,
                    "actions": ",".join(map(str, actions)),
                    "n_aux": int(candidate["aux"]),
                    "retained_cubic": cubic_count - int(candidate["reduced"]),
                    "reduced": int(candidate["reduced"]),
                    "logical_Q": int(candidate["logical_Q"]),
                    "maximum_penalty": float(candidate["M"]),
                    "category": category,
                    "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
                    "input_hash": input_hash,
                    "historical_resources_json": json.dumps({k: candidate[k] for k in ("Q", "G", "D", "M", "J", "logical_Q")}, sort_keys=True),
                })
    return rows


def make_tasks(candidates: list[dict[str, Any]], config_hash: str, implementation_hash: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for candidate in candidates:
        for seed in SEEDS:
            task_key = {
                "instance_id": candidate["instance_id"],
                "candidate_id": candidate["candidate_id"],
                "topology": candidate["topology"],
                "synthesis": candidate["synthesis"],
                "seed": seed,
                "config_hash": config_hash,
                "implementation_hash": implementation_hash,
            }
            tasks.append({
                "task_id": task_id(task_key),
                **task_key,
                "family": candidate["family"],
                "candidate": candidate,
            })
    return tasks


def environment_payload(run: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    try:
        import importlib.metadata as metadata
        for name in ("qiskit", "qiskit-aer", "numpy", "scipy", "reportlab"):
            try:
                packages[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                packages[name] = None
    except Exception:
        pass
    return {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "working_directory": str(ROOT),
        "config_hash": config.get("config_hash"),
    }


def implementation_hash() -> str:
    paths = [ROOT / "scripts" / "multiseed_experiment.py", ROOT / "scripts" / "multiseed_compile.py", ROOT / "scripts" / "multiseed_core.py", ROOT / "scripts" / "multiseed_validation.py"]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_config(run: Path, source_run: Path, samples: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    impl = implementation_hash()
    freeze = read_json(run / "inputs/experiments/compiled_results/freeze.json")
    config: dict[str, Any] = {
        "schema_version": "URSS_MULTISEED_V1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_before_p1",
        "source_snapshot": str(source_run),
        "source_freeze_sha256": sha256_file(run / "inputs/experiments/compiled_results/freeze.json"),
        "seeds": list(SEEDS),
        "control_seed": 1729,
        "families": {"max3sat": 30, "constructed": 30},
        "restricted_subset": {"max3sat": 10, "constructed": 10, "rule": "same_selection_hash_order_prefix"},
        "selection_rule": "sha256(URSS_MULTISEED_V1|family_label|instance_id), then instance_id",
        "topologies": list(TOPOLOGIES),
        "synthesis": list(SYNTHESIS),
        "candidate_library": "all archived full_keys plus mixed_keys from frozen target-specific 32-design banks; native/full/degenerate selective retained",
        "budget_grid": {"Q": list(Q_BUDGETS), "G": list(G_BUDGETS), "D": list(D_BUDGETS), "M": list(M_BUDGETS)},
        "resource_definitions": {
            "Q": "active physical qubit footprint including initial logical sites and every routed site",
            "G": "compiled CX count in the cost layer",
            "D": "CX-only circuit depth",
            "M": "maximum Rosenberg penalty coefficient",
            "missing_value": "unknown; never converted to zero",
        },
        "compiler": {
            "qiskit_version_from_freeze": freeze.get("qiskit"),
            "optimization_level": 3,
            "basis_gates": ["rz", "sx", "x", "cx"],
            "routing": "sabre",
            "heuristic": "decay",
            "sabre_trials": 8,
            "seed_transpiler": "one of declared external seeds",
            "initial_layout": "identity",
            "layout_method": "trivial",
            "placement_search": "disabled/guarded; SabreLayout, VF2Layout, VF2PostLayout rejected",
            "topology_source": "inputs/experiments/compiled_study.py::topology",
            "pass_manager_source": "scripts/multiseed_compile.py::pass_manager, explicit SabreSwap",
        },
        "parallelism": {"formal_workers": min(4, os.cpu_count() or 1), "thread_env": {"QISKIT_PARALLEL": "FALSE", "RAYON_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}, "task_timeout_seconds": 300},
        "T_cap_seconds": None,
        "sample_count": len([row for row in samples if row["selected"]]),
        "candidate_row_count": len(candidates),
        "implementation_hash": impl,
        "compiled_study_source_sha256": sha256_file(run / "inputs/experiments/compiled_study.py"),
        "git_head": git_head(),
        "initial_worktree_status_sha256": sha256_file(run / "initial_git_status.txt") if (run / "initial_git_status.txt").is_file() else None,
    }
    config_path = run / "experiment_config.json"
    # The configuration digest is over the canonical payload before the digest
    # field is inserted, avoiding an impossible self-referential file hash.
    try:
        from .multiseed_p1 import PROTOCOL
    except ImportError:
        from multiseed_p1 import PROTOCOL
    config["p1_protocol"] = PROTOCOL
    config["manifest_hashes"] = {name: sha256_file(run / name) for name in ("candidate_manifest.csv", "instance_manifest.csv", "INPUT_COPY_MANIFEST.json")}
    config["compiler_implementation_hash"] = compiler_identity(run)
    config["config_hash"] = stable_digest(config)
    atomic_json(config_path, config)
    # JSON is a complete, valid YAML 1.2 representation.
    atomic_json(run / "experiment_config.yaml", config)
    return config


def git_head() -> str | None:
    try:
        import subprocess
        if not (ROOT / ".git").exists():
            return None
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return None


def p0(run: Path | None = None) -> Path:
    source_run = latest_input_run()
    if run is None:
        run = ROOT / "results" / ("multiseed_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if run.exists():
        raise RuntimeError(f"Refusing to overwrite existing run directory: {run}")
    run.mkdir(parents=True)
    if (ROOT / '.git').exists():
        initial_status = __import__('subprocess').check_output(['git','status','--porcelain','--untracked-files=all'],cwd=ROOT)
        patch = __import__('subprocess').check_output(['git','diff','--binary'],cwd=ROOT)
    else:
        initial_status = b'No project-local Git repository; parent repository intentionally ignored.\n'
        patch = b''
    atomic_write(run / 'initial_git_status.txt', initial_status)
    atomic_write(run / 'initial_worktree.patch', patch)
    copied = copy_input_snapshot(run, source_run)
    atomic_json(run / "INPUT_COPY_MANIFEST.json", {"source_run": str(source_run), "files": copied})
    samples = sample_manifest(run)
    write_csv(run / "instance_manifest.csv", samples, samples[0].keys())
    candidates = build_candidate_rows(run, samples)
    write_csv(run / "candidate_manifest.csv", candidates, candidates[0].keys())
    config = write_config(run, source_run, samples, candidates)
    tasks = make_tasks(candidates, config["config_hash"], config["implementation_hash"])
    task_rows = []
    for task in tasks:
        row = {key: value for key, value in task.items() if key != "candidate"}
        row["candidate_id"] = task["candidate"]["candidate_id"]
        row["input_hash"] = task["candidate"]["input_hash"]
        task_rows.append(row)
    write_csv(run / "task_manifest.csv", task_rows, task_rows[0].keys())
    atomic_json(run / "environment.json", environment_payload(run, config))
    (run / "logs").mkdir(exist_ok=True)
    atomic_json(run / "RUN_STATE.json", {"run_id": run.name, "stage": "p0_pass", "status": "pass", "planned_task_count": len(tasks), "full_sample": True, "T_cap_seconds": None, "updated_utc": datetime.now(timezone.utc).isoformat()})
    return run


def load_run(run: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    run = run.resolve()
    config = read_json(run / "experiment_config.json")
    validate_config(run, config)
    for key, expected in (("seeds", list(SEEDS)), ("topologies", list(TOPOLOGIES)), ("synthesis", list(SYNTHESIS)), ("budget_grid", {"Q": list(Q_BUDGETS), "G": list(G_BUDGETS), "D": list(D_BUDGETS), "M": list(M_BUDGETS)})):
        if config.get(key) != expected:
            raise ValueError("Unsupported frozen protocol: " + key)
    with (run / "instance_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        samples = list(csv.DictReader(handle))
    with (run / "candidate_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        candidates = list(csv.DictReader(handle))
    with (run / "task_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        tasks = list(csv.DictReader(handle))
    regenerated = make_tasks(candidates, config['config_hash'], config['implementation_hash'])
    if Counter(natural_key(t) for t in tasks) != Counter(natural_key(t) for t in regenerated):
        raise ValueError('Task manifest differs from frozen candidate library')
    lookup = candidate_lookup(candidates)
    for t in tasks:
        if t['config_hash'] != config['config_hash'] or t['implementation_hash'] != config['implementation_hash'] or t['input_hash'] != lookup[t['candidate_id']]['input_hash']:
            raise ValueError('Task provenance mismatch')
    hashes = config.get('manifest_hashes')
    if hashes is None:
        # Historical immutable archive provides the binding absent in V1 config.
        with (ROOT / ('BASE_FILE_MANIFEST.csv' if (ROOT / 'BASE_FILE_MANIFEST.csv').exists() else 'FILE_MANIFEST.csv')).open(encoding='utf-8-sig', newline='') as handle:
            archive = {r['path']: r['sha256'] for r in csv.DictReader(handle)}
        origin = read_json(run / 'CORRECTION_SOURCE.json')['source_run'] if (run / 'CORRECTION_SOURCE.json').exists() else run.relative_to(ROOT).as_posix()
        hashes = {name: archive[origin + '/' + name] for name in ('candidate_manifest.csv', 'instance_manifest.csv', 'task_manifest.csv', 'INPUT_COPY_MANIFEST.json')}
    for name, expected in hashes.items():
        if sha256_file(run / name) != expected:
            raise ValueError('Frozen manifest hash mismatch: ' + name)
    return config, samples, candidates, tasks


def candidate_lookup(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["candidate_id"]: row for row in candidates}


def compile_batch_worker(arguments: tuple[str, list[dict[str, Any]], int, int, str]) -> dict[str, Any]:
    run_text, batch_tasks, seed, trials, attempt_id = arguments
    run = Path(run_text)
    experiments = run / "inputs" / "experiments"
    compiler = import_module(experiments / "compiled_study.py", f"compiler_{os.getpid()}_{seed}")
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    multiseed_compile = import_module(scripts / "multiseed_compile.py", f"multiseed_compile_{os.getpid()}_{seed}")
    groups: dict[int, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
    start = time.perf_counter()
    rows: list[dict[str, Any]] = []
    for task in batch_tasks:
        candidate = task["candidate"]
        logical_width = int(candidate["logical_Q"])
        if logical_width > 12:
            rows.append({**{key: task[key] for key in ("task_id", "instance_id", "candidate_id", "topology", "synthesis", "seed")}, "attempt_id": attempt_id, "status": "width_exceeded", "resources_json": "", "error": "logical width exceeds device capacity", "elapsed_seconds": 0.0, "circuit_sha256": "", "circuit_path": ""})
            continue
        instance_path = experiments / "compiled_results" / "instances" / f"{task['instance_id']}.json"
        payload = read_json(instance_path)
        instance = payload["instance"]
        actions = parse_actions(candidate["actions"])
        polynomial, logical = compiler.representation(instance, actions)
        circuit = compiler.cost_circuit(polynomial, logical_width, task["synthesis"])
        groups[logical_width].append((task, circuit))
    for width, group in groups.items():
        pass_manager = multiseed_compile.pass_manager(compiler, group[0][0]["topology"], width, seed, trials)
        try:
            compiled_list = []
            traces = []
            for task, circuit in group:
                trace = {'declared': {'seed': seed, 'trials': trials, 'heuristic': 'decay'}, 'observed_passes': [], 'observed_sabre': []}
                def callback(**kwargs):
                    operation = kwargs['pass_']
                    name = type(operation).__name__
                    trace['observed_passes'].append(name)
                    if name in {'SabreLayout', 'VF2Layout', 'VF2PostLayout'}:
                        raise ValueError('Unexpected placement search: ' + name)
                    if name == 'SabreSwap':
                        actual = {'seed': operation.seed, 'trials': operation.trials, 'heuristic': operation.heuristic}
                        trace['observed_sabre'].append(actual)
                        if actual != trace['declared']:
                            raise ValueError('Observed SABRE settings differ')
                compiled = pass_manager.run(circuit, callback=callback)
                if task.get('semantic', attempt_id.startswith('repeat_') or attempt_id == 'seed_2718'):
                    trace['semantic'] = multiseed_compile.verify_formal_semantics(compiler, run, task, compiled)
                compiled_list.append(compiled)
                traces.append(trace)
        except Exception as exc:
            for task, _ in group:
                rows.append({**{key: task[key] for key in ("task_id", "instance_id", "candidate_id", "topology", "synthesis", "seed")}, "attempt_id": attempt_id, "status": "compile_error", "resources_json": "", "error": f"{type(exc).__name__}: {exc}", "elapsed_seconds": time.perf_counter() - start, "circuit_sha256": "", "circuit_path": ""})
            continue
        for task, compiled, trace in zip((item[0] for item in group), compiled_list, traces):
            candidate = task["candidate"]
            try:
                initial = compiled.layout.initial_index_layout(filter_ancillas=True)
                if list(initial) != list(range(width)):
                    raise ValueError(f"initial layout {initial} is not identity")
                allowed = set(compiler.topology(task["topology"]))
                active = set(range(width))
                for instruction in compiled.data:
                    positions = tuple(compiled.find_bit(qubit).index for qubit in instruction.qubits)
                    active.update(positions)
                    if len(positions) == 2 and (instruction.operation.name != "cx" or positions not in allowed):
                        raise ValueError(f"invalid routed edge {positions}")
                parameter_names = sorted(parameter.name for parameter in compiled.parameters)
                if parameter_names != ["gamma"]:
                    raise ValueError(f"symbolic parameter set changed: {parameter_names}")
                resources = {
                    "Q": len(active),
                    "logical_Q": int(candidate["logical_Q"]),
                    "G": int(compiled.count_ops().get("cx", 0)),
                    "D": int(compiled.depth(filter_function=lambda item: len(item.qubits) == 2)),
                    "M": float(candidate["maximum_penalty"]),
                    "total_gates": int(compiled.size()),
                    "all_gate_depth": int(compiled.depth()),
                }
                resources["J"] = (int(candidate["n_aux"]) / 4 + resources["G"] / 160 + resources["D"] / 120 + resources["M"] / 8) / 4
                # A compact QPY digest makes every output circuit auditable without
                # expanding the result directory by hundreds of gigabytes.
                import qiskit.qpy
                buffer = BytesIO()
                qiskit.qpy.dump(compiled, buffer)
                circuit_hash = sha256_bytes(buffer.getvalue())
                rows.append({**{key: task[key] for key in ("task_id", "instance_id", "candidate_id", "topology", "synthesis", "seed")}, "attempt_id": attempt_id, "status": "compiled", "resources_json": json.dumps(resources, sort_keys=True, separators=(",", ":")), "error": "", "elapsed_seconds": time.perf_counter() - start, "circuit_sha256": circuit_hash, "circuit_path": f"circuit_digests/{task['task_id']}.json", "trace_json": json.dumps(trace, sort_keys=True, separators=(",", ":"))})
            except Exception as exc:
                rows.append({**{key: task[key] for key in ("task_id", "instance_id", "candidate_id", "topology", "synthesis", "seed")}, "attempt_id": attempt_id, "status": "compile_error", "resources_json": "", "error": f"{type(exc).__name__}: {exc}", "elapsed_seconds": time.perf_counter() - start, "circuit_sha256": "", "circuit_path": ""})
    return {"status": "pass", "seed": seed, "attempt_id": attempt_id, "rows": rows, "elapsed_seconds": time.perf_counter() - start}


def candidate_batches(run: Path, candidates: list[dict[str, Any]], samples: list[dict[str, Any]], seeds: Iterable[int] = SEEDS) -> list[tuple[str, list[dict[str, Any]], int, int, str]]:
    selected_ids = {row["instance_id"] for row in samples if str(row["selected"]).lower() == "true"}
    by_batch: dict[tuple[str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    lookup = candidate_lookup(candidates)
    for candidate in candidates:
        if candidate["instance_id"] not in selected_ids:
            continue
        for seed in seeds:
            by_batch[(candidate["instance_id"], candidate["topology"], candidate["synthesis"], int(seed))].append(candidate)
    config = read_json(run / "experiment_config.json")
    batches = []
    for (instance_id, topology, synthesis, seed), batch_candidates in sorted(by_batch.items()):
        tasks = []
        for candidate in batch_candidates:
            task_key = {"instance_id": candidate["instance_id"], "candidate_id": candidate["candidate_id"], "topology": candidate["topology"], "synthesis": candidate["synthesis"], "seed": seed}
            tasks.append({"task_id": task_id(task_key), **task_key, "candidate": candidate})
        attempt = f"formal_{seed}"
        batches.append((f"{instance_id}_{topology}_{synthesis}_{seed}", tasks, seed, config["compiler"]["sabre_trials"], attempt))
    return batches


def write_batch(run: Path, batch_id: str, result: Mapping[str, Any], config: Mapping[str, Any], *, expected=None, candidates=None) -> None:
    rows = []
    for row in result["rows"]:
        copied = dict(row)
        copied["circuit_path"] = f"circuit_digests/{batch_id}.json"
        rows.append(copied)
    if expected is None or candidates is None:
        _, samples, candidates, _ = load_run(run)
        expected = next(tasks for bid, tasks, *_ in candidate_batches(run, candidates, samples) if bid == batch_id)
    validate_rows(expected, rows, candidates)
    if (run / 'raw' / f'{batch_id}.json').exists():
        raise RuntimeError('Refusing to overwrite an existing attempt')
    payload = {"batch_id": batch_id, "config_hash": config["config_hash"], "implementation_hash": config["implementation_hash"], **result, "rows": rows}
    atomic_json(run / "raw" / f"{batch_id}.json", payload)
    digest_rows = {row["task_id"]: {"sha256": row.get("circuit_sha256", ""), "trace": row.get("trace_json", "")} for row in rows}
    atomic_json(run / "circuit_digests" / f"{batch_id}.json", digest_rows)


def load_raw_rows(run: Path, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    _, samples, candidates, _ = load_run(run)
    expected = {bid: tasks for bid, tasks, *_ in candidate_batches(run, candidates, samples)}
    rows: list[dict[str, Any]] = []
    for path in sorted((run / "raw").glob("*.json")):
        payload = read_json(path)
        if payload.get("config_hash") != config["config_hash"] or payload.get("implementation_hash") != config["implementation_hash"]:
            raise RuntimeError(f"Raw batch provenance mismatch: {path}")
        if path.stem not in expected:
            raise RuntimeError('Unexpected raw batch: ' + path.name)
        validate_cached_batch(payload, config, tasks=expected[path.stem], candidates=candidates, run=run)
        rows.extend(payload.get("rows", []))
    return rows


def validate_cached_batch(payload, config, expected_row_count=None, *, tasks=None, candidates=None, run=None):
    for field in ('config_hash', 'implementation_hash'):
        if payload.get(field) != config.get(field):
            raise RuntimeError('Cache mismatch: ' + field)
    if payload.get('status') not in {'pass', 'error'}:
        raise RuntimeError('Cache is not terminal')
    if tasks is None:
        raise RuntimeError('Expected task identities required; row count is insufficient')
    return validate_rows(tasks, payload.get('rows', []), candidates, run)


def run_formal(run: Path, workers: int | None = None) -> None:
    config, samples, candidates, tasks = load_run(run)
    batches = candidate_batches(run, candidates, samples)
    pending = []
    for batch_id, batch_tasks, seed, trials, attempt in batches:
        output = run / 'raw' / f'{batch_id}.json'
        if output.is_file():
            validate_cached_batch(read_json(output), config, tasks=batch_tasks, candidates=candidates, run=run)
        else:
            pending.append((batch_id, batch_tasks, seed, trials, attempt))
    if pending:
        require_current_compiler(run, config)
        try:
            from .multiseed_p1 import require_full_gate
        except ImportError:
            from multiseed_p1 import require_full_gate
        require_full_gate(sys.modules[__name__], run, config, samples, candidates)
        try:
            from .multiseed_scheduler import execute_batches
        except ImportError:
            from multiseed_scheduler import execute_batches
        for batch_id, result in execute_batches(run, pending, workers or config['parallelism']['formal_workers'], config['parallelism']['task_timeout_seconds']):
            write_batch(run, batch_id, result, config, expected=next(b[1] for b in pending if b[0] == batch_id), candidates=candidates)
    rows = load_raw_rows(run, config)
    status = validate_rows(tasks, rows, candidates, run)
    write_csv(run / 'compilation_rows.csv', rows, sorted({k for r in rows for k in r}))
    atomic_json(run / 'RUN_STATE.json', {'stage': 'formal_complete', 'status': 'pass' if not status['failed_count'] else 'fail', **status, 'postprocess_complete': False})
    if status['failed_count']:
        raise RuntimeError('Execution complete with failed compilation tasks')


def compiler_identity(run):
    import inspect
    paths = [ROOT / 'scripts' / name for name in ('multiseed_compile.py', 'multiseed_scheduler.py')]
    paths.append(run / 'inputs/experiments/compiled_study.py')
    return stable_digest({**{p.name: sha256_file(p) for p in paths}, "formal_worker": sha256_bytes(inspect.getsource(compile_batch_worker).encode())})


def execution_identity(run, config):
    return {'config_hash': config['config_hash'], 'compiler_hash': compiler_identity(run),
            'inputs_manifest_hash': sha256_file(run / 'INPUT_COPY_MANIFEST.json')}


def require_current_compiler(run, config):
    import importlib.metadata
    if importlib.metadata.version('qiskit') != config['compiler']['qiskit_version_from_freeze']:
        raise RuntimeError('Qiskit version differs from frozen configuration')
    if config.get('compiler_implementation_hash') != compiler_identity(run):
        raise RuntimeError('Compiler implementation changed or legacy identity: create a new P0 run; saved resources remain available for reanalysis')


def preflight_job(job, config):
    try:
        from .multiseed_scheduler import execute_batches
    except ImportError:
        from multiseed_scheduler import execute_batches
    run, tasks, seed, trials, attempt = job
    batches = [('preflight', tasks, seed, trials, attempt)]
    return next(execute_batches(Path(run), batches, config['parallelism']['formal_workers'], config['parallelism']['task_timeout_seconds']))[1]


def p1(run: Path, scope='full') -> None:
    try:
        from .multiseed_p1 import run_p1
    except ImportError:
        from multiseed_p1 import run_p1
    run_p1(sys.modules[__name__], run, scope)


def budgets_array() -> np.ndarray:
    return np.array(list(itertools.product(Q_BUDGETS, G_BUDGETS, D_BUDGETS, M_BUDGETS)), dtype=float)


def candidate_states(candidate, results, budgets):
    states = np.full(len(budgets), UNKNOWN, dtype=np.uint8)
    feasible = np.zeros(len(budgets), dtype=bool)
    known = bool(results)
    for row in results:
        if row.get('status') == 'compiled':
            try:
                r = json.loads(row['resources_json'])
                validate_resources(r)
                if len(budgets) == len(Q_BUDGETS)*len(G_BUDGETS)*len(D_BUDGETS)*len(M_BUDGETS):
                    feasible |= feasible_slice(r, (len(Q_BUDGETS),len(G_BUDGETS),len(D_BUDGETS),len(M_BUDGETS)))
                else:
                    feasible |= np.all(np.array([r[d] for d in DIMENSIONS]) <= budgets + [0,0,0,1e-9], axis=1)
            except (ValueError, KeyError, TypeError):
                known = False
        elif not capacity_excluded(candidate, row):
            known = False
    if known:
        states[:] = FALSE
    states[feasible] = TRUE
    return states


def feasible_slice(resources: Mapping[str, Any], shape: tuple[int, int, int, int]) -> np.ndarray:
    """Build a monotone budget mask by slicing, avoiding 20k-cell broadcasts."""
    validate_resources(resources)
    thresholds = []
    for values, dimension in ((Q_BUDGETS, "Q"), (G_BUDGETS, "G"), (D_BUDGETS, "D"), (M_BUDGETS, "M")):
        threshold = float(resources[dimension])
        index = next((i for i, value in enumerate(values) if float(value) + 1e-9 >= threshold), len(values))
        thresholds.append(index)
    mask = np.zeros(shape, dtype=bool)
    if all(index < size for index, size in zip(thresholds, shape)):
        mask[thresholds[0]:, thresholds[1]:, thresholds[2]:, thresholds[3]:] = True
    return mask.ravel()


def classify_layer(candidates: list[dict[str, Any]], result_by_candidate: Mapping[str, list[Mapping[str, Any]]], budgets: np.ndarray) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    shape = (len(Q_BUDGETS), len(G_BUDGETS), len(D_BUDGETS), len(M_BUDGETS))
    mixed_yes = np.zeros(len(budgets), dtype=bool)
    mixed_unknown = np.zeros(len(budgets), dtype=bool)
    nonmixed_yes = np.zeros(len(budgets), dtype=bool)
    nonmixed_unknown = np.zeros(len(budgets), dtype=bool)
    state_by_candidate: dict[str, np.ndarray] = {}
    for candidate in candidates:
        candidate_rows = result_by_candidate.get(candidate["candidate_id"], [])
        states = candidate_states(candidate, candidate_rows, budgets)
        state_by_candidate[candidate["candidate_id"]] = states
        category = candidate["category"]
        if category == "strict_mixed":
            mixed_yes |= states == TRUE
            mixed_unknown |= states == UNKNOWN
        else:
            nonmixed_yes |= states == TRUE
            nonmixed_unknown |= states == UNKNOWN
    output = np.full(len(budgets), UNKNOWN, dtype=np.uint8)
    output[nonmixed_yes] = FALSE
    output[~nonmixed_yes & ~mixed_yes & ~mixed_unknown] = FALSE
    output[mixed_yes & ~nonmixed_yes & ~nonmixed_unknown] = TRUE
    return output, state_by_candidate


def pooled_layer(candidates: list[dict[str, Any]], result_by_candidate: Mapping[str, list[Mapping[str, Any]]], budgets: np.ndarray) -> np.ndarray:
    return classify_layer(candidates, result_by_candidate, budgets)[0]


def frontier_ids(candidates: list[dict[str, Any]], result_by_candidate: Mapping[str, list[Mapping[str, Any]]]) -> tuple[set[str], bool]:
    vectors = []
    complete = True
    for candidate in candidates:
        rows = result_by_candidate.get(candidate["candidate_id"], [])
        if not rows or any(row.get("status") not in {"compiled", "width_exceeded"} for row in rows):
            complete = False
        for row in rows:
            if row.get("status") == "compiled":
                resources = json.loads(row["resources_json"])
                vectors.append((candidate["candidate_id"], np.array([float(resources[d]) for d in DIMENSIONS])))
    ids: set[str] = set()
    for index, (candidate_id, vector) in enumerate(vectors):
        dominated = False
        for other_index, (_, other) in enumerate(vectors):
            if index == other_index:
                continue
            if np.all(other <= vector + 1e-10) and np.any(other < vector - 1e-10):
                dominated = True
                break
        if not dominated:
            ids.add(candidate_id)
    return ids, complete


def historical_lookup(run: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    directory = run / "inputs" / "experiments" / "compiled_results" / "instances"
    for path in directory.glob("*.json"):
        payload = read_json(path)
        for target in payload.get("results", []):
            for candidate_id, candidate in target.get("candidates", {}).items():
                lookup[(payload["instance"]["id"], target["topology"], target["strategy"], candidate_id)] = candidate
    return lookup


def analyse(run: Path) -> None:
    config, samples, candidates, _ = load_run(run)
    with (run / "compilation_rows.csv").open(encoding="utf-8-sig", newline="") as handle:
        compilation = list(csv.DictReader(handle))
    validate_rows(load_run(run)[3], compilation, candidates, run)
    candidate_by_id = candidate_lookup(candidates)
    rows_by_layer_seed: dict[tuple[str, str, str, int], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in compilation:
        rows_by_layer_seed[(row["instance_id"], row["topology"], row["synthesis"], int(row["seed"]))][row["candidate_id"]].append(row)
    budgets = budgets_array()
    array_store: dict[str, np.ndarray] = {}
    summary_rows = []
    robust_path = run / 'robust_regions.csv'
    robust_handle = robust_path.open('w', encoding='utf-8', newline='')
    robust_writer = None
    robust_count = 0
    flip_rows = []
    pareto_rows = []
    selector_rows = []
    pooled_rows = []
    classification_rows = []
    selected_ids = {row["instance_id"] for row in samples if str(row["selected"]).lower() == "true"}
    restricted_ids = {row["instance_id"] for row in samples if str(row["restricted"]).lower() == "true"}
    historical = historical_lookup(run)
    baseline_rows = []
    compilation_index: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    # Index once; scanning all 101k rows for every candidate would make the
    # post-processing quadratic while leaving the scientific calculation unchanged.
    with (run / "compilation_rows.csv").open(encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            compilation_index[(item["instance_id"], item["candidate_id"], item["topology"], item["synthesis"], int(item["seed"]))] = item
    layer_candidates: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        layer_candidates[(candidate["instance_id"], candidate["topology"], candidate["synthesis"])].append(candidate)
        history = json.loads(candidate["historical_resources_json"])
        baseline_rows.append({"instance_id": candidate["instance_id"], "family": candidate["family"], "topology": candidate["topology"], "synthesis": candidate["synthesis"], "candidate_id": candidate["candidate_id"], "seed": 1729, "historical_Q": history["Q"], "historical_G": history["G"], "historical_D": history["D"], "historical_M": history["M"], "historical_J": history["J"]})
    for layer_index, (layer, layer_cands) in enumerate(sorted(layer_candidates.items()), 1):
        instance_id, topology, synthesis = layer
        family = layer_cands[0]["family"]
        seed_classes: dict[int, np.ndarray] = {}
        seed_states: dict[int, dict[str, np.ndarray]] = {}
        for seed in SEEDS:
            result_map = rows_by_layer_seed[(instance_id, topology, synthesis, seed)]
            classes, state_map = classify_layer(layer_cands, result_map, budgets)
            seed_classes[seed] = classes
            seed_states[seed] = state_map
            key = stable_digest({"layer": layer, "seed": seed})[:24]
            array_store[key] = classes.reshape((len(Q_BUDGETS), len(G_BUDGETS), len(D_BUDGETS), len(M_BUDGETS)))
            classification_rows.append({"family": family, "instance_id": instance_id, "topology": topology, "synthesis": synthesis, "seed": seed, "array_key": key, "shape": "7x61x7x7", "true_cells": int((classes == TRUE).sum()), "false_cells": int((classes == FALSE).sum()), "unknown_cells": int((classes == UNKNOWN).sum()), "encoding": "classification_arrays.npz; values 0=FALSE,1=TRUE,2=UNKNOWN"})
            summary_rows.append({"family": family, "family_label": FAMILY_LABELS[family], "instance_id": instance_id, "restricted": instance_id in restricted_ids, "topology": topology, "synthesis": synthesis, "seed": seed, "true_cells": int((classes == TRUE).sum()), "false_cells": int((classes == FALSE).sum()), "unknown_cells": int((classes == UNKNOWN).sum()), "true_present": bool(np.any(classes == TRUE))})
            frontier, complete = frontier_ids(layer_cands, result_map)
            baseline_frontier = frontier_ids(layer_cands, rows_by_layer_seed[(instance_id, topology, synthesis, 1729)])[0]
            union = frontier | baseline_frontier
            pareto_rows.append({"family": family, "instance_id": instance_id, "topology": topology, "synthesis": synthesis, "seed": seed, "frontier_count": len(frontier), "baseline_frontier_count": len(baseline_frontier), "jaccard_vs_1729": (len(frontier & baseline_frontier) / len(union) if union else "N/A"), "complete": complete})
            selector_rows.append({'family': family, 'instance_id': instance_id, 'topology': topology, 'synthesis': synthesis, 'seed': seed,
                                  **selector_metrics(layer_cands, rows_by_layer_seed[(instance_id, topology, synthesis, 1729)], result_map, budgets)})
        baseline = seed_classes[1729]
        pooled = pooled_layer(layer_cands, {candidate["candidate_id"]: [row for seed in SEEDS for row in rows_by_layer_seed[(instance_id, topology, synthesis, seed)].get(candidate["candidate_id"], [{"status": "missing"}])] for candidate in layer_cands}, budgets)
        pooled_rows.append({"family": family, "instance_id": instance_id, "topology": topology, "synthesis": synthesis, "true_cells": int((pooled == TRUE).sum()), "false_cells": int((pooled == FALSE).sum()), "unknown_cells": int((pooled == UNKNOWN).sum()), "any_true": bool(np.any(pooled == TRUE)), "seed_union_interpretation": "union_of_complete_actual_circuit_vectors; no componentwise minima"})
        baseline_true = baseline == TRUE
        for index, point in enumerate(budgets):
            values = [int(seed_classes[seed][index]) for seed in SEEDS]
            if any(value != UNKNOWN for value in values) or baseline_true[index]:
                robust_row = {"family": family, "instance_id": instance_id, "restricted": instance_id in restricted_ids, "topology": topology, "synthesis": synthesis, "Q": int(point[0]), "G": int(point[1]), "D": int(point[2]), "M": float(point[3]), "seed_true_count": values.count(TRUE), "seed_false_count": values.count(FALSE), "seed_unknown_count": values.count(UNKNOWN), "baseline_1729": values[0], "pooled_status": int(pooled[index])}
                if robust_writer is None:
                    robust_writer = csv.DictWriter(robust_handle, fieldnames=list(robust_row))
                    robust_writer.writeheader()
                robust_writer.writerow(robust_row)
                robust_count += 1
        flip_rows.append({'family': family, 'instance_id': instance_id, 'restricted': instance_id in restricted_ids, 'topology': topology, 'synthesis': synthesis, **retention_metrics(seed_classes)})
        if layer_index == 1 or layer_index % 30 == 0 or layer_index == len(layer_candidates):
            print(f"MULTISEED analysis layers {layer_index}/{len(layer_candidates)}", flush=True)
    np.savez_compressed(run / "classification_arrays.npz", **array_store)
    write_csv(run / "seed_summary.csv", summary_rows, summary_rows[0].keys())
    write_csv(run / "budget_classification.csv", classification_rows, classification_rows[0].keys())
    robust_handle.close()
    write_csv(run / "classification_flips.csv", flip_rows, flip_rows[0].keys())
    write_csv(run / "pareto_stability.csv", pareto_rows, pareto_rows[0].keys())
    write_csv(run / "selector_stability.csv", selector_rows, selector_rows[0].keys())
    write_csv(run / "pooled_seed_summary.csv", pooled_rows, pooled_rows[0].keys())
    for row in baseline_rows:
        match = compilation_index.get((row["instance_id"], row["candidate_id"], row["topology"], row["synthesis"], 1729))
        if match and match["status"] == "compiled":
            resources = json.loads(match["resources_json"])
            for dimension in DIMENSIONS:
                row[f"new_{dimension}"] = resources[dimension]
                row[f"delta_{dimension}"] = float(resources[dimension]) - float(row[f"historical_{dimension}"])
            row["new_status"] = match["status"]
            row["changed"] = any(abs(float(row[f"delta_{dimension}"])) > 1e-10 for dimension in DIMENSIONS)
        else:
            row["new_status"] = match["status"] if match else "missing"
            row["changed"] = True
        row["comparison_scope"] = "historical Qiskit 2.5.2 seed-1729 archive vs explicit-trials-8 controlled rerun"
    write_csv(run / "baseline_comparison.csv", baseline_rows, baseline_rows[0].keys())
    atomic_json(run / "ANALYSIS_STATE.json", {"status": "pass", "layer_count": len(layer_candidates), "summary_row_count": len(summary_rows), "robust_region_row_count": robust_count, "updated_utc": datetime.now(timezone.utc).isoformat()})
    generate_figures(run, summary_rows, flip_rows, pareto_rows)
    write_report(run, config, samples, candidates, summary_rows, flip_rows, pareto_rows, pooled_rows)
    state = read_json(run / 'ANALYSIS_STATE.json')
    state.update(compilation_sha256=sha256_file(run / 'compilation_rows.csv'), config_hash=config['config_hash'],
                 postprocess_implementation_hash=implementation_hash(), scientific_unknown_cells=sum(r['unknown_cells'] for r in summary_rows),
                 artifact_hashes={p.relative_to(run).as_posix():sha256_file(p) for p in [run/'classification_arrays.npz',run/'seed_summary.csv',run/'classification_flips.csv',run/'selector_stability.csv',run/'seed_region_presence.csv',*sorted((run/'figures').glob('*.svg'))]})
    atomic_json(run / 'ANALYSIS_STATE.json', state)


def svg_bar_chart(path: Path, labels: list[str], values: list[float], title: str, y_label: str) -> None:
    width, height = 1000, 540
    margin_left, margin_bottom, chart_w, chart_h = 90, 90, 850, 350
    maximum = max(values or [1.0]) or 1.0
    bars = []
    gap = chart_w / max(1, len(values))
    for index, value in enumerate(values):
        x = margin_left + index * gap + gap * 0.15
        bar_w = gap * 0.7
        bar_h = chart_h * value / maximum
        y = margin_bottom + chart_h - bar_h
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="#476c9b"/>')
        bars.append(f'<text x="{x+bar_w/2:.1f}" y="{margin_bottom+chart_h+22}" text-anchor="middle" font-size="11">{labels[index]}</text>')
        bars.append(f'<text x="{x+bar_w/2:.1f}" y="{max(18,y-5):.1f}" text-anchor="middle" font-size="11">{value:.2f}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/><text x="500" y="34" text-anchor="middle" font-size="20" font-family="Arial">{title}</text>
<line x1="{margin_left}" y1="{margin_bottom}" x2="{margin_left}" y2="{margin_bottom+chart_h}" stroke="#333"/><line x1="{margin_left}" y1="{margin_bottom+chart_h}" x2="{margin_left+chart_w}" y2="{margin_bottom+chart_h}" stroke="#333"/>
<text x="24" y="270" transform="rotate(-90 24 270)" text-anchor="middle" font-size="13">{y_label}</text>{''.join(bars)}
</svg>'''
    atomic_write(path, svg)


def generate_figures(run: Path, summary_rows: list[dict[str, Any]], flip_rows: list[dict[str, Any]], pareto_rows: list[dict[str, Any]]) -> None:
    figure_dir = run / "figures"
    figure_dir.mkdir(exist_ok=True)
    labels = [str(seed) for seed in SEEDS]
    true_cells = [sum(int(row["true_cells"]) for row in summary_rows if int(row["seed"]) == seed) for seed in SEEDS]
    svg_bar_chart(figure_dir / "seed_true_region_cells.svg", labels, [float(value) for value in true_cells], "Strict mixed-only TRUE cells by compiler seed", "sum of classified budget cells")
    presence = [{'seed': seed, 'nonempty_settings': sum(int(r['true_cells']) > 0 for r in summary_rows if int(r['seed']) == seed),
                 'total_settings': sum(int(r['seed']) == seed for r in summary_rows)} for seed in SEEDS]
    for row in presence:
        row['fraction'] = row['nonempty_settings'] / row['total_settings']
    write_csv(run / 'seed_region_presence.csv', presence, presence[0].keys())
    svg_bar_chart(figure_dir / 'region_presence_by_seed.svg', labels, [r['fraction'] for r in presence], 'Settings with nonempty TRUE region by seed', 'fraction of all instance/topology/synthesis settings')
    jaccard = [float(row["jaccard_vs_1729"]) for row in pareto_rows if row["jaccard_vs_1729"] != "N/A"]
    svg_bar_chart(figure_dir / "pareto_jaccard_distribution.svg", ["median", "minimum"], [float(np.median(jaccard)) if jaccard else 0.0, min(jaccard) if jaccard else 0.0], "Pareto frontier Jaccard similarity to seed 1729", "Jaccard")


def write_report(run: Path, config: Mapping[str, Any], samples: list[dict[str, Any]], candidates: list[dict[str, Any]], summaries: list[dict[str, Any]], flips: list[dict[str, Any]], pareto: list[dict[str, Any]], pooled: list[dict[str, Any]]) -> None:
    counts = Counter()
    for row in summaries:
        counts[(int(row["seed"]), "true")] += int(row["true_cells"])
        counts[(int(row["seed"]), "unknown")] += int(row["unknown_cells"])
    baseline = [row for row in flips if int(row["baseline_true_cells"]) > 0]
    common = sum(int(row["common_true_cells"]) for row in flips)
    base_cells = sum(int(row["baseline_true_cells"]) for row in flips)
    report = f'''# URSS multi-seed compilation robustness experiment

Run ID: `{run.name}`  
Status: derived analysis complete; consult AUDIT.json for separate acceptance status  
Controlled seed set: `{list(SEEDS)}`; seed `1729` is the comparison seed.  
Environment: Qiskit `{config["compiler"].get("qiskit_version_from_freeze")}` frozen input, explicit `SabreSwap(trials=8)`, identity placement, line-12/ring-12/grid-12, canonical/reuse synthesis.  
The historical archive used Qiskit 2.5.2 with implicit routing trials; `baseline_comparison.csv` therefore treats this run as a controlled re-baseline rather than claiming that only the seed changed.

## Scope and completion

- Complete sample: 30 Max-3SAT and 30 constructed (`pair_star_isolated`) instances.
- Restricted sample: the first 10 of each family under the declared selection hash, nested in the complete sample.
- Candidate rows: {len(candidates)}; formal task rows: see `task_manifest.csv` (the complete task count is audited in `AUDIT.json`).
- Every result is classified against a complete `(Q,G,D,M)` budget tuple. Missing resource values remain `UNKNOWN`.
- `classification_arrays.npz` is the complete cell-level archive; `budget_classification.csv` is represented by the seed summary and robust-region tables because a fully expanded 37-million-row CSV would obscure rather than improve auditability.

## Results

Across instance/topology/synthesis layers, seed-1729 baseline TRUE cells total `{base_cells}`. The five-seed common TRUE cells total `{common}`; baseline retention is `{(common / base_cells if base_cells else float("nan")):.4f}` when the baseline denominator is nonzero. The per-layer result, UNKNOWN coverage, and classification flips are in `seed_summary.csv`, `robust_regions.csv`, and `classification_flips.csv`.

Seed TRUE-cell totals: {', '.join(f'{seed}={counts[(seed, "true")]}' for seed in SEEDS)}.  
Seed UNKNOWN-cell totals: {', '.join(f'{seed}={counts[(seed, "unknown")]}' for seed in SEEDS)}.

Pareto stability is reported in `pareto_stability.csv`; pooled five-seed feasibility is reported separately in `pooled_seed_summary.csv` and uses a union of complete actual circuit vectors, never componentwise minima. Selector re-selection under the existing resource score is in `selector_stability.csv`.

## Engineering audit

`RUN_STATE.json` records execution completeness; `compilation_rows.csv` records every candidate/instance/topology/synthesis/seed task and its terminal status. Each raw batch is atomically written under `raw/`; compact QPY digests and pass-manager provenance are under `circuit_digests/`. `baseline_comparison.csv` records the controlled seed-1729 comparison to the historical archive.

## Scientific limits

These are five fixed descriptive compilation seeds, a finite frozen candidate library, three fixed 12-qubit topologies, and two synthesis strategies. They do not establish compiler-seed independence for all seeds or global infeasibility outside the tested library. UNKNOWN cells and compile failures remain visible in the audit.

## Reproduction

```powershell
python -X utf8 -B scripts/multiseed_experiment.py --stage analyze --run-dir results/multiseed_20260918T163717Z --output-dir corrections/NEW_ANALYSIS
python -X utf8 -B scripts/multiseed_experiment.py --stage audit --run-dir corrections/NEW_ANALYSIS
```
Use a new output directory for every published correction. See `README_REPRODUCE_REPAIRS.md` for environment and formal replay commands.
'''
    atomic_write(run / "EXPERIMENT_REPORT.md", report)
    note = f'''# Paper update notes for `{run.name}`

The current manuscript source is `paper/main.tex`. Add the following paragraph to the experimental-results discussion after the compiled-resource comparison, replacing placeholders only with values from the audited CSV files:

> We additionally evaluated the frozen candidate library under five fixed transpiler seeds (1729, 2718, 31415, 57721, and 65537), with explicit SABRE trials set to 8 and identity placement on line-12, ring-12, and grid-12 topologies. The complete sample contained 30 Max-3SAT and 30 constructed instances, with a nested 10-instance restricted subset per family. We report seed-wise strict mixed-only regions, their five-seed intersection, classification flips, UNKNOWN coverage, and Pareto-frontier stability. Because the historical archive used a different effective routing configuration, the new seed-1729 run is treated as a controlled re-baseline; it is not described as a seed-only change. The evidence is limited to the frozen candidate library, software stack, topologies, and five tested seeds.

Exact run artifacts: `{run.as_posix()}`. The audited numerical values are in `seed_summary.csv`, `classification_flips.csv`, `pareto_stability.csv`, and `pooled_seed_summary.csv`.
'''
    atomic_write(run / "PAPER_UPDATE_NOTES.md", note)


def audit(run: Path) -> None:
    config, samples, candidates, tasks = load_run(run)
    rows = []
    if (run / "compilation_rows.csv").is_file():
        with (run / "compilation_rows.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    terminal = Counter(row.get("status") for row in rows)
    errors = []
    validation = {'coverage_complete': False, 'compiled_count': terminal['compiled'], 'failed_count': terminal['compile_error'] + terminal['timeout']}
    try:
        validation = validate_rows(tasks, rows, candidates, run)
        raw = load_raw_rows(run, config)
        validate_rows(tasks, raw, candidates, run)
        left = {natural_key(r): {k:str(v) for k,v in r.items()} for r in raw}
        right = {natural_key(r): {k:str(v) for k,v in r.items()} for r in rows}
        if left != right:
            raise ValueError('Raw and aggregate rows differ')
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        errors.append(str(exc))
    postprocess = (run / 'ANALYSIS_STATE.json').is_file() and read_json(run / 'ANALYSIS_STATE.json').get('status') == 'pass'
    analysis_state = read_json(run / 'ANALYSIS_STATE.json') if postprocess else {}
    if postprocess:
        if analysis_state.get('compilation_sha256') != sha256_file(run / 'compilation_rows.csv') or analysis_state.get('config_hash') != config['config_hash']:
            errors.append('Analysis provenance mismatch')
        if not analysis_state.get('artifact_hashes'):
            errors.append('Analysis artifact bindings missing')
        for relative, expected in analysis_state.get('artifact_hashes', {}).items():
            if sha256_file(run / relative) != expected:
                errors.append('Analysis artifact changed: ' + relative)
    summary = {
        "schema_version": "URSS_MULTISEED_AUDIT_V2",
        "status": "pass" if not errors and validation["coverage_complete"] and not validation["failed_count"] and postprocess else "fail",
        **validation, "errors": errors, "postprocess_complete": postprocess,
        "run_id": run.name,
        "planned_tasks": len(tasks),
        "observed_compilation_rows": len(rows),
        "terminal_counts": terminal,
        "pending_tasks": max(0, len(tasks) - len(rows)),
        "capacity_exceeded": terminal.get("width_exceeded", 0),
        "timeouts": terminal.get("timeout", 0),
        "compile_errors": terminal.get("compile_error", 0),
        "successful_compiles": terminal.get("compiled", 0),
        "sample_counts": Counter(row["family_label"] for row in samples if str(row["selected"]).lower() == "true"),
        "candidate_rows": len(candidates),
        "five_seed_set": list(SEEDS),
        "config_hash": config.get("config_hash"),
        "implementation_hash": config.get("implementation_hash"),
        "scientific_unknown_cells": analysis_state.get("scientific_unknown_cells"),
        "scientific_unknowns_are_visible": True,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(run / "AUDIT.json", summary)
    state = read_json(run / "RUN_STATE.json") if (run / "RUN_STATE.json").is_file() else {}
    state.update({"stage": "p4_complete", "status": summary["status"], "audit": summary, "updated_utc": datetime.now(timezone.utc).isoformat()})
    atomic_json(run / "RUN_STATE.json", state)
    files = []
    for path in sorted(run.rglob("*")):
        if path.is_file() and path.name not in {"SHA256_MANIFEST.csv", "SHA256_MANIFEST.sha256"}:
            files.append({"path": path.relative_to(run).as_posix(), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    write_csv(run / "SHA256_MANIFEST.csv", files, ("path", "sha256", "size_bytes"))
    atomic_write(run / "SHA256_MANIFEST.sha256", sha256_file(run / "SHA256_MANIFEST.csv") + "\n")
    if summary["status"] != "pass":
        raise RuntimeError("Audit acceptance failed: " + str(errors))


def create_correction(source, output):
    if not output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Correction output must stay inside project')
    if output.exists():
        raise ValueError('Correction output already exists')
    config, _, _, tasks = load_run(source)
    output.mkdir(parents=True)
    for name in ('inputs', 'raw', 'circuit_digests'):
        shutil.copytree(source / name, output / name)
    for name in ('experiment_config.json','INPUT_COPY_MANIFEST.json','candidate_manifest.csv','instance_manifest.csv','task_manifest.csv','compilation_rows.csv','baseline_comparison.csv'):
        shutil.copy2(source / name, output / name)
    atomic_json(output / 'experiment_config.yaml', config)
    write_csv(output / 'TASK_ID_MAPPING.csv', [{'legacy_manifest_task_id':t['task_id'], 'canonical_result_task_id':task_id(t), **{k:t[k] for k in ('instance_id','candidate_id','topology','synthesis','seed')}} for t in tasks], ['legacy_manifest_task_id','canonical_result_task_id','instance_id','candidate_id','topology','synthesis','seed'])
    atomic_json(output / 'CORRECTION_SOURCE.json', {'source_run': source.relative_to(ROOT).as_posix(),
                'source_config_hash': config['config_hash'], 'source_compilation_sha256': sha256_file(source / 'compilation_rows.csv'),
                'compilation_implementation_hash': config['implementation_hash'],
                'postprocess_implementation_hash': implementation_hash(), 'historical_pass_trace_scope': 'declared settings only; not observed callbacks'})
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("p0", "p1", "run", "analyze", "audit", "all"), required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--workers", type=int)
    parser.add_argument("--p1-scope", choices=("full", "representative"), default="full")
    parser.add_argument("--output-dir", type=Path, help="New directory required for historical analysis/audit")
    args = parser.parse_args()
    run = args.run_dir.resolve() if args.run_dir else None
    if args.stage == "p0":
        run = p0(run)
        print(run)
        return 0
    if run is None:
        latest = sorted((ROOT / "results").glob("multiseed_*/RUN_STATE.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not latest:
            raise RuntimeError("--run-dir is required before P1")
        run = latest[0].parent
    if args.output_dir:
        run = create_correction(run, args.output_dir.resolve())
    if (run / 'experiment_config.json').exists() and 'compiler_implementation_hash' not in read_json(run / 'experiment_config.json') and not (run / 'CORRECTION_SOURCE.json').exists():
        raise RuntimeError('Historical run is read-only; supply --output-dir for saved-resource analysis/audit')
    if args.stage == "p1":
        p1(run, args.p1_scope)
    elif args.stage == "run":
        run_formal(run, args.workers)
    elif args.stage == "analyze":
        analyse(run)
    elif args.stage == "audit":
        audit(run)
    else:
        p1(run, args.p1_scope)
        run_formal(run, args.workers)
        analyse(run)
        audit(run)
    print(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
