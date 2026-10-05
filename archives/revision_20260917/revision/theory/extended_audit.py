"""Executed correctness and scaling diagnostics, deliberately not a large benchmark.

Higher-degree tests use an independent exact sequential substitution routine.
Search diagnostics exercise the project's existing interruptible certifier.
No files outside revision/theory are changed.
"""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction as F
from itertools import combinations, product
from pathlib import Path
import csv
import hashlib
import json
import math
import random
import statistics
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "code" / "source"
sys.path.insert(0, str(HERE.parent / "python_deps"))
sys.path.insert(0, str(SOURCE))
from verify_theory import star_forest, polynomial, compile_reference as independent_compile
from urss_pipeline.reference_compiler import compile_reference
from urss_pipeline.e1_exactness import action_options
from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.fibre_selector import FibreMoments
from urss_pipeline.review_search import branch_and_bound_fibre_optimum


def masked(poly):
    return [(sum(1 << i for i in term), coefficient) for term, coefficient in poly.items()]


def value(poly_masked, assignment):
    return sum(c for mask, c in poly_masked if assignment & mask == mask)


def one_substitution(poly, pair, n, margin):
    selected = {term: c for term, c in poly.items() if len(term) > 2 and set(pair) <= set(term)}
    residual = {tuple(i for i in term if i not in pair): c for term, c in selected.items()}
    rmask = masked(residual)
    sharp = max(abs(value(rmask, x)) for x in range(1 << n))
    sufficient = sum(abs(c) for c in residual.values())
    result = defaultdict(F)
    for term, c in poly.items():
        result[tuple(sorted((*[i for i in term if i not in pair], n))) if term in selected else term] += c
    M = sharp + margin
    a, b = pair
    for term, c in ((pair, M), ((a, n), -2 * M), ((b, n), -2 * M), ((n,), 3 * M)):
        result[term] += c
    return {term: c for term, c in result.items() if c}, sharp, sufficient


def higher_degree_audit():
    rows = []
    total_steps = total_step_assignments = total_final_assignments = 0
    for degree in (4, 5):
        n_original = degree + 2
        possible = [(0, 1, *tail) for tail in combinations(range(2, n_original), degree - 2)]
        for seed in range(12):
            rng = random.Random(20260917 + degree * 100 + seed)
            selected = rng.sample(possible, min(4, len(possible)))
            original = {term: F(rng.choice((-3, -2, -1, 1, 2, 3))) for term in selected}
            # Nonzero affine terms make the objective more than a nonnegative sum.
            original[(0,)] = F(-1)
            original[(n_original - 1,)] = F(1, 2)
            current, n = original, n_original
            step_records = []
            while max(map(len, current), default=0) > 2:
                counts = defaultdict(int)
                for term in current:
                    if len(term) > 2:
                        for pair in combinations(term, 2):
                            counts[pair] += 1
                pair = min(counts, key=lambda p: (-counts[p], p))
                strict, sharp, sufficient = one_substitution(current, pair, n, F(1, 4))
                threshold, _, _ = one_substitution(current, pair, n, F(0))
                below, _, _ = one_substitution(current, pair, n, -F(1, 4))
                cmask, smask, tmask, bmask = map(masked, (current, strict, threshold, below))
                below_failed = threshold_tied = False
                for x in range(1 << n):
                    truth = value(cmask, x)
                    svalues = [value(smask, x | y << n) for y in (0, 1)]
                    tvalues = [value(tmask, x | y << n) for y in (0, 1)]
                    bvalues = [value(bmask, x | y << n) for y in (0, 1)]
                    assert min(svalues) == truth and svalues.count(truth) == 1
                    assert min(tvalues) == truth
                    assert svalues[((x >> pair[0]) & 1) * ((x >> pair[1]) & 1)] == truth
                    threshold_tied |= tvalues.count(truth) == 2
                    below_failed |= min(bvalues) < truth
                assert threshold_tied and below_failed
                step_records.append({"pair": pair, "current_variables": n, "sharp": str(sharp),
                                     "l1_sufficient": str(sufficient), "assignments": 1 << n})
                total_steps += 1
                total_step_assignments += 1 << n
                current, n = strict, n + 1
            final_mask = masked(current)
            original_mask = masked(original)
            for x in range(1 << n_original):
                vals = [value(final_mask, x | y << n_original) for y in range(1 << (n - n_original))]
                truth = value(original_mask, x)
                assert min(vals) == truth and vals.count(truth) == 1
            total_final_assignments += 1 << n
            rows.append({"degree": degree, "seed": seed, "original_variables": n_original,
                         "final_variables": n, "sequential_steps": len(step_records), "steps": step_records})
    # Explicit cancellation gap: A=u v-u w (or u v w-u v z).
    examples = []
    for degree in (4, 5):
        left = tuple(range(degree))
        right = (*range(degree - 1), degree)
        source = {left: F(1), right: F(-1)}
        _, sharp, sufficient = one_substitution(source, (0, 1), degree + 1, F(1, 4))
        assert sharp == 1 and sufficient == 2
        examples.append({"degree": degree, "sharp": 1, "l1_sufficient": 2})
    return {"instances": len(rows), "steps": total_steps, "step_assignments": total_step_assignments,
            "final_lift_assignments": total_final_assignments, "examples": examples, "rows": rows}


