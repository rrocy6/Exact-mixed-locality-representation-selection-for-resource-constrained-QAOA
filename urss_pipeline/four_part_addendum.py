"""Append-only four-part experimental addendum for the frozen fibre-v2 study.

The module deliberately reads the frozen E1--E6 inputs but writes only below a
new output root.  Each phase has a small transaction marker so an interrupted
phase can be resumed without replacing a completed result.
"""

from __future__ import annotations

import csv
import hashlib
import heapq
import json
import math
import shutil
import statistics
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from .e1_exactness import action_options
from .e2_resources import (
    COMPILED_FIELDS,
    _evaluate_design,
    _fast_evaluate_design,
    _qiskit_cost_circuit,
    _two_qubit_depth,
    summarise_compiled_rows,
)
from .e3_qaoa import QAOABudgetSpec, QAOADesign, statevector_data
from .e4_warmstart import (
    MARGINAL_FIELDS,
    RUN_FIELDS,
    SUMMARY_FIELDS as WARM_SUMMARY_FIELDS,
    RelaxationMoments,
    _latex_table as warm_latex_table,
    marginal_diagnostic_rows,
    optimize_warmstart_run,
    summarise_warmstart_runs,
    warm_start_specs,
    write_marginal_figure_pdf,
)
from .fibre_rerun import deserialize_actions
from .fibre_selector import (
    FibreCandidate,
    FibreMoments,
    FibreSearchResult,
    _candidate,
    beam_select_fibre_design,
    fibre_normalisation,
    greedy_select_fibre_design,
    solve_deterministic_sa_rlt_level2,
)
from .generators import derive_seed, generate_max3sat, generate_spin_glass
from .identity import stable_instance_json
from .metadata import canonical_metadata, exact_ground_truth, polynomial_for_instance
from .polynomial import Polynomial, Support, canonicalize, cubic_supports


class FourPartAddendumError(RuntimeError):
    """The additive experiment cannot continue without violating its protocol."""


