"""Formal Step 4 / E2 logical and compiled-resource pipeline."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
import statistics
import time
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from .e1_exactness import (
    MixedRepresentation,
    action_options,
    build_mixed_representation,
    select_resource_optimal_design,
    verify_data_freeze,
)
from .polynomial import Polynomial, Support, canonicalize, cubic_supports, pair_shadow
from .reference_compiler import ReferenceCompilation, compile_reference
from .representations import minimum_pair_cover


class E2ResourcesError(RuntimeError):
    """Formal E2 cannot proceed or failed a mandatory fairness gate."""


LOGICAL_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "random_rep_seed",
    "design_id",
    "n_original",
    "n_aux",
    "n_qubits",
    "retained_cubic",
    "quadratic_couplings",
    "M_max",
    "coefficient_dynamic_range",
    "active_pair_count",
    "selector_status",
    "selector_objective",
    "selector_compiler_calls",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


COMPILED_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "random_rep_seed",
    "design_id",
    "n_original",
    "n_aux",
    "n_qubits",
    "retained_cubic",
    "quadratic_couplings",
    "M_max",
    "coefficient_dynamic_range",
    "topology_id",
    "topology_capacity",
    "transpiler_seed",
    "two_qubit_gates",
    "two_qubit_depth",
    "swap_count",
    "swap_count_method",
    "routing_overhead",
    "compile_runtime_sec",
    "status",
    "failure_kind",
    "failure_message",
    "compiler_protocol_id",
    "qiskit_version",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


SUMMARY_FIELDS = (
    "instance_id",
    "family",
    "split",
    "representation",
    "topology_id",
    "scheduled_row_count",
    "success_count",
    "failure_count",
    "random_rep_seed_count",
    "transpiler_seed_count",
    "two_qubit_gates_mean",
    "two_qubit_gates_median",
    "two_qubit_gates_std",
    "two_qubit_gates_ci95_low",
    "two_qubit_gates_ci95_high",
    "two_qubit_depth_mean",
    "two_qubit_depth_median",
    "two_qubit_depth_std",
    "two_qubit_depth_ci95_low",
    "two_qubit_depth_ci95_high",
    "swap_count_mean",
    "swap_count_median",
    "routing_overhead_mean",
    "routing_overhead_median",
    "compile_runtime_sec_mean",
    "compile_runtime_sec_median",
    "status",
    "failure_kinds",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


SELECTOR_FIELDS = (
    "instance_id",
    "family",
    "split",
    "method",
    "certificate_status",
    "selected_design_id",
    "selected_n_aux",
    "selected_two_qubit_gates",
    "selected_two_qubit_depth",
    "selected_M_max",
    "objective",
    "certified_optimum_objective",
    "regret",
    "hit_certified_design",
    "runtime_sec",
    "compiler_calls",
    "weights_tuned_on",
    "test_retuning_used",
    "status",
    "config_hash",
    "manifest_hash",
    "code_commit",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise E2ResourcesError(f"Expected JSON object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


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


def _fraction(value: object) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def _canonical_polynomial(path: Path) -> tuple[str, Polynomial]:
    record = _load_json(path)
    terms = record.get("terms")
    if not isinstance(terms, list):
        raise E2ResourcesError(f"Malformed canonical record: {path}")
    polynomial = canonicalize(
        (tuple(item["support"]), item["coefficient"])  # type: ignore[index]
        for item in terms
    )
    return str(record["family"]), polynomial


def _serialise_actions(actions: Sequence[Support | None]) -> list[list[int] | None]:
    return [list(action) if action is not None else None for action in actions]


def _action_key(
    cubics: Sequence[Support], actions: Sequence[Support | None]
) -> tuple[int, ...]:
    return tuple(
        action_options(cubic).index(action)
        for cubic, action in zip(cubics, actions)
    )


def _design_id(actions: Sequence[Support | None]) -> str:
    payload = json.dumps(
        _serialise_actions(actions), separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    return "design_" + hashlib.sha256(payload).hexdigest()[:20]


def _stable_actions_key(
    actions: Sequence[Support | None],
) -> tuple[tuple[int, int, int], ...]:
    return tuple(
        (0, 0, 0) if action is None else (1, action[0], action[1])
        for action in actions
    )


def _full_actions(polynomial: Mapping[Support, object]) -> tuple[Support, ...]:
    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    candidates = pair_shadow(set(cubics))
    cover = minimum_pair_cover(
        set(cubics), maximum_pair_candidates=max(24, len(candidates))
    )
    return tuple(
        next(pair for pair in cover if set(pair).issubset(cubic))
        for cubic in cubics
    )


@dataclass(frozen=True)
class DesignEvaluation:
    actions: tuple[Support | None, ...]
    representation: MixedRepresentation
    reference: ReferenceCompilation
    score: Fraction
    feasible: bool
    vector: tuple[Fraction, Fraction, Fraction, Fraction]


@dataclass(frozen=True)
class SearchResult:
    actions: tuple[Support | None, ...]
    evaluation: DesignEvaluation
    status: str
    compiler_calls: int
    runtime_sec: float


@dataclass(frozen=True)
class FastDesignEvaluation:
    actions: tuple[Support | None, ...]
    score: Fraction
    feasible: bool
    vector: tuple[Fraction, Fraction, Fraction, Fraction]
    n_auxiliary: int
    n_qubits: int
    two_qubit_gate_count: int
    two_qubit_depth: int
    maximum_penalty: Fraction


def _fast_evaluate_design(
    canonical: Mapping[Support, object],
    cubics: Sequence[Support],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    selector: Mapping[str, object],
    apply_qaoa_hard_limits: bool,
) -> FastDesignEvaluation:
    """Compute the exact selector resources without materialising Pauli fractions."""

    action_tuple = tuple(actions)
    active_pairs = tuple(sorted({action for action in action_tuple if action is not None}))
    auxiliaries = {
        pair: n_original + index
        for index, pair in enumerate(active_pairs, start=1)
    }
    totals: dict[Support, Fraction] = {
        support: _fraction(coefficient)
        for support, coefficient in canonical.items()
        if len(support) <= 2
    }
    assigned: dict[Support, list[Fraction]] = {pair: [] for pair in active_pairs}
    for cubic, action in zip(cubics, action_tuple):
        coefficient = _fraction(canonical[cubic])
        if action is None:
            totals[cubic] = totals.get(cubic, Fraction(0)) + coefficient
        else:
            remaining = next(variable for variable in cubic if variable not in action)
            support = tuple(sorted((auxiliaries[action], remaining)))
            totals[support] = totals.get(support, Fraction(0)) + coefficient
            assigned[action].append(coefficient)

    maximum_penalty = Fraction(0)
    for pair in active_pairs:
        positive = sum((value for value in assigned[pair] if value > 0), Fraction(0))
        negative = sum((-value for value in assigned[pair] if value < 0), Fraction(0))
        penalty = max(positive, negative) + 1
        maximum_penalty = max(maximum_penalty, penalty)
        left, right = pair
        auxiliary = auxiliaries[pair]
        for support, value in (
            ((left, right), penalty),
            ((left, auxiliary), -2 * penalty),
            ((right, auxiliary), -2 * penalty),
            ((auxiliary,), 3 * penalty),
        ):
            support = tuple(sorted(support))
            totals[support] = totals.get(support, Fraction(0)) + value
    totals = {support: value for support, value in totals.items() if value}

    denominator_lcm = 1
    for coefficient in totals.values():
        denominator_lcm = math.lcm(denominator_lcm, coefficient.denominator)
    scale = 8 * denominator_lcm
    pauli: dict[Support, int] = {}
    for support, coefficient in totals.items():
        scaled = coefficient.numerator * (scale // coefficient.denominator)
        unit = scaled // (1 << len(support))
        for size in range(len(support) + 1):
            sign = -1 if size % 2 else 1
            for z_support in combinations(support, size):
                pauli[z_support] = pauli.get(z_support, 0) + sign * unit
    ordered_supports = sorted(
        (
            support
            for support, coefficient in pauli.items()
            if coefficient and len(support) >= 2
        ),
        key=lambda support: (len(support), support),
    )
    availability = [0] * (n_original + len(active_pairs) + 1)
    gate_count = 0
    depth = 0
    for support in ordered_supports:
        target = support[-1]
        controls = support[:-1]
        for control in (*controls, *reversed(controls)):
            layer = 1 + max(availability[control], availability[target])
            availability[control] = layer
            availability[target] = layer
            depth = max(depth, layer)
            gate_count += 1

    weights = selector["weights"]  # type: ignore[assignment]
    scales = selector["scales"]  # type: ignore[assignment]
    limits = selector["feasibility_limits"]  # type: ignore[assignment]
    n_auxiliary = len(active_pairs)
    n_qubits = n_original + n_auxiliary
    vector = (
        Fraction(n_auxiliary, 1) / _fraction(scales["auxiliary_count"]),  # type: ignore[index]
        Fraction(gate_count, 1) / _fraction(scales["two_qubit_gate_count"]),  # type: ignore[index]
        Fraction(depth, 1) / _fraction(scales["two_qubit_depth"]),  # type: ignore[index]
        maximum_penalty / _fraction(scales["maximum_penalty"]),  # type: ignore[index]
    )
    score = sum(
        (
            _fraction(weight) * coordinate
            for weight, coordinate in zip(
                (
                    weights["auxiliary_count"],  # type: ignore[index]
                    weights["two_qubit_gate_count"],  # type: ignore[index]
                    weights["two_qubit_depth"],  # type: ignore[index]
                    weights["maximum_penalty"],  # type: ignore[index]
                ),
                vector,
            )
        ),
        Fraction(0),
    )
    feasible = True
    if apply_qaoa_hard_limits:
        feasible = (
            n_qubits <= int(limits["maximum_qubits"])  # type: ignore[index]
            and gate_count <= int(limits["maximum_two_qubit_gates_per_cost_layer"])  # type: ignore[index]
            and depth <= int(limits["maximum_two_qubit_depth_per_cost_layer"])  # type: ignore[index]
            and maximum_penalty <= _fraction(limits["maximum_penalty"])  # type: ignore[index]
        )
    return FastDesignEvaluation(
        actions=action_tuple,
        score=score,
        feasible=feasible,
        vector=vector,
        n_auxiliary=n_auxiliary,
        n_qubits=n_qubits,
        two_qubit_gate_count=gate_count,
        two_qubit_depth=depth,
        maximum_penalty=maximum_penalty,
    )


def _evaluate_design(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    selector: Mapping[str, object],
    apply_qaoa_hard_limits: bool,
) -> DesignEvaluation:
    representation = build_mixed_representation(
        polynomial,
        n_original=n_original,
        actions=actions,
        default_margin=1,
    )
    reference = compile_reference(
        representation.polynomial, n_qubits=representation.n_qubits
    )
    maximum_penalty = max(
        representation.penalties.values(), default=Fraction(0)
    )
    weights = selector["weights"]  # type: ignore[assignment]
    scales = selector["scales"]  # type: ignore[assignment]
    limits = selector["feasibility_limits"]  # type: ignore[assignment]
    vector = (
        Fraction(representation.n_auxiliary, 1)
        / _fraction(scales["auxiliary_count"]),  # type: ignore[index]
        Fraction(reference.two_qubit_gate_count, 1)
        / _fraction(scales["two_qubit_gate_count"]),  # type: ignore[index]
        Fraction(reference.two_qubit_depth, 1)
        / _fraction(scales["two_qubit_depth"]),  # type: ignore[index]
        maximum_penalty
        / _fraction(scales["maximum_penalty"]),  # type: ignore[index]
    )
    score = sum(
        (
            _fraction(weight) * coordinate
            for weight, coordinate in zip(
                (
                    weights["auxiliary_count"],  # type: ignore[index]
                    weights["two_qubit_gate_count"],  # type: ignore[index]
                    weights["two_qubit_depth"],  # type: ignore[index]
                    weights["maximum_penalty"],  # type: ignore[index]
                ),
                vector,
            )
        ),
        Fraction(0),
    )
    feasible = True
    if apply_qaoa_hard_limits:
        feasible = (
            representation.n_qubits <= int(limits["maximum_qubits"])  # type: ignore[index]
            and reference.two_qubit_gate_count
            <= int(limits["maximum_two_qubit_gates_per_cost_layer"])  # type: ignore[index]
            and reference.two_qubit_depth
            <= int(limits["maximum_two_qubit_depth_per_cost_layer"])  # type: ignore[index]
            and maximum_penalty <= _fraction(limits["maximum_penalty"])  # type: ignore[index]
        )
    return DesignEvaluation(
        actions=tuple(actions),
        representation=representation,
        reference=reference,
        score=score,
        feasible=feasible,
        vector=vector,
    )


def _dominates(
    left: DesignEvaluation | FastDesignEvaluation,
    right: DesignEvaluation | FastDesignEvaluation,
) -> bool:
    return all(a <= b for a, b in zip(left.vector, right.vector)) and any(
        a < b for a, b in zip(left.vector, right.vector)
    )


def _pareto_rank_and_crowding(
    candidates: Sequence[
        tuple[
            tuple[Support | None, ...],
            DesignEvaluation | FastDesignEvaluation,
        ]
    ],
) -> dict[tuple[Support | None, ...], tuple[int, float]]:
    items = list(candidates)
    result: dict[tuple[Support | None, ...], tuple[int, float]] = {}
    dominates: list[list[int]] = [[] for _ in items]
    dominated_count = [0] * len(items)
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if _dominates(items[left][1], items[right][1]):
                dominates[left].append(right)
                dominated_count[right] += 1
            elif _dominates(items[right][1], items[left][1]):
                dominates[right].append(left)
                dominated_count[left] += 1
    fronts: list[list[int]] = [
        [index for index, count in enumerate(dominated_count) if count == 0]
    ]
    while fronts[-1]:
        following: list[int] = []
        for index in fronts[-1]:
            for dominated in dominates[index]:
                dominated_count[dominated] -= 1
                if dominated_count[dominated] == 0:
                    following.append(dominated)
        fronts.append(following)

    for rank, indices in enumerate(fronts[:-1]):
        front = [items[index] for index in indices]
        crowding = {item[0]: 0.0 for item in front}
        if len(front) <= 2:
            for item in front:
                crowding[item[0]] = math.inf
        else:
            for dimension in range(4):
                ordered = sorted(
                    front,
                    key=lambda item: (
                        item[1].vector[dimension],
                        _stable_actions_key(item[0]),
                    ),
                )
                crowding[ordered[0][0]] = math.inf
                crowding[ordered[-1][0]] = math.inf
                low = float(ordered[0][1].vector[dimension])
                high = float(ordered[-1][1].vector[dimension])
                if high == low:
                    continue
                for index in range(1, len(ordered) - 1):
                    key = ordered[index][0]
                    if math.isinf(crowding[key]):
                        continue
                    before = float(ordered[index - 1][1].vector[dimension])
                    after = float(ordered[index + 1][1].vector[dimension])
                    crowding[key] += (after - before) / (high - low)
        for item in front:
            result[item[0]] = (rank, crowding[item[0]])
    return result


def _beam_allocate(
    candidates: Sequence[
        tuple[
            tuple[Support | None, ...],
            DesignEvaluation | FastDesignEvaluation,
        ]
    ],
    *,
    cubics: Sequence[Support],
    beam_width: int,
    score_fraction: float,
) -> list[tuple[Support | None, ...]]:
    unique = {actions: evaluation for actions, evaluation in candidates}
    feasible = [
        (actions, evaluation)
        for actions, evaluation in unique.items()
        if evaluation.feasible
    ]
    if not feasible:
        raise E2ResourcesError("Selector beam has no feasible state")
    score_count = min(
        len(feasible), max(1, int(round(beam_width * score_fraction)))
    )
    by_score = sorted(
        feasible,
        key=lambda item: (
            item[1].score,
            _action_key(cubics[: len(item[0])], item[0]),
        ),
    )
    selected = [item[0] for item in by_score[:score_count]]
    remaining = [item for item in feasible if item[0] not in set(selected)]
    if len(selected) < beam_width and remaining:
        ranks = _pareto_rank_and_crowding(remaining)
        remaining.sort(
            key=lambda item: (
                ranks[item[0]][0],
                -ranks[item[0]][1],
                _action_key(cubics[: len(item[0])], item[0]),
            )
        )
        selected.extend(
            item[0] for item in remaining[: beam_width - len(selected)]
        )
    return selected[:beam_width]


def beam_select_design(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    apply_qaoa_hard_limits: bool,
) -> SearchResult:
    """Run the frozen deterministic Pareto beam and return its incumbent."""

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    settings = selector["search_settings"]  # type: ignore[assignment]
    beam_width = int(settings["beam_width"])  # type: ignore[index]
    allocation = settings["beam_allocation"]  # type: ignore[index]
    score_fraction = float(allocation["smallest_resource_score_fraction"])
    cache: dict[tuple[Support | None, ...], FastDesignEvaluation] = {}

    def evaluate(completed: tuple[Support | None, ...]) -> FastDesignEvaluation:
        if completed not in cache:
            cache[completed] = _fast_evaluate_design(
                canonical,
                cubics,
                n_original=n_original,
                actions=completed,
                selector=selector,
                apply_qaoa_hard_limits=apply_qaoa_hard_limits,
            )
        return cache[completed]

    beam: list[tuple[Support | None, ...]] = [()]
    for depth, cubic in enumerate(cubics):
        candidates: list[
            tuple[tuple[Support | None, ...], FastDesignEvaluation]
        ] = []
        for prefix in beam:
            for action in action_options(cubic):
                child = prefix + (action,)
                completed = child + (None,) * (len(cubics) - len(child))
                candidates.append((child, evaluate(completed)))
        beam = _beam_allocate(
            candidates,
            cubics=cubics,
            beam_width=beam_width,
            score_fraction=score_fraction,
        )

    finalists = [(actions, evaluate(actions)) for actions in beam]
    finalists = [item for item in finalists if item[1].feasible]
    if not finalists:
        raise E2ResourcesError("Selector beam produced no feasible complete design")
    actions, fast_evaluation = min(
        finalists,
        key=lambda item: (item[1].score, _action_key(cubics, item[0])),
    )
    evaluation = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if (
        evaluation.score != fast_evaluation.score
        or evaluation.reference.two_qubit_gate_count
        != fast_evaluation.two_qubit_gate_count
        or evaluation.reference.two_qubit_depth != fast_evaluation.two_qubit_depth
    ):
        raise E2ResourcesError("Fast selector resources differ from full reference compiler")
    return SearchResult(
        actions=actions,
        evaluation=evaluation,
        status=(
            "pareto_beam_incumbent_qaoa_limits"
            if apply_qaoa_hard_limits
            else "pareto_beam_incumbent_compilation_scope"
        ),
        compiler_calls=len(cache),
        runtime_sec=time.perf_counter() - started,
    )


def greedy_select_design(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    apply_qaoa_hard_limits: bool,
) -> SearchResult:
    """Deterministic native-completion greedy selector for validation."""

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    actions: list[Support | None] = [None] * len(cubics)
    cache: dict[tuple[Support | None, ...], FastDesignEvaluation] = {}
    for index, cubic in enumerate(cubics):
        choices: list[FastDesignEvaluation] = []
        for action in action_options(cubic):
            candidate = tuple(actions[:index] + [action] + actions[index + 1 :])
            if candidate not in cache:
                cache[candidate] = _fast_evaluate_design(
                    canonical,
                    cubics,
                    n_original=n_original,
                    actions=candidate,
                    selector=selector,
                    apply_qaoa_hard_limits=apply_qaoa_hard_limits,
                )
            if cache[candidate].feasible:
                choices.append(cache[candidate])
        if not choices:
            raise E2ResourcesError("Greedy selector has no feasible action")
        chosen = min(
            choices,
            key=lambda item: (item.score, _action_key(cubics, item.actions)),
        )
        actions[index] = chosen.actions[index]
    final = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=tuple(actions),
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    fast_final = _fast_evaluate_design(
        canonical,
        cubics,
        n_original=n_original,
        actions=tuple(actions),
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if (
        final.score != fast_final.score
        or final.reference.two_qubit_gate_count != fast_final.two_qubit_gate_count
        or final.reference.two_qubit_depth != fast_final.two_qubit_depth
    ):
        raise E2ResourcesError("Fast greedy resources differ from full reference compiler")
    return SearchResult(
        actions=tuple(actions),
        evaluation=final,
        status="greedy_native_completion_heuristic",
        compiler_calls=len(cache) + 1,
        runtime_sec=time.perf_counter() - started,
    )


def matched_random_designs(
    polynomial: Mapping[Support, object],
    *,
    selected_actions: Sequence[Support | None],
    instance_id: str,
    seed_bundle: Sequence[int],
) -> list[tuple[int, tuple[Support | None, ...]]]:
    """Construct scalable random designs matched on distinct auxiliaries."""

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    target = len({action for action in selected_actions if action is not None})
    if target == 0:
        return [(seed, (None,) * len(cubics)) for seed in seed_bundle]
    pairs = tuple(sorted(pair_shadow(set(cubics))))
    if target > len(pairs) or target > len(cubics):
        raise E2ResourcesError("Matched-random auxiliary target is impossible")

    def pair_matching(
        chosen: Sequence[Support], rng: random.Random
    ) -> dict[Support, int] | None:
        order = list(chosen)
        rng.shuffle(order)
        used: set[int] = set()
        assignment: dict[Support, int] = {}

        def visit(position: int) -> bool:
            if position == len(order):
                return True
            pair = order[position]
            candidates = [
                index
                for index, cubic in enumerate(cubics)
                if index not in used and set(pair).issubset(cubic)
            ]
            rng.shuffle(candidates)
            for index in candidates:
                used.add(index)
                assignment[pair] = index
                if visit(position + 1):
                    return True
                used.remove(index)
                assignment.pop(pair, None)
            return False

        return assignment if visit(0) else None

    outputs: list[tuple[int, tuple[Support | None, ...]]] = []
    for base_seed in seed_bundle:
        digest = hashlib.sha256(f"{instance_id}:{base_seed}".encode("ascii")).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        result: tuple[Support | None, ...] | None = None
        for _ in range(4096):
            chosen = rng.sample(list(pairs), target)
            matching = pair_matching(chosen, rng)
            if matching is None:
                continue
            actions: list[Support | None] = [None] * len(cubics)
            for pair, index in matching.items():
                actions[index] = pair
            for index, cubic in enumerate(cubics):
                if actions[index] is not None:
                    continue
                options: list[Support | None] = [None]
                options.extend(
                    pair for pair in chosen if set(pair).issubset(cubic)
                )
                actions[index] = rng.choice(options)
            candidate = tuple(actions)
            if (
                len({action for action in candidate if action is not None}) == target
                and candidate != tuple(selected_actions)
            ):
                result = candidate
                break
        if result is None:
            result = tuple(selected_actions)
        outputs.append((base_seed, result))
    return outputs


def logical_resource_record(
    *,
    instance_id: str,
    family: str,
    split: str,
    representation_name: str,
    random_rep_seed: int | None,
    evaluation: DesignEvaluation,
    selector_status: str,
    selector_compiler_calls: int,
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
) -> dict[str, object]:
    polynomial = evaluation.representation.polynomial
    maximum_penalty = max(
        evaluation.representation.penalties.values(), default=Fraction(0)
    )
    return {
        "instance_id": instance_id,
        "family": family,
        "split": split,
        "representation": representation_name,
        "random_rep_seed": "" if random_rep_seed is None else random_rep_seed,
        "design_id": _design_id(evaluation.actions),
        "n_original": evaluation.representation.original_width,
        "n_aux": evaluation.representation.n_auxiliary,
        "n_qubits": evaluation.representation.n_qubits,
        "retained_cubic": sum(1 for support in polynomial if len(support) == 3),
        "quadratic_couplings": sum(
            1 for support in polynomial if len(support) == 2
        ),
        "M_max": float(maximum_penalty),
        "coefficient_dynamic_range": (
            evaluation.reference.coefficient_dynamic_range
        ),
        "active_pair_count": len(evaluation.representation.active_pairs),
        "selector_status": selector_status,
        "selector_objective": float(evaluation.score),
        "selector_compiler_calls": selector_compiler_calls,
        "config_hash": config_hash,
        "manifest_hash": manifest_hash,
        "code_commit": code_commit,
    }


def _two_qubit_depth(circuit: object) -> int:
    availability: dict[int, int] = {}
    maximum = 0
    for item in circuit.data:  # type: ignore[attr-defined]
        qubits = [circuit.find_bit(qubit).index for qubit in item.qubits]  # type: ignore[attr-defined]
        if len(qubits) != 2:
            continue
        layer = 1 + max(availability.get(qubits[0], 0), availability.get(qubits[1], 0))
        availability[qubits[0]] = layer
        availability[qubits[1]] = layer
        maximum = max(maximum, layer)
    return maximum


def _qiskit_cost_circuit(evaluation: DesignEvaluation):
    try:
        from qiskit import QuantumCircuit
        from qiskit.circuit import Parameter
    except ImportError as error:
        raise E2ResourcesError("Formal E2 requires the frozen Qiskit stack") from error

    circuit = QuantumCircuit(evaluation.representation.n_qubits)
    gamma = Parameter("gamma")
    for support, coefficient in sorted(
        evaluation.reference.pauli.items(), key=lambda item: (len(item[0]), item[0])
    ):
        if not support:
            continue
        target = support[-1] - 1
        angle = float(2 * coefficient) * gamma
        if len(support) == 1:
            circuit.rz(angle, target)
            continue
        controls = [variable - 1 for variable in support[:-1]]
        for control in controls:
            circuit.cx(control, target)
        circuit.rz(angle, target)
        for control in reversed(controls):
            circuit.cx(control, target)
    return circuit


def compile_sparse_design(
    evaluation: DesignEvaluation,
    *,
    compiler_config: Mapping[str, object],
    transpiler_seed: int,
) -> dict[str, object]:
    """Compile one design to the frozen sparse topology and retain failures."""

    architectures = {
        str(item["id"]): item  # type: ignore[index]
        for item in compiler_config["architectures"]  # type: ignore[index]
    }
    sparse = architectures["device_sparse_v1"]
    coupling_map = [tuple(edge) for edge in sparse["coupling_map"]]  # type: ignore[index]
    capacity = 1 + max(max(edge) for edge in coupling_map)
    if evaluation.representation.n_qubits > capacity:
        return {
            "topology_capacity": capacity,
            "two_qubit_gates": "",
            "two_qubit_depth": "",
            "swap_count": "",
            "swap_count_method": "not_applicable_width_infeasible",
            "routing_overhead": "",
            "compile_runtime_sec": 0.0,
            "status": "infeasible_width_exceeds_topology",
            "failure_kind": "expected_capacity_failure",
            "failure_message": (
                f"logical width {evaluation.representation.n_qubits} exceeds "
                f"device_sparse_v1 capacity {capacity}"
            ),
            "qiskit_version": str(
                compiler_config["software"]["qiskit_version"]  # type: ignore[index]
            ),
        }

    try:
        import qiskit
        from qiskit import transpile
        from qiskit.transpiler import CouplingMap
    except ImportError as error:
        raise E2ResourcesError("Formal E2 requires qiskit==2.4.2") from error

    expected_version = str(compiler_config["software"]["qiskit_version"])  # type: ignore[index]
    if qiskit.__version__ != expected_version:
        raise E2ResourcesError(
            f"Qiskit version mismatch: expected {expected_version}, received {qiskit.__version__}"
        )

    circuit = _qiskit_cost_circuit(evaluation)
    observed_swaps: list[int] = []

    def callback(**kwargs):
        dag = kwargs.get("dag")
        pass_object = kwargs.get("pass_")
        if dag is None or pass_object is None:
            return
        pass_name = pass_object.__class__.__name__.lower()
        counts = dag.count_ops()
        swaps = int(counts.get("swap", 0))
        if swaps or "swap" in pass_name or "routing" in pass_name:
            observed_swaps.append(swaps)

    started = time.perf_counter()
    try:
        compiled = transpile(
            circuit,
            basis_gates=list(compiler_config["basis_gates"]),  # type: ignore[arg-type,index]
            coupling_map=CouplingMap(list(coupling_map)),
            optimization_level=int(compiler_config["optimization_level"]),  # type: ignore[index]
            layout_method=str(compiler_config["layout_method"]),  # type: ignore[index]
            routing_method=str(compiler_config["routing_method"]),  # type: ignore[index]
            translation_method=str(compiler_config["translation_method"]),  # type: ignore[index]
            seed_transpiler=transpiler_seed,
            callback=callback,
        )
    except Exception as error:  # compiler failures must become scheduled rows
        return {
            "topology_capacity": capacity,
            "two_qubit_gates": "",
            "two_qubit_depth": "",
            "swap_count": "",
            "swap_count_method": "compiler_failed",
            "routing_overhead": "",
            "compile_runtime_sec": time.perf_counter() - started,
            "status": "compiler_failure",
            "failure_kind": error.__class__.__name__,
            "failure_message": str(error)[:500],
            "qiskit_version": qiskit.__version__,
        }

    runtime = time.perf_counter() - started
    two_qubit_gates = sum(
        1 for item in compiled.data if len(item.qubits) == 2
    )
    two_qubit_depth = _two_qubit_depth(compiled)
    routing_overhead = two_qubit_gates - evaluation.reference.two_qubit_gate_count
    swap_count = max(observed_swaps, default=0)
    swap_method = "routing_pass_callback"
    if swap_count == 0 and routing_overhead > 0:
        swap_count = max(0, routing_overhead // 3)
        swap_method = "post_translation_cx_overhead_equivalent_floor"

    directed_edges = set(coupling_map)
    for item in compiled.data:
        if len(item.qubits) != 2:
            continue
        endpoints = tuple(compiled.find_bit(qubit).index for qubit in item.qubits)
        if endpoints not in directed_edges:
            raise E2ResourcesError(
                f"Compiled two-qubit edge {endpoints} violates frozen coupling map"
            )
    return {
        "topology_capacity": capacity,
        "two_qubit_gates": two_qubit_gates,
        "two_qubit_depth": two_qubit_depth,
        "swap_count": swap_count,
        "swap_count_method": swap_method,
        "routing_overhead": routing_overhead,
        "compile_runtime_sec": runtime,
        "status": "pass",
        "failure_kind": "",
        "failure_message": "",
        "qiskit_version": qiskit.__version__,
    }


def compile_design_rows(
    logical: Mapping[str, object],
    evaluation: DesignEvaluation,
    *,
    compiler_config: Mapping[str, object],
    protocol_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seeds = [int(seed) for seed in compiler_config["transpiler_seed_bundle"]]  # type: ignore[index]
    for seed in seeds:
        started = time.perf_counter()
        reference = compile_reference(
            evaluation.representation.polynomial,
            n_qubits=evaluation.representation.n_qubits,
        )
        reference_runtime = time.perf_counter() - started
        common = {
            field: logical[field]
            for field in (
                "instance_id",
                "family",
                "split",
                "representation",
                "random_rep_seed",
                "design_id",
                "n_original",
                "n_aux",
                "n_qubits",
                "retained_cubic",
                "quadratic_couplings",
                "M_max",
                "coefficient_dynamic_range",
                "config_hash",
                "manifest_hash",
                "code_commit",
            )
        }
        rows.append(
            {
                **common,
                "topology_id": "all_to_all_reference",
                "topology_capacity": "unbounded_compilation_tier_logical_reference",
                "transpiler_seed": seed,
                "two_qubit_gates": reference.two_qubit_gate_count,
                "two_qubit_depth": reference.two_qubit_depth,
                "swap_count": 0,
                "swap_count_method": "reference_definition",
                "routing_overhead": 0,
                "compile_runtime_sec": reference_runtime,
                "status": "pass",
                "failure_kind": "",
                "failure_message": "",
                "compiler_protocol_id": protocol_id,
                "qiskit_version": str(compiler_config["software"]["qiskit_version"]),  # type: ignore[index]
            }
        )
        sparse = compile_sparse_design(
            evaluation,
            compiler_config=compiler_config,
            transpiler_seed=seed,
        )
        rows.append(
            {
                **common,
                "topology_id": "device_sparse_v1",
                "transpiler_seed": seed,
                "compiler_protocol_id": protocol_id,
                **sparse,
            }
        )
    return rows


def _uncertainty(values: Sequence[float]) -> dict[str, float | str]:
    if not values:
        return {
            "mean": "",
            "median": "",
            "std": "",
            "ci95_low": "",
            "ci95_high": "",
        }
    mean = statistics.fmean(values)
    median = statistics.median(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    half_width = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "mean": mean,
        "median": median,
        "std": std,
        "ci95_low": mean - half_width,
        "ci95_high": mean + half_width,
    }


def summarise_compiled_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, object]]] = {}
    for row in rows:
        key = (
            str(row["instance_id"]),
            str(row["family"]),
            str(row["split"]),
            str(row["representation"]),
            str(row["topology_id"]),
        )
        groups.setdefault(key, []).append(row)
    output: list[dict[str, object]] = []
    for key, group in sorted(groups.items()):
        successes = [row for row in group if row["status"] == "pass"]
        failures = [row for row in group if row["status"] != "pass"]

        def values(field: str) -> list[float]:
            return [float(row[field]) for row in successes]

        gates = _uncertainty(values("two_qubit_gates"))
        depth = _uncertainty(values("two_qubit_depth"))
        swaps = _uncertainty(values("swap_count"))
        overhead = _uncertainty(values("routing_overhead"))
        runtime = _uncertainty(values("compile_runtime_sec"))
        failure_kinds = sorted({str(row["failure_kind"]) for row in failures})
        if not failures:
            status = "pass"
        elif not successes and all(
            row["status"] == "infeasible_width_exceeds_topology"
            for row in failures
        ):
            status = "expected_infeasible_width"
        else:
            status = "unexpected_compiler_failure"
        output.append(
            {
                "instance_id": key[0],
                "family": key[1],
                "split": key[2],
                "representation": key[3],
                "topology_id": key[4],
                "scheduled_row_count": len(group),
                "success_count": len(successes),
                "failure_count": len(failures),
                "random_rep_seed_count": len(
                    {str(row["random_rep_seed"]) for row in group if str(row["random_rep_seed"])}
                ),
                "transpiler_seed_count": len(
                    {int(row["transpiler_seed"]) for row in group}
                ),
                "two_qubit_gates_mean": gates["mean"],
                "two_qubit_gates_median": gates["median"],
                "two_qubit_gates_std": gates["std"],
                "two_qubit_gates_ci95_low": gates["ci95_low"],
                "two_qubit_gates_ci95_high": gates["ci95_high"],
                "two_qubit_depth_mean": depth["mean"],
                "two_qubit_depth_median": depth["median"],
                "two_qubit_depth_std": depth["std"],
                "two_qubit_depth_ci95_low": depth["ci95_low"],
                "two_qubit_depth_ci95_high": depth["ci95_high"],
                "swap_count_mean": swaps["mean"],
                "swap_count_median": swaps["median"],
                "routing_overhead_mean": overhead["mean"],
                "routing_overhead_median": overhead["median"],
                "compile_runtime_sec_mean": runtime["mean"],
                "compile_runtime_sec_median": runtime["median"],
                "status": status,
                "failure_kinds": ";".join(failure_kinds),
                "config_hash": group[0]["config_hash"],
                "manifest_hash": group[0]["manifest_hash"],
                "code_commit": group[0]["code_commit"],
            }
        )
    return output


def selector_validation_rows(
    oracle_rows: Sequence[Mapping[str, str]],
    *,
    data_directory: Path,
    config: Mapping[str, object],
    config_hash: str,
    manifest_hash: str,
    code_commit: str,
) -> list[dict[str, object]]:
    selector = config["selector"]  # type: ignore[assignment]
    output: list[dict[str, object]] = []
    for ordinal, row in enumerate(sorted(oracle_rows, key=lambda item: item["instance_id"]), start=1):
        canonical_path = data_directory / row["canonical_file"]
        if _sha256(canonical_path) != row["canonical_sha256"]:
            raise E2ResourcesError(
                f"Canonical coefficient hash mismatch: {row['instance_id']}"
            )
        family, polynomial = _canonical_polynomial(canonical_path)
        n_original = int(row["n"])
        started = time.perf_counter()
        optimum_actions, optimum_report = select_resource_optimal_design(
            polynomial,
            n_original=n_original,
            selector_config=selector,
            positive_margin=1,
        )
        optimum_runtime = time.perf_counter() - started
        optimum = _evaluate_design(
            polynomial,
            n_original=n_original,
            actions=optimum_actions,
            selector=selector,
            apply_qaoa_hard_limits=True,
        )
        beam = beam_select_design(
            polynomial,
            n_original=n_original,
            selector=selector,
            apply_qaoa_hard_limits=True,
        )
        greedy = greedy_select_design(
            polynomial,
            n_original=n_original,
            selector=selector,
            apply_qaoa_hard_limits=True,
        )
        methods = (
            (
                "full_space_optimum",
                "certified_complete_resource_objective",
                optimum,
                optimum_runtime,
                int(optimum_report["design_count"]),
            ),
            (
                "pareto_beam",
                "beam_incumbent_not_certified",
                beam.evaluation,
                beam.runtime_sec,
                beam.compiler_calls,
            ),
            (
                "greedy_native_completion",
                "heuristic_result_not_certified",
                greedy.evaluation,
                greedy.runtime_sec,
                greedy.compiler_calls,
            ),
        )
        for method, certificate, evaluation, runtime, compiler_calls in methods:
            maximum_penalty = max(
                evaluation.representation.penalties.values(), default=Fraction(0)
            )
            regret = evaluation.score - optimum.score
            if regret < 0:
                raise E2ResourcesError(
                    f"Selector validation produced negative regret: {row['instance_id']}"
                )
            output.append(
                {
                    "instance_id": row["instance_id"],
                    "family": family,
                    "split": row["split"],
                    "method": method,
                    "certificate_status": certificate,
                    "selected_design_id": _design_id(evaluation.actions),
                    "selected_n_aux": evaluation.representation.n_auxiliary,
                    "selected_two_qubit_gates": evaluation.reference.two_qubit_gate_count,
                    "selected_two_qubit_depth": evaluation.reference.two_qubit_depth,
                    "selected_M_max": float(maximum_penalty),
                    "objective": float(evaluation.score),
                    "certified_optimum_objective": float(optimum.score),
                    "regret": float(regret),
                    "hit_certified_design": evaluation.actions == optimum.actions,
                    "runtime_sec": runtime,
                    "compiler_calls": compiler_calls,
                    "weights_tuned_on": "train+validation_frozen_step1",
                    "test_retuning_used": False,
                    "status": "pass",
                    "config_hash": config_hash,
                    "manifest_hash": manifest_hash,
                    "code_commit": code_commit,
                }
            )
        if ordinal % 5 == 0:
            pass
    return output


def _verify_hash(path: Path, sidecar: Path) -> str:
    if not path.is_file() or not sidecar.is_file():
        raise E2ResourcesError(f"Missing frozen file/hash: {path} / {sidecar}")
    actual = _sha256(path)
    declared = sidecar.read_text(encoding="utf-8").strip()
    if actual != declared:
        raise E2ResourcesError(f"Frozen hash mismatch: {path}")
    return actual


def verify_e2_inputs(
    *,
    config_path: Path,
    config_hash_path: Path,
    data_directory: Path,
    results_directory: Path,
) -> dict[str, object]:
    freeze = verify_data_freeze(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
    )
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["status"] != "frozen" or config["freeze_gate"]["blocked"]:
        raise E2ResourcesError("E2 requires the formal frozen configuration")
    if config["selector"]["retune_on_test"] is not False:
        raise E2ResourcesError("Selector test retuning must be disabled")
    if config["selector"]["tune_on"] != ["train", "validation"]:
        raise E2ResourcesError("Selector tuning splits differ from frozen config")
    compiler = config["compiler"]
    if compiler["same_protocol_for_all_representations"] is not True:
        raise E2ResourcesError("Compiler fairness flag is not frozen true")
    architecture_ids = [item["id"] for item in compiler["architectures"]]
    if architecture_ids != ["all_to_all_reference", "device_sparse_v1"]:
        raise E2ResourcesError("Unexpected frozen topology set")
    seeds = compiler["transpiler_seed_bundle"]
    if len(seeds) != 5 or len(set(seeds)) != 5:
        raise E2ResourcesError("E2 requires five distinct transpiler seeds")

    compilation_path = data_directory / "manifests" / "compilation_v1.csv"
    compilation_hash = _verify_hash(
        compilation_path,
        data_directory / "manifests" / "compilation_v1.sha256",
    )
    compilation_rows = _read_csv(compilation_path)
    compilation_counts: dict[str, int] = {}
    for row in compilation_rows:
        compilation_counts[row["family"]] = compilation_counts.get(row["family"], 0) + 1
    if compilation_counts != {"cubic_spin_glass": 90, "max3sat": 90}:
        raise E2ResourcesError(f"Wrong compilation manifest counts: {compilation_counts}")

    oracle_path = data_directory / "manifests" / "oracle_v1.csv"
    oracle_hash = _verify_hash(
        oracle_path, data_directory / "manifests" / "oracle_v1.sha256"
    )
    oracle_rows = _read_csv(oracle_path)
    if len(oracle_rows) != 60:
        raise E2ResourcesError("Wrong oracle manifest count")

    e1_artifacts = (
        results_directory / "e1_exactness.csv",
        results_directory / "e1_penalty_witnesses.json",
        results_directory / "e1_penalty_trials.json",
        results_directory / "e1_selected_designs.json",
        results_directory / "e1_validation_summary.json",
    )
    for artifact in e1_artifacts:
        _verify_hash(artifact, artifact.with_suffix(".sha256"))
    e1_summary = _load_json(results_directory / "e1_validation_summary.json")
    if not (
        e1_summary.get("status") == "pass"
        and e1_summary.get("e2_e6_may_continue") is True
        and int(e1_summary.get("strict_mismatch_count", -1)) == 0
        and int(e1_summary.get("strict_inconsistent_minimiser_count", -1)) == 0
        and int(e1_summary.get("canonical_coefficient_hash_mismatch_count", -1)) == 0
    ):
        raise E2ResourcesError("Formal E1 stop gate does not permit E2")
    return {
        **freeze,
        "config": config,
        "compilation_manifest_hash": compilation_hash,
        "compilation_rows": compilation_rows,
        "oracle_manifest_hash": oracle_hash,
        "oracle_rows": oracle_rows,
        "e1_summary_hash": _sha256(results_directory / "e1_validation_summary.json"),
    }


def _format_number(value: object) -> str:
    if value == "" or value is None:
        return "--"
    number = float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.2f}"


def _latex_table(
    logical_rows: Sequence[Mapping[str, object]],
    summary_rows: Sequence[Mapping[str, object]],
) -> str:
    representation_order = (
        "all_native",
        "fully_quadratized",
        "selective",
        "matched_random_selective",
    )
    lines = [
        "% Auto-generated formal E2 resource summary; do not edit by hand.",
        "\\begin{tabular}{lllrrrrrr}",
        "\\toprule",
        "Family & Topology & Representation & $N$ & Aux. & 2Q gates & 2Q depth & SWAP & Success \\\\",
        "\\midrule",
    ]
    for family in ("max3sat", "cubic_spin_glass"):
        for topology in ("all_to_all_reference", "device_sparse_v1"):
            for representation in representation_order:
                logical = [
                    row
                    for row in logical_rows
                    if row["family"] == family and row["representation"] == representation
                ]
                summaries = [
                    row
                    for row in summary_rows
                    if row["family"] == family
                    and row["topology_id"] == topology
                    and row["representation"] == representation
                    and int(row["success_count"]) > 0
                ]
                n_value = statistics.median(float(row["n_qubits"]) for row in logical)
                aux_value = statistics.median(float(row["n_aux"]) for row in logical)
                gates = (
                    statistics.median(float(row["two_qubit_gates_median"]) for row in summaries)
                    if summaries
                    else ""
                )
                depth = (
                    statistics.median(float(row["two_qubit_depth_median"]) for row in summaries)
                    if summaries
                    else ""
                )
                swaps = (
                    statistics.median(float(row["swap_count_median"]) for row in summaries)
                    if summaries
                    else ""
                )
                success = sum(int(row["success_count"]) for row in summaries)
                scheduled = sum(
                    int(row["scheduled_row_count"])
                    for row in summary_rows
                    if row["family"] == family
                    and row["topology_id"] == topology
                    and row["representation"] == representation
                )
                labels = [family, topology, representation]
                labels = [label.replace("_", "\\_") for label in labels]
                lines.append(
                    f"{labels[0]} & {labels[1]} & {labels[2]} & "
                    f"{_format_number(n_value)} & {_format_number(aux_value)} & "
                    f"{_format_number(gates)} & {_format_number(depth)} & "
                    f"{_format_number(swaps)} & {success}/{scheduled} \\\\"
                )
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def _figure_medians(
    logical_rows: Sequence[Mapping[str, object]],
    summary_rows: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, float]]:
    representations = (
        "all_native",
        "fully_quadratized",
        "selective",
        "matched_random_selective",
    )
    output: dict[str, dict[str, float]] = {}
    for representation in representations:
        logical = [row for row in logical_rows if row["representation"] == representation]
        reference = [
            row
            for row in summary_rows
            if row["representation"] == representation
            and row["topology_id"] == "all_to_all_reference"
            and int(row["success_count"]) > 0
        ]
        sparse = [
            row
            for row in summary_rows
            if row["representation"] == representation
            and row["topology_id"] == "device_sparse_v1"
            and int(row["success_count"]) > 0
        ]
        output[representation] = {
            "logical_qubits": statistics.median(float(row["n_qubits"]) for row in logical),
            "reference_gates": statistics.median(float(row["two_qubit_gates_median"]) for row in reference),
            "sparse_gates": statistics.median(float(row["two_qubit_gates_median"]) for row in sparse) if sparse else 0.0,
            "sparse_overhead": statistics.median(float(row["routing_overhead_median"]) for row in sparse) if sparse else 0.0,
        }
    return output


def write_resource_figure_pdf(
    path: Path,
    logical_rows: Sequence[Mapping[str, object]],
    summary_rows: Sequence[Mapping[str, object]],
) -> str:
    """Create the required one-page vector PDF with ReportLab."""

    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as error:
        raise E2ResourcesError("Formal E2 PDF output requires reportlab==4.4.9") from error

    if reportlab.Version != "4.4.9":
        raise E2ResourcesError(
            f"ReportLab version mismatch: expected 4.4.9, received {reportlab.Version}"
        )
    values = _figure_medians(logical_rows, summary_rows)
    regular_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    font_candidates = (
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("C:/Windows/Fonts/DejaVuSans.ttf"),
            Path("C:/Windows/Fonts/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ),
    )
    for regular_path, bold_path in font_candidates:
        if regular_path.is_file() and bold_path.is_file():
            pdfmetrics.registerFont(TTFont("E2Sans", str(regular_path)))
            pdfmetrics.registerFont(TTFont("E2SansBold", str(bold_path)))
            regular_font = "E2Sans"
            bold_font = "E2SansBold"
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    pdf = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1)
    pdf.setTitle("Formal E2 logical and compiled resources")
    pdf.setAuthor("URSS formal pipeline")
    pdf.setFillColor(colors.HexColor("#17324D"))
    pdf.setFont(bold_font, 18)
    pdf.drawString(42, height - 44, "Formal E2: logical and compiled resources")
    pdf.setFont(regular_font, 8.5)
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.drawString(
        42,
        height - 60,
        "Medians across the frozen compilation manifest; sparse bars use successful scheduled rows only.",
    )

    labels = {
        "all_native": "Native",
        "fully_quadratized": "Full",
        "selective": "Selected",
        "matched_random_selective": "Matched random",
    }
    panels = (
        ("logical_qubits", "Logical qubits"),
        ("reference_gates", "Reference 2Q gates"),
        ("sparse_gates", "Sparse 2Q gates"),
        ("sparse_overhead", "Sparse routing overhead"),
    )
    palette = (
        colors.HexColor("#1F77B4"),
        colors.HexColor("#FF7F0E"),
        colors.HexColor("#2CA02C"),
        colors.HexColor("#9467BD"),
    )
    left = 42
    bottom = 92
    gap = 18
    panel_width = (width - 2 * left - gap) / 2
    panel_height = (height - bottom - 86 - gap) / 2
    for panel_index, (metric, title) in enumerate(panels):
        column = panel_index % 2
        row = 1 - panel_index // 2
        x0 = left + column * (panel_width + gap)
        y0 = bottom + row * (panel_height + gap)
        pdf.setStrokeColor(colors.HexColor("#CFD8DC"))
        pdf.setFillColor(colors.white)
        pdf.roundRect(x0, y0, panel_width, panel_height, 5, fill=1, stroke=1)
        pdf.setFillColor(colors.HexColor("#17324D"))
        pdf.setFont(bold_font, 10)
        pdf.drawString(x0 + 12, y0 + panel_height - 18, title)
        raw = [values[key][metric] for key in labels]
        maximum = max(raw) if max(raw) > 0 else 1.0
        chart_bottom = y0 + 34
        chart_height = panel_height - 64
        bar_gap = 15
        bar_width = (panel_width - 36 - 3 * bar_gap) / 4
        for index, (key, label) in enumerate(labels.items()):
            value = values[key][metric]
            bar_height = chart_height * value / maximum
            x = x0 + 18 + index * (bar_width + bar_gap)
            pdf.setFillColor(palette[index])
            pdf.rect(x, chart_bottom, bar_width, bar_height, fill=1, stroke=0)
            pdf.setFillColor(colors.HexColor("#263238"))
            pdf.setFont(bold_font, 7.5)
            pdf.drawCentredString(x + bar_width / 2, chart_bottom + bar_height + 4, _format_number(value))
            pdf.setFont(regular_font, 6.5)
            pdf.drawCentredString(x + bar_width / 2, chart_bottom - 11, label)

    expected_failures = sum(
        int(row["failure_count"])
        for row in summary_rows
        if row["status"] == "expected_infeasible_width"
    )
    unexpected_failures = sum(
        int(row["failure_count"])
        for row in summary_rows
        if row["status"] == "unexpected_compiler_failure"
    )
    pdf.setFillColor(colors.HexColor("#455A64"))
    pdf.setFont(regular_font, 8)
    pdf.drawString(
        42,
        58,
        f"Expected sparse-width failures retained: {expected_failures}; unexpected compiler failures: {unexpected_failures}.",
    )
    pdf.drawString(
        42,
        44,
        "The 12-qubit frozen sparse topology cannot host wider compilation-tier designs; no row is silently removed.",
    )
    pdf.setFont(regular_font, 7)
    pdf.drawRightString(width - 42, 28, "Generated by the frozen formal E2 pipeline")
    pdf.showPage()
    pdf.save()
    return reportlab.Version


def _protocol_id(compiler_config: Mapping[str, object]) -> str:
    payload = json.dumps(
        compiler_config, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return "compiler_" + hashlib.sha256(payload).hexdigest()[:24]


def _representation_designs(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    instance_id: str,
    config: Mapping[str, object],
) -> tuple[
    list[tuple[str, int | None, DesignEvaluation, str, int]],
    dict[str, object],
]:
    selector = config["selector"]  # type: ignore[assignment]
    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    native_actions: tuple[Support | None, ...] = (None,) * len(cubics)
    native = _evaluate_design(
        polynomial,
        n_original=n_original,
        actions=native_actions,
        selector=selector,
        apply_qaoa_hard_limits=False,
    )
    full_actions = _full_actions(polynomial)
    full = _evaluate_design(
        polynomial,
        n_original=n_original,
        actions=full_actions,
        selector=selector,
        apply_qaoa_hard_limits=False,
    )
    selected = beam_select_design(
        polynomial,
        n_original=n_original,
        selector=selector,
        apply_qaoa_hard_limits=False,
    )
    random_seed_bundle = [
        int(seed)
        for seed in config["representations"]["matched_random"]["seed_bundle"]  # type: ignore[index]
    ]
    random_actions = matched_random_designs(
        polynomial,
        selected_actions=selected.actions,
        instance_id=instance_id,
        seed_bundle=random_seed_bundle,
    )
    designs: list[tuple[str, int | None, DesignEvaluation, str, int]] = [
        ("all_native", None, native, "endpoint_not_searched", 0),
        ("fully_quadratized", None, full, "deterministic_minimum_pair_cover", 0),
        (
            "selective",
            None,
            selected.evaluation,
            selected.status,
            selected.compiler_calls,
        ),
    ]
    for seed, actions in random_actions:
        evaluation = _evaluate_design(
            polynomial,
            n_original=n_original,
            actions=actions,
            selector=selector,
            apply_qaoa_hard_limits=False,
        )
        designs.append(
            (
                "matched_random_selective",
                seed,
                evaluation,
                "matched_on_auxiliary_count",
                0,
            )
        )
    design_record = {
        "instance_id": instance_id,
        "n_original": n_original,
        "selection_scope": (
            "compilation_resource_only_frozen_weights_without_qaoa_hard_limits"
        ),
        "selected_search_status": selected.status,
        "selected_runtime_sec": selected.runtime_sec,
        "selected_compiler_calls": selected.compiler_calls,
        "selected_actions": _serialise_actions(selected.actions),
        "selected_design_id": _design_id(selected.actions),
        "matched_random": [
            {
                "seed": seed,
                "actions": _serialise_actions(actions),
                "design_id": _design_id(actions),
                "degenerate_to_selected": actions == selected.actions,
            }
            for seed, actions in random_actions
        ],
    }
    return designs, design_record


def _fairness_audit(
    compiled_rows: Sequence[Mapping[str, object]],
    *,
    compilation_instance_ids: set[str],
    compiler_config: Mapping[str, object],
) -> dict[str, int]:
    seeds = {int(value) for value in compiler_config["transpiler_seed_bundle"]}  # type: ignore[index]
    topologies = {"all_to_all_reference", "device_sparse_v1"}
    instance_ids = {str(row["instance_id"]) for row in compiled_rows}
    instance_alignment_failures = len(compilation_instance_ids ^ instance_ids)
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    for row in compiled_rows:
        key = (
            str(row["instance_id"]),
            str(row["representation"]),
            str(row["design_id"]),
        )
        groups.setdefault(key, []).append(row)
    topology_failures = 0
    seed_failures = 0
    protocol_failures = 0
    for group in groups.values():
        if {str(row["topology_id"]) for row in group} != topologies:
            topology_failures += 1
        for topology in topologies:
            observed = {
                int(row["transpiler_seed"])
                for row in group
                if row["topology_id"] == topology
            }
            if observed != seeds:
                seed_failures += 1
        if len({str(row["compiler_protocol_id"]) for row in group}) != 1:
            protocol_failures += 1
    return {
        "instance_alignment_failure_count": instance_alignment_failures,
        "topology_bundle_failure_count": topology_failures,
        "seed_bundle_failure_count": seed_failures,
        "compiler_protocol_failure_count": protocol_failures,
    }


def run_e2_resources_pipeline(
    *,
    config_path: str | Path,
    config_hash_path: str | Path,
    data_directory: str | Path,
    results_directory: str | Path,
    tables_directory: str | Path,
    figures_directory: str | Path,
    code_commit: str,
    assumptions_path: str | Path | None = None,
    run_commands_path: str | Path | None = None,
    progress=None,
) -> dict[str, object]:
    """Run formal E2 and emit every raw, summary, selector, and report artifact."""

    config_path = Path(config_path)
    config_hash_path = Path(config_hash_path)
    data_directory = Path(data_directory)
    results_directory = Path(results_directory)
    tables_directory = Path(tables_directory)
    figures_directory = Path(figures_directory)
    project_root = results_directory.parent
    relative_targets = (
        Path("results/e2_logical_resources.csv"),
        Path("results/e2_compiled_resources_by_seed.csv"),
        Path("results/e2_compiled_resources_summary.csv"),
        Path("results/selector_validation.csv"),
        Path("results/e2_designs.json"),
        Path("results/e2_validation_summary.json"),
        Path("tables/table_e2_resources.tex"),
        Path("figures/figure_e2_resources.pdf"),
    )
    if any((project_root / path).exists() for path in relative_targets):
        raise FileExistsError("Formal E2 output already exists; refusing overwrite")
    staging = project_root / "e2_step4_building"
    if staging.exists():
        raise E2ResourcesError(f"Incomplete E2 staging directory exists: {staging}")

    freeze = verify_e2_inputs(
        config_path=config_path,
        config_hash_path=config_hash_path,
        data_directory=data_directory,
        results_directory=results_directory,
    )
    config = freeze["config"]  # type: ignore[assignment]
    compiler_config = config["compiler"]  # type: ignore[index]
    protocol_id = _protocol_id(compiler_config)
    config_hash = str(freeze["config_hash"])
    manifest_hash = str(freeze["compilation_manifest_hash"])
    compilation_rows = freeze["compilation_rows"]  # type: ignore[assignment]
    oracle_rows = freeze["oracle_rows"]  # type: ignore[assignment]

    staging.mkdir(parents=True)
    logical_rows: list[dict[str, object]] = []
    compiled_rows: list[dict[str, object]] = []
    design_records: list[dict[str, object]] = []
    try:
        for ordinal, row in enumerate(
            sorted(compilation_rows, key=lambda item: item["instance_id"]), start=1
        ):
            canonical_path = data_directory / row["canonical_file"]
            if _sha256(canonical_path) != row["canonical_sha256"]:
                raise E2ResourcesError(
                    f"Canonical coefficient hash mismatch: {row['instance_id']}"
                )
            family, polynomial = _canonical_polynomial(canonical_path)
            if family != row["family"]:
                raise E2ResourcesError(f"Family mismatch: {row['instance_id']}")
            designs, design_record = _representation_designs(
                polynomial,
                n_original=int(row["n"]),
                instance_id=row["instance_id"],
                config=config,
            )
            design_record.update(
                {
                    "family": family,
                    "split": row["split"],
                    "config_hash": config_hash,
                    "manifest_hash": manifest_hash,
                    "code_commit": code_commit,
                }
            )
            design_records.append(design_record)
            for representation, random_seed, evaluation, selector_status, calls in designs:
                logical = logical_resource_record(
                    instance_id=row["instance_id"],
                    family=family,
                    split=row["split"],
                    representation_name=representation,
                    random_rep_seed=random_seed,
                    evaluation=evaluation,
                    selector_status=selector_status,
                    selector_compiler_calls=calls,
                    config_hash=config_hash,
                    manifest_hash=manifest_hash,
                    code_commit=code_commit,
                )
                logical_rows.append(logical)
                compiled_rows.extend(
                    compile_design_rows(
                        logical,
                        evaluation,
                        compiler_config=compiler_config,
                        protocol_id=protocol_id,
                    )
                )
            if progress and (ordinal % 5 == 0 or ordinal == len(compilation_rows)):
                progress(
                    f"E2 COMPILATION: {ordinal}/{len(compilation_rows)} instances scheduled"
                )

        summary_rows = summarise_compiled_rows(compiled_rows)
        if progress:
            progress("E2 SELECTOR VALIDATION: starting certified oracle comparisons")
        selector_rows = selector_validation_rows(
            oracle_rows,
            data_directory=data_directory,
            config=config,
            config_hash=config_hash,
            manifest_hash=str(freeze["oracle_manifest_hash"]),
            code_commit=code_commit,
        )
        fairness = _fairness_audit(
            compiled_rows,
            compilation_instance_ids={row["instance_id"] for row in compilation_rows},
            compiler_config=compiler_config,
        )
        unexpected_failures = sum(
            1 for row in compiled_rows if row["status"] == "compiler_failure"
        )
        expected_infeasible = sum(
            1
            for row in compiled_rows
            if row["status"] == "infeasible_width_exceeds_topology"
        )
        selector_negative_regret = sum(
            1 for row in selector_rows if float(row["regret"]) < -1e-12
        )
        selector_test_retuning = sum(
            1 for row in selector_rows if row["test_retuning_used"] is not False
        )
        matched_degenerate = sum(
            1
            for record in design_records
            for random_record in record["matched_random"]  # type: ignore[index]
            if random_record["degenerate_to_selected"]  # type: ignore[index]
        )
        gates = (
            fairness["instance_alignment_failure_count"] == 0
            and fairness["topology_bundle_failure_count"] == 0
            and fairness["seed_bundle_failure_count"] == 0
            and fairness["compiler_protocol_failure_count"] == 0
            and unexpected_failures == 0
            and expected_infeasible > 0
            and selector_negative_regret == 0
            and selector_test_retuning == 0
            and len(logical_rows) == 1440
            and len(compiled_rows) == 14400
            and len(summary_rows) == 1440
            and len(selector_rows) == 180
        )

        logical_path = staging / "results/e2_logical_resources.csv"
        compiled_path = staging / "results/e2_compiled_resources_by_seed.csv"
        summary_path = staging / "results/e2_compiled_resources_summary.csv"
        selector_path = staging / "results/selector_validation.csv"
        designs_path = staging / "results/e2_designs.json"
        table_path = staging / "tables/table_e2_resources.tex"
        figure_path = staging / "figures/figure_e2_resources.pdf"
        validation_path = staging / "results/e2_validation_summary.json"
        _write_csv(logical_path, logical_rows, LOGICAL_FIELDS)
        _write_csv(compiled_path, compiled_rows, COMPILED_FIELDS)
        _write_csv(summary_path, summary_rows, SUMMARY_FIELDS)
        _write_csv(selector_path, selector_rows, SELECTOR_FIELDS)
        _write_json(
            designs_path,
            {
                "schema_version": "e2_designs_v1",
                "selection_scope": (
                    "compilation_resource_only_frozen_weights_without_qaoa_hard_limits"
                ),
                "designs": design_records,
            },
        )
        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(
            _latex_table(logical_rows, summary_rows),
            encoding="utf-8",
            newline="\n",
        )
        reportlab_version = write_resource_figure_pdf(
            figure_path, logical_rows, summary_rows
        )
        artifact_hashes = {
            str(path.relative_to(staging)): _write_hash(path)
            for path in (
                logical_path,
                compiled_path,
                summary_path,
                selector_path,
                designs_path,
                table_path,
                figure_path,
            )
        }
        validation = {
            "status": "pass" if gates else "fail",
            "scope": "formal_step4_e2_logical_and_compiled_resources",
            "config_hash": config_hash,
            "compilation_manifest_hash": manifest_hash,
            "oracle_manifest_hash": freeze["oracle_manifest_hash"],
            "e1_validation_summary_hash": freeze["e1_summary_hash"],
            "code_commit": code_commit,
            "compiler_protocol_id": protocol_id,
            "qiskit_version": compiler_config["software"]["qiskit_version"],
            "reportlab_version": reportlab_version,
            "compilation_instance_count": len(compilation_rows),
            "logical_row_count": len(logical_rows),
            "compiled_raw_row_count": len(compiled_rows),
            "compiled_summary_row_count": len(summary_rows),
            "selector_validation_row_count": len(selector_rows),
            "expected_sparse_width_infeasible_row_count": expected_infeasible,
            "unexpected_compiler_failure_count": unexpected_failures,
            "matched_random_degenerate_to_selected_count": matched_degenerate,
            "selector_negative_regret_count": selector_negative_regret,
            "selector_test_retuning_count": selector_test_retuning,
            **fairness,
            "compilation_selector_scope": (
                "frozen_weights_without_qaoa_hard_limits_because_compilation_tier_includes_n_above_qmax"
            ),
            "sparse_capacity_policy": (
                "retain_infeasible_width_rows_for_frozen_12_qubit_topology"
            ),
            "artifact_hashes": artifact_hashes,
            "e3_e6_may_continue": gates,
        }
        _write_json(validation_path, validation)
        _write_hash(validation_path)
        if not gates:
            raise E2ResourcesError(
                f"Formal E2 fairness/resource gate failed; staging retained at {staging}"
            )

        for relative in relative_targets:
            source = staging / relative
            target = project_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            shutil.move(
                str(source.with_suffix(".sha256")),
                str(target.with_suffix(".sha256")),
            )
        shutil.rmtree(staging)
    except Exception:
        raise

    if assumptions_path is not None:
        assumptions = Path(assumptions_path)
        section = f"""\n## Formal Step 4 / E2 resources (v1)\n\n- Status: `pass`; E3-E6 continuation is allowed.\n- Frozen compilation instances: `180`; logical rows: `1440`; raw compiler rows: `14400`.\n- Every design uses both frozen topology IDs and the complete five-seed transpiler bundle.\n- Expected sparse width failures retained: `{expected_infeasible}`; unexpected compiler failures: `0`.\n- The compilation tier includes widths above Qmax and above the frozen 12-qubit sparse device. Its selector uses the frozen weights without QAOA hard limits, while oracle selector validation retains the QAOA feasibility limits and complete-space certification.\n- Sparse rows wider than 12 qubits are retained as `infeasible_width_exceeds_topology`; they are not excluded or imputed.\n- Selector weights were not tuned on test. Certified, beam-incumbent, and heuristic rows are distinguished in `results/selector_validation.csv`.\n- Compiler protocol ID: `{protocol_id}`.\n- Config hash: `{config_hash}`; compilation manifest hash: `{manifest_hash}`.\n- Matched-random designs degenerating to the selected design: `{matched_degenerate}`; this is reported rather than resampled when no distinct matched design was found.\n"""
        assumptions.write_text(
            assumptions.read_text(encoding="utf-8").rstrip() + "\n" + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if run_commands_path is not None:
        commands = Path(run_commands_path)
        section = """\n## Formal Step 4 / E2 command (v1)\n\n```powershell\npython .\\run_e2_resources.py `\n  --config .\\configs\\experiment_config_v1.yaml `\n  --config-hash .\\configs\\experiment_config_v1.sha256 `\n  --data .\\data `\n  --results .\\results `\n  --tables .\\tables `\n  --figures .\\figures `\n  --assumptions .\\assumptions_and_decisions.md `\n  --run-commands .\\RUN_COMMANDS.md\n```\n\nRequired result: `E2 RESOURCE GATE: pass` and `e3_e6_may_continue=true`.\n"""
        commands.write_text(
            commands.read_text(encoding="utf-8").rstrip() + "\n" + section.lstrip(),
            encoding="utf-8",
            newline="\n",
        )
    if progress:
        progress("E2 RESOURCE GATE: pass")
    return validation