def compiler_crosscheck():
    checked = 0
    for L in range(2, 33):
        for H in range(1, 9):
            terms, n = star_forest([L] + [1] * H)
            assignments = [[None] * (L + H), [(0, 1)] * L + [None] * H,
                           [(0, 1)] * L + [tuple(term[:2]) for term in terms[L:]]]
            for assignment in assignments:
                poly, width = polynomial(terms, n, assignment)
                translated = {tuple(q + 1 for q in support): c for support, c in poly.items()}
                observed = compile_reference(translated, n_qubits=width)
                assert independent_compile(poly, width) == (observed.two_qubit_gate_count, observed.two_qubit_depth)
                checked += 1
    return checked


def selector_settings(n):
    return {
        "weights": {"auxiliary_count": .05, "two_qubit_gate_count": .45,
                    "two_qubit_depth": .45, "maximum_penalty": .05},
        "scales": {"auxiliary_count": 6, "two_qubit_gate_count": 128,
                   "two_qubit_depth": 96, "maximum_penalty": 64},
        "fibre_risk": {"positive_penalty_margin": 1, "threshold_tau": 1,
                       "numeric_tolerance": 1e-9},
        "feasibility_limits": {"maximum_qubits": n + 20,
            "maximum_two_qubit_gates_per_cost_layer": 512,
            "maximum_two_qubit_depth_per_cost_layer": 512, "maximum_penalty": 128},
        "search_settings": {"beam_width": 16},
    }


def make_search_case(m, seed):
    rng = random.Random(2026091700 + m * 10 + seed)
    n = 8
    terms = sorted(rng.sample(list(combinations(range(1, n + 1), 3)), m))
    poly = {term: rng.choice((-3, -2, -1, 1, 2, 3)) for term in terms}
    # Synthetic exact moments of the all-zero assignment: diagnostic is identically
    # zero and is not asserted to be an LP optimum. This isolates search scaling.
    moments = FibreMoments(0.0, {i: 0.0 for i in range(1, n + 1)},
        {pair: 0.0 for pair in combinations(range(1, n + 1), 2)},
        "synthetic_zero_assignment", "No relaxation solved; diagnostic vacuous", 0.0, 0.0,
        hashlib.sha256(b"synthetic_zero_assignment").hexdigest())
    return poly, n, selector_settings(n), moments


def exact_score(poly, n, selector):
    best = None
    for actions in product(*(action_options(term) for term in sorted(poly))):
        item = _evaluate_design(poly, n_original=n, actions=actions,
                                selector=selector, apply_qaoa_hard_limits=True)
        if item.feasible and (best is None or item.score < best):
            best = item.score
    return best


