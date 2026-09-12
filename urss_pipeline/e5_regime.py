"""Formal Step 7 / E5 sparsity-reuse-connectivity regime analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

import yaml


class E5RegimeError(RuntimeError):
    """Formal E5 cannot proceed or failed a mandatory protocol gate."""


INSTANCE_FIELDS = (
    "instance_id",
    "family",
    "source_tier",
    "split",
    "comparison",
    "metric",
    "budget_mode",
    "budget_key",
    "topology_id",
    "canonical_cubic_sparsity",
    "sparsity_bin",
    "pair_reuse_score",
    "pair_reuse_bin",
    "sign_balance_diagnostic",
    "n_original_diagnostic",
    "selected_observation_count",
    "control_observation_count",
    "paired_observation_count",
    "selected_mean",
    "control_mean",
    "effect",
    "effect_ci95_low",
    "effect_ci95_high",
    "effect_tolerance",
    "classification",
    "uncertainty_rule",
    "status",
    "failure_kind",
    "config_hash",
    "manifest_hash",
    "analysis_config_hash",
    "code_commit",
)


SUMMARY_FIELDS = (
    "view",
    "family",
    "source_tier",
    "metric",
    "budget_mode",
    "budget_key",
    "topology_id",
    "sparsity_bin",
    "pair_reuse_bin",
    "instance_count",
    "uncertainty_unit_count",
    "help_count",
    "little_effect_count",
    "hurt_count",
    "help_fraction",
    "little_effect_fraction",
    "hurt_fraction",
    "mean_effect",
    "effect_ci95_low",
    "effect_ci95_high",
    "mean_canonical_cubic_sparsity",
    "mean_pair_reuse_score",
    "status",
    "config_hash",
    "manifest_hash",
    "analysis_config_hash",
    "code_commit",
)


PRIMARY_AXES = (
    "canonical_cubic_sparsity",
    "pair_reuse",
    "connectivity_routing",
)
DIAGNOSTIC_AXES = ("sign_balance", "n_original")
TREATMENT = "selective"
CONTROL = "matched_random_selective"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_hash(path: Path, sidecar: Path | None = None) -> str:
    sidecar = sidecar or path.with_suffix(".sha256")
    if not path.is_file() or not sidecar.is_file():
        raise E5RegimeError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = _sha256(path)
    declared = sidecar.read_text(encoding="utf-8").strip().lower()
    if actual != declared:
        raise E5RegimeError(f"Frozen hash mismatch: {path}")
    return actual


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E5RegimeError(f"Expected JSON object: {path}")
    return payload


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_hash(path: Path) -> str:
    digest = _sha256(path)
    path.with_suffix(".sha256").write_text(
        digest + "\n", encoding="utf-8", newline="\n"
    )
    return digest


def paired_interval(values: Sequence[float], critical_value: float = 1.96) -> tuple[float, float, float]:
    """Return mean and a fixed, predeclared normal-approximation paired interval."""

    if not values:
        raise E5RegimeError("Cannot estimate an empty paired effect")
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    standard_error = statistics.stdev(values) / math.sqrt(len(values))
    half_width = critical_value * standard_error
    return mean, mean - half_width, mean + half_width


def classify_effect(ci_low: float, ci_high: float, tolerance: float) -> str:
    """Apply the frozen rule to normalised, control-minus-selective effects.

    ``little_effect`` is the historical residual category, including uncertain
    intervals; it is not evidence of equivalence or a small true effect.
    """

    if ci_low > tolerance:
        return "help"
    if ci_high < -tolerance:
        return "hurt"
    return "little_effect"


def assign_bin(value: float, specification: Mapping[str, object]) -> str:
    bins = specification.get("bins")
    if not isinstance(bins, list):
        raise E5RegimeError("Coverage-bin specification is malformed")
    for item in bins:
        if not isinstance(item, dict):
            raise E5RegimeError("Coverage-bin entry is malformed")
        lower = float(item["lower"])
        upper = float(item["upper"])
        upper_ok = value <= upper if item.get("upper_inclusive") else value < upper
        if value >= lower and upper_ok:
            return str(item["id"])
    raise E5RegimeError(f"Structural value outside frozen bins: {value}")


def _metadata_index(
    metadata_rows: Sequence[Mapping[str, str]],
) -> dict[str, Mapping[str, str]]:
    index: dict[str, Mapping[str, str]] = {}
    for row in metadata_rows:
        instance_id = row["instance_id"]
        if instance_id in index:
            raise E5RegimeError(f"Duplicate structural metadata: {instance_id}")
        index[instance_id] = row
    return index


def _structural_fields(
    metadata: Mapping[str, str], analysis: Mapping[str, object]
) -> dict[str, object]:
    coverage = analysis["coverage_bins"]
    if not isinstance(coverage, dict):
        raise E5RegimeError("Missing E5 coverage bins")
    sparsity_spec = coverage["canonical_cubic_sparsity"]
    reuse_spec = coverage["pair_reuse"]
    if not isinstance(sparsity_spec, dict) or not isinstance(reuse_spec, dict):
        raise E5RegimeError("Malformed E5 coverage bins")
    sparsity = float(metadata[str(sparsity_spec["source_field"])])
    reuse = float(metadata[str(reuse_spec["source_field"])])
    positive = float(metadata.get("positive_cubic_count", 0) or 0)
    negative = float(metadata.get("negative_cubic_count", 0) or 0)
    sign_balance = positive / (positive + negative) if positive + negative else 0.5
    return {
        "canonical_cubic_sparsity": sparsity,
        "sparsity_bin": assign_bin(sparsity, sparsity_spec),
        "pair_reuse_score": reuse,
        "pair_reuse_bin": assign_bin(reuse, reuse_spec),
        "sign_balance_diagnostic": sign_balance,
        "n_original_diagnostic": int(metadata["n"]),
    }


def _base_row(
    *,
    instance_id: str,
    family: str,
    source_tier: str,
    metric: str,
    budget_mode: str,
    budget_key: str,
    topology_id: str,
    metadata: Mapping[str, str],
    analysis: Mapping[str, object],
    config_hash: str,
    manifest_hash: str,
    analysis_config_hash: str,
    code_commit: str,
) -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "family": family,
        "source_tier": source_tier,
        "split": "test",
        "comparison": f"{TREATMENT}_vs_{CONTROL}",
        "metric": metric,
        "budget_mode": budget_mode,
        "budget_key": budget_key,
        "topology_id": topology_id,
        **_structural_fields(metadata, analysis),
        "config_hash": config_hash,
        "manifest_hash": manifest_hash,
        "analysis_config_hash": analysis_config_hash,
        "code_commit": code_commit,
    }


def qaoa_instance_rows(
    run_rows: Sequence[Mapping[str, str]],
    metadata_by_id: Mapping[str, Mapping[str, str]],
    exact_optima: Mapping[str, float],
    analysis: Mapping[str, object],
    *,
    config_hash: str,
    manifest_hash: str,
    analysis_config_hash: str,
    code_commit: str,
) -> list[dict[str, object]]:
    """Pair every selected E3 restart with the matched-random seed average."""

    effect_spec = analysis["effects"]["qaoa_original_objective"]  # type: ignore[index]
    tolerance = float(effect_spec["tolerance"])  # type: ignore[index]
    critical = float(analysis["uncertainty"]["critical_value"])  # type: ignore[index]
    groups: dict[tuple[str, str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in run_rows:
        if row["split"] != "test":
            continue
        if row["representation"] not in {TREATMENT, CONTROL}:
            continue
        key = (row["instance_id"], row["budget_mode"], row["budget_key"])
        groups[key].append(row)
    output: list[dict[str, object]] = []
    for (instance_id, budget_mode, budget_key), rows in sorted(groups.items()):
        if instance_id not in metadata_by_id or instance_id not in exact_optima:
            raise E5RegimeError(f"Missing frozen E3 metadata/truth: {instance_id}")
        selected = [row for row in rows if row["representation"] == TREATMENT]
        controls = [row for row in rows if row["representation"] == CONTROL]
        if any(row["status"] != "pass" for row in selected + controls):
            raise E5RegimeError(f"Formal E3 contains failed paired rows: {instance_id}")
        selected_by_restart: dict[str, list[float]] = defaultdict(list)
        control_by_restart: dict[str, list[float]] = defaultdict(list)
        for row in selected:
            selected_by_restart[row["restart_id"]].append(
                float(row["original_objective_mean"])
            )
        for row in controls:
            control_by_restart[row["restart_id"]].append(
                float(row["original_objective_mean"])
            )
        if set(selected_by_restart) != set(control_by_restart):
            raise E5RegimeError(f"E3 restart pairing mismatch: {instance_id}")
        scale = max(1.0, abs(exact_optima[instance_id]))
        effects: list[float] = []
        for restart in sorted(selected_by_restart):
            if len(selected_by_restart[restart]) != 1:
                raise E5RegimeError(f"Duplicate selected restart: {instance_id}")
            selected_value = selected_by_restart[restart][0]
            control_value = statistics.fmean(control_by_restart[restart])
            effects.append((control_value - selected_value) / scale)
        mean, low, high = paired_interval(effects, critical)
        metadata = metadata_by_id[instance_id]
        row = _base_row(
            instance_id=instance_id,
            family=metadata["family"],
            source_tier="qaoa",
            metric="qaoa_original_objective",
            budget_mode=budget_mode,
            budget_key=budget_key,
            topology_id="device_sparse_v1",
            metadata=metadata,
            analysis=analysis,
            config_hash=config_hash,
            manifest_hash=manifest_hash,
            analysis_config_hash=analysis_config_hash,
            code_commit=code_commit,
        )
        row.update(
            {
                "selected_observation_count": len(selected),
                "control_observation_count": len(controls),
                "paired_observation_count": len(effects),
                "selected_mean": statistics.fmean(
                    float(item["original_objective_mean"]) for item in selected
                ),
                "control_mean": statistics.fmean(
                    float(item["original_objective_mean"]) for item in controls
                ),
                "effect": mean,
                "effect_ci95_low": low,
                "effect_ci95_high": high,
                "effect_tolerance": tolerance,
                "classification": classify_effect(low, high, tolerance),
                "uncertainty_rule": "paired_normal_interval_by_restart",
                "status": "pass",
                "failure_kind": "",
            }
        )
        output.append(row)
    return output


def compiled_instance_rows(
    compiled_rows: Sequence[Mapping[str, str]],
    compilation_test_ids: Sequence[str],
    metadata_by_id: Mapping[str, Mapping[str, str]],
    analysis: Mapping[str, object],
    *,
    config_hash: str,
    manifest_hash: str,
    analysis_config_hash: str,
    code_commit: str,
    topology_ids: Sequence[str] = ("all_to_all_reference", "device_sparse_v1"),
) -> list[dict[str, object]]:
    """Pair E2 compiler seeds while retaining expected sparse infeasibility."""

    critical = float(analysis["uncertainty"]["critical_value"])  # type: ignore[index]
    metric_specs = (
        ("compiled_two_qubit_gates", "two_qubit_gates"),
        ("compiled_two_qubit_depth", "two_qubit_depth"),
        ("routing_overhead", "routing_overhead"),
    )
    relevant: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
    for row in compiled_rows:
        if row["split"] == "test" and row["representation"] in {TREATMENT, CONTROL}:
            relevant[(row["instance_id"], row["topology_id"])].append(row)
    output: list[dict[str, object]] = []
    for instance_id in sorted(compilation_test_ids):
        if instance_id not in metadata_by_id:
            raise E5RegimeError(f"Missing compilation structural metadata: {instance_id}")
        metadata = metadata_by_id[instance_id]
        for topology in topology_ids:
            rows = relevant.get((instance_id, topology), [])
            selected = [row for row in rows if row["representation"] == TREATMENT]
            controls = [row for row in rows if row["representation"] == CONTROL]
            statuses = {row["status"] for row in selected + controls}
            expected_infeasible = (
                bool(selected and controls)
                and statuses == {"infeasible_width_exceeds_topology"}
            )
            for metric_name, source_field in metric_specs:
                tolerance = float(analysis["effects"][metric_name]["tolerance"])  # type: ignore[index]
                base = _base_row(
                    instance_id=instance_id,
                    family=metadata["family"],
                    source_tier="compilation",
                    metric=metric_name,
                    budget_mode="not_applicable",
                    budget_key="not_applicable",
                    topology_id=topology,
                    metadata=metadata,
                    analysis=analysis,
                    config_hash=config_hash,
                    manifest_hash=manifest_hash,
                    analysis_config_hash=analysis_config_hash,
                    code_commit=code_commit,
                )
                if expected_infeasible:
                    base.update(
                        {
                            "selected_observation_count": len(selected),
                            "control_observation_count": len(controls),
                            "paired_observation_count": 0,
                            "selected_mean": "",
                            "control_mean": "",
                            "effect": "",
                            "effect_ci95_low": "",
                            "effect_ci95_high": "",
                            "effect_tolerance": tolerance,
                            "classification": "not_estimable",
                            "uncertainty_rule": "not_estimable_expected_width_infeasible",
                            "status": "expected_infeasible",
                            "failure_kind": "width_exceeds_frozen_sparse_topology",
                        }
                    )
                    output.append(base)
                    continue
                if (
                    not selected
                    or not controls
                    or any(row["status"] != "pass" for row in selected + controls)
                ):
                    base.update(
                        {
                            "selected_observation_count": len(selected),
                            "control_observation_count": len(controls),
                            "paired_observation_count": 0,
                            "selected_mean": "",
                            "control_mean": "",
                            "effect": "",
                            "effect_ci95_low": "",
                            "effect_ci95_high": "",
                            "effect_tolerance": tolerance,
                            "classification": "not_estimable",
                            "uncertainty_rule": "not_estimable_unexpected_failure",
                            "status": "unpaired_failure",
                            "failure_kind": "missing_or_failed_compiler_pair",
                        }
                    )
                    output.append(base)
                    continue
                selected_by_seed: dict[str, list[float]] = defaultdict(list)
                control_by_seed: dict[str, list[float]] = defaultdict(list)
                for row in selected:
                    selected_by_seed[row["transpiler_seed"]].append(float(row[source_field]))
                for row in controls:
                    control_by_seed[row["transpiler_seed"]].append(float(row[source_field]))
                if set(selected_by_seed) != set(control_by_seed):
                    raise E5RegimeError(f"E2 transpiler-seed pairing mismatch: {instance_id}")
                effects: list[float] = []
                for seed in sorted(selected_by_seed):
                    if len(selected_by_seed[seed]) != 1:
                        raise E5RegimeError(f"Duplicate selected compiler seed: {instance_id}")
                    selected_value = selected_by_seed[seed][0]
                    control_value = statistics.fmean(control_by_seed[seed])
                    scale = max(1.0, abs(control_value))
                    effects.append((control_value - selected_value) / scale)
                mean, low, high = paired_interval(effects, critical)
                base.update(
                    {
                        "selected_observation_count": len(selected),
                        "control_observation_count": len(controls),
                        "paired_observation_count": len(effects),
                        "selected_mean": statistics.fmean(
                            float(row[source_field]) for row in selected
                        ),
                        "control_mean": statistics.fmean(
                            float(row[source_field]) for row in controls
                        ),
                        "effect": mean,
                        "effect_ci95_low": low,
                        "effect_ci95_high": high,
                        "effect_tolerance": tolerance,
                        "classification": classify_effect(low, high, tolerance),
                        "uncertainty_rule": "paired_normal_interval_by_transpiler_seed",
                        "status": "pass",
                        "failure_kind": "",
                    }
                )
                output.append(base)
    return output


def summarise_regime_rows(
    rows: Sequence[Mapping[str, object]],
    critical_value: float = 1.96,
) -> list[dict[str, object]]:
    """Create separate-family and family-balanced combined regime cells."""

    passed = [row for row in rows if row["status"] == "pass"]
    keys = (
        "source_tier",
        "metric",
        "budget_mode",
        "budget_key",
        "topology_id",
        "sparsity_bin",
        "pair_reuse_bin",
    )
    output: list[dict[str, object]] = []

    def emit(view: str, family: str, group_rows: Sequence[Mapping[str, object]]) -> None:
        effects = [float(row["effect"]) for row in group_rows]
        if view == "combined_family_balanced":
            by_family: dict[str, list[float]] = defaultdict(list)
            for row in group_rows:
                by_family[str(row["family"])].append(float(row["effect"]))
            uncertainty_values = [statistics.fmean(values) for values in by_family.values()]
        else:
            uncertainty_values = effects
        mean, low, high = paired_interval(uncertainty_values, critical_value)
        sample = group_rows[0]
        counts = {
            label: sum(row["classification"] == label for row in group_rows)
            for label in ("help", "little_effect", "hurt")
        }
        n = len(group_rows)
        output.append(
            {
                "view": view,
                "family": family,
                **{key: sample[key] for key in keys},
                "instance_count": n,
                "uncertainty_unit_count": len(uncertainty_values),
                "help_count": counts["help"],
                "little_effect_count": counts["little_effect"],
                "hurt_count": counts["hurt"],
                "help_fraction": counts["help"] / n,
                "little_effect_fraction": counts["little_effect"] / n,
                "hurt_fraction": counts["hurt"] / n,
                "mean_effect": mean,
                "effect_ci95_low": low,
                "effect_ci95_high": high,
                "mean_canonical_cubic_sparsity": statistics.fmean(
                    float(row["canonical_cubic_sparsity"]) for row in group_rows
                ),
                "mean_pair_reuse_score": statistics.fmean(
                    float(row["pair_reuse_score"]) for row in group_rows
                ),
                "status": "pass",
                "config_hash": sample["config_hash"],
                "manifest_hash": sample["manifest_hash"],
                "analysis_config_hash": sample["analysis_config_hash"],
                "code_commit": sample["code_commit"],
            }
        )

    family_groups: dict[tuple[object, ...], list[Mapping[str, object]]] = defaultdict(list)
    combined_groups: dict[tuple[object, ...], list[Mapping[str, object]]] = defaultdict(list)
    for row in passed:
        family_key = (row["family"],) + tuple(row[key] for key in keys)
        family_groups[family_key].append(row)
        combined_key = tuple(row[key] for key in keys)
        combined_groups[combined_key].append(row)
    for key, group_rows in sorted(family_groups.items(), key=lambda item: tuple(map(str, item[0]))):
        emit("family", str(key[0]), group_rows)
    for _, group_rows in sorted(combined_groups.items(), key=lambda item: tuple(map(str, item[0]))):
        emit("combined_family_balanced", "combined", group_rows)
    return output


def _latex_table(rows: Sequence[Mapping[str, object]]) -> str:
    """Build a compact help/little-effect/hurt overview for Overleaf."""

    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if row["status"] == "pass":
            groups[(str(row["family"]), str(row["source_tier"]), str(row["metric"]))].append(row)
    lines = [
        "% Auto-generated formal E5 regime classification table; do not edit by hand.",
        "\\begin{tabular}{lllrrrrr}",
        "\\toprule",
        "Family & Source & Endpoint & $N$ & Help & Little & Hurt & Mean effect \\\\",
        "\\midrule",
    ]
    for (family, source, metric), group in sorted(groups.items()):
        effects = [float(row["effect"]) for row in group]
        help_count = sum(row["classification"] == "help" for row in group)
        little_count = sum(row["classification"] == "little_effect" for row in group)
        hurt_count = sum(row["classification"] == "hurt" for row in group)
        labels = [value.replace("_", "\\_") for value in (family, source, metric)]
        lines.append(
            f"{labels[0]} & {labels[1]} & {labels[2]} & {len(group)} & "
            f"{help_count} & {little_count} & {hurt_count} & "
            f"{statistics.fmean(effects):.3f} \\\\"
        )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def write_regime_figure_pdf(
    path: Path, rows: Sequence[Mapping[str, object]]
) -> str:
    """Create a six-panel vector PDF for continuous trends and connectivity."""

    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E5RegimeError("Formal E5 PDF requires reportlab==4.4.9") from error
    if reportlab.Version != "4.4.9":
        raise E5RegimeError(
            f"ReportLab version mismatch: expected 4.4.9, received {reportlab.Version}"
        )
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    candidates = (
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    )
    for regular, bold in candidates:
        if regular.is_file() and bold.is_file():
            regular_font = "E5Sans"
            bold_font = "E5SansBold"
            if regular_font not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(regular_font, str(regular)))
                pdfmetrics.registerFont(TTFont(bold_font, str(bold)))
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    pdf.setTitle("Formal E5: sparsity-reuse-connectivity regime map")
    pdf.setFont(bold_font, 16)
    pdf.drawString(36, height - 34, "Formal E5: sparsity-reuse-connectivity regime map")
    pdf.setFont(regular_font, 7.5)
    pdf.drawString(
        36,
        height - 48,
        "Positive effect means selective helps; uncertainty-crossing effects remain little effect.",
    )
    legend_x = width - 246
    for offset, (label, colour) in enumerate(
        (
            ("help", colors.HexColor("#1B9E77")),
            ("little effect", colors.HexColor("#7570B3")),
            ("hurt", colors.HexColor("#D95F02")),
        )
    ):
        item_x = legend_x + offset * 78
        pdf.setFillColor(colour)
        pdf.circle(item_x, height - 45, 3, stroke=0, fill=1)
        pdf.setFillColor(colors.black)
        pdf.drawString(item_x + 6, height - 48, label)
    panels = [
        ("Max-3SAT: effect vs sparsity", "max3sat", "sparsity"),
        ("Spin glass: effect vs sparsity", "cubic_spin_glass", "sparsity"),
        ("Combined: effect vs pair reuse", "combined", "reuse"),
        ("Max-3SAT: connectivity", "max3sat", "connectivity"),
        ("Spin glass: connectivity", "cubic_spin_glass", "connectivity"),
        ("All endpoints: classifications", "combined", "classification"),
    ]
    margin_x, gap_x = 36.0, 16.0
    panel_w = (width - 2 * margin_x - 2 * gap_x) / 3
    panel_h = 224.0
    top_y = height - 78
    palette = {
        "help": colors.HexColor("#1B9E77"),
        "little_effect": colors.HexColor("#7570B3"),
        "hurt": colors.HexColor("#D95F02"),
    }

    def panel_box(index: int) -> tuple[float, float]:
        column, row = index % 3, index // 3
        return margin_x + column * (panel_w + gap_x), top_y - row * (panel_h + 24) - panel_h

    passed = [row for row in rows if row["status"] == "pass"]
    for index, (title, family, kind) in enumerate(panels):
        x, y = panel_box(index)
        pdf.setStrokeColor(colors.HexColor("#C8D3DF"))
        pdf.rect(x, y, panel_w, panel_h, stroke=1, fill=0)
        pdf.setFont(bold_font, 8.5)
        pdf.setFillColor(colors.HexColor("#17324D"))
        pdf.drawString(x + 8, y + panel_h - 14, title)
        subset = passed if family == "combined" else [row for row in passed if row["family"] == family]
        if kind in {"sparsity", "reuse"}:
            x_field = "canonical_cubic_sparsity" if kind == "sparsity" else "pair_reuse_score"
            x_label = "canonical cubic sparsity" if kind == "sparsity" else "pair reuse"
            values = [(float(row[x_field]), float(row["effect"]), str(row["classification"])) for row in subset]
            if values:
                xmin, xmax = min(v[0] for v in values), max(v[0] for v in values)
                ymin = min(-0.1, min(v[1] for v in values))
                ymax = max(0.1, max(v[1] for v in values))
                plot_x, plot_y = x + 34, y + 28
                plot_w, plot_h = panel_w - 46, panel_h - 54
                pdf.setStrokeColor(colors.HexColor("#94A3B8"))
                pdf.line(plot_x, plot_y, plot_x, plot_y + plot_h)
                zero_y = plot_y + (0 - ymin) / (ymax - ymin) * plot_h
                pdf.line(plot_x, zero_y, plot_x + plot_w, zero_y)
                for xv, effect, label in values:
                    px = plot_x + (xv - xmin) / max(xmax - xmin, 1e-12) * plot_w
                    py = plot_y + (effect - ymin) / max(ymax - ymin, 1e-12) * plot_h
                    pdf.setFillColor(palette[label])
                    pdf.circle(px, py, 2.4, stroke=0, fill=1)
                pdf.setFillColor(colors.black)
                pdf.setFont(regular_font, 6.5)
                pdf.drawCentredString(plot_x + plot_w / 2, y + 10, x_label)
                pdf.saveState()
                pdf.translate(x + 9, plot_y + plot_h / 2)
                pdf.rotate(90)
                pdf.drawCentredString(0, 0, "normalised paired effect")
                pdf.restoreState()
        elif kind == "connectivity":
            resource = [row for row in subset if row["source_tier"] == "compilation"]
            labels = ("all_to_all_reference", "device_sparse_v1")
            means = [
                statistics.fmean(float(row["effect"]) for row in resource if row["topology_id"] == label)
                if any(row["topology_id"] == label for row in resource)
                else 0.0
                for label in labels
            ]
            origin = y + 82
            scale = 70 / max(0.1, max(abs(value) for value in means))
            for offset, (label, value) in enumerate(zip(labels, means)):
                bx = x + 52 + offset * 92
                pdf.setFillColor(colors.HexColor("#2A6F97") if value >= 0 else colors.HexColor("#D95F02"))
                if value >= 0:
                    pdf.rect(bx, origin, 42, value * scale, stroke=0, fill=1)
                else:
                    pdf.rect(bx, origin + value * scale, 42, -value * scale, stroke=0, fill=1)
                pdf.setFillColor(colors.black)
                pdf.setFont(regular_font, 6.2)
                pdf.drawCentredString(bx + 21, y + 38, "all-to-all" if offset == 0 else "sparse grid")
                pdf.drawCentredString(bx + 21, y + 27, f"{value:.3f}")
            pdf.setStrokeColor(colors.HexColor("#94A3B8"))
            pdf.line(x + 28, origin, x + panel_w - 18, origin)
        else:
            counts = {
                label: sum(row["classification"] == label for row in subset)
                for label in ("help", "little_effect", "hurt")
            }
            total = max(1, sum(counts.values()))
            labels = ("help", "little_effect", "hurt")
            for offset, label in enumerate(labels):
                bx = x + 36 + offset * 74
                bar_h = counts[label] / total * 120
                pdf.setFillColor(palette[label])
                pdf.rect(bx, y + 50, 44, bar_h, stroke=0, fill=1)
                pdf.setFillColor(colors.black)
                pdf.setFont(regular_font, 6.2)
                pdf.drawCentredString(bx + 22, y + 35, label.replace("_", " "))
                pdf.drawCentredString(bx + 22, y + 24, str(counts[label]))
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.setFont(regular_font, 6.5)
    pdf.drawRightString(width - 36, 18, "Frozen E5 analysis v1; sign balance and n are diagnostic only")
    pdf.save()
    return reportlab.Version


def _validate_analysis_config(analysis: Mapping[str, object]) -> None:
    if analysis.get("frozen_before_test_result_inspection") is not True:
        raise E5RegimeError("E5 analysis config was not predeclared")
    policy = analysis.get("input_policy")
    if not isinstance(policy, dict) or policy != {
        "allowed_split": "test",
        "regenerate_instances": False,
        "replace_instances": False,
        "select_instances_by_winner": False,
    }:
        raise E5RegimeError("E5 frozen-test input policy changed")
    if tuple(analysis.get("primary_axes", ())) != PRIMARY_AXES:
        raise E5RegimeError("E5 primary axes changed")
    if tuple(analysis.get("diagnostic_only_axes", ())) != DIAGNOSTIC_AXES:
        raise E5RegimeError("E5 diagnostic-only axes changed")
    comparison = analysis.get("comparison")
    if not isinstance(comparison, dict) or (
        comparison.get("treatment") != TREATMENT
        or comparison.get("control") != CONTROL
    ):
        raise E5RegimeError("E5 comparison changed")
    effects = analysis.get("effects")
    if not isinstance(effects, dict) or {
        key: float(effects[key]["tolerance"])  # type: ignore[index]
        for key in effects
    } != {
        "qaoa_original_objective": 0.01,
        "compiled_two_qubit_gates": 0.05,
        "compiled_two_qubit_depth": 0.05,
        "routing_overhead": 0.05,
    }:
        raise E5RegimeError("E5 effect endpoints or tolerances changed")


def verify_e5_inputs(
    config_path: Path,
    config_hash_path: Path,
    analysis_config_path: Path,
    analysis_config_hash_path: Path,
    data_directory: Path,
    results_directory: Path,
) -> dict[str, object]:
    config_hash = _verify_hash(config_path, config_hash_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("status") != "frozen":
        raise E5RegimeError("E5 requires the frozen formal experiment config")
    if tuple(config["benchmark"]["primary_regime_axes"]) != (
        "canonical_cubic_sparsity",
        "pair_reuse",
        "hardware_connectivity",
    ):
        raise E5RegimeError("Experiment config primary regime axes changed")
    analysis_hash = _verify_hash(analysis_config_path, analysis_config_hash_path)
    analysis = _load_json(analysis_config_path)
    _validate_analysis_config(analysis)
    audit_path = data_directory / "benchmark_audit_v1.json"
    _verify_hash(audit_path, data_directory / "benchmark_audit_v1.sha256")
    audit = _load_json(audit_path)
    if not (
        audit.get("status") == "pass"
        and audit.get("formal_split_created") is True
        and audit.get("test_split_frozen_before_results") is True
        and int(audit.get("split_leakage_count", -1)) == 0
        and audit.get("selector_or_qaoa_results_used_for_selection") is False
    ):
        raise E5RegimeError("Formal data freeze does not permit E5")
    manifest_hashes: dict[str, str] = {}
    manifests: dict[str, list[dict[str, str]]] = {}
    for name in ("qaoa_v1.csv", "compilation_v1.csv"):
        path = data_directory / "manifests" / name
        manifest_hashes[name] = _verify_hash(path, path.with_suffix(".sha256"))
        manifests[name] = _read_csv(path)
    metadata_path = data_directory / "metadata" / "metadata_v1.csv"
    if not metadata_path.is_file():
        raise E5RegimeError("Frozen structural metadata is missing")
    metadata_rows = _read_csv(metadata_path)
    metadata = _metadata_index(metadata_rows)
    truth_path = data_directory / "ground_truth" / "ground_truth_v1.csv"
    truth_hash = _verify_hash(truth_path, truth_path.with_suffix(".sha256"))
    truth_rows = _read_csv(truth_path)
    exact_optima = {
        row["instance_id"]: float(row["optimum_original"])
        for row in truth_rows
        if row["split"] == "test" and row["exact_truth"] == "True"
    }
    e2_paths = (
        results_directory / "e2_compiled_resources_by_seed.csv",
        results_directory / "e2_validation_summary.json",
    )
    e3_paths = (
        results_directory / "e3_qaoa_runs.csv",
        results_directory / "e3_validation_summary.json",
    )
    e4_paths = (
        results_directory / "e4_warmstart_runs.csv",
        results_directory / "e4_marginal_diagnostics.csv",
        results_directory / "e4_warmstart_summary.csv",
        results_directory / "e4_validation_summary.json",
    )
    for path in e2_paths + e3_paths + e4_paths:
        _verify_hash(path, path.with_suffix(".sha256"))
    e2 = _load_json(results_directory / "e2_validation_summary.json")
    e3 = _load_json(results_directory / "e3_validation_summary.json")
    e4 = _load_json(results_directory / "e4_validation_summary.json")
    if not (
        e2.get("status") == "pass"
        and e2.get("e3_e6_may_continue") is True
        and int(e2.get("unexpected_compiler_failure_count", -1)) == 0
        and int(e2.get("selector_test_retuning_count", -1)) == 0
    ):
        raise E5RegimeError("Formal E2 gate does not permit E5")
    if not (
        e3.get("status") == "pass"
        and e3.get("e4_e6_may_continue") is True
        and int(e3.get("non_original_primary_score_count", -1)) == 0
        and int(e3.get("seed_policy_mismatch_count", -1)) == 0
        and int(e3.get("best_only_or_missing_budget_group_count", -1)) == 0
    ):
        raise E5RegimeError("Formal E3 gate does not permit E5")
    if not (
        e4.get("status") == "pass"
        and e4.get("e5_e6_may_continue") is True
        and int(e4.get("cold_e3_reproduction_mismatch_count", -1)) == 0
        and int(e4.get("failed_run_count", -1)) == 0
    ):
        raise E5RegimeError("Formal E4 gate does not permit E5")
    qaoa_test_ids = sorted(
        row["instance_id"] for row in manifests["qaoa_v1.csv"] if row["split"] == "test"
    )
    compilation_test_ids = sorted(
        row["instance_id"]
        for row in manifests["compilation_v1.csv"]
        if row["split"] == "test"
    )
    if len(qaoa_test_ids) != 14 or len(compilation_test_ids) != 36:
        raise E5RegimeError("Frozen E5 test-set counts changed")
    if not set(qaoa_test_ids + compilation_test_ids).issubset(metadata):
        raise E5RegimeError("Frozen E5 test metadata is incomplete")
    if not set(qaoa_test_ids).issubset(exact_optima):
        raise E5RegimeError("Frozen QAOA test truth is incomplete")
    return {
        "config": config,
        "config_hash": config_hash,
        "analysis": analysis,
        "analysis_hash": analysis_hash,
        "qaoa_manifest_hash": manifest_hashes["qaoa_v1.csv"],
        "compilation_manifest_hash": manifest_hashes["compilation_v1.csv"],
        "metadata": metadata,
        "metadata_hash": _sha256(metadata_path),
        "exact_optima": exact_optima,
        "ground_truth_hash": truth_hash,
        "qaoa_test_ids": qaoa_test_ids,
        "compilation_test_ids": compilation_test_ids,
        "compiled_rows": _read_csv(results_directory / "e2_compiled_resources_by_seed.csv"),
        "qaoa_rows": _read_csv(results_directory / "e3_qaoa_runs.csv"),
        "e2_summary_hash": _sha256(results_directory / "e2_validation_summary.json"),
        "e3_summary_hash": _sha256(results_directory / "e3_validation_summary.json"),
        "e4_summary_hash": _sha256(results_directory / "e4_validation_summary.json"),
    }


def run_e5_regime_pipeline(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    analysis_config_path: str | Path,
    analysis_config_hash_path: str | Path,
    data_directory: str | Path,
    results_directory: str | Path,
    tables_directory: str | Path,
    figures_directory: str | Path,
    code_commit: str,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
) -> dict[str, object]:
    """Run frozen E5 analysis without generating or replacing any instances."""

    config_path = Path(config_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    figures_directory = Path(figures_directory)
    project_root = results_directory.parent
    targets = (
        results_directory / "e5_regime_instance_level.csv",
        results_directory / "e5_regime_summary.csv",
        results_directory / "e5_validation_summary.json",
        tables_directory / "table_e5_help_tie_hurt.tex",
        figures_directory / "figure_e5_regime_map.pdf",
    )
    if any(path.exists() for path in targets):
        raise FileExistsError("Formal E5 output already exists; refusing overwrite")
    staging = project_root / "e5_step7_building"
    if staging.exists():
        raise E5RegimeError(f"Incomplete E5 staging directory exists: {staging}")
    frozen = verify_e5_inputs(
        config_path,
        Path(config_hash_path),
        Path(analysis_config_path),
        Path(analysis_config_hash_path),
        data_directory,
        results_directory,
    )
    analysis = frozen["analysis"]
    assert isinstance(analysis, dict)
    metadata = frozen["metadata"]
    assert isinstance(metadata, dict)
    qaoa_rows = qaoa_instance_rows(
        frozen["qaoa_rows"],  # type: ignore[arg-type]
        metadata,
        frozen["exact_optima"],  # type: ignore[arg-type]
        analysis,
        config_hash=str(frozen["config_hash"]),
        manifest_hash=str(frozen["qaoa_manifest_hash"]),
        analysis_config_hash=str(frozen["analysis_hash"]),
        code_commit=code_commit,
    )
    compiled_rows = compiled_instance_rows(
        frozen["compiled_rows"],  # type: ignore[arg-type]
        frozen["compilation_test_ids"],  # type: ignore[arg-type]
        metadata,
        analysis,
        config_hash=str(frozen["config_hash"]),
        manifest_hash=str(frozen["compilation_manifest_hash"]),
        analysis_config_hash=str(frozen["analysis_hash"]),
        code_commit=code_commit,
    )
    instance_rows = sorted(
        qaoa_rows + compiled_rows,
        key=lambda row: (
            str(row["source_tier"]),
            str(row["family"]),
            str(row["instance_id"]),
            str(row["metric"]),
            str(row["topology_id"]),
            str(row["budget_key"]),
        ),
    )
    critical = float(analysis["uncertainty"]["critical_value"])  # type: ignore[index]
    summary_rows = summarise_regime_rows(instance_rows, critical)
    expected_infeasible = sum(row["status"] == "expected_infeasible" for row in instance_rows)
    unexpected_failures = sum(row["status"] == "unpaired_failure" for row in instance_rows)
    classifications = {
        label: sum(row["classification"] == label for row in instance_rows)
        for label in ("help", "little_effect", "hurt")
    }
    gates = (
        len(qaoa_rows) == 56
        and len(compiled_rows) == 216
        and len(instance_rows) == 272
        and unexpected_failures == 0
        and all(row["split"] == "test" for row in instance_rows)
        and all(row["comparison"] == f"{TREATMENT}_vs_{CONTROL}" for row in instance_rows)
        and all(row["status"] in {"pass", "expected_infeasible"} for row in instance_rows)
        and classifications["help"] + classifications["little_effect"] + classifications["hurt"]
        == 272 - expected_infeasible
    )
    staging.mkdir()
    try:
        output_paths = {
            "results/e5_regime_instance_level.csv": staging / "results/e5_regime_instance_level.csv",
            "results/e5_regime_summary.csv": staging / "results/e5_regime_summary.csv",
            "tables/table_e5_help_tie_hurt.tex": staging / "tables/table_e5_help_tie_hurt.tex",
            "figures/figure_e5_regime_map.pdf": staging / "figures/figure_e5_regime_map.pdf",
        }
        _write_csv(output_paths["results/e5_regime_instance_level.csv"], instance_rows, INSTANCE_FIELDS)
        _write_csv(output_paths["results/e5_regime_summary.csv"], summary_rows, SUMMARY_FIELDS)
        table_path = output_paths["tables/table_e5_help_tie_hurt.tex"]
        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(_latex_table(instance_rows), encoding="utf-8", newline="\n")
        reportlab_version = write_regime_figure_pdf(
            output_paths["figures/figure_e5_regime_map.pdf"], instance_rows
        )
        artifact_hashes = {
            relative: _write_hash(path) for relative, path in output_paths.items()
        }
        validation = {
            "scope": "formal_step7_e5_sparsity_reuse_connectivity_regime_map",
            "status": "pass" if gates else "fail",
            "e6_may_continue": gates,
            "config_hash": frozen["config_hash"],
            "analysis_config_hash": frozen["analysis_hash"],
            "metadata_hash": frozen["metadata_hash"],
            "ground_truth_hash": frozen["ground_truth_hash"],
            "qaoa_manifest_hash": frozen["qaoa_manifest_hash"],
            "compilation_manifest_hash": frozen["compilation_manifest_hash"],
            "e2_validation_summary_hash": frozen["e2_summary_hash"],
            "e3_validation_summary_hash": frozen["e3_summary_hash"],
            "e4_validation_summary_hash": frozen["e4_summary_hash"],
            "code_commit": code_commit,
            "primary_axes": list(PRIMARY_AXES),
            "diagnostic_only_axes": list(DIAGNOSTIC_AXES),
            "treatment": TREATMENT,
            "control": CONTROL,
            "frozen_qaoa_test_instance_count": len(frozen["qaoa_test_ids"]),  # type: ignore[arg-type]
            "frozen_compilation_test_instance_count": len(frozen["compilation_test_ids"]),  # type: ignore[arg-type]
            "qaoa_instance_level_row_count": len(qaoa_rows),
            "compiled_instance_level_row_count": len(compiled_rows),
            "instance_level_row_count": len(instance_rows),
            "summary_row_count": len(summary_rows),
            "expected_infeasible_row_count": expected_infeasible,
            "unexpected_failure_count": unexpected_failures,
            "non_test_input_count": sum(row["split"] != "test" for row in instance_rows),
            "winner_based_instance_selection_count": 0,
            "help_count": classifications["help"],
            "little_effect_count": classifications["little_effect"],
            "hurt_count": classifications["hurt"],
            "effect_tolerances": {
                key: value["tolerance"] for key, value in analysis["effects"].items()  # type: ignore[union-attr]
            },
            "uncertainty_method": analysis["uncertainty"]["method"],  # type: ignore[index]
            "predeclared_coverage_bins": analysis["coverage_bins"],
            "reportlab_version": reportlab_version,
            "artifact_hashes": artifact_hashes,
        }
        validation_path = staging / "results/e5_validation_summary.json"
        _write_json(validation_path, validation)
        _write_hash(validation_path)
        if not gates:
            raise E5RegimeError(f"Formal E5 gate failed; staging retained at {staging}")
        for relative in (
            "results/e5_regime_instance_level.csv",
            "results/e5_regime_summary.csv",
            "results/e5_validation_summary.json",
            "tables/table_e5_help_tie_hurt.tex",
            "figures/figure_e5_regime_map.pdf",
        ):
            source = staging / relative
            destination = project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            shutil.move(str(source.with_suffix(".sha256")), str(destination.with_suffix(".sha256")))
        for directory in ("results", "tables", "figures"):
            (staging / directory).rmdir()
        staging.rmdir()
        if assumptions_path is not None:
            with Path(assumptions_path).open("a", encoding="utf-8", newline="") as stream:
                stream.write(
                    "\n## Formal Step 7 / E5 regime-map decisions\n\n"
                    "- Only frozen test results were read; no instance was generated, replaced, or filtered by winner.\n"
                    "- Primary axes are canonical cubic sparsity, pair reuse, and connectivity/routing.\n"
                    "- Sign balance and original width remain supplementary diagnostics only.\n"
                    "- Selective is paired against the auxiliary-count-matched random control.\n"
                    "- The immutable `configs/e5_analysis_v1.json` fixes bins, tolerances, and the 95% paired uncertainty rule before analysis.\n"
                    "- Negative and null results, expected sparse-width infeasibility, and per-cell sample sizes are retained.\n"
                )
        if run_commands_path is not None:
            with Path(run_commands_path).open("a", encoding="utf-8", newline="") as stream:
                stream.write(
                    "\n## Formal Step 7 / E5 regime map\n\n"
                    "```powershell\n"
                    "python .\\run_e5_regime.py `\n"
                    "  --config .\\configs\\experiment_config_v1.yaml `\n"
                    "  --config-hash .\\configs\\experiment_config_v1.sha256 `\n"
                    "  --analysis-config .\\configs\\e5_analysis_v1.json `\n"
                    "  --analysis-config-hash .\\configs\\e5_analysis_v1.sha256 `\n"
                    "  --data .\\data `\n"
                    "  --results .\\results `\n"
                    "  --tables .\\tables `\n"
                    "  --figures .\\figures `\n"
                    "  --assumptions .\\assumptions_and_decisions.md `\n"
                    "  --run-commands .\\RUN_COMMANDS.md\n"
                    "```\n"
                )
        return validation
    except Exception:
        raise
