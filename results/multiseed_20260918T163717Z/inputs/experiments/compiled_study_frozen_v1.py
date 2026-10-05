"""Frozen fresh compiled-resource experiment; run --help for stages.

All indices are zero-based. Neither compilation nor selection uses QAOA outcomes.
The primary comparison uses exactly 32 feasible candidate evaluations per search
space; the random control is evaluated separately and cannot alter selection.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, itertools, json, math, os
from pathlib import Path
import random, statistics, sys, time
from datetime import datetime, timezone

os.environ.setdefault("QISKIT_PARALLEL", "FALSE")
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "compiled_results"
CONFIG = {
    "protocol": "fresh-compiled-resources-v1", "seed": 202609173,
    "families": {"max3sat": 30, "spin_glass": 30, "pair_star_isolated": 30},
    "candidate_budget_per_space": 32, "penalty_multiplier": 1.1,
    "compiler_seed": 1729, "optimization_level": 3,
    "basis": ["rz", "sx", "x", "cx"],
    "topologies": ["line12", "ring12", "grid12"],
    "strategies": ["canonical", "reuse"],
    "score": "(aux/4 + CX/160 + CX_depth/120 + Mmax/8)/4",
    "budgets": {"Q": list(range(6,13)), "G": list(range(0,241,4)),
                "D": [24,48,72,96,120,160,240], "M": [0,1.1,2.2,3.3,4.4,6.6,8.8]},
    "primary_contrasts": ["strict-mixed-only feasibility with logical endpoint certificate",
       "equal-candidate-budget J: mixed versus full", "ranking and Pareto stability between synthesis strategies"],
    "search_scope": "32-candidate target-specific finite library, not global optimum",
    "sample_scope": "new small-instance compiler evidence; no quality-threshold claim",
    "width_budget": "Q is active physical footprint, including occupied inputs and all routed sites; logical_Q=n+aux also recorded",
}

def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False),encoding="utf8")

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def key(actions): return ",".join(map(str,actions))
def pairs(edge): return list(itertools.combinations(edge,2))
def add(poly, support, coeff):
    support = tuple(sorted(support)); poly[support] = poly.get(support,0.)+coeff
    if abs(poly[support]) < 1e-12: del poly[support]

def original(instance):
    return {tuple(t["support"]): float(t["coefficient"]) for t in instance["terms"]}

def cubic_terms(instance): return sorted((e,c) for e,c in original(instance).items() if len(e)==3)

def representation(instance, actions):
    poly = original(instance); cubics = cubic_terms(instance)
    buckets={}
    for (e,c),a in zip(cubics,actions):
        if a>=0: buckets.setdefault(pairs(e)[a],[]).append((e,c))
    penalty={}
    for i,(p,items) in enumerate(sorted(buckets.items())):
        y=instance["n"]+i
        threshold=max(sum(max(c,0) for e,c in items),sum(max(-c,0) for e,c in items))
        m=CONFIG["penalty_multiplier"]*threshold; penalty[p]=m
        for e,c in items:
            add(poly,e,-c); add(poly,(y,next(v for v in e if v not in p)),c)
        add(poly,p,m); add(poly,(p[0],y),-2*m); add(poly,(p[1],y),-2*m); add(poly,(y,),3*m)
    return poly,{"Q":instance["n"]+len(buckets),"aux":len(buckets),
        "reduced":sum(a>=0 for a in actions),"M":max(penalty.values(),default=0),
        "max_aux_degree":max((2+len(v) for v in buckets.values()),default=0)}

def pauli(poly):
    result={}
    for e,c in poly.items():
        for r in range(len(e)+1):
            for s in itertools.combinations(e,r): add(result,s,c*((-1)**r)/(2**len(e)))
    return result

def topology(name):
    if name=="line12": e=[(i,i+1) for i in range(11)]
    elif name=="ring12": e=[(i,(i+1)%12) for i in range(12)]
    elif name=="grid12": e=[(4*r+c,4*r+c+1) for r in range(3) for c in range(3)]+[(4*r+c,4*(r+1)+c) for r in range(2) for c in range(4)]
    else: raise ValueError(name)
    return e+[(b,a) for a,b in e]

def distances(name):
    d=[[0 if i==j else 99 for j in range(12)] for i in range(12)]
    for a,b in topology(name): d[a][b]=1
    for k in range(12):
        for i in range(12):
            for j in range(12): d[i][j]=min(d[i][j],d[i][k]+d[k][j])
    return d

def cost_circuit(poly, n, strategy):
    from qiskit import QuantumCircuit
    from qiskit.circuit import Parameter
    qc=QuantumCircuit(n); gamma=Parameter("gamma")
    terms=[(s,c) for s,c in pauli(poly).items() if s]
    if strategy=="canonical":
        gadgets=[(s[-1],tuple(s[:-1]),c) for s,c in sorted(terms,key=lambda z:(len(z[0]),z[0]))]
    else:
        # All Z gadgets commute. Re-root each at the most common incident qubit,
        # group by root, then nearest parity support to expose CNOT cancellation.
        frequency={i:sum(i in s for s,c in terms) for i in range(n)}
        groups={}
        for s,c in terms:
            root=min(s,key=lambda i:(-frequency[i],i))
            groups.setdefault(root,[]).append((tuple(i for i in s if i!=root),c))
        gadgets=[]
        for root,remaining in sorted(groups.items()):
            previous=()
            while remaining:
                nxt=min(remaining,key=lambda z:(len(set(z[0])^set(previous)),z[0]))
                remaining.remove(nxt); previous=nxt[0]; gadgets.append((root,*nxt))
    # No barriers: the transpiler can optimize across every gadget boundary.
    for target,controls,c in gadgets:
        for control in controls: qc.cx(control,target)
        qc.rz(2*c*gamma,target)
        for control in reversed(controls): qc.cx(control,target)
    return qc

def compile_one(instance,actions,topo,strategy,return_circuit=False):
    from qiskit import transpile
    from qiskit.transpiler import CouplingMap
    poly,logical=representation(instance,actions)
    if logical["Q"]>12: raise ValueError("Candidate exceeds declared device capacity")
    qc=cost_circuit(poly,logical["Q"],strategy)
    compiled=transpile(qc,basis_gates=CONFIG["basis"],coupling_map=CouplingMap(topology(topo)),
        initial_layout=list(range(logical["Q"])),routing_method="sabre",
        seed_transpiler=CONFIG["compiler_seed"],optimization_level=CONFIG["optimization_level"])
    active=set(range(logical["Q"]))
    for instruction in compiled.data:
        active.update(compiled.find_bit(q).index for q in instruction.qubits)
    logical["logical_Q"]=logical["Q"]; logical["Q"]=len(active)
    logical.update(G=int(compiled.count_ops().get("cx",0)),
        D=int(compiled.depth(filter_function=lambda instruction: len(instruction.qubits)==2)),
        all_gate_depth=int(compiled.depth()),total_gates=int(compiled.size()))
    logical["J"]=(logical["aux"]/4+logical["G"]/160+logical["D"]/120+logical["M"]/8)/4
    return (logical,compiled) if return_circuit else logical

def generate():
    rng=random.Random(CONFIG["seed"]); instances=[]
    for family,count in CONFIG["families"].items():
        for index in range(count):
            n=9 if family=="pair_star_isolated" else 6; poly={}
            if family=="pair_star_isolated":
                perm=list(range(n)); rng.shuffle(perm)
                # Four leaves plus a disjoint triple; iid positive weights.
                edges=[(0,1,k) for k in range(2,6)]+[(6,7,8)]
                for e in edges: add(poly,tuple(perm[i] for i in e),rng.choice([0.75,1.,1.25]))
            else:
                edges=rng.sample(list(itertools.combinations(range(n),3)),5)
                if family=="max3sat":
                    for e in edges:
                        term={():1.}
                        for i in e:
                            nxt={}; neg=rng.choice([False,True])
                            for s,c in term.items():
                                if neg: add(nxt,s+(i,),c)
                                else: add(nxt,s,c); add(nxt,s+(i,),-c)
                            term=nxt
                        for s,c in term.items(): add(poly,s,c)
                else:
                    # H(s)=sum J_ijk s_i s_j s_k,
                    # with s_i=1-2x_i, includes the implied lower-order terms.
                    for e in edges:
                        c=rng.choice([-1.,1.])
                        for r in range(len(e)+1):
                            for s in itertools.combinations(e,r): add(poly,s,c*((-2)**r))
                    # Scale f by 1/8 so cubic coefficient magnitudes are one.
                    poly={s:c/8 for s,c in poly.items()}
            instances.append({"id":f"{family}_{index:03d}","family":family,"n":n,
                "terms":[{"support":list(s),"coefficient":c} for s,c in sorted(poly.items())]})
    return instances

def design_libraries(instance):
    m=len(cubic_terms(instance)); edges=[e for e,c in cubic_terms(instance)]
    metadata={}
    for actions in itertools.product(range(-1,3),repeat=m):
        _,res=representation(instance,actions); metadata[actions]=res
    full=[a for a,r in metadata.items() if r["reduced"]==m and r["Q"]<=12]
    mixed=[a for a,r in metadata.items() if r["Q"]<=12]
    minaux=min(full,key=lambda a:(metadata[a]["aux"],metadata[a]["M"],a))
    frequency={p:sum(set(p)<=set(e) for e in edges) for e in edges for p in pairs(e)}
    reuse=tuple(min(range(3),key=lambda j:(-frequency[pairs(e)[j]],pairs(e)[j])) for e in edges)
    if metadata[reuse]["Q"]>12: reuse=minaux
    rng=random.Random(CONFIG["seed"]+int(hashlib.sha256(instance["id"].encode()).hexdigest()[:8],16))
    rng.shuffle(full); rng.shuffle(mixed)
    # Match reduced-term cardinalities approximately equally in the proposal bank.
    mixed.sort(key=lambda a: rng.random())
    def fill(initial,source):
        out=list(dict.fromkeys(initial))
        for a in source:
            if a not in out: out.append(a)
            if len(out)==CONFIG["candidate_budget_per_space"]: break
        assert len(out)==CONFIG["candidate_budget_per_space"]
        return out
    libraries={}
    for topo in CONFIG["topologies"]:
        d=distances(topo)
        hardware=tuple(min(range(3),key=lambda j:(d[pairs(e)[j][0]][pairs(e)[j][1]],-frequency[pairs(e)[j]],j)) for e in edges)
        if metadata[hardware]["Q"]>12: hardware=minaux
        starts=[minaux,reuse,hardware]
        fullbank=fill(starts,full)
        native=(-1,)*m
        # Greedy prefixes of maximal reuse explicitly preserve strong mixed candidates.
        prefixes=[tuple(a if j<k else -1 for j,a in enumerate(reuse)) for k in range(1,m)]
        buckets=[tuple(pairs(e).index(p) if set(p)<=set(e) else -1 for e in edges)
                 for p in sorted(frequency,key=lambda p:(-frequency[p],p)) if frequency[p]>1]
        mixedbank=fill([native,*starts,*buckets,*prefixes],mixed)
        libraries[topo]={"full":fullbank,"mixed":mixedbank,"min_aux":minaux,"max_reuse":reuse,"hardware":hardware}
    allfull=[{"actions":list(a),"Q":r["Q"],"M":r["M"]} for a,r in metadata.items() if r["reduced"]==m]
    return libraries,metadata,allfull

def run_instance(instance):
    import qiskit
    libs,metadata,allfull=design_libraries(instance)
    results=[]; compiler_calls=0
    for topo in CONFIG["topologies"]:
        lib=libs[topo]
        for strategy in CONFIG["strategies"]:
            cache={}
            def measure(a):
                nonlocal compiler_calls
                if a not in cache:
                    cache[a]=compile_one(instance,a,topo,strategy); compiler_calls+=1
                return cache[a]
            for a in set(lib["full"]+lib["mixed"]): measure(a)
            bestfull=min(lib["full"],key=lambda a:(measure(a)["J"],a))
            bestmixed=min(lib["mixed"],key=lambda a:(measure(a)["J"],a))
            beststrict=min((a for a in lib["mixed"] if 0<metadata[a]["reduced"]<len(a)),key=lambda a:(measure(a)["J"],a))
            selected=metadata[beststrict]
            matching=[a for a,r in metadata.items() if r["aux"]==selected["aux"] and r["reduced"]==selected["reduced"] and a!=beststrict]
            rng=random.Random(CONFIG["seed"]+sum(map(ord,instance["id"]+topo+strategy)))
            penalty_matching=[a for a in matching if abs(metadata[a]["M"]-selected["M"])<1e-10]
            match=rng.choice(penalty_matching or matching) if matching else beststrict
            measure(match)
            baseline={"native":(-1,)*len(bestfull),"resource_full":bestfull,"resource_mixed":bestmixed,
                      "best_strict_mixed":beststrict,"min_aux_full":lib["min_aux"],"max_reuse":lib["max_reuse"],
                      "hardware_distance":lib["hardware"],"matched_random":match}
            results.append({"topology":topo,"strategy":strategy,
                "full_keys":[key(a) for a in lib["full"]],"mixed_keys":[key(a) for a in lib["mixed"]],
                "baselines":{name:{"actions":list(a),**measure(a)} for name,a in baseline.items()},
                "candidates":{key(a):{"actions":list(a),**r} for a,r in cache.items()},
                "matched_random_degenerate":not bool(matching),"matched_random_penalty_exact":bool(penalty_matching),
                "scheduled_evaluations_per_space":32})
    payload={"instance":instance,"compiler_calls":compiler_calls,"qiskit":qiskit.__version__,
             "full_logical_enumeration":allfull,"results":results}
    dump(OUT/"instances"/(instance["id"]+".json"),payload)
    return instance["id"],compiler_calls

def freeze():
    import qiskit, numpy, scipy
    path=OUT/"freeze.json"
    if path.exists(): raise RuntimeError("Freeze already exists; do not silently overwrite")
    # Freeze is written before any fresh evaluation instances are generated.
    payload={"frozen_utc":datetime.now(timezone.utc).isoformat(),"source_sha256":sha(__file__),
       "protocol_sha256":sha(ROOT/"COMPILED_PROTOCOL.md"),
       "config":CONFIG,"python":sys.version,"qiskit":qiskit.__version__,"numpy":numpy.__version__,"scipy":scipy.__version__}
    dump(path,payload)
    instances=generate(); dump(OUT/"instances_frozen.json",instances)
    dump(OUT/"generation_audit.json",{"freeze_sha256":sha(path),"instances_sha256":sha(OUT/"instances_frozen.json"),
       "generated_utc":datetime.now(timezone.utc).isoformat(),"count":len(instances),"source_sha256":sha(__file__)})
    print("Frozen before generation:",payload["source_sha256"],flush=True)

def run(workers):
    frozen=json.loads((OUT/"freeze.json").read_text())
    assert frozen["source_sha256"]==sha(__file__),"Source changed after freeze"
    assert frozen["config"]==CONFIG
    instances=json.loads((OUT/"instances_frozen.json").read_text())
    pending=[x for x in instances if not (OUT/"instances"/(x["id"]+".json")).exists()]
    start=time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(run_instance,x) for x in pending]
        for count,f in enumerate(concurrent.futures.as_completed(futures),1):
            iid,calls=f.result(); print(f"{count}/{len(pending)} {iid}: {calls} compiles; elapsed {time.time()-start:.1f}s",flush=True)

def verify():
    import numpy as np
    from qiskit import QuantumCircuit
    from qiskit.quantum_info import Operator, Statevector
    examples=[{"n":4,"terms":[{"support":[0,1,2],"coefficient":1.},{"support":[0,1,3],"coefficient":-0.7}]}]
    checked=0; errors=[]
    for ins in examples:
        for actions in itertools.product(range(-1,3),repeat=2):
            poly,r=representation(ins,actions); n=ins["n"]; nq=r["Q"]
            value=lambda p,z:sum(c*math.prod(z[i] for i in s) for s,c in p.items())
            for x in itertools.product([0,1],repeat=n):
                reduced=min(value(poly,x+y) for y in itertools.product([0,1],repeat=nq-n))
                assert abs(reduced-value(original(ins),x))<1e-10
            for strategy in CONFIG["strategies"]:
                qc=cost_circuit(poly,nq,strategy).assign_parameters({"gamma":0.371})
                diagonal=np.diag(Operator(qc).data)
                expected=np.array([np.exp(-1j*.371*value(poly,tuple((i>>j)&1 for j in range(nq)))) for i in range(2**nq)])
                ratio=diagonal/expected; err=float(np.max(np.abs(ratio-ratio[0])))
                errors.append(err); assert err<1e-10; checked+=1
    routed=0
    for actions in [(-1,-1),(0,0)]:
        poly,logical=representation(examples[0],actions); nq=logical["Q"]
        for topo in CONFIG["topologies"]:
            allowed=set(topology(topo))
            for strategy in CONFIG["strategies"]:
                metrics,compiled=compile_one(examples[0],actions,topo,strategy,True)
                for instruction in compiled.data:
                    if instruction.operation.name=="cx":
                        assert tuple(compiled.find_bit(q).index for q in instruction.qubits) in allowed
                physical=compiled.layout.final_index_layout(filter_ancillas=True)
                prepared=QuantumCircuit(compiled.num_qubits)
                for q in range(nq): prepared.h(q)
                prepared.compose(compiled.assign_parameters({"gamma":0.371}),inplace=True)
                actual=Statevector.from_instruction(prepared).data
                desired=np.zeros_like(actual)
                for x in itertools.product([0,1],repeat=nq):
                    output=sum(bit*(2**physical[i]) for i,bit in enumerate(x))
                    desired[output]=np.exp(-1j*.371*value(poly,x))/(2**(nq/2))
                overlap=np.vdot(desired,actual); error=float(np.max(np.abs(actual-overlap*desired)))
                assert error<1e-10; errors.append(error); routed+=1
    dump(OUT/"semantic_checks.json",{"development_examples_only":True,"exact_representations_checked":16,
        "logical_circuit_unitaries_checked":checked,"routed_statevector_checks":routed,"maximum_phase_error":max(errors)})
    print("Semantic checks passed",max(errors),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("stage",choices=["verify","freeze","run"])
    parser.add_argument("--workers",type=int,default=4); args=parser.parse_args()
    if args.stage=="verify": verify()
    elif args.stage=="freeze": freeze()
    else: run(args.workers)
