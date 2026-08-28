"""Frozen fibre-aware representation selector for experiment config v2.

This module is deliberately additive.  The v1 resource-only selector remains
available for reproduction of the already frozen E1--E6 results.  V2 uses one
SA/RLT level-2 moment set per raw instance, an analytically normalised expected
fibre excess as a hard guardrail and Pareto coordinate, and deterministic
resource-score tie breaking.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, product
from typing import Iterable, Mapping, Sequence

import numpy as np

from .e1_exactness import action_options, build_mixed_representation
from .e2_resources import (
    DesignEvaluation,
    FastDesignEvaluation,
    _action_key,
    _evaluate_design,
    _fast_evaluate_design,
)
from .polynomial import Polynomial, Support, canonicalize, cubic_supports, evaluate_pubo, pair_shadow


class FibreSelectorError(RuntimeError):
    """The frozen v2 fibre-aware selector cannot produce a valid result."""


@dataclass(frozen=True)
class FibreMoments:
    """One deterministic optimal SA/RLT level-2 moment vector."""

    objective: float
    singles: Mapping[int, float]
    pairs: Mapping[Support, float]
    status: str
    solver_message: str
    primary_runtime_sec: float
    secondary_runtime_sec: float
    moment_sha256: str


@dataclass(frozen=True)
class FibrePairContribution:
    pair: Support
    assigned_cubic_count: int
    threshold: float
    penalty: float
    mu_product: float
    pair_moment: float
    violation_probability: float
    rosenberg_expectation: float
    residual_expectation: float
    fibre_excess: float


@dataclass(frozen=True)
class FibreRisk:
    excess: float
    normalisation: float
    normalised_excess: float
    union_violation_bound: float
    contributions: tuple[FibrePairContribution, ...]


@dataclass(frozen=True)
class FibreCandidate:
    actions: tuple[Support | None, ...]
    resources: FastDesignEvaluation
    risk: FibreRisk
    feasible: bool

    @property
    def score(self) -> Fraction:
        return self.resources.score

    @property
    def pareto_vector(self) -> tuple[float, ...]:
        return tuple(float(value) for value in self.resources.vector) + (
            self.risk.normalised_excess,
        )


@dataclass(frozen=True)
class FibreSearchResult:
    actions: tuple[Support | None, ...]
    evaluation: DesignEvaluation
    risk: FibreRisk
    status: str
    candidate_evaluations: int
    runtime_sec: float
    certified_optimum_score: Fraction | None = None
    regret: Fraction | None = None


def _moment_digest(
    objective: float,
    singles: Mapping[int, float],
    pairs: Mapping[Support, float],
) -> str:
    payload = [f"objective={objective:.17g}"]
    payload.extend(f"mu:{index}={singles[index]:.17g}" for index in sorted(singles))
    payload.extend(
        f"q:{pair[0]},{pair[1]}={pairs[pair]:.17g}" for pair in sorted(pairs)
    )
    return hashlib.sha256("\n".join(payload).encode("ascii")).hexdigest()


def _secondary_weight(label: str) -> float:
    """Return a deterministic, non-decimal-declared secondary LP weight."""

    digest = hashlib.sha256(label.encode("ascii")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return 1.0 + integer / float(1 << 64)


def solve_deterministic_sa_rlt_level2(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    method: str = "highs",
    presolve: bool = True,
    primary_optimum_tolerance: float = 1e-9,
) -> FibreMoments:
    """Solve SA/RLT level-2 with a frozen secondary optimum-face selector.

    The primary objective is the canonical polynomial relaxation.  A second LP
    is solved on the primary optimum face using SHA256-derived positive weights
    in the declared variable order.  This removes dependence on an arbitrary
    HiGHS optimum whenever the primary LP has multiple optimal moment vectors.
    """

    from scipy.optimize import linprog

    canonical = canonicalize(polynomial)
    singles = tuple(range(1, n_original + 1))
    pairs = tuple(combinations(singles, 2))
    triples = tuple(sorted(support for support in canonical if len(support) == 3))
    indices: dict[tuple[str, object], int] = {}
    labels: list[str] = []
    for variable in singles:
        indices[("mu", variable)] = len(indices)
        labels.append(f"mu:{variable}")
    for pair in pairs:
        indices[("q", pair)] = len(indices)
        labels.append(f"q:{pair[0]},{pair[1]}")
    for triple in triples:
        indices[("t", triple)] = len(indices)
        labels.append("t:" + ",".join(str(value) for value in triple))

    primary = np.zeros(len(indices), dtype=np.float64)
    constant = 0.0
    for support, coefficient in canonical.items():
        value = float(coefficient)
        if not support:
            constant += value
        elif len(support) == 1:
            primary[indices[("mu", support[0])]] += value
        elif len(support) == 2:
            primary[indices[("q", tuple(support))]] += value
        elif len(support) == 3:
            primary[indices[("t", tuple(support))]] += value
        else:
            raise FibreSelectorError("SA/RLT level-2 received degree above three")

    rows: list[np.ndarray] = []
    bounds: list[float] = []

    def inequality(terms: Mapping[tuple[str, object], float], upper: float) -> None:
        row = np.zeros(len(indices), dtype=np.float64)
        for key, coefficient in terms.items():
            row[indices[key]] = coefficient
        rows.append(row)
        bounds.append(float(upper))

    for i, j in pairs:
        pair = (i, j)
        inequality({("q", pair): 1, ("mu", i): -1}, 0)
        inequality({("q", pair): 1, ("mu", j): -1}, 0)
        inequality({("mu", i): 1, ("mu", j): 1, ("q", pair): -1}, 1)

    for triple in triples:
        i, j, k = triple
        t_key = ("t", triple)
        for variable in triple:
            inequality({t_key: 1, ("mu", variable): -1}, 0)
        inequality(
            {
                ("mu", i): 1,
                ("mu", j): 1,
                ("mu", k): 1,
                t_key: -1,
            },
            2,
        )
        for pair, remaining in (((i, j), k), ((i, k), j), ((j, k), i)):
            inequality({t_key: 1, ("q", pair): -1}, 0)
            inequality({("q", pair): 1, ("mu", remaining): 1, t_key: -1}, 1)

    matrix = np.asarray(rows, dtype=np.float64)
    upper = np.asarray(bounds, dtype=np.float64)
    variable_bounds = [(0.0, 1.0)] * len(indices)
    started = time.perf_counter()
    first = linprog(
        primary,
        A_ub=matrix,
        b_ub=upper,
        bounds=variable_bounds,
        method=method,
        options={"presolve": bool(presolve)},
    )
    primary_runtime = time.perf_counter() - started
    if not first.success or first.x is None:
        raise FibreSelectorError(
            f"Primary SA/RLT level-2 failed: status={first.status}; {first.message}"
        )

    tolerance = float(primary_optimum_tolerance)
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise FibreSelectorError("Primary optimum tolerance must be positive")
    optimum = float(first.fun)
    secondary_matrix = np.vstack((matrix, primary, -primary))
    secondary_upper = np.concatenate(
        (upper, np.asarray([optimum + tolerance, -optimum + tolerance]))
    )
    secondary = np.asarray(
        [_secondary_weight(label) for label in labels], dtype=np.float64
    )
    started = time.perf_counter()
    second = linprog(
        secondary,
        A_ub=secondary_matrix,
        b_ub=secondary_upper,
        bounds=variable_bounds,
        method=method,
        options={"presolve": bool(presolve)},
    )
    secondary_runtime = time.perf_counter() - started
    if not second.success or second.x is None:
        raise FibreSelectorError(
            f"Secondary SA/RLT tie break failed: status={second.status}; {second.message}"
        )
    values = np.asarray(second.x, dtype=np.float64)
    realised_primary = float(primary @ values)
    if abs(realised_primary - optimum) > 1.1 * tolerance:
        raise FibreSelectorError("Secondary moment vector left the primary optimum face")

    first_moments = {i: float(values[indices[("mu", i)]]) for i in singles}
    pair_moments = {pair: float(values[indices[("q", pair)]]) for pair in pairs}
    all_values = (*first_moments.values(), *pair_moments.values())
    if any(value < -1e-8 or value > 1 + 1e-8 for value in all_values):
        raise FibreSelectorError("Relaxation moment outside [0,1]")
    first_moments = {key: min(1.0, max(0.0, value)) for key, value in first_moments.items()}
    pair_moments = {key: min(1.0, max(0.0, value)) for key, value in pair_moments.items()}
    objective = realised_primary + constant
    return FibreMoments(
        objective=objective,
        singles=first_moments,
        pairs=pair_moments,
        status="optimal_primary_then_deterministic_secondary",
        solver_message=str(second.message),
        primary_runtime_sec=primary_runtime,
        secondary_runtime_sec=secondary_runtime,
        moment_sha256=_moment_digest(objective, first_moments, pair_moments),
    )


def fibre_normalisation(
    polynomial: Mapping[Support, object], *, positive_margin: float
) -> float:
    """Return the paper's design-independent candidate-pair normalisation."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    pairs = tuple(sorted(pair_shadow(set(cubics))))
    if not pairs:
        return 1.0
    margin = float(positive_margin)
    if margin <= 0:
        raise FibreSelectorError("Strict positive penalty margin is required")
    return 4.0 * sum(
        sum(abs(float(canonical[cubic])) for cubic in cubics if set(pair).issubset(cubic))
        + margin
        for pair in pairs
    )


