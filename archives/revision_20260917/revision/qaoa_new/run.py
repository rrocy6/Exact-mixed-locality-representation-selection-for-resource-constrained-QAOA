"""Locally frozen fresh QAOA experiment. Commands: test, freeze, run, verify.

Requires numpy, scipy, pyyaml. Existing model helpers are reused and hashed;
the selector, simulation, objective accounting and validation are explicit here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "code" / "source"
sys.path.insert(0, str(SOURCE))
import numpy as np
from scipy.optimize import minimize
from urss_pipeline.generators import generate_max3sat, generate_spin_glass, derive_seed
from urss_pipeline.polynomial import max3sat_to_pubo, spin_glass_to_pubo, evaluate_pubo
from urss_pipeline.polynomial import evaluate_max3sat_direct, evaluate_spin_glass_direct
from urss_pipeline.e1_exactness import build_mixed_representation
from urss_pipeline.e2_resources import _fast_evaluate_design
from urss_pipeline.e4_warmstart import solve_sa_rlt_level2, product_state, _apply_matched_mixer

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def sources():
    return [HERE / "protocol.json", HERE / "run.py", *sorted((SOURCE / "urss_pipeline").glob("*.py"))]

def freeze():
    if (HERE / "freeze.json").exists():
        verify_freeze()
        return
    if (HERE / "results").exists() or (HERE / "instances").exists():
        raise RuntimeError("Cannot freeze after evaluation generation")
    write(HERE / "freeze.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "hashes": {str(p.relative_to(HERE.parent)): sha(p) for p in sources()},
        "versions": {p: importlib.metadata.version(p) for p in ["numpy", "scipy", "PyYAML"]},
        "local_freeze_only": True,
    })

def verify_freeze():
    for name, digest in read(HERE / "freeze.json")["hashes"].items():
        if sha(HERE.parent / name) != digest:
            raise RuntimeError("Frozen implementation changed: " + name)

def truth_values(poly, width):
    indices = np.arange(1 << width, dtype=np.uint64)
    values = np.zeros(len(indices))
    for support, coefficient in poly.items():
        mask = np.ones(len(indices), dtype=bool)
        for variable in support:
            mask &= ((indices >> (variable - 1)) & 1).astype(bool)
        values += float(coefficient) * mask
    return values

def select(poly, n, cfg, seed):
    """128 resource evaluations per domain; endpoint data never score QAOA."""
    cubics = tuple(sorted(k for k in poly if len(k) == 3))
    m = len(cubics)
    opts = [tuple(itertools.combinations(c, 2)) for c in cubics]
    selector = {
        "weights": {k: .25 for k in ["auxiliary_count", "two_qubit_gate_count", "two_qubit_depth", "maximum_penalty"]},
        "scales": dict(auxiliary_count=4, two_qubit_gate_count=160, two_qubit_depth=120, maximum_penalty=8),
        "feasibility_limits": {}, "fibre_risk": {"positive_penalty_margin": cfg["penalty_margin"]},
    }
    def evaluate(codes):
        actions = tuple(None if v == -1 else opts[i][v] for i, v in enumerate(codes))
        e = _fast_evaluate_design(poly, cubics, n_original=n, actions=actions, selector=selector, apply_qaoa_hard_limits=False)
        return e
    result, metadata = {}, {}
    # Finite domains are generated then seeded-permuted: deterministic, equal
    # candidate-call budget, no QAOA response enters representation choice.
    for name in cfg["representation_domains"]:
        if name == "native":
            candidates = [(-1,) * m]
        else:
            choices = range(3) if name == "full" else range(-1, 3)
            domain = [a for a in itertools.product(choices, repeat=m)
                      if name == "full" or 0 < sum(x != -1 for x in a) < m]
            rng = np.random.default_rng(derive_seed(seed, "selection", name))
            budget = min(len(domain), cfg["candidate_evaluations_per_domain"])
            candidates = [domain[i] for i in rng.choice(len(domain), budget, replace=False)]
        evaluated = [evaluate(a) for a in candidates]
        best = min(zip(candidates, evaluated), key=lambda a: (a[1].score, a[0]))[1]
        result[name] = build_mixed_representation(poly, n_original=n, actions=best.actions, default_margin=cfg["penalty_margin"])
        metadata[name] = dict(actions=[list(a) if a is not None else None for a in best.actions],
            calls=len(evaluated), domain_size=1 if name == "native" else len(domain),
            score=float(best.score), auxiliary_count=best.n_auxiliary, width=best.n_qubits,
            gates=best.two_qubit_gate_count, depth=best.two_qubit_depth, penalty=float(best.maximum_penalty))
    metadata["unrestricted_among_evaluated"] = min(result, key=lambda a: metadata[a]["score"])
    return result, metadata

class Simulation:
    def __init__(self, poly, representation, probabilities):
        self.n = representation.n_qubits
        self.probabilities = np.array(probabilities)
        self.initial = product_state(probabilities)
        self.energy = truth_values(representation.polynomial, self.n)
        original = truth_values(poly, representation.original_width)
        self.original = np.tile(original, 1 << representation.n_auxiliary)
        self.inconsistent = np.zeros(1 << self.n, dtype=bool)
        index = np.arange(1 << self.n)
        for pair, variable in representation.auxiliary_indices.items():
            expect = ((index >> (pair[0]-1)) & 1) * ((index >> (pair[1]-1)) & 1)
            self.inconsistent |= expect != ((index >> (variable-1)) & 1)
        self.p0 = float(np.abs(self.initial)**2 @ self.original)
        self.optimum = float(original.min())
        self.span = float(original.max() - original.min())

    def state(self, x):
        state = self.initial * np.exp(-1j * (float(x[0]) % (2*math.pi)) * self.energy)
        _apply_matched_mixer(state, float(x[1]) % math.pi, self.probabilities)
        return state

    def objective(self, x):
        state = self.state(x)
        return float(np.abs(state)**2 @ self.original)

    def metrics(self, x):
        state = self.state(x)
        probabilities = np.abs(state)**2
        norm = float(probabilities.sum())
        if abs(norm - 1) > 1e-10:
            raise AssertionError("State normalisation error")
        return dict(original_mean=float(probabilities @ self.original),
            encoded_mean=float(probabilities @ self.energy),
            auxiliary_inconsistency=float(probabilities @ self.inconsistent),
            optimum_probability=float(probabilities @ np.isclose(self.original, self.optimum)), norm=norm)

    def scan(self, gamma_count, beta_count):
        """Simulate each of gamma_count*beta_count circuits, batching gammas."""
        gammas = np.arange(gamma_count) * 2*math.pi / gamma_count
        betas = np.arange(beta_count) * math.pi / beta_count
        phased = np.exp(-1j * np.outer(gammas, self.energy)) * self.initial[None, :]
        grid = np.empty((gamma_count, beta_count))
        for j, beta in enumerate(betas):
            state = phased.copy()
            c, s = math.cos(beta), math.sin(beta)
            for qubit, p in enumerate(self.probabilities):
                stride = 1 << qubit
                view = state.reshape((gamma_count, -1, stride*2))
                lo, hi = view[..., :stride].copy(), view[..., stride:].copy()
                x, z = 2*math.sqrt(p*(1-p)), 1-2*p
                view[..., :stride] = (c-1j*s*z)*lo - 1j*s*x*hi
                view[..., stride:] = -1j*s*x*lo + (c+1j*s*z)*hi
            grid[:, j] = np.sum(np.abs(state)**2 * self.original[None, :], axis=1)
        return gammas, betas, grid

def optimise(sim, starts, method, budget, seed):
    trace, best_value, best_x = [], math.inf, None
    rng = np.random.default_rng(seed)
    for restart, start in enumerate(starts):
        calls = 0
        def objective(x):
            nonlocal calls, best_value, best_x
            value = sim.objective(x)
            calls += 1
            if value < best_value:
                best_value, best_x = value, list(map(float, x))
            trace.append(dict(call=len(trace)+1, restart=restart, objective=value, incumbent=best_value))
            return value
        options = dict(maxiter=budget, tol=1e-12, rhobeg=.5) if method == "COBYLA" else dict(maxfev=budget, xatol=0., fatol=0.)
        minimum = minimize(objective, start, method=method, options=options)
        completion_calls = 0
        while calls < budget:
            objective(rng.uniform([0, 0], [2*math.pi, math.pi]))
            completion_calls += 1
        if calls != budget:
            raise AssertionError(("Unequal budget", method, calls, budget))
        trace[-1]["uniform_completion_calls"] = completion_calls
        trace[-1]["optimizer_message"] = str(minimum.message)
    return dict(parameters=best_x, objective=best_value, calls=len(trace), trace=trace, **sim.metrics(best_x))

def scanned_refinement(sim, cfg):
    gammas, betas, grid = sim.scan(cfg["scan_gamma_points"], cfg["scan_beta_points"])
    order = np.argsort(grid.ravel())[:cfg["scan_refinement_starts"]]
    starts = [[gammas[i], betas[j]] for i,j in (np.unravel_index(k, grid.shape) for k in order)]
    result = optimise(sim, starts, "Nelder-Mead", cfg["scan_refinement_max_evaluations"], 91873)
    result["grid_minimum"] = float(grid.min())
    result["grid_calls"] = int(grid.size)
    result["grid_shape"] = list(grid.shape)
    return result, grid

def generate(family, number, cfg):
    rejected = []
    for attempt in range(1000):
        seed = derive_seed(cfg["master_seed"], "fresh_confirmation", family, number, attempt)
        kwargs = dict(n=cfg["n_original"], generator_mode=cfg["generator_mode"], master_seed=cfg["master_seed"], instance_seed=seed, generator_version="fresh_confirmation_20260917_v1")
        if family == "max3sat":
            instance = generate_max3sat(clause_density=cfg["density"], **kwargs)
            poly = max3sat_to_pubo(instance)
        else:
            instance = generate_spin_glass(hyperedges_per_variable=cfg["density"], **kwargs)
            poly = spin_glass_to_pubo(instance)
        if sum(len(k)==3 for k in poly) >= 2:
            return instance, poly, seed, rejected
        rejected.append(dict(attempt=attempt, seed=seed, reason="fewer than two nonzero cubic supports"))
    raise RuntimeError("generation exhausted")

def task(family, number):
    verify_freeze()
    cfg = read(HERE / "protocol.json")
    path = HERE / "results" / f"{family}_{number:02d}.json"
    if path.exists():
        return str(path)
    start_time = time.perf_counter()
    instance, poly, seed, rejected = generate(family, number, cfg)
    n = cfg["n_original"]
    write(HERE / "instances" / f"{family}_{number:02d}.json", instance)
    original = truth_values(poly, n)
    direct = evaluate_max3sat_direct if family == "max3sat" else evaluate_spin_glass_direct
    for index in range(1 << n):
        bits = [(index >> i)&1 for i in range(n)]
        assert original[index] == direct(instance, bits)
    representations, selections = select(poly, n, cfg, seed)
    moments = solve_sa_rlt_level2(poly, n_original=n)
    clip = lambda a: np.clip(a, cfg["clipping_delta"], 1-cfg["clipping_delta"])
    originals = np.array([clip(moments.singles[i]) for i in range(1,n+1)])
    rng = np.random.default_rng(derive_seed(seed, "common_parameter_starts"))
    starts = rng.uniform([0,0], [2*math.pi, math.pi], size=(cfg["restarts"],2))
    rounded = [int(moments.singles[i] > .5) for i in range(1,n+1)]
    sampling = np.random.default_rng(derive_seed(seed, "independent_sampling")).random((cfg["independent_samples"],n)) < originals
    sample_values = original[sampling.astype(int) @ (2**np.arange(n))]
    rows = []
    for name, representation in representations.items():
        encoded = truth_values(representation.polynomial, representation.n_qubits)
        min_over_aux = encoded.reshape((-1, 1 << n)).min(axis=0)
        assert np.array_equal(min_over_aux, original), "Pointwise exactness failed"
        pair_order = sorted(representation.auxiliary_indices, key=representation.auxiliary_indices.get)
        policies = {"cold": np.full(representation.n_qubits, .5),
            "pair": np.r_[originals, [clip(moments.pairs[p]) for p in pair_order]]}
        if pair_order:
            policies["independence"] = np.r_[originals, [clip(originals[i-1]*originals[j-1]) for i,j in pair_order]]
        for policy, probabilities in policies.items():
            sim = Simulation(poly, representation, probabilities)
            run = optimise(sim, starts, "COBYLA", cfg["evaluations_per_restart"], derive_seed(seed,"completion"))
            row = dict(representation=name, warming=policy, probabilities=probabilities.tolist(),
                p0=sim.p0, equal_effort=run, span=sim.span)
            if policy == "pair":
                row["second_optimizer"] = optimise(sim, starts, "Nelder-Mead", cfg["evaluations_per_restart"], derive_seed(seed,"second_completion"))
                row["scan_refined"], grid = scanned_refinement(sim, cfg)
                gridpath = HERE / "grids" / f"{family}_{number:02d}_{name}.npz"
                gridpath.parent.mkdir(exist_ok=True)
                np.savez_compressed(gridpath, objective=grid)
                row["grid_file"] = str(gridpath.relative_to(HERE))
            rows.append(row)
    output = dict(family=family, number=number, instance_id=instance["instance_id"], seed=seed,
        rejected_generation_attempts=rejected, freeze_sha256=sha(HERE/"freeze.json"),
        optimum=float(original.min()), maximum=float(original.max()), cold_p0=float(original.mean()),
        classical_rounding=float(evaluate_pubo(poly, rounded)),
        independent_sampling_mean=float(sample_values.mean()),
        independent_sampling_mc_standard_error=float(sample_values.std(ddof=1)/math.sqrt(len(sample_values))),
        independent_sampling_expected_mean=float(np.abs(product_state(originals))**2 @ original),
        moments=dict(singles={str(k):v for k,v in moments.singles.items()}, pairs={str(k):v for k,v in moments.pairs.items()},
                     objective=moments.objective, status=moments.status),
        selections=selections, rows=rows, elapsed_seconds=time.perf_counter()-start_time)
    write(path, output)
    return f"{family} {number} completed in {output['elapsed_seconds']:.1f}s"

def tests():
    poly = {(): 2, (1,): -1, (1,2,3): 2, (1,2,4): -3}
    r = build_mixed_representation(poly, n_original=4, actions=((1,2),None))
    sim = Simulation(poly,r,[.2,.3,.4,.5,.15])
    original = truth_values(poly,4)
    assert np.array_equal(truth_values(r.polynomial,5).reshape((-1,16)).min(0), original)
    assert abs(sim.objective([0,.837])-sim.p0)<1e-10
    gammas,betas,grid = sim.scan(7,9)
    for i,j in [(0,0),(1,3),(6,8)]:
        assert abs(grid[i,j]-sim.objective([gammas[i],betas[j]]))<1e-10
    # Independently apply full Kronecker mixer for a five-qubit circuit.
    gamma,beta = .671,.391
    full = np.eye(1,dtype=complex)
    for p in sim.probabilities:
        b = np.array([[1-2*p,2*np.sqrt(p*(1-p))],[2*np.sqrt(p*(1-p)),2*p-1]])
        u = np.cos(beta)*np.eye(2)-1j*np.sin(beta)*b
        full = np.kron(u,full)
    expected = full @ (sim.initial*np.exp(-1j*gamma*sim.energy))
    assert np.max(np.abs(expected-sim.state([gamma,beta])))<1e-12
    assert abs(sim.objective([gamma+2*math.pi,beta+math.pi])-sim.objective([gamma,beta]))<1e-10
    for method in ["COBYLA","Nelder-Mead"]:
        run=optimise(sim,[[.2,.3],[.7,.4]],method,30,13)
        assert run["calls"]==60
    print("PASS: exactness, original marginal, p0 mixer, scan/scalar, dense matrix, periodicity, budgets")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["test","freeze","run","verify"])
    parser.add_argument("--workers",type=int,default=2)
    args=parser.parse_args()
    if args.command=="test":
        tests()
    elif args.command=="freeze":
        tests(); freeze(); print("Frozen before generation")
    elif args.command=="verify":
        verify_freeze()
        cfg=read(HERE/"protocol.json")
        files=list((HERE/"results").glob("*.json"))
        assert len(files)==len(cfg["families"])*cfg["instances_per_family"]
        for path in files:
            r=read(path)
            assert r["freeze_sha256"]==sha(HERE/"freeze.json")
            assert len(r["rows"])==8
            for row in r["rows"]:
                assert row["equal_effort"]["calls"]==360
                assert abs(row["equal_effort"]["norm"]-1)<1e-10
                if row["warming"]!="cold":
                    assert abs(row["p0"]-r["independent_sampling_expected_mean"])<1e-10
        print("PASS: 60 independent instances, 480 arms, equal calls, frozen inputs, p0 equality, norms")
    else:
        verify_freeze()
        cfg=read(HERE/"protocol.json")
        jobs=[(f,i) for f in cfg["families"] for i in range(cfg["instances_per_family"])]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(task,*job) for job in jobs]
            for future in as_completed(futures):
                print(future.result(),flush=True)

if __name__=="__main__":
    main()
