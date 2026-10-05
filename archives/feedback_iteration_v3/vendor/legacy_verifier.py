"""Portable, read-only verification of the supplied 2026-09-17 URSS delivery.

Original experiment sources, freezes and result files are never edited. Outputs
go to --output. The historical Windows paths are interpreted portably, while
their original bytes and hashes remain authoritative.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.metadata as metadata
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import time

os.environ.setdefault("QISKIT_PARALLEL", "FALSE")
os.environ.setdefault("RAYON_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def relative(root, name):
    p = PurePosixPath(name.replace("\\", "/"))
    require(not p.is_absolute() and ".." not in p.parts and ":" not in str(p), "Unsafe manifest path")
    result = root.joinpath(*p.parts)
    require(result.resolve().is_relative_to(root.resolve()), "Path leaves archive")
    return result


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def integrity(root):
    manifest = read(root / "MANIFEST_SHA256.json")
    for name, digest in manifest.items():
        require(sha(relative(root, name)) == digest, "Archive hash mismatch: " + name)
    revision = root / "revision"
    frozen = read(revision / "qaoa_new/freeze.json")
    for name, digest in frozen["hashes"].items():
        require(sha(relative(revision, name)) == digest, "Frozen source mismatch: " + name)
    exp = revision / "experiments"
    freeze = read(exp / "compiled_results/freeze.json")
    amendment = read(exp / "compiled_results/amendment_01.json")
    for file, expected in [
        ("compiled_study_frozen_v1.py", freeze["source_sha256"]),
        ("COMPILED_PROTOCOL_frozen_v1.md", freeze["protocol_sha256"]),
        ("compiled_study.py", amendment["amended_source_sha256"]),
        ("COMPILED_PROTOCOL.md", amendment["amended_protocol_sha256"]),
    ]:
        require(sha(exp / file) == expected, file + " freeze/amendment mismatch")
    return {"archive_files": len(manifest), "qaoa_frozen_files": len(frozen["hashes"]),
            "compiler_original_and_amended_hashes": "PASS"}


def environment(root):
    expected = {}
    for line in (root / "requirements-revision.txt").read_text().splitlines():
        if "==" in line:
            key, value = line.strip().split("==")
            expected[key] = value
    actual = {}
    for key, value in expected.items():
        actual[key] = metadata.version(key)
        require(actual[key] == value, f"Dependency mismatch: {key}: {actual[key]} != {value}")
    return {"python": sys.version, "platform": platform.platform(), "packages": actual}


def independent_state(poly, rep, probabilities, angles):
    """Tensor contractions, independent of the delivered strided mixer helper."""
    import numpy as np
    n = rep.n_qubits
    indices = np.arange(1 << n)
    bits = ((indices[:, None] >> np.arange(n)) & 1)
    p = np.asarray(probabilities)
    initial = np.sqrt(np.prod(np.where(bits, p, 1-p), axis=1)).astype(complex)
    def values(polynomial):
        result = np.zeros(len(indices))
        for support, coefficient in polynomial.items():
            result += float(coefficient) * (np.prod(bits[:, np.array(support)-1], axis=1) if support else 1)
        return result
    original = values(poly)
    encoded = values(rep.polynomial)
    gamma, beta = angles
    state = (initial * np.exp(-1j * gamma * encoded)).reshape((2,) * n)
    for q, probability in enumerate(p):
        x, z = 2 * math.sqrt(probability * (1-probability)), 1-2*probability
        mixer = math.cos(beta)*np.eye(2) - 1j*math.sin(beta)*np.array([[z,x],[x,-z]])
        axis = n-1-q
        state = np.moveaxis(np.tensordot(mixer, state, axes=([1], [axis])), 0, axis)
    probabilities1 = np.abs(state.ravel())**2
    inconsistent = np.zeros(len(indices), dtype=bool)
    for (i,j), y in rep.auxiliary_indices.items():
        inconsistent |= bits[:,y-1] != bits[:,i-1]*bits[:,j-1]
    return {"original_mean": float(probabilities1 @ original), "encoded_mean": float(probabilities1 @ encoded),
            "norm": float(probabilities1.sum()), "auxiliary_inconsistency": float(probabilities1 @ inconsistent),
            "optimum_probability": float(probabilities1 @ np.isclose(original, original.min())),
            "p0": float(np.abs(initial)**2 @ original)}


def verify_qaoa(root, replay, replay_all=False):
    import numpy as np
    from scipy.stats import spearmanr
    revision = root / "revision"
    qroot = revision / "qaoa_new"
    run = load("urss_checked_qaoa", qroot / "run.py")
    cfg = read(qroot / "protocol.json")
    data = [read(p) for p in sorted((qroot / "results").glob("*.json"))]
    require(len(data) == len({r['instance_id'] for r in data}) == len({r['seed'] for r in data}) == 60, "QAOA identity counts")
    calls = Counter(); completions = Counter(); states = 0; grids = 0; max_error = 0.
    grid_samples = 0; selection_checks = 0; exactness_checks = 0; replayed = []
    freeze_hash = sha(qroot / "freeze.json")
    signature = lambda poly: tuple((k,float(v)) for k,v in sorted(poly.items()))
    signatures = set()
    for r in data:
        require(r['freeze_sha256'] == freeze_hash, "Result freeze reference")
        instance = read(qroot / "instances" / f"{r['family']}_{r['number']:02d}.json")
        generated, poly, seed, rejected = run.generate(r['family'], r['number'], cfg)
        require(generated == instance and seed == r['seed'] and rejected == r['rejected_generation_attempts'], "Generator replay")
        signatures.add(signature(poly))
        representations, selections = run.select(poly, cfg['n_original'], cfg, seed)
        require(selections == r['selections'], "Selector replay " + r['instance_id'])
        selection_checks += 3
        original = run.truth_values(poly, 6)
        require(float(original.min()) == r['optimum'] and float(original.max()) == r['maximum'], "Original range")
        for representation in representations.values():
            encoded = run.truth_values(representation.polynomial, representation.n_qubits).reshape((-1,64))
            require(np.max(abs(encoded.min(axis=0)-original)) < 1e-10, "Pointwise exactness")
            require(np.all(np.sum(np.isclose(encoded, original[None,:], atol=1e-10, rtol=0),axis=0)==1), "Unique fibre minimizer")
            exactness_checks += 1
        require(len(r['rows']) == 8 and len({(row['representation'],row['warming']) for row in r['rows']}) == 8, "Arm identities")
        for row in r['rows']:
            representation = representations[row['representation']]
            if row['warming'] != 'cold':
                require(abs(row['p0']-r['independent_sampling_expected_mean']) < 1e-10, "Preparation equality")
            for method, quota in [('equal_effort',360),('second_optimizer',360),('scan_refined',960)]:
                if method not in row:
                    continue
                result = row[method]; trace = result['trace']
                require(result['calls']==len(trace)==quota, "Quota/trace count")
                require([t['call'] for t in trace]==list(range(1,quota+1)), "Nonconsecutive trace")
                cumulative = np.minimum.accumulate([t['objective'] for t in trace])
                require(np.max(abs(cumulative-np.array([t['incumbent'] for t in trace])))<1e-10, "Incumbent trace")
                require(abs(cumulative[-1]-result['objective'])<1e-10, "Final objective mismatch")
                fresh = independent_state(poly,representation,row['probabilities'],result['parameters'])
                err=max(abs(fresh[k]-result[k]) for k in fresh if k!='p0')
                require(err<1e-9 and abs(fresh['p0']-row['p0'])<1e-10, "Saved parameter replay")
                max_error=max(max_error,err); states+=1;calls[method]+=quota
                completions[method]+=sum(t.get('uniform_completion_calls',0) for t in trace)
            if 'grid_file' in row:
                with np.load(relative(qroot,row['grid_file'])) as archive:
                    grid=archive['objective']
                require(grid.shape==(65,65) and np.isfinite(grid).all(), "Grid data")
                require(abs(grid.min()-row['scan_refined']['grid_minimum'])<1e-10, "Grid minimum")
                require(row['scan_refined']['objective']<=grid.min()+1e-9, "Refinement worse than grid")
                for i,j in [(0,0),(0,38),(1,3),(11,19),(37,61),(64,64)]:
                    fresh=independent_state(poly,representation,row['probabilities'],[2*math.pi*i/65,math.pi*j/65])
                    err=abs(fresh['original_mean']-grid[i,j]);require(err<1e-9,"Sampled grid replay")
                    max_error=max(max_error,err);grid_samples+=1
                grids+=1;calls['grid']+=grid.size
        if replay and (replay_all or r['number']==0):
            rng=np.random.default_rng(run.derive_seed(seed,'common_parameter_starts'))
            starts=rng.uniform([0,0],[2*math.pi,math.pi],size=(3,2))
            errors=[]; replay_details=[]
            for row in r['rows']:
                sim=run.Simulation(poly,representations[row['representation']],row['probabilities'])
                new=run.optimise(sim,starts,'COBYLA',120,run.derive_seed(seed,'completion'))
                difference=new['objective']-row['equal_effort']['objective']
                errors.append(abs(difference))
                replay_details.append({'representation':row['representation'],'warming':row['warming'],
                    'archived_objective':row['equal_effort']['objective'],'replayed_objective':new['objective'],
                    'difference':difference,'within_1e-8':abs(difference)<1e-8})
            replayed.append({'family':r['family'],'instance_number':r['number'],'arms':8,'maximum_objective_difference':max(errors),
                'within_1e-8':max(errors)<1e-8,'arm_results':replay_details})
        print(f"QAOA {r['family']} {r['number']:02d}: verified",flush=True)
    historical=[]
    for path in (revision/'code/source/data/raw').glob('*/*.json'):
        ins=read(path)
        if ins.get('problem',{}).get('n')==6 and ins.get('family') in ['max3sat','spin_glass']:
            fun=run.max3sat_to_pubo if ins['family']=='max3sat' else run.spin_glass_to_pubo
            historical.append(signature(fun(ins)))
    require(len(signatures)==60 and not signatures.intersection(historical),"Objective overlap")
    stored=read(qroot/'analysis/summary.json');families={}
    for fam in cfg['families']:
        group=[r for r in data if r['family']==fam]
        lookup=lambda r,rep,policy='pair':next(x for x in r['rows'] if x['representation']==rep and x['warming']==policy)
        def interval(vals):
            a=np.asarray(vals);rng=np.random.default_rng(3619)
            boot=a[rng.integers(0,len(a),size=(10000,len(a)))].mean(axis=1)
            return {'mean':float(a.mean()),'low':float(np.quantile(boot,.025)),'high':float(np.quantile(boot,.975))}
        stat={}
        measures={'classical_preparation_gain':[r['cold_p0']-lookup(r,'native')['p0'] for r in group]}
        for rep in ['native','proper_mixed','full']:
            measures[rep+'_incremental_gain']=[lookup(r,rep)['p0']-lookup(r,rep)['equal_effort']['objective'] for r in group]
            if rep!='native':
                measures[rep+'_pair_information_gain']=[lookup(r,rep,'independence')['equal_effort']['objective']-lookup(r,rep)['equal_effort']['objective'] for r in group]
        for key,values in measures.items():
            stat[key]=interval(values)
            require(max(abs(stat[key][k]-stored['families'][fam][key][k]) for k in stat[key])<1e-12,"Bootstrap summary mismatch")
        for rep in ['native','proper_mixed','full']:
            for method, suffix in [('equal_effort','pair_equal_mean'),('second_optimizer','second_mean'),('scan_refined','scan_mean')]:
                mean=float(np.mean([lookup(r,rep)[method]['objective'] for r in group]))
                require(abs(mean-stored['families'][fam][rep+'_'+suffix]['mean'])<1e-12,"Objective table mismatch")
        families[fam]=stat
    return {'instances':60,'arms':480,'exact_representations':exactness_checks,'selector_replays':selection_checks,
            'parameter_state_replays':states,'saved_grids':grids,'independent_grid_points':grid_samples,
            'maximum_numeric_difference':max_error,'calls':dict(calls),'completion_calls':dict(completions),
            'unique_objectives':len(signatures),'historical_n6_objectives':len(historical),'overlap':0,
            'families':families,'optimizer_replay_status':('PASS' if all(x['within_1e-8'] for x in replayed) else 'DIFFERENCES') if replay else 'NOT_RUN',
            'optimizer_replays':replayed}


def verify_compilation(root):
    import numpy as np
    exp=root/'revision/experiments';sys.path.insert(0,str(exp))
    comp=load('compiled_study',exp/'compiled_study.py')
    analysis=load('urss_checked_compiled_analysis',exp/'analyse_compiled_study.py')
    expected=comp.generate()
    require(expected==read(exp/'compiled_results/instances_frozen.json'),'Compiler generator replay')
    data=[read(p) for p in sorted((exp/'compiled_results/instances').glob('*.json'))]
    require(len(data)==90,'Compiler instance count')
    frozen={r['id']:r for r in expected}
    totals=Counter();any_counts=Counter();all_counts=Counter();counts=Counter()
    sample_comparisons=[];phase_cells=0;settings=0
    old_phase={ (r['id'],r['topology'],r['strategy']):r for r in read(exp/'compiled_results/per_instance_phase_counts.json')}
    for payload in data:
        ins=payload['instance'];iid=ins['id'];require(ins==frozen[iid],'Compiler source instance')
        libraries,logical,allfull=comp.design_libraries(ins)
        require(allfull==payload['full_logical_enumeration'],'Full enumeration replay')
        require(len(payload['results'])==6,'Compiler settings count');flags=[]
        for result in payload['results']:
            topo=result['topology'];strategy=result['strategy'];lib=libraries[topo]
            require(result['full_keys']==[comp.key(a) for a in lib['full']],'Full candidate library')
            require(result['mixed_keys']==[comp.key(a) for a in lib['mixed']],'Mixed candidate library')
            require(len(result['full_keys'])==len(result['mixed_keys'])==result['scheduled_evaluations_per_space'],'Candidate fairness')
            for key,row in result['candidates'].items():
                logical_row=logical[tuple(row['actions'])]
                for k in ['aux','reduced','M','max_aux_degree']:
                    require(abs(logical_row[k]-row[k])<1e-9,'Logical resource mismatch')
                require(logical_row['Q']==row['logical_Q']<=row['Q']<=12,'Width accounting')
                score=(row['aux']/4+row['G']/160+row['D']/120+row['M']/8)/4
                require(abs(score-row['J'])<1e-12,'Resource score')
            classes,cert=analysis.classify(payload,result)
            old=old_phase[(iid,topo,strategy)]
            require(np.bincount(classes.ravel(),minlength=5).tolist()==old['class_cells'] and int(cert.sum())==old['certified_cells'],'Phase-map recount')
            flags.append(bool(cert.any()));counts[(ins['family'],topo,strategy)]+=bool(cert.any())
            phase_cells+=cert.size;settings+=1
            totals['scheduled']+=2*len(lib['full']);totals['compiler_calls']+=len(result['candidates'])
            # First indexed instance of each family, all topologies/syntheses,
            # three representation endpoints selected before seeing replay.
            if iid.endswith('_000'):
                for name in ['native','resource_full','best_strict_mixed']:
                    old=result['baselines'][name]
                    fresh=comp.compile_one(ins,tuple(old['actions']),topo,strategy)
                    differences={k:[old[k],fresh[k]] for k in ['Q','logical_Q','G','D','M','J'] if abs(old[k]-fresh[k])>1e-9}
                    sample_comparisons.append({'id':iid,'topology':topo,'strategy':strategy,'representation':name,'differences':differences})
        any_counts[ins['family']]+=any(flags);all_counts[ins['family']]+=all(flags)
        print('Compiler records '+iid+': verified',flush=True)
    return {'instances':90,'settings':settings,'budget_cells_recounted':phase_cells,'compiler_calls_recorded':totals['compiler_calls'],
            'scheduled_candidate_evaluations':totals['scheduled'],'certified_any_setting':dict(any_counts),'certified_all_settings':dict(all_counts),
            'certified_counts':[{'family':k[0],'topology':k[1],'strategy':k[2],'instances':v} for k,v in sorted(counts.items())],
            'actual_recompilations':len(sample_comparisons),'recompilation_mismatches':[x for x in sample_comparisons if x['differences']]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent/'payload')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--integrity-only',action='store_true')
    parser.add_argument('--replay-optimizers',action='store_true')
    parser.add_argument('--replay-all',action='store_true')
    args=parser.parse_args();args.root=args.root.resolve();args.output=args.output.resolve()
    require(not args.output.is_relative_to(args.root),'Audit output must be outside archival payload')
    require(not args.output.exists(), 'Output already exists; choose a NEW verification directory')
    require(not sys.flags.optimize, 'Run verification without Python -O')
    args.output.mkdir(parents=True)
    if args.replay_all: args.replay_optimizers=True
    require(not (args.integrity_only and args.replay_optimizers), 'Integrity-only cannot include optimizer replay')
    result={'status':'RUNNING','scope':'Supplied 20260917 revision only','started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    try:
        result['integrity']=integrity(args.root)
        if not args.integrity_only:
            result['environment']=environment(args.root)
            result['qaoa']=verify_qaoa(args.root,args.replay_optimizers,args.replay_all)
            result['compilation']=verify_compilation(args.root)
        result['integrity_after']=integrity(args.root)
        result['requested_scope']={'integrity_only':args.integrity_only,'optimizer_replay':('all_60_instances' if args.replay_all else 'first_instance_per_family') if args.replay_optimizers else 'NOT_RUN'}
        result['archive_evidence_status']='PASS'
        result['replay_covers_all_equal_effort_arms']=args.replay_all
        result['optimizer_replay_methods']=['COBYLA equal_effort'] if args.replay_optimizers else []
        result['observed_runtime']=platform.platform()
        numeric_replay_changed=(bool(result.get('compilation',{}).get('recompilation_mismatches')) or
            any(not x['within_1e-8'] for x in result.get('qaoa',{}).get('optimizer_replays',[])))
        result['status']='PASS_WITH_REPLAY_DIFFERENCES' if numeric_replay_changed else 'PASS'
    except Exception as exc:
        result['status']='FAIL';result['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (args.output/'verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print('VERIFICATION_STATUS: '+result['status'],flush=True)
    return 2 if result['status']!='PASS' else 0


if __name__=='__main__':
    raise SystemExit(main())