def search_audit():
    rows = []
    interruption_checks = []
    for m in (3, 5, 7, 9, 11):
        for seed in range(3):
            poly, n, selector, moments = make_search_case(m, seed)
            cert = branch_and_bound_fibre_optimum(poly, n_original=n, selector=selector,
                moments=moments, max_nodes=10000, max_evaluations=2000, time_limit_sec=2.0,
                trace_interval_nodes=256, apply_qaoa_hard_limits=True)
            if m <= 5:
                true_optimum = exact_score(poly, n, selector)
                assert cert.final_lower_bound <= true_optimum <= cert.final_upper_bound
                if cert.proof_complete:
                    assert cert.final_upper_bound == true_optimum
            else:
                true_optimum = None
            row = {"terms": m, "seed": seed, "design_space": 4 ** m,
                "evaluated_candidates": cert.result.candidate_evaluations if cert.result else 0,
                "explored_nodes": cert.explored_nodes, "evaluated_leaves": cert.evaluated_leaves,
                "runtime_sec": cert.runtime_sec, "proof_complete": cert.proof_complete,
                "termination": cert.termination_reason, "lower": float(cert.final_lower_bound),
                "upper": float(cert.final_upper_bound),
                "gap": float(cert.final_upper_bound - cert.final_lower_bound),
                "frontier_nodes": len(cert.frontier), "pruned_by_bound": cert.pruned_by_bound,
                "exhaustive_optimum": float(true_optimum) if true_optimum is not None else None,
                "trace": cert.trace}
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "trace"}), flush=True)
    poly, n, selector, moments = make_search_case(3, 0)
    exact = exact_score(poly, n, selector)
    for limit in (0, 1, 10, 40):
        cert = branch_and_bound_fibre_optimum(poly, n_original=n, selector=selector, moments=moments,
                max_nodes=limit, apply_qaoa_hard_limits=True)
        assert cert.final_lower_bound <= exact <= cert.final_upper_bound
        interruption_checks.append({"max_nodes": limit, "lower": float(cert.final_lower_bound),
            "upper": float(cert.final_upper_bound) if math.isfinite(cert.final_upper_bound) else None,
            "upper_is_infinite": not math.isfinite(cert.final_upper_bound),
            "termination": cert.termination_reason, "frontier_nodes": len(cert.frontier)})
    return {"rows": rows, "interruption_checks": interruption_checks, "timeout_runs": timeout_audit(),
            "scope": "Synthetic search diagnostics only; eight original bits; mixed integer coefficients; vacuous fibre diagnostic; reference compiler; no QAOA",
            "limits": {"max_nodes": 10000, "max_evaluations": 2000, "wall_seconds": 2.0}}


def timeout_audit():
    poly, n, selector, moments = make_search_case(11, 0)
    rows = []
    for seconds in (.1, .5, 2.0):
        cert = branch_and_bound_fibre_optimum(poly, n_original=n, selector=selector,
            moments=moments, time_limit_sec=seconds, trace_interval_nodes=256,
            apply_qaoa_hard_limits=True)
        assert cert.termination_reason == 'time_limit' and not cert.proof_complete
        row = {"time_limit_sec": seconds, "runtime_sec": cert.runtime_sec,
               "evaluated_candidates": cert.result.candidate_evaluations,
               "explored_nodes": cert.explored_nodes, "frontier_nodes": len(cert.frontier),
               "lower": float(cert.final_lower_bound), "upper": float(cert.final_upper_bound),
               "gap": float(cert.final_upper_bound - cert.final_lower_bound),
               "termination": cert.termination_reason, "trace": cert.trace}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != 'trace'}), flush=True)
    return rows