def fibre_risk(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    moments: FibreMoments,
    positive_margin: float = 1.0,
    tolerance: float = 1e-9,
) -> FibreRisk:
    """Evaluate the frozen closed-form expected fibre excess."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    normalisation = fibre_normalisation(
        canonical, positive_margin=float(positive_margin)
    )
    return _fibre_risk_from_canonical(
        canonical,
        cubics,
        normalisation=normalisation,
        n_original=n_original,
        actions=actions,
        moments=moments,
        positive_margin=positive_margin,
        tolerance=tolerance,
    )


def _fibre_risk_from_canonical(
    canonical: Polynomial,
    cubics: Sequence[Support],
    *,
    normalisation: float,
    n_original: int,
    actions: Sequence[Support | None],
    moments: FibreMoments,
    positive_margin: float,
    tolerance: float = 1e-9,
) -> FibreRisk:
    """Evaluate fibre risk using instance-level precomputed invariants."""

    action_tuple = tuple(actions)
    if len(action_tuple) != len(cubics):
        raise FibreSelectorError("Action vector length differs from cubic support count")
    if set(moments.singles) != set(range(1, n_original + 1)):
        raise FibreSelectorError("Moment vector does not cover every original variable")
    assigned: dict[Support, list[tuple[Support, float]]] = {}
    for cubic, action in zip(cubics, action_tuple):
        if action is None:
            continue
        if not set(action).issubset(cubic):
            raise FibreSelectorError(f"Action {action} is not contained in {cubic}")
        assigned.setdefault(action, []).append((cubic, float(canonical[cubic])))

    contributions: list[FibrePairContribution] = []
    total = 0.0
    violation_sum = 0.0
    for pair in sorted(assigned):
        coefficients = [coefficient for _, coefficient in assigned[pair]]
        positive = sum(value for value in coefficients if value > 0)
        negative = sum(-value for value in coefficients if value < 0)
        threshold = max(positive, negative)
        penalty = threshold + float(positive_margin)
        left, right = pair
        mu_left = float(moments.singles[left])
        mu_right = float(moments.singles[right])
        t_value = mu_left * mu_right
        if pair not in moments.pairs:
            raise FibreSelectorError(f"Missing pair moment for active pair {pair}")
        q_value = float(moments.pairs[pair])
        residual = 0.0
        for cubic, coefficient in assigned[pair]:
            remaining = next(variable for variable in cubic if variable not in pair)
            residual += coefficient * float(moments.singles[remaining])
        violation = q_value * (1.0 - t_value) + (1.0 - q_value) * t_value
        rosenberg = t_value + q_value * (3.0 - 2.0 * mu_left - 2.0 * mu_right)
        contribution = (q_value - t_value) * residual + penalty * rosenberg
        if contribution < -tolerance:
            raise FibreSelectorError(
                f"Closed-form fibre contribution is negative for {pair}: {contribution}"
            )
        contribution = max(0.0, contribution)
        total += contribution
        violation_sum += violation
        contributions.append(
            FibrePairContribution(
                pair=pair,
                assigned_cubic_count=len(assigned[pair]),
                threshold=threshold,
                penalty=penalty,
                mu_product=t_value,
                pair_moment=q_value,
                violation_probability=violation,
                rosenberg_expectation=rosenberg,
                residual_expectation=residual,
                fibre_excess=contribution,
            )
        )
    return FibreRisk(
        excess=total,
        normalisation=normalisation,
        normalised_excess=total / normalisation,
        union_violation_bound=min(1.0, violation_sum),
        contributions=tuple(contributions),
    )


def enumerate_expected_fibre_excess(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    moments: FibreMoments,
    positive_margin: float = 1.0,
) -> float:
    """Directly enumerate the independent product distribution for validation."""

    representation = build_mixed_representation(
        polynomial,
        n_original=n_original,
        actions=actions,
        default_margin=positive_margin,
    )
    active_pairs = tuple(representation.active_pairs)
    total = 0.0
    for original_bits in product((0, 1), repeat=n_original):
        probability_x = math.prod(
            moments.singles[index] if bit else 1.0 - moments.singles[index]
            for index, bit in enumerate(original_bits, start=1)
        )
        if probability_x == 0:
            continue
        original_value = float(evaluate_pubo(polynomial, original_bits))
        for auxiliary_bits in product((0, 1), repeat=len(active_pairs)):
            probability_y = math.prod(
                moments.pairs[pair] if bit else 1.0 - moments.pairs[pair]
                for pair, bit in zip(active_pairs, auxiliary_bits)
            )
            if probability_y == 0:
                continue
            augmented = tuple(original_bits) + tuple(auxiliary_bits)
            represented = float(evaluate_pubo(representation.polynomial, augmented))
            total += probability_x * probability_y * (represented - original_value)
    return total


def _candidate(
    canonical: Polynomial,
    cubics: Sequence[Support],
    *,
    n_original: int,
    actions: Sequence[Support | None],
    selector: Mapping[str, object],
    moments: FibreMoments,
    normalisation: float,
    tau: float,
    positive_margin: float,
    apply_qaoa_hard_limits: bool,
) -> FibreCandidate:
    resources = _fast_evaluate_design(
        canonical,
        cubics,
        n_original=n_original,
        actions=actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    risk = _fibre_risk_from_canonical(
        canonical,
        cubics,
        normalisation=normalisation,
        n_original=n_original,
        actions=actions,
        moments=moments,
        positive_margin=positive_margin,
    )
    tolerance = float(selector["fibre_risk"]["numeric_tolerance"])  # type: ignore[index]
    return FibreCandidate(
        actions=tuple(actions),
        resources=resources,
        risk=risk,
        feasible=resources.feasible and risk.normalised_excess <= tau + tolerance,
    )


def _dominates(left: FibreCandidate, right: FibreCandidate) -> bool:
    return all(a <= b for a, b in zip(left.pareto_vector, right.pareto_vector)) and any(
        a < b for a, b in zip(left.pareto_vector, right.pareto_vector)
    )


def _stable_actions_key(actions: Sequence[Support | None]) -> tuple[tuple[int, ...], ...]:
    return tuple((-1,) if action is None else tuple(action) for action in actions)


def _pareto_rank_and_crowding(
    candidates: Sequence[FibreCandidate],
) -> dict[tuple[Support | None, ...], tuple[int, float]]:
    """Return deterministic nondominated rank and five-coordinate crowding."""

    items = list(candidates)
    result: dict[tuple[Support | None, ...], tuple[int, float]] = {}
    dominates: list[list[int]] = [[] for _ in items]
    dominated_count = [0] * len(items)
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if _dominates(items[left], items[right]):
                dominates[left].append(right)
                dominated_count[right] += 1
            elif _dominates(items[right], items[left]):
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
        crowding = {item.actions: 0.0 for item in front}
        if len(front) <= 2:
            for item in front:
                crowding[item.actions] = math.inf
        else:
            for dimension in range(5):
                ordered = sorted(
                    front,
                    key=lambda item: (
                        item.pareto_vector[dimension],
                        _stable_actions_key(item.actions),
                    ),
                )
                crowding[ordered[0].actions] = math.inf
                crowding[ordered[-1].actions] = math.inf
                low = ordered[0].pareto_vector[dimension]
                high = ordered[-1].pareto_vector[dimension]
                if high == low:
                    continue
                for position in range(1, len(ordered) - 1):
                    key = ordered[position].actions
                    if math.isinf(crowding[key]):
                        continue
                    before = ordered[position - 1].pareto_vector[dimension]
                    after = ordered[position + 1].pareto_vector[dimension]
                    crowding[key] += (after - before) / (high - low)
        for item in front:
            result[item.actions] = (rank, crowding[item.actions])
    return result


def _pareto_order(candidates: Sequence[FibreCandidate]) -> list[FibreCandidate]:
    ranks = _pareto_rank_and_crowding(candidates)
    return sorted(
        candidates,
        key=lambda item: (
            not item.feasible,
            ranks[item.actions][0],
            -ranks[item.actions][1],
            _stable_actions_key(item.actions),
        ),
    )


def _candidate_vectors(cubics: Sequence[Support]) -> Iterable[tuple[Support | None, ...]]:
    return product(*(action_options(cubic) for cubic in cubics))


def enumerate_fibre_candidates(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    moments: FibreMoments,
    apply_qaoa_hard_limits: bool = True,
) -> tuple[FibreCandidate, ...]:
    """Return every oracle candidate with resource and fibre diagnostics."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    settings = selector["search_settings"]  # type: ignore[assignment]
    maximum = int(settings["certification"]["max_complete_candidate_evaluations"])  # type: ignore[index]
    design_count = 4 ** len(cubics)
    if design_count > maximum:
        raise FibreSelectorError(
            f"Oracle enumeration requires {design_count} candidates; limit is {maximum}"
        )
    fibre = selector["fibre_risk"]  # type: ignore[assignment]
    margin = float(fibre["positive_penalty_margin"])  # type: ignore[index]
    normalisation = fibre_normalisation(canonical, positive_margin=margin)
    return tuple(
        _candidate(
            canonical,
            cubics,
            n_original=n_original,
            actions=actions,
            selector=selector,
            moments=moments,
            normalisation=normalisation,
            tau=math.inf,
            positive_margin=margin,
            apply_qaoa_hard_limits=apply_qaoa_hard_limits,
        )
        for actions in _candidate_vectors(cubics)
    )