PHASES = ("certification", "topologies", "selector_ablation", "strong_bias")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fields or (list(rows[0]) if rows else []))
    if not names:
        raise FourPartAddendumError(f"CSV fields are required: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=names, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in names})


def write_hash(path: Path) -> str:
    digest = sha256_file(path)
    path.with_suffix(path.suffix + ".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise FourPartAddendumError(f"Expected JSON object: {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_addendum_config(path: Path) -> tuple[dict[str, object], str]:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise FourPartAddendumError("Missing addendum config or SHA-256 sidecar")
    digest = sha256_file(path)
    if sidecar.read_text(encoding="utf-8-sig").strip().lower() != digest:
        raise FourPartAddendumError("Addendum config hash mismatch")
    value = read_json(path)
    if value.get("status") != "frozen" or value.get("schema_version") != "four_part_addendum_v1":
        raise FourPartAddendumError("Addendum config is not the frozen v1 protocol")
    return value, digest


def verify_parent_config(path: Path, sidecar: Path, expected: str) -> dict[str, object]:
    """Verify raw bytes, accepting only the known archive CRLF transport case."""

    declared = sidecar.read_text(encoding="utf-8-sig").strip().lower()
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    normalized = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if expected != declared or (actual != declared and normalized != declared):
        raise FourPartAddendumError("Frozen parent config provenance mismatch")
    value = yaml.safe_load(raw.decode("utf-8-sig"))
    if not isinstance(value, dict) or value.get("config_id") != "experiment_config_v2":
        raise FourPartAddendumError("Unexpected parent config")
    return value


def prepare_output_provenance(
    *,
    output_root: Path,
    config_path: Path,
    config_hash: str,
    parent_config_path: Path,
    code_commit: str,
    parent_commit: str,
) -> None:
    """Freeze config, seed declarations, and commits inside the result root."""

    provenance = output_root / "provenance"
    provenance.mkdir(parents=True, exist_ok=True)
    config_copy = provenance / config_path.name
    if config_copy.exists():
        if sha256_file(config_copy) != config_hash:
            raise FourPartAddendumError("Output provenance config changed")
    else:
        shutil.copy2(config_path, config_copy)
        write_hash(config_copy)
    parent_copy = provenance / parent_config_path.name
    parent_bytes = parent_config_path.read_bytes()
    if parent_copy.exists():
        if parent_copy.read_bytes() != parent_bytes:
            raise FourPartAddendumError("Output parent-config provenance changed")
    else:
        shutil.copy2(parent_config_path, parent_copy)
        write_hash(parent_copy)
    record_path = provenance / "source_checkpoint.json"
    record = {
        "schema_version": "four_part_source_checkpoint_v1",
        "code_commit": code_commit,
        "parent_commit": parent_commit,
        "addendum_config_hash": config_hash,
        "old_e1_e6_overwritten": False,
    }
    if record_path.exists():
        if read_json(record_path) != record:
            raise FourPartAddendumError("Output source checkpoint changed between phases")
    else:
        write_json(record_path, record)
        write_hash(record_path)


def _phase_start(root: Path, phase: str, config_hash: str, resume: bool) -> Path:
    if phase not in PHASES:
        raise FourPartAddendumError(f"Unknown phase: {phase}")
    directory = root / phase
    marker = directory / "RUN_STATE.json"
    if marker.exists():
        state = read_json(marker)
        if state.get("config_hash") != config_hash:
            raise FourPartAddendumError(f"{phase} state belongs to another config")
        if state.get("status") == "pass":
            raise FourPartAddendumError(f"{phase} is complete; overwrite is forbidden")
        if not resume:
            raise FourPartAddendumError(f"{phase} is incomplete; rerun with --resume")
    elif directory.exists() and any(directory.iterdir()):
        raise FourPartAddendumError(f"Untracked nonempty phase directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    write_json(
        marker,
        {
            "schema_version": "four_part_phase_state_v1",
            "phase": phase,
            "status": "incomplete",
            "config_hash": config_hash,
            "started_unix_time": time.time(),
            "old_e1_e6_overwritten": False,
        },
    )
    return directory


def _phase_finish(directory: Path, audit: Mapping[str, object]) -> None:
    if audit.get("status") != "pass":
        raise FourPartAddendumError("Cannot finish a non-passing phase")
    audit_path = directory / "PHASE_AUDIT.json"
    write_json(audit_path, audit)
    audit_hash = write_hash(audit_path)
    write_json(
        directory / "RUN_STATE.json",
        {
            "schema_version": "four_part_phase_state_v1",
            "phase": directory.name,
            "status": "pass",
            "config_hash": audit["config_hash"],
            "audit_hash": audit_hash,
            "completed_unix_time": time.time(),
            "old_e1_e6_overwritten": False,
        },
    )


def _manifest_row_by_id(data_root: Path, tier: str) -> dict[str, dict[str, str]]:
    return {
        row["instance_id"]: row
        for row in read_csv(data_root / "manifests" / f"{tier}_v1.csv")
    }


def _canonical_instance(data_root: Path, row: Mapping[str, str]) -> tuple[str, int, Polynomial]:
    path = data_root / row["canonical_file"]
    payload = read_json(path)
    polynomial = canonicalize(
        (tuple(item["support"]), item["coefficient"])
        for item in payload["terms"]  # type: ignore[index]
    )
    return str(payload["family"]), int(row["n"]), polynomial


def load_fibre_moments(path: Path, *, tier: str | None = None) -> dict[str, FibreMoments]:
    records = read_json(path).get("records")
    if not isinstance(records, list):
        raise FourPartAddendumError("Malformed frozen moment bundle")
    output: dict[str, FibreMoments] = {}
    for row in records:
        if tier is not None and row.get("tier") != tier:
            continue
        output[str(row["instance_id"])] = FibreMoments(
            objective=float(row["objective"]),
            singles={int(key): float(value) for key, value in row["singles"].items()},
            pairs={
                tuple(int(value) for value in key.split(",")): float(item)
                for key, item in row["pairs"].items()
            },
            status=str(row["status"]),
            solver_message="loaded_frozen_v2",
            primary_runtime_sec=float(row["primary_runtime_sec"]),
            secondary_runtime_sec=float(row["secondary_runtime_sec"]),
            moment_sha256=str(row["moment_sha256"]),
        )
    return output


def _fraction(value: object) -> Fraction:
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _partial_resource_lower_bound(
    canonical: Polynomial,
    cubics: Sequence[Support],
    prefix: Sequence[Support | None],
    selector: Mapping[str, object],
    margin: float,
) -> tuple[Fraction, int, Fraction]:
    active = sorted({item for item in prefix if item is not None})
    assigned: dict[Support, list[Fraction]] = {pair: [] for pair in active}
    for cubic, action in zip(cubics, prefix):
        if action is not None:
            assigned[action].append(_fraction(canonical[cubic]))
    maximum = Fraction(0)
    for coefficients in assigned.values():
        positive = sum((value for value in coefficients if value > 0), Fraction(0))
        negative = sum((-value for value in coefficients if value < 0), Fraction(0))
        maximum = max(maximum, max(positive, negative) + _fraction(margin))
    weights = selector["weights"]  # type: ignore[index]
    scales = selector["scales"]  # type: ignore[index]
    lower = (
        _fraction(weights["auxiliary_count"]) * len(active) / _fraction(scales["auxiliary_count"])
        + _fraction(weights["maximum_penalty"]) * maximum / _fraction(scales["maximum_penalty"])
    )
    return lower, len(active), maximum


@dataclass(frozen=True)
class BranchAndBoundCertificate:
    result: FibreSearchResult
    trace: tuple[dict[str, object], ...]
    explored_nodes: int
    evaluated_leaves: int
    pruned_by_bound: int
    pruned_by_capacity: int
    proof_complete: bool
    final_lower_bound: Fraction
    final_upper_bound: Fraction
    runtime_sec: float


def branch_and_bound_fibre_optimum(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    moments: FibreMoments,
    trace_interval_nodes: int = 256,
    apply_qaoa_hard_limits: bool = True,
) -> BranchAndBoundCertificate:
    """Certify the fibre-aware optimum with a genuine best-bound tree search."""

    from .e2_resources import _action_key

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    fibre = selector["fibre_risk"]  # type: ignore[index]
    margin = float(fibre["positive_penalty_margin"])
    tau = float(fibre["threshold_tau"])
    normalisation = fibre_normalisation(canonical, positive_margin=margin)
    limits = selector["feasibility_limits"]  # type: ignore[index]
    initial_actions = (None,) * len(cubics)
    incumbent = _candidate(
        canonical,
        cubics,
        n_original=n_original,
        actions=initial_actions,
        selector=selector,
        moments=moments,
        normalisation=normalisation,
        tau=tau,
        positive_margin=margin,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if not incumbent.feasible:
        raise FourPartAddendumError("All-native certification incumbent is infeasible")

    counter = 0
    heap: list[tuple[Fraction, tuple[int, ...], int, tuple[Support | None, ...]]] = []
    heapq.heappush(heap, (Fraction(0), (), counter, ()))
    explored = leaves = pruned_bound = pruned_capacity = 0
    trace: list[dict[str, object]] = []

    def incumbent_key(item: FibreCandidate) -> tuple[object, ...]:
        return (item.score, item.risk.normalised_excess, _action_key(cubics, item.actions))

    def sample(event: str, current_lower: Fraction) -> None:
        upper = incumbent.score
        trace.append(
            {
                "event": event,
                "elapsed_sec": time.perf_counter() - started,
                "explored_nodes": explored,
                "evaluated_leaves": leaves,
                "frontier_nodes": len(heap),
                "lower_bound": float(current_lower),
                "upper_bound": float(upper),
                "gap": float(max(Fraction(0), upper - current_lower)),
            }
        )

    sample("initial_incumbent", Fraction(0))
    while heap:
        lower, action_key, _, prefix = heapq.heappop(heap)
        explored += 1
        if lower > incumbent.score:
            pruned_bound += 1
            continue
        depth = len(prefix)
        if depth == len(cubics):
            leaves += 1
            item = _candidate(
                canonical,
                cubics,
                n_original=n_original,
                actions=prefix,
                selector=selector,
                moments=moments,
                normalisation=normalisation,
                tau=tau,
                positive_margin=margin,
                apply_qaoa_hard_limits=apply_qaoa_hard_limits,
            )
            if item.feasible and incumbent_key(item) < incumbent_key(incumbent):
                incumbent = item
                frontier_lower = heap[0][0] if heap else incumbent.score
                sample("incumbent_update", min(frontier_lower, incumbent.score))
        else:
            for option_index, action in enumerate(action_options(cubics[depth])):
                child = prefix + (action,)
                child_lower, active, partial_penalty = _partial_resource_lower_bound(
                    canonical, cubics, child, selector, margin
                )
                if apply_qaoa_hard_limits and (
                    n_original + active > int(limits["maximum_qubits"])
                    or partial_penalty > _fraction(limits["maximum_penalty"])
                ):
                    pruned_capacity += 1
                    continue
                if child_lower > incumbent.score:
                    pruned_bound += 1
                    continue
                counter += 1
                heapq.heappush(
                    heap,
                    (child_lower, action_key + (option_index,), counter, child),
                )
        if trace_interval_nodes > 0 and explored % trace_interval_nodes == 0:
            frontier_lower = heap[0][0] if heap else incumbent.score
            sample("node_interval", min(frontier_lower, incumbent.score))

    runtime = time.perf_counter() - started
    evaluation = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=incumbent.actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if evaluation.score != incumbent.score:
        raise FourPartAddendumError("B&B fast and reference scores differ")
    result = FibreSearchResult(
        actions=incumbent.actions,
        evaluation=evaluation,
        risk=incumbent.risk,
        status="certified_branch_and_bound_fibre_aware_optimum",
        candidate_evaluations=leaves,
        runtime_sec=runtime,
        certified_optimum_score=incumbent.score,
        regret=Fraction(0),
    )
    sample("proof_complete", incumbent.score)
    return BranchAndBoundCertificate(
        result=result,
        trace=tuple(trace),
        explored_nodes=explored,
        evaluated_leaves=leaves,
        pruned_by_bound=pruned_bound,
        pruned_by_capacity=pruned_capacity,
        proof_complete=True,
        final_lower_bound=incumbent.score,
        final_upper_bound=incumbent.score,
        runtime_sec=runtime,
    )


def _actions_payload(actions: Sequence[Support | None]) -> list[list[int] | None]:
    return [None if action is None else list(action) for action in actions]


def _certification_table(rows: Sequence[Mapping[str, object]]) -> str:
    lines = [
        "% Auto-generated B&B certification summary.",
        "\\begin{tabular}{llrrrrrr}",
        "\\toprule",
        "Family & Proof & $N$ & Median nodes & Max nodes & Median time (s) & Max gap & Matches frozen \\\\",
        "\\midrule",
    ]
    for family in sorted({str(row["family"]) for row in rows}):
        group = [row for row in rows if row["family"] == family]
        lines.append(
            f"{family.replace('_', '\\_')} & all & {len(group)} & "
            f"{statistics.median(float(row['explored_nodes']) for row in group):.0f} & "
            f"{max(int(row['explored_nodes']) for row in group)} & "
            f"{statistics.median(float(row['runtime_sec']) for row in group):.3f} & "
            f"{max(float(row['final_gap']) for row in group):.2e} & "
            f"{sum(bool(row['matches_frozen_optimum']) for row in group)}/{len(group)} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _certificate_pdf(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    width, height = landscape(A4)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    pdf.setTitle("Branch-and-bound certification gaps")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(42, height - 42, "Certification: gap versus elapsed time")
    left, bottom, chart_w, chart_h = 65, 65, width - 110, height - 140
    pdf.setStrokeColor(colors.grey)
    pdf.rect(left, bottom, chart_w, chart_h)
    traces = [read_csv(Path(str(row["trace_file"]))) for row in rows]
    max_time = max((float(point["elapsed_sec"]) for trace in traces for point in trace), default=1.0)
    max_gap = max((float(point["gap"]) for trace in traces for point in trace), default=1.0)
    max_time = max(max_time, 1e-12)
    max_gap = max(max_gap, 1e-12)
    palette = {"cubic_spin_glass": colors.HexColor("#1F77B4"), "max3sat": colors.HexColor("#E67E22")}
    for row, trace in zip(rows, traces):
        pdf.setStrokeColor(palette[str(row["family"])])
        points = [
            (
                left + chart_w * float(point["elapsed_sec"]) / max_time,
                bottom + chart_h * float(point["gap"]) / max_gap,
            )
            for point in trace
        ]
        for first, second in zip(points, points[1:]):
            pdf.line(first[0], first[1], second[0], second[1])
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left, 42, f"Elapsed time (seconds), max={max_time:.3g}")
    pdf.drawString(5, bottom + chart_h / 2, f"Gap / max={max_gap:.3g}")
    pdf.save()


def run_certification(
    *,
    repo: Path,
    output_root: Path,
    config: Mapping[str, object],
    config_hash: str,
    parent: Mapping[str, object],
    code_commit: str,
    resume: bool,
) -> None:
    directory = _phase_start(output_root, "certification", config_hash, resume)
    data_root = repo / "data"
    rows_by_id = _manifest_row_by_id(data_root, "oracle")
    moments = load_fibre_moments(repo / "fibre_selector_v2" / "sa_rlt_moments_v2.json", tier="oracle")
    frozen_records = {
        str(row["instance_id"]): row
        for row in read_json(repo / "fibre_selector_v2" / "oracle_representation_designs_v2.json")["records"]  # type: ignore[index]
    }
    results: list[dict[str, object]] = []
    trace_fields = (
        "event", "elapsed_sec", "explored_nodes", "evaluated_leaves", "frontier_nodes",
        "lower_bound", "upper_bound", "gap",
    )
    for instance_id, manifest in sorted(rows_by_id.items()):
        record_path = directory / "instances" / f"{instance_id}.json"
        trace_path = directory / "traces" / f"{instance_id}.csv"
        if resume and record_path.exists() and trace_path.exists():
            row = read_json(record_path)
            row["trace_file"] = str(trace_path)
            results.append(row)
            continue
        family, n_original, polynomial = _canonical_instance(data_root, manifest)
        certificate = branch_and_bound_fibre_optimum(
            polynomial,
            n_original=n_original,
            selector=parent["selector"],  # type: ignore[arg-type,index]
            moments=moments[instance_id],
            trace_interval_nodes=int(config["certification"]["trace_interval_nodes"]),  # type: ignore[index]
        )
        frozen = frozen_records[instance_id]["selected"]
        row = {
            "instance_id": instance_id,
            "family": family,
            "n_original": n_original,
            "cubic_count": len(cubic_supports(polynomial)),
            "proof_complete": certificate.proof_complete,
            "lower_bound": float(certificate.final_lower_bound),
            "upper_bound": float(certificate.final_upper_bound),
            "final_gap": float(certificate.final_upper_bound - certificate.final_lower_bound),
            "explored_nodes": certificate.explored_nodes,
            "evaluated_leaves": certificate.evaluated_leaves,
            "pruned_by_bound": certificate.pruned_by_bound,
            "pruned_by_capacity": certificate.pruned_by_capacity,
            "runtime_sec": certificate.runtime_sec,
            "selected_actions": _actions_payload(certificate.result.actions),
            "matches_frozen_optimum": abs(float(frozen["certified_optimum_score"]) - float(certificate.final_upper_bound)) <= 1e-12,
            "config_hash": config_hash,
            "code_commit": code_commit,
        }
        write_csv(trace_path, certificate.trace, trace_fields)
        write_hash(trace_path)
        write_json(record_path, row)
        write_hash(record_path)
        row["trace_file"] = str(trace_path)
        results.append(row)
    public_rows = [{key: value for key, value in row.items() if key != "trace_file"} for row in results]
    fields = tuple(public_rows[0])
    summary_path = directory / "certification_instances.csv"
    write_csv(summary_path, public_rows, fields)
    write_hash(summary_path)
    table_path = directory / "certificate_summary_table.tex"
    table_path.write_text(_certification_table(public_rows), encoding="utf-8", newline="\n")
    write_hash(table_path)
    figure_path = directory / "gap_versus_time.pdf"
    _certificate_pdf(figure_path, results)
    write_hash(figure_path)
    passed = (
        len(public_rows) == 60
        and all(bool(row["proof_complete"]) for row in public_rows)
        and all(float(row["final_gap"]) == 0 for row in public_rows)
        and all(bool(row["matches_frozen_optimum"]) for row in public_rows)
    )
    audit = {
        "schema_version": "certification_addendum_audit_v1",
        "status": "pass" if passed else "fail",
        "instance_count": len(public_rows),
        "proof_count": sum(bool(row["proof_complete"]) for row in public_rows),
        "zero_gap_count": sum(float(row["final_gap"]) == 0 for row in public_rows),
        "matches_frozen_optimum_count": sum(bool(row["matches_frozen_optimum"]) for row in public_rows),
        "algorithm": "best_bound_branch_and_bound_with_monotone_resource_lower_bound",
        "config_hash": config_hash,
        "code_commit": code_commit,
        "old_e1_e6_overwritten": False,
    }
    _phase_finish(directory, audit)


def topology_definitions(config: Mapping[str, object]) -> dict[str, dict[str, object]]:
    items = config["additional_topologies"]["architectures"]  # type: ignore[index]
    output: dict[str, dict[str, object]] = {}
    for item in items:  # type: ignore[union-attr]
        edges = [tuple(int(value) for value in edge) for edge in item["coupling_map"]]
        output[str(item["id"])] = {"capacity": int(item["capacity"]), "coupling_map": edges}
    return output


def compile_topology_design(
    evaluation,
    *,
    compiler_config: Mapping[str, object],
    topology_id: str,
    capacity: int,
    coupling_map: Sequence[tuple[int, int]],
    transpiler_seed: int,
) -> dict[str, object]:
    if evaluation.representation.n_qubits > capacity:
        return {
            "topology_capacity": capacity, "two_qubit_gates": "", "two_qubit_depth": "",
            "swap_count": "", "swap_count_method": "not_applicable_width_infeasible",
            "routing_overhead": "", "compile_runtime_sec": 0.0,
            "status": "infeasible_width_exceeds_topology", "failure_kind": "expected_capacity_failure",
            "failure_message": f"logical width {evaluation.representation.n_qubits} exceeds {topology_id} capacity {capacity}",
            "qiskit_version": str(compiler_config["software"]["qiskit_version"]),  # type: ignore[index]
        }
    import qiskit
    from qiskit import transpile
    from qiskit.transpiler import CouplingMap

    expected = str(compiler_config["software"]["qiskit_version"])  # type: ignore[index]
    if qiskit.__version__ != expected:
        raise FourPartAddendumError(f"Qiskit version mismatch: {qiskit.__version__} != {expected}")
    circuit = _qiskit_cost_circuit(evaluation)
    observed_swaps: list[int] = []

    def callback(**kwargs):
        dag = kwargs.get("dag")
        pass_object = kwargs.get("pass_")
        if dag is not None and pass_object is not None:
            counts = dag.count_ops()
            if counts.get("swap", 0) or "routing" in pass_object.__class__.__name__.lower():
                observed_swaps.append(int(counts.get("swap", 0)))

    started = time.perf_counter()
    try:
        compiled = transpile(
            circuit,
            basis_gates=list(compiler_config["basis_gates"]),  # type: ignore[index]
            coupling_map=CouplingMap(list(coupling_map)),
            optimization_level=int(compiler_config["optimization_level"]),
            layout_method=str(compiler_config["layout_method"]),
            routing_method=str(compiler_config["routing_method"]),
            translation_method=str(compiler_config["translation_method"]),
            seed_transpiler=transpiler_seed,
            callback=callback,
        )
    except Exception as error:
        return {
            "topology_capacity": capacity, "two_qubit_gates": "", "two_qubit_depth": "",
            "swap_count": "", "swap_count_method": "compiler_failed", "routing_overhead": "",
            "compile_runtime_sec": time.perf_counter() - started, "status": "compiler_failure",
            "failure_kind": error.__class__.__name__, "failure_message": str(error)[:500],
            "qiskit_version": qiskit.__version__,
        }
    runtime = time.perf_counter() - started
    gates = sum(len(item.qubits) == 2 for item in compiled.data)
    depth = _two_qubit_depth(compiled)
    overhead = gates - evaluation.reference.two_qubit_gate_count
    swaps = max(observed_swaps, default=0)
    method = "routing_pass_callback"
    if swaps == 0 and overhead > 0:
        swaps = max(0, overhead // 3)
        method = "post_translation_cx_overhead_equivalent_floor"
    edges = set(coupling_map)
    for item in compiled.data:
        if len(item.qubits) == 2:
            endpoint = tuple(compiled.find_bit(qubit).index for qubit in item.qubits)
            if endpoint not in edges:
                raise FourPartAddendumError(f"Compiled edge {endpoint} violates {topology_id}")
    return {
        "topology_capacity": capacity, "two_qubit_gates": gates, "two_qubit_depth": depth,
        "swap_count": swaps, "swap_count_method": method, "routing_overhead": overhead,
        "compile_runtime_sec": runtime, "status": "pass", "failure_kind": "",
        "failure_message": "", "qiskit_version": qiskit.__version__,
    }


def _logical_designs_from_bundle(
    *,
    record: Mapping[str, object],
    polynomial: Polynomial,
    n_original: int,
    selector: Mapping[str, object],
) -> list[tuple[str, int | None, object]]:
    selected = record["selected"]
    result = [
        (
            "selective", None,
            _evaluate_design(polynomial, n_original=n_original, actions=deserialize_actions(selected["actions"]), selector=selector, apply_qaoa_hard_limits=False),  # type: ignore[index]
        )
    ]
    for item in record["matched_random"]:  # type: ignore[index]
        result.append(
            (
                "matched_random_selective", int(item["random_rep_seed"]),
                _evaluate_design(polynomial, n_original=n_original, actions=deserialize_actions(item["actions"]), selector=selector, apply_qaoa_hard_limits=False),
            )
        )
    return result


def run_topologies(
    *,
    repo: Path,
    output_root: Path,
    config: Mapping[str, object],
    config_hash: str,
    parent: Mapping[str, object],
    code_commit: str,
    resume: bool,
) -> None:
    directory = _phase_start(output_root, "topologies", config_hash, resume)
    data_root = repo / "data"
    manifests = _manifest_row_by_id(data_root, "compilation")
    bundle = read_json(repo / "fibre_selector_v2" / "compilation_representation_designs_v2.json")
    records = {str(item["instance_id"]): item for item in bundle["records"]}  # type: ignore[index]
    compiler = parent["compiler"]  # type: ignore[index]
    topology_map = topology_definitions(config)
    seeds = [int(seed) for seed in compiler["transpiler_seed_bundle"]]  # type: ignore[index]
    raw_rows: list[dict[str, object]] = []
    protocol_id = "four_part_addendum_topologies_v1"
    for instance_id, manifest in sorted(manifests.items()):
        family, n_original, polynomial = _canonical_instance(data_root, manifest)
        designs = _logical_designs_from_bundle(
            record=records[instance_id], polynomial=polynomial, n_original=n_original,
            selector=parent["selector"],  # type: ignore[index]
        )
        for representation, random_seed, evaluation in designs:
            rep = evaluation.representation
            common = {
                "instance_id": instance_id, "family": family, "split": manifest["split"],
                "representation": representation, "random_rep_seed": random_seed or "",
                "design_id": "design_" + hashlib.sha256(json.dumps(_actions_payload(evaluation.actions), separators=(",", ":")).encode()).hexdigest()[:20],
                "n_original": n_original, "n_aux": rep.n_auxiliary, "n_qubits": rep.n_qubits,
                "retained_cubic": len(cubic_supports(rep.polynomial)),
                "quadratic_couplings": sum(len(support) == 2 for support in rep.polynomial),
                "M_max": float(max(rep.penalties.values(), default=0)),
                "coefficient_dynamic_range": max((abs(float(value)) for value in rep.polynomial.values()), default=0),
                "compiler_protocol_id": protocol_id, "config_hash": config_hash,
                "manifest_hash": sha256_file(data_root / "manifests" / "compilation_v1.csv"),
                "code_commit": code_commit,
            }
            for topology_id, topology in topology_map.items():
                for seed in seeds:
                    compiled = compile_topology_design(
                        evaluation, compiler_config=compiler, topology_id=topology_id,
                        capacity=int(topology["capacity"]), coupling_map=topology["coupling_map"],  # type: ignore[arg-type]
                        transpiler_seed=seed,
                    )
                    raw_rows.append({**common, "topology_id": topology_id, "transpiler_seed": seed, **compiled})
    raw_path = directory / "additional_topology_compiled_by_seed.csv"
    write_csv(raw_path, raw_rows, COMPILED_FIELDS)
    write_hash(raw_path)
    old_rows = read_csv(repo / "fibre_e1_e6_v2" / "results" / "e2_compiled_resources_by_seed.csv")
    old_relevant = [row for row in old_rows if row["representation"] in {"selective", "matched_random_selective"}]
    combined = old_relevant + [{key: value for key, value in row.items()} for row in raw_rows]
    summary = summarise_compiled_rows(combined)
    summary_path = directory / "e2_all_topology_summary.csv"
    write_csv(summary_path, summary)
    write_hash(summary_path)
    test_ids = {instance_id for instance_id, row in manifests.items() if row["split"] == "test"}
    e5_rows = []
    for row in raw_rows:
        if row["instance_id"] in test_ids:
            e5_rows.append({
                "instance_id": row["instance_id"], "family": row["family"], "topology_id": row["topology_id"],
                "representation": row["representation"], "transpiler_seed": row["transpiler_seed"],
                "two_qubit_gates": row["two_qubit_gates"], "two_qubit_depth": row["two_qubit_depth"],
                "swap_count": row["swap_count"], "routing_overhead": row["routing_overhead"],
                "status": row["status"], "failure_kind": row["failure_kind"],
            })
    e5_path = directory / "e5_additional_topology_instance_inputs.csv"
    write_csv(e5_path, e5_rows)
    write_hash(e5_path)
    audit = {
        "schema_version": "additional_topology_audit_v1", "status": "pass",
        "scheduled_row_count": len(raw_rows), "topology_ids": sorted(topology_map),
        "representation_ids": sorted({str(row["representation"]) for row in raw_rows}),
        "transpiler_seed_count": len(seeds), "old_rows_reused_read_only": len(old_relevant),
        "qaoa_runs_executed": 0, "config_hash": config_hash, "code_commit": code_commit,
        "old_e1_e6_overwritten": False,
    }
    _phase_finish(directory, audit)


def _selector_variant(parent_selector: Mapping[str, object], changes: Mapping[str, object]) -> dict[str, object]:
    value = json.loads(json.dumps(parent_selector))
    for path, item in changes.items():
        node = value
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = item
    return value


def max_reuse_actions(polynomial: Mapping[Support, object]) -> tuple[Support | None, ...]:
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    counts = Counter(pair for cubic in cubics for pair in action_options(cubic) if pair is not None)
    return tuple(
        min((pair for pair in action_options(cubic) if pair is not None), key=lambda pair: (-counts[pair], pair))
        for cubic in cubics
    )


def selector_ablation_variants(config: Mapping[str, object]) -> list[dict[str, object]]:
    settings = config["selector_ablation"]  # type: ignore[index]
    main = settings["main"]
    variants: list[dict[str, object]] = [{"variant_id": "main", **main}]
    for weight in settings["weight_variants"]:
        variants.append({"variant_id": str(weight["id"]), **main, "weights": weight["weights"]})
    for width in settings["beam_widths"]:
        if int(width) != int(main["beam_width"]):
            variants.append({"variant_id": f"beam_{width}", **main, "beam_width": int(width)})
    for threshold in settings["fibre_thresholds"]:
        if float(threshold) != float(main["fibre_threshold"]):
            variants.append({"variant_id": f"tau_{threshold}", **main, "fibre_threshold": float(threshold)})
    for margin in settings["penalty_margins"]:
        if float(margin) != float(main["penalty_margin"]):
            variants.append({"variant_id": f"margin_{margin}", **main, "penalty_margin": float(margin)})
    return variants


def run_selector_ablation(
    *,
    repo: Path,
    output_root: Path,
    config: Mapping[str, object],
    config_hash: str,
    parent: Mapping[str, object],
    code_commit: str,
    resume: bool,
) -> None:
    directory = _phase_start(output_root, "selector_ablation", config_hash, resume)
    data_root = repo / "data"
    manifests = _manifest_row_by_id(data_root, "oracle")
    moments = load_fibre_moments(repo / "fibre_selector_v2" / "sa_rlt_moments_v2.json", tier="oracle")
    variants = selector_ablation_variants(config)
    rows: list[dict[str, object]] = []
    for instance_id, manifest in sorted(manifests.items()):
        family, n_original, polynomial = _canonical_instance(data_root, manifest)
        for variant in variants:
            selector = _selector_variant(
                parent["selector"],  # type: ignore[arg-type,index]
                {
                    "weights": variant["weights"],
                    "search_settings.beam_width": variant["beam_width"],
                    "fibre_risk.threshold_tau": variant["fibre_threshold"],
                    "fibre_risk.positive_penalty_margin": variant["penalty_margin"],
                },
            )
            try:
                result = beam_select_fibre_design(
                    polynomial, n_original=n_original, selector=selector,
                    moments=moments[instance_id], apply_qaoa_hard_limits=True,
                )
                row = {
                    "instance_id": instance_id, "family": family, "variant_id": variant["variant_id"],
                    "method": "deterministic_pareto_beam", "weights_json": json.dumps(variant["weights"], sort_keys=True, separators=(",", ":")),
                    "beam_width": variant["beam_width"], "fibre_threshold": variant["fibre_threshold"],
                    "penalty_margin": variant["penalty_margin"], "status": "pass",
                    "resource_score": float(result.evaluation.score), "normalised_fibre_excess": result.risk.normalised_excess,
                    "n_auxiliary": result.evaluation.representation.n_auxiliary,
                    "two_qubit_gates": result.evaluation.reference.two_qubit_gate_count,
                    "two_qubit_depth": result.evaluation.reference.two_qubit_depth,
                    "maximum_penalty": float(max(result.evaluation.representation.penalties.values(), default=0)),
                    "actions_json": json.dumps(_actions_payload(result.actions), separators=(",", ":")),
                }
            except Exception as error:
                row = {
                    "instance_id": instance_id, "family": family, "variant_id": variant["variant_id"],
                    "method": "deterministic_pareto_beam", "weights_json": json.dumps(variant["weights"], sort_keys=True, separators=(",", ":")),
                    "beam_width": variant["beam_width"], "fibre_threshold": variant["fibre_threshold"],
                    "penalty_margin": variant["penalty_margin"], "status": "no_feasible_design",
                    "failure_kind": error.__class__.__name__, "failure_message": str(error)[:300],
                }
            row.update({"config_hash": config_hash, "code_commit": code_commit})
            rows.append(row)
        main_selector = parent["selector"]  # type: ignore[index]
        for method in ("greedy", "maximum_reuse"):
            if method == "greedy":
                result = greedy_select_fibre_design(
                    polynomial, n_original=n_original, selector=main_selector,
                    moments=moments[instance_id], apply_qaoa_hard_limits=True,
                )
                actions = result.actions
                score = result.evaluation.score
                risk = result.risk.normalised_excess
                evaluation = result.evaluation
                feasible = True
            else:
                actions = max_reuse_actions(polynomial)
                candidate = _candidate(
                    canonicalize(polynomial), tuple(sorted(cubic_supports(polynomial))),
                    n_original=n_original, actions=actions, selector=main_selector,
                    moments=moments[instance_id],
                    normalisation=fibre_normalisation(polynomial, positive_margin=1.0),
                    tau=0.02, positive_margin=1.0, apply_qaoa_hard_limits=True,
                )
                evaluation = _evaluate_design(polynomial, n_original=n_original, actions=actions, selector=main_selector, apply_qaoa_hard_limits=True)
                score, risk, feasible = candidate.score, candidate.risk.normalised_excess, candidate.feasible
            rows.append({
                "instance_id": instance_id, "family": family, "variant_id": f"baseline_{method}",
                "method": method, "weights_json": json.dumps(config["selector_ablation"]["main"]["weights"], sort_keys=True, separators=(",", ":")),  # type: ignore[index]
                "beam_width": "not_applicable", "fibre_threshold": 0.02, "penalty_margin": 1.0,
                "status": "pass" if feasible else "infeasible_baseline", "resource_score": float(score),
                "normalised_fibre_excess": risk, "n_auxiliary": evaluation.representation.n_auxiliary,
                "two_qubit_gates": evaluation.reference.two_qubit_gate_count,
                "two_qubit_depth": evaluation.reference.two_qubit_depth,
                "maximum_penalty": float(max(evaluation.representation.penalties.values(), default=0)),
                "actions_json": json.dumps(_actions_payload(actions), separators=(",", ":")),
                "config_hash": config_hash, "code_commit": code_commit,
            })
    fields = sorted({key for row in rows for key in row})
    raw_path = directory / "selector_ablation_raw.csv"
    write_csv(raw_path, rows, fields)
    write_hash(raw_path)
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["family"]), str(row["variant_id"]))].append(row)
    summary = []
    for (family, variant), group in sorted(grouped.items()):
        passing = [row for row in group if row["status"] == "pass"]
        summary.append({
            "family": family, "variant_id": variant, "instance_count": len(group),
            "pass_count": len(passing), "feasible_fraction": len(passing) / len(group),
            "resource_score_mean": statistics.fmean(float(row["resource_score"]) for row in passing) if passing else "",
            "fibre_excess_mean": statistics.fmean(float(row["normalised_fibre_excess"]) for row in passing) if passing else "",
            "n_auxiliary_mean": statistics.fmean(float(row["n_auxiliary"]) for row in passing) if passing else "",
            "config_hash": config_hash, "code_commit": code_commit,
        })
    summary_path = directory / "selector_ablation_summary.csv"
    write_csv(summary_path, summary)
    write_hash(summary_path)
    audit = {
        "schema_version": "selector_ablation_audit_v1", "status": "pass",
        "instance_count": len(manifests), "variant_count": len(variants), "baseline_count": 2,
        "old_qaoa_runs_executed": 0, "main_setting_changed": False,
        "config_hash": config_hash, "code_commit": code_commit, "old_e1_e6_overwritten": False,
    }
    _phase_finish(directory, audit)


def rank_strong_bias_candidates(rows: Sequence[Mapping[str, object]], take_per_family: int) -> list[dict[str, object]]:
    forbidden = {key for row in rows for key in row if "qaoa" in key.lower() or key in {"original_objective_mean", "optimum_hit_rate"}}
    if forbidden:
        raise FourPartAddendumError(f"QAOA outcome leaked into screening: {sorted(forbidden)}")
    selected: list[dict[str, object]] = []
    families = sorted({str(row["family"]) for row in rows})
    for family in families:
        group = [dict(row) for row in rows if row["family"] == family and int(row["active_auxiliary_count"]) > 0]
        group.sort(
            key=lambda row: (
                -float(row["median_abs_single_margin"]),
                -float(row["mean_active_pair_dependence"]),
                str(row["instance_id"]),
            )
        )
        for rank, row in enumerate(group[:take_per_family], start=1):
            row["screening_rank"] = rank
            selected.append(row)
    return selected


def _strong_bias_pool(config: Mapping[str, object]) -> Iterable[dict[str, object]]:
    settings = config["strong_bias"]  # type: ignore[index]
    master = int(settings["master_seed"])
    maximum = int(settings["candidate_pool_per_family"])
    n_values = [int(value) for value in settings["n_values"]]
    modes = [str(value) for value in settings["generator_modes"]]
    spin_values = [float(value) for value in settings["spin_hyperedges_per_variable"]]
    sat_values = [float(value) for value in settings["max3sat_clause_densities"]]
    for family in ("cubic_spin_glass", "max3sat"):
        for index in range(maximum):
            n = n_values[index % len(n_values)]
            mode = modes[(index // len(n_values)) % len(modes)]
            if family == "cubic_spin_glass":
                regime = spin_values[(index // (len(n_values) * len(modes))) % len(spin_values)]
                seed = derive_seed(master, family, index, n, mode, regime)
                try:
                    yield generate_spin_glass(
                        n=n, hyperedges_per_variable=regime, generator_mode=mode,
                        master_seed=master, instance_seed=seed, generator_version="four_part_strong_bias_v1",
                    )
                except RuntimeError:
                    # Some dense anchor-pair combinations cannot span the
                    # requested hyperedge count.  The fixed attempt ordinal is
                    # retained, and the failure is data-free/QAOA-free.
                    continue
            else:
                regime = sat_values[(index // (len(n_values) * len(modes))) % len(sat_values)]
                seed = derive_seed(master, family, index, n, mode, regime)
                try:
                    yield generate_max3sat(
                        n=n, clause_density=regime, generator_mode=mode,
                        master_seed=master, instance_seed=seed, generator_version="four_part_strong_bias_v1",
                    )
                except RuntimeError:
                    continue


def _relaxation_as_e4(moments: FibreMoments) -> RelaxationMoments:
    return RelaxationMoments(
        objective=moments.objective, singles=moments.singles, pairs=moments.pairs,
        status=moments.status, solver_message=moments.solver_message,
        runtime_sec=moments.primary_runtime_sec + moments.secondary_runtime_sec,
    )


def run_strong_bias(
    *,
    repo: Path,
    output_root: Path,
    config: Mapping[str, object],
    config_hash: str,
    parent: Mapping[str, object],
    code_commit: str,
    resume: bool,
) -> None:
    directory = _phase_start(output_root, "strong_bias", config_hash, resume)
    raw_dir = directory / "selected_instances" / "raw"
    canonical_dir = directory / "selected_instances" / "canonical"
    screening_rows: list[dict[str, object]] = []
    selected_objects: dict[str, tuple[dict[str, object], Polynomial, FibreMoments, FibreSearchResult]] = {}
    settings = config["strong_bias"]  # type: ignore[index]
    for instance in _strong_bias_pool(config):
        instance_id = str(instance["instance_id"])
        polynomial = polynomial_for_instance(instance)
        n_original = int(instance["problem"]["n"])  # type: ignore[index]
        moments = solve_deterministic_sa_rlt_level2(
            polynomial, n_original=n_original,
            primary_optimum_tolerance=float(parent["relaxation"]["optimum_face_tie_break"]["primary_optimum_tolerance"]),  # type: ignore[index]
        )
        try:
            selected = beam_select_fibre_design(
                polynomial, n_original=n_original, selector=parent["selector"],  # type: ignore[arg-type,index]
                moments=moments, apply_qaoa_hard_limits=True,
            )
        except Exception:
            continue
        active_pairs = tuple(selected.evaluation.representation.active_pairs)
        if not active_pairs or selected.evaluation.representation.n_qubits > int(parent["selector"]["feasibility_limits"]["maximum_qubits"]):  # type: ignore[index]
            continue
        clipping = float(parent["qaoa"]["warm_start"]["clipping_delta"])  # type: ignore[index]
        clip = lambda value: min(1.0 - clipping, max(clipping, float(value)))
        dependencies = [abs(clip(moments.pairs[pair]) - clip(moments.singles[pair[0]]) * clip(moments.singles[pair[1]])) for pair in active_pairs]
        screening_rows.append({
            "instance_id": instance_id, "family": instance["family"], "n_original": n_original,
            "active_auxiliary_count": len(active_pairs),
            "median_abs_single_margin": statistics.median(abs(value - 0.5) for value in moments.singles.values()),
            "mean_active_pair_dependence": statistics.fmean(dependencies),
            "relaxation_objective": moments.objective, "moment_sha256": moments.moment_sha256,
            "screening_source": "relaxation_signal_only", "config_hash": config_hash,
        })
        selected_objects[instance_id] = (instance, polynomial, moments, selected)
    screening_path = directory / "strong_bias_screening_pool.csv"
    write_csv(screening_path, screening_rows)
    write_hash(screening_path)
    chosen = rank_strong_bias_candidates(screening_rows, int(settings["selected_per_family"]))
    if Counter(str(row["family"]) for row in chosen) != Counter({"cubic_spin_glass": 10, "max3sat": 10}):
        raise FourPartAddendumError("Strong-bias screen did not produce 10 usable instances per family")
    selected_path = directory / "strong_bias_selected_instances.csv"
    write_csv(selected_path, chosen)
    write_hash(selected_path)
    run_rows: list[dict[str, object]] = []
    marginal_rows: list[dict[str, object]] = []
    budget_rows: list[dict[str, object]] = []
    optimizer = parent["qaoa"]["optimizer"]  # type: ignore[index]
    optimizer_seeds = [int(value) for value in optimizer["seed_bundle"]]  # type: ignore[index]
    circuit_seeds = [int(value) for value in parent["qaoa"]["circuit_seed_bundle"]]  # type: ignore[index]
    measurement_seeds = [int(value) for value in parent["qaoa"]["measurement_seed_bundle"]]  # type: ignore[index]
    for screen in chosen:
        instance_id = str(screen["instance_id"])
        instance, polynomial, fibre_moments, selected = selected_objects[instance_id]
        raw_path = raw_dir / str(instance["family"]) / f"{instance_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(stable_instance_json(instance), encoding="utf-8", newline="\n")
        write_hash(raw_path)
        canonical_payload = {
            "instance_id": instance_id, "family": instance["family"],
            "terms": [{"support": list(support), "coefficient": str(value)} for support, value in canonicalize(polynomial).items()],
        }
        canonical_path = canonical_dir / f"{instance_id}.json"
        write_json(canonical_path, canonical_payload)
        write_hash(canonical_path)
        e4_moments = _relaxation_as_e4(fibre_moments)
        design = QAOADesign("selective", None, selected.evaluation)
        compiled_gates = []
        from .e2_resources import compile_sparse_design
        for seed in parent["compiler"]["transpiler_seed_bundle"]:  # type: ignore[index]
            result = compile_sparse_design(selected.evaluation, compiler_config=parent["compiler"], transpiler_seed=int(seed))  # type: ignore[arg-type,index]
            if result["status"] != "pass":
                raise FourPartAddendumError(f"Strong-bias cost layer compile failed: {instance_id}")
            compiled_gates.append(int(result["two_qubit_gates"]))
        per_layer = int(statistics.median(compiled_gates))
        truth = exact_ground_truth(instance)
        optimum = float(truth["optimum_original"])
        data = statevector_data(polynomial, selected.evaluation.representation, optimum_original=optimum)
        budgets = [
            QAOABudgetSpec("equal_layer", "equal_layer_p1", 1, None, per_layer, per_layer),
            QAOABudgetSpec("equal_layer", "equal_layer_p2", 2, None, per_layer, 2 * per_layer),
        ]
        if bool(settings["include_budget_256"]):
            depth = 256 // per_layer
            if depth > 0:
                budgets.append(QAOABudgetSpec("equal_compiled_two_qubit_gates", "equal_2q_budget_256", depth, 256, per_layer, depth * per_layer))
        specs = warm_start_specs(design, e4_moments, clipping_delta=float(parent["qaoa"]["warm_start"]["clipping_delta"]))  # type: ignore[index]
        if len(specs) != 4:
            raise FourPartAddendumError("Strong-bias instance lacks all four warm-start policies")
        budget_rows.append({
            "instance_id": instance_id, "family": instance["family"], "n_aux": selected.evaluation.representation.n_auxiliary,
            "n_qubits": selected.evaluation.representation.n_qubits,
            "compiled_2q_gates_by_seed_json": json.dumps(compiled_gates, separators=(",", ":")),
            "compiled_2q_gates_per_layer": per_layer, "budget_keys_json": json.dumps([item.key for item in budgets], separators=(",", ":")),
            "config_hash": config_hash, "code_commit": code_commit,
        })
        marginal_rows.extend(marginal_diagnostic_rows(
            instance_id=instance_id, family=str(instance["family"]), moments=e4_moments,
            designs=[design], clipping_delta=float(parent["qaoa"]["warm_start"]["clipping_delta"]),  # type: ignore[index]
            config_hash=config_hash, manifest_hash=sha256_file(selected_path), code_commit=code_commit,
            solver_package="scipy.optimize.linprog", solver_method="highs_primary_then_sha256_optimum_face",
        ))
        for budget in budgets:
            for spec in specs:
                for restart_id in range(int(optimizer["restarts"])):
                    row = optimize_warmstart_run(
                        instance_id=instance_id, family=str(instance["family"]), design=design,
                        budget=budget, data=data, warm_spec=spec, moments=e4_moments,
                        restart_id=restart_id, optimizer_seed=optimizer_seeds[restart_id],
                        circuit_seed=circuit_seeds[restart_id], measurement_seed=measurement_seeds[restart_id],
                        qaoa_config=parent["qaoa"], config_hash=config_hash, manifest_hash=sha256_file(selected_path),  # type: ignore[arg-type,index]
                        e3_summary_hash="not_applicable_new_addendum", code_commit=code_commit,
                    )
                    run_rows.append(row)
    budget_path = directory / "strong_bias_budget_plan.csv"
    write_csv(budget_path, budget_rows)
    write_hash(budget_path)
    marginal_path = directory / "strong_bias_marginal_diagnostics.csv"
    write_csv(marginal_path, marginal_rows, MARGINAL_FIELDS)
    write_hash(marginal_path)
    run_path = directory / "strong_bias_warmstart_runs.csv"
    write_csv(run_path, run_rows, RUN_FIELDS)
    write_hash(run_path)
    if any(row["status"] != "pass" for row in run_rows) or any(int(row["p"]) == 0 for row in run_rows):
        raise FourPartAddendumError("Strong-bias run gate failed")
    summary = summarise_warmstart_runs(run_rows)
    summary_path = directory / "strong_bias_warmstart_summary.csv"
    write_csv(summary_path, summary, WARM_SUMMARY_FIELDS)
    write_hash(summary_path)
    table_path = directory / "strong_bias_warmstart_summary.tex"
    table_path.write_text(warm_latex_table(summary), encoding="utf-8", newline="\n")
    write_hash(table_path)
    figure_path = directory / "strong_bias_marginals.pdf"
    write_marginal_figure_pdf(figure_path, marginal_rows)
    write_hash(figure_path)
    audit = {
        "schema_version": "strong_bias_warmstart_audit_v1", "status": "pass",
        "selected_count": len(chosen), "selected_per_family": dict(Counter(str(row["family"]) for row in chosen)),
        "run_count": len(run_rows), "failed_run_count": 0,
        "policies": sorted({f"{row['warm_start_policy']}::{row['pair_closure']}" for row in run_rows}),
        "p_values": sorted({int(row["p"]) for row in run_rows}),
        "screening_used_qaoa_outcomes": False, "old_e3_e4_e6_rerun": False,
        "config_hash": config_hash, "code_commit": code_commit, "old_e1_e6_overwritten": False,
    }
    _phase_finish(directory, audit)


def build_result_pack(*, output_root: Path, config_hash: str) -> tuple[Path, Path]:
    zip_path = output_root.parent / "URSS_FOUR_PART_ADDENDUM_V1_RESULT_PACK.zip"
    sidecar = zip_path.with_suffix(zip_path.suffix + ".sha256")
    if zip_path.exists() or sidecar.exists():
        raise FourPartAddendumError("Final result pack already exists; overwrite is forbidden")
    audits = []
    for phase in PHASES:
        state_path = output_root / phase / "RUN_STATE.json"
        audit_path = output_root / phase / "PHASE_AUDIT.json"
        if not state_path.is_file() or not audit_path.is_file():
            raise FourPartAddendumError(f"Missing completed phase: {phase}")
        state = read_json(state_path)
        audit = read_json(audit_path)
        if state.get("status") != "pass" or audit.get("status") != "pass" or audit.get("config_hash") != config_hash:
            raise FourPartAddendumError(f"Phase gate failed: {phase}")
        audits.append(audit)
    final_audit = output_root / "FOUR_PART_ADDENDUM_FINAL_AUDIT.json"
    write_json(final_audit, {
        "schema_version": "four_part_addendum_final_audit_v1", "status": "pass",
        "phase_count": len(audits), "phase_ids": list(PHASES),
        "manifest_path": "SHA256_MANIFEST.csv",
        "config_hash": config_hash, "old_e1_e6_overwritten": False,
    })
    write_hash(final_audit)
    manifest_path = output_root / "SHA256_MANIFEST.csv"
    manifest_sidecar = manifest_path.with_suffix(manifest_path.suffix + ".sha256")
    rows = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path not in {manifest_path, manifest_sidecar}:
            rows.append({"relative_path": path.relative_to(output_root).as_posix(), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    write_csv(manifest_path, rows, ("relative_path", "sha256", "size_bytes"))
    write_hash(manifest_path)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(output_root.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    (Path(output_root.name) / path.relative_to(output_root)).as_posix(),
                )
    digest = write_hash(zip_path)
    if digest != sidecar.read_text(encoding="utf-8").strip():
        raise FourPartAddendumError("Final ZIP sidecar mismatch")
    return zip_path, sidecar