def write_summary(higher, crosscheck, search):
    lines = [r"\subsection{Higher-degree checks and limits of certification}",
        r"\label{app:higher-degree-scaling-audit}",
        "An additional correctness audit used 24 degree-four/five polynomials (12 of each),",
        "each with four overlapping high-order monomials and affine terms.",
        f"Across {higher['steps']} sequential shared substitutions, exhaustive checks covered",
        f"{higher['step_assignments']:,} assignments of the current variables. At each step,",
        r"$M=\|A\|_\infty$ preserved values, $M=\|A\|_\infty+1/4$ gave a unique",
        r"consistent lift, and $M=\|A\|_\infty-1/4$ produced a counterexample.",
        f"The final composed representations were checked over {higher['final_lift_assignments']:,}",
        "original-plus-auxiliary assignments; all pointwise and unique-lift checks passed.",
        "These are small truth-table checks, not an efficient arbitrary-degree implementation.",
        "The existing implementation and an independent rational-polynomial compiler also",
        f"agreed in all {crosscheck} representation compilations from 248 pair-star-family instances.",
        "",
        r"The sharp threshold can itself require exponential Boolean optimisation.",
        r"For an aggregate residual $A(v)=\sum_B a_Bv_B$, the readily computed bound",
        r"$M\geq\sum_B|a_B|$ is sufficient but need not be sharp. For instance,",
        r"$A=u v-u w$ has $\|A\|_\infty=1$ although its coefficient absolute sum is $2$;",
        r"$A=u v w-u v z$ gives the same gap in a degree-five substitution.",
        r"Sharpness here is restricted to the specified Rosenberg construction.",
        "",
        "We additionally exercised the existing interruptible branch-and-bound code on",
        "three synthetic eight-variable instances at each support size below, using the",
        "declared reference compiler, resource weights $(0.05,0.45,0.45,0.05)$ and",
        "scales $(6,128,96,64)$ in auxiliary/gate/depth/penalty order, penalties with margin one, and",
        r"budgets $(Q_{\max},G_{\max},D_{\max},M_{\max})=(28,512,512,128)$.",
        "Nonzero cubic coefficients were sampled from the integers of magnitude one to three.",
        "The fibre diagnostic was made",
        "vacuous using the moments of the all-zero assignment; no relaxation quality or",
        "guardrail benefit is claimed. Each run had limits of 10,000 nodes, 2,000 candidate",
        "evaluations and 2 seconds, checked between atomic search operations.",
        r"\begin{center}\begin{tabular}{rrrrrl}", r"\toprule",
        r"$m$ & $4^m$ & Complete & Median time (s) & Median gap & Termination\\",r"\midrule"]
    for m in (3, 5, 7, 9, 11):
        rows = [r for r in search['rows'] if r['terms'] == m]
        reasons = "/".join(sorted({r['termination'].replace('_', r'\_') for r in rows}))
        lines.append(f"{m} & {4**m:,} & {sum(r['proof_complete'] for r in rows)}/3 & "
                     f"{statistics.median(r['runtime_sec'] for r in rows):.3f} & "
                     f"{statistics.median(r['gap'] for r in rows):.4f} & {reasons}\\\\")
    lines += [r"\bottomrule\end{tabular}\end{center}",
        "Separate wall-time-only runs on the first eleven-term instance stopped at",
        "0.1, 0.5 and 2 seconds with remaining score gaps of " +
        ", ".join(f"{r['gap']:.4f}" for r in search['timeout_runs']) + ", respectively.",
        "For all six cases with three or five cubic terms, a separate exhaustive enumeration",
        "verified that the reported interval contained the optimum. Four explicit node-limit",
        "interruptions on a three-term case also retained a valid interval, including the",
        "zero-node case with no incumbent and infinite upper bound. Detailed node, evaluation,",
        "frontier and bound traces accompany the reproducibility bundle. Positive remaining",
        "gaps at interruption are not certificates of near-optimality. These results demonstrate",
        "correct bound accounting and rapid growth of the search burden, not scalability.",
        "The bound sets gate and depth contributions to zero, which leaves loose intervals",
        "even when the incumbent improves; stronger bounds would be needed for larger proofs.",
        "Certificates remain relative to the declared representation grammar, score, compiler",
        "and implemented numerical feasibility rule; time limits may be exceeded by the duration",
        "of one atomic operation."]
    (HERE / "higher_degree_scaling_section.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == '__main__':
    if '--timeouts-only' in sys.argv:
        saved = json.loads((HERE / "extended_audit_results.json").read_text(encoding='utf-8'))
        higher, crosscheck, search = saved['higher_degree'], saved['existing_compiler_crosschecks'], saved['search']
        search['timeout_runs'] = timeout_audit()
    else:
        higher = higher_degree_audit()
        crosscheck = compiler_crosscheck()
        print(json.dumps({"higher_degree_instances": higher["instances"], "steps": higher["steps"],
            "step_assignments": higher["step_assignments"], "final_lift_assignments": higher["final_lift_assignments"],
            "existing_compiler_crosschecks": crosscheck}), flush=True)
        search = search_audit()
    results = {"higher_degree": higher, "existing_compiler_crosschecks": crosscheck, "search": search}
    (HERE / "extended_audit_results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    with (HERE / "search_scaling.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [key for key in search['rows'][0] if key != 'trace']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in search['rows'])
    write_summary(higher, crosscheck, search)