def certify_fibre_optimum(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    moments: FibreMoments,
    apply_qaoa_hard_limits: bool = True,
) -> FibreSearchResult:
    """Enumerate the complete oracle design space and certify the v2 optimum."""

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    candidates = enumerate_fibre_candidates(
        canonical,
        n_original=n_original,
        selector=selector,
        moments=moments,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    return certify_fibre_optimum_from_candidates(
        canonical,
        n_original=n_original,
        selector=selector,
        candidates=candidates,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
        runtime_sec=time.perf_counter() - started,
    )


def certify_fibre_optimum_from_candidates(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    candidates: Sequence[FibreCandidate],
    apply_qaoa_hard_limits: bool = True,
    runtime_sec: float = 0.0,
) -> FibreSearchResult:
    """Certify the optimum from a complete, already evaluated leaf set."""

    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    expected = 4 ** len(cubics)
    if len(candidates) != expected:
        raise FibreSelectorError(
            f"Certification received {len(candidates)} of {expected} complete candidates"
        )
    tau = float(selector["fibre_risk"]["threshold_tau"])  # type: ignore[index]
    feasible = [candidate for candidate in candidates if candidate.feasible]
    tolerance = float(selector["fibre_risk"]["numeric_tolerance"])  # type: ignore[index]
    feasible = [
        candidate
        for candidate in feasible
        if candidate.risk.normalised_excess <= tau + tolerance
    ]
    if not feasible:
        raise FibreSelectorError("No fibre-feasible oracle design")
    winner = min(
        feasible,
        key=lambda item: (
            item.score,
            item.risk.normalised_excess,
            _action_key(cubics, item.actions),
        ),
    )
    evaluation = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=winner.actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if evaluation.score != winner.score:
        raise FibreSelectorError("Certified fast score differs from reference evaluation")
    return FibreSearchResult(
        actions=winner.actions,
        evaluation=evaluation,
        risk=winner.risk,
        status="certified_complete_fibre_aware_optimum",
        candidate_evaluations=len(candidates),
        runtime_sec=float(runtime_sec),
        certified_optimum_score=winner.score,
        regret=Fraction(0),
    )


def beam_select_fibre_design(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    moments: FibreMoments,
    apply_qaoa_hard_limits: bool,
    certified: FibreSearchResult | None = None,
) -> FibreSearchResult:
    """Run the frozen deterministic fibre-aware Pareto beam."""

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    settings = selector["search_settings"]  # type: ignore[assignment]
    width = int(settings["beam_width"])  # type: ignore[index]
    allocation = settings["beam_allocation"]  # type: ignore[index]
    score_fraction = float(allocation["smallest_resource_score_fraction"])
    fibre = selector["fibre_risk"]  # type: ignore[assignment]
    tau = float(fibre["threshold_tau"])  # type: ignore[index]
    margin = float(fibre["positive_penalty_margin"])  # type: ignore[index]
    normalisation = fibre_normalisation(canonical, positive_margin=margin)
    cache: dict[tuple[Support | None, ...], FibreCandidate] = {}

    def evaluate(completed: tuple[Support | None, ...]) -> FibreCandidate:
        if completed not in cache:
            cache[completed] = _candidate(
                canonical,
                cubics,
                n_original=n_original,
                actions=completed,
                selector=selector,
                moments=moments,
                normalisation=normalisation,
                tau=tau,
                positive_margin=margin,
                apply_qaoa_hard_limits=apply_qaoa_hard_limits,
            )
        return cache[completed]

    beam: list[tuple[Support | None, ...]] = [()]
    for depth, cubic in enumerate(cubics):
        choices: dict[tuple[Support | None, ...], FibreCandidate] = {}
        for prefix in beam:
            for action in action_options(cubic):
                child = prefix + (action,)
                completed = child + (None,) * (len(cubics) - len(child))
                candidate = evaluate(completed)
                # A native-completed prefix is only a beam surrogate.  Its fibre
                # excess can decrease when a later cubic is assigned to an already
                # active pair, so the hard tau gate is applied only to finalists.
                # Resource feasibility is retained because it is the frozen v1
                # beam convention and all-native remains an explicit fallback.
                if candidate.resources.feasible:
                    choices[child] = candidate
        if not choices:
            raise FibreSelectorError(f"Fibre-aware beam empty at depth {depth + 1}")
        score_count = min(len(choices), max(1, int(round(width * score_fraction))))
        by_score = sorted(
            choices.items(),
            key=lambda item: (
                not item[1].feasible,
                item[1].score,
                item[1].risk.normalised_excess,
                _action_key(cubics[: len(item[0])], item[0]),
            ),
        )
        selected = [item[0] for item in by_score[:score_count]]
        selected_set = set(selected)
        remainder = [
            item[1] for item in choices.items() if item[0] not in selected_set
        ]
        pareto = _pareto_order(remainder)
        selected.extend(
            candidate.actions[: depth + 1]
            for candidate in pareto[: width - len(selected)]
        )
        beam = selected[:width]

    finalists = [evaluate(actions) for actions in beam]
    feasible = [candidate for candidate in finalists if candidate.feasible]
    if not feasible:
        fallback = evaluate((None,) * len(cubics))
        if not fallback.feasible:
            raise FibreSelectorError(
                "Fibre-aware beam and declared all-native fallback are infeasible"
            )
        feasible = [fallback]
    winner = min(
        feasible,
        key=lambda item: (
            item.score,
            item.risk.normalised_excess,
            _action_key(cubics, item.actions),
        ),
    )
    evaluation = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=winner.actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    optimum = certified.certified_optimum_score if certified is not None else None
    regret = evaluation.score - optimum if optimum is not None else None
    if regret is not None and regret < 0:
        raise FibreSelectorError("Beam objective is below certified optimum")
    return FibreSearchResult(
        actions=winner.actions,
        evaluation=evaluation,
        risk=winner.risk,
        status=(
            "fibre_aware_pareto_beam_qaoa_limits"
            if apply_qaoa_hard_limits
            else "fibre_aware_pareto_beam_compilation_scope"
        ),
        candidate_evaluations=len(cache),
        runtime_sec=time.perf_counter() - started,
        certified_optimum_score=optimum,
        regret=regret,
    )


def greedy_select_fibre_design(
    polynomial: Mapping[Support, object],
    *,
    n_original: int,
    selector: Mapping[str, object],
    moments: FibreMoments,
    apply_qaoa_hard_limits: bool,
    certified: FibreSearchResult | None = None,
) -> FibreSearchResult:
    """Run the frozen native-completion greedy fibre-aware heuristic."""

    started = time.perf_counter()
    canonical = canonicalize(polynomial)
    cubics = tuple(sorted(cubic_supports(canonical)))
    fibre = selector["fibre_risk"]  # type: ignore[assignment]
    tau = float(fibre["threshold_tau"])  # type: ignore[index]
    margin = float(fibre["positive_penalty_margin"])  # type: ignore[index]
    normalisation = fibre_normalisation(canonical, positive_margin=margin)
    actions: list[Support | None] = [None] * len(cubics)
    cache: dict[tuple[Support | None, ...], FibreCandidate] = {}

    def evaluate(candidate_actions: tuple[Support | None, ...]) -> FibreCandidate:
        if candidate_actions not in cache:
            cache[candidate_actions] = _candidate(
                canonical,
                cubics,
                n_original=n_original,
                actions=candidate_actions,
                selector=selector,
                moments=moments,
                normalisation=normalisation,
                tau=tau,
                positive_margin=margin,
                apply_qaoa_hard_limits=apply_qaoa_hard_limits,
            )
        return cache[candidate_actions]

    for index, cubic in enumerate(cubics):
        choices: list[FibreCandidate] = []
        for action in action_options(cubic):
            candidate_actions = tuple(
                actions[:index] + [action] + actions[index + 1 :]
            )
            candidate = evaluate(candidate_actions)
            if candidate.feasible:
                choices.append(candidate)
        if not choices:
            raise FibreSelectorError(
                f"Fibre-aware greedy has no feasible action at depth {index + 1}"
            )
        chosen = min(
            choices,
            key=lambda item: (
                item.score,
                item.risk.normalised_excess,
                _action_key(cubics, item.actions),
            ),
        )
        actions[index] = chosen.actions[index]

    winner = evaluate(tuple(actions))
    evaluation = _evaluate_design(
        canonical,
        n_original=n_original,
        actions=winner.actions,
        selector=selector,
        apply_qaoa_hard_limits=apply_qaoa_hard_limits,
    )
    if evaluation.score != winner.score:
        raise FibreSelectorError("Greedy fast score differs from reference evaluation")
    optimum = certified.certified_optimum_score if certified is not None else None
    regret = evaluation.score - optimum if optimum is not None else None
    if regret is not None and regret < 0:
        raise FibreSelectorError("Greedy objective is below certified optimum")
    return FibreSearchResult(
        actions=winner.actions,
        evaluation=evaluation,
        risk=winner.risk,
        status="fibre_aware_greedy_native_completion",
        candidate_evaluations=len(cache),
        runtime_sec=time.perf_counter() - started,
        certified_optimum_score=optimum,
        regret=regret,
    )


def actions_payload(actions: Sequence[Support | None]) -> list[list[int] | None]:
    return [list(action) if action is not None else None for action in actions]


def design_id(actions: Sequence[Support | None]) -> str:
    encoded = repr(actions_payload(actions)).encode("ascii")
    return "fibre_design_" + hashlib.sha256(encoded).hexdigest()[:20]


def matched_random_fibre_designs(
    polynomial: Mapping[Support, object],
    *,
    selected_actions: Sequence[Support | None],
    instance_id: str,
    seed_bundle: Sequence[int],
    maximum_pair_set_attempts: int,
) -> list[tuple[int, tuple[Support | None, ...]]]:
    """Construct bounded-time random designs matched on auxiliary count.

    Candidate pair sets are SHA256-seeded.  Feasibility is decided with a
    polynomial augmenting-path bipartite matching between active pairs and
    cubic terms, avoiding the exponential recursive backtracking used by v1.
    """

    cubics = tuple(sorted(cubic_supports(canonicalize(polynomial))))
    selected = tuple(selected_actions)
    target = len({action for action in selected if action is not None})
    if target == 0:
        return [(int(seed), (None,) * len(cubics)) for seed in seed_bundle]
    pairs = tuple(sorted(pair_shadow(set(cubics))))
    maximum = int(maximum_pair_set_attempts)
    if maximum <= 0:
        raise FibreSelectorError("Matched-random pair-set attempts must be positive")
    if target > len(pairs) or target > len(cubics):
        raise FibreSelectorError("Matched-random auxiliary target is impossible")

    def matching(
        chosen: Sequence[Support], rng: random.Random
    ) -> dict[Support, int] | None:
        adjacency = {
            pair: [
                index
                for index, cubic in enumerate(cubics)
                if set(pair).issubset(cubic)
            ]
            for pair in chosen
        }
        for candidates in adjacency.values():
            rng.shuffle(candidates)
        order = list(chosen)
        rng.shuffle(order)
        cubic_owner: dict[int, Support] = {}

        def augment(pair: Support, seen: set[int]) -> bool:
            for index in adjacency[pair]:
                if index in seen:
                    continue
                seen.add(index)
                owner = cubic_owner.get(index)
                if owner is None or augment(owner, seen):
                    cubic_owner[index] = pair
                    return True
            return False

        for pair in order:
            if not augment(pair, set()):
                return None
        return {pair: index for index, pair in cubic_owner.items()}

    def materialise(
        chosen: Sequence[Support],
        anchors: Mapping[Support, int],
        rng: random.Random,
    ) -> tuple[Support | None, ...]:
        actions: list[Support | None] = [None] * len(cubics)
        for pair, index in anchors.items():
            actions[index] = pair
        for index, cubic in enumerate(cubics):
            if actions[index] is not None:
                continue
            options: list[Support | None] = [None]
            options.extend(pair for pair in chosen if set(pair).issubset(cubic))
            actions[index] = rng.choice(options)
        return tuple(actions)

    selected_pairs = tuple(
        sorted({action for action in selected if action is not None})
    )
    outputs: list[tuple[int, tuple[Support | None, ...]]] = []
    for base_seed in seed_bundle:
        digest = hashlib.sha256(f"{instance_id}:{base_seed}".encode("ascii")).digest()
        rng = random.Random(int.from_bytes(digest[:8], "big"))
        result: tuple[Support | None, ...] | None = None
        for _ in range(maximum):
            chosen = tuple(rng.sample(list(pairs), target))
            anchors = matching(chosen, rng)
            if anchors is None:
                continue
            candidate = materialise(chosen, anchors, rng)
            if candidate != selected:
                result = candidate
                break
        if result is None:
            for _ in range(maximum):
                anchors = matching(selected_pairs, rng)
                if anchors is None:
                    break
                candidate = materialise(selected_pairs, anchors, rng)
                if candidate != selected:
                    result = candidate
                    break
        outputs.append((int(base_seed), result if result is not None else selected))
    return outputs
