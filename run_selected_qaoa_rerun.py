"""Execute only QAOA designs changed by the reviewed selector, with frozen inputs.

Prepare creates a self-contained immutable plan; run supports verified checkpoints.
No historical CSV, selector input, LP vector, or manuscript source is overwritten.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, os, platform, shutil, subprocess, sys, time, traceback, zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from fractions import Fraction
from importlib.metadata import version
from pathlib import Path
import numpy as np
import yaml
from urss_pipeline import e3_qaoa as e3, e4_warmstart as e4, e6_noise as e6
from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.fibre_selector import design_id as selector_id
from warmstart_correction import strict_null

ARCHIVE_SHA = '9e539a0aa387393e482e5ac0f186ace9695af39d05017fe3bc90eefefe5dd5e5'
BASE_COMMIT = '6329f6f51d48f96f1133f8a5c67db4c1b32c4566'
STUDIES = ('E3', 'E4_corrected_original', 'E4_corrected_targeted', 'E6')
METRICS = ('original_objective_mean','original_objective_best','optimum_hit_rate','encoded_energy_mean','auxiliary_inconsistency_rate')


def digest_bytes(raw): return hashlib.sha256(raw).hexdigest()
def sha(path): return digest_bytes(Path(path).read_bytes())
def encode(obj): return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
def identity(obj): return digest_bytes(encode(obj))
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def write_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_bytes(encode(obj)+b'\n');tmp.replace(path)
def write_csv(path, rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    keys=sorted({k for r in rows for k in r})
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def utc(): return datetime.now(timezone.utc).isoformat()
def actions(raw): return tuple(tuple(a) if a is not None else None for a in raw)
def polynomial(raw): return {tuple(t['support']):Fraction(t['coefficient']) for t in raw}
def terms(poly): return [{'support':list(k),'coefficient':str(v)} for k,v in sorted(poly.items())]
def group_key(row): return (str(row['instance_id']),str(row['representation']),str(row['random_rep_seed']))
def row_key(row, study):
    return group_key(row)+(str(row['budget_key']),str(row['restart_id']),str(row.get('warm_start_policy','')),str(row.get('pair_closure','')),str(row.get('noise_level','')))
def git(repo,*args):
    return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True,encoding='utf-8').stdout.strip()
def environment():
    return {'python':platform.python_version(),'platform':platform.platform(),
            'packages':{p:version(p) for p in ['numpy','scipy','PyYAML','qiskit','qiskit-aer']},
            'OMP_NUM_THREADS':os.environ.get('OMP_NUM_THREADS'),'OPENBLAS_NUM_THREADS':os.environ.get('OPENBLAS_NUM_THREADS')}
def source_paths(repo):
    return sorted([*repo.glob('urss_pipeline/*.py'),repo/'run_selected_qaoa_rerun.py',repo/'warmstart_correction.py',repo/'postprocess_correction.py',repo/'run_review_postprocess.py'])


def check_exact(data, representation):
    n=representation.original_width
    encoded=data.encoded_energies.reshape((-1,1<<n))
    reference=data.original_energies[:1<<n]
    minima=encoded.min(axis=0)
    mismatch=int(np.count_nonzero(np.abs(minima-reference)>1e-10))
    minimisers=np.abs(encoded-minima[None,:])<1e-10
    inconsistent=int(np.count_nonzero(minimisers & data.inconsistent.reshape(encoded.shape).astype(bool)))
    if mismatch or inconsistent: raise ValueError('New encoding exactness failed')
    return {'original_assignments':1<<n,'encoded_assignments':encoded.size,'mismatch_count':mismatch,'inconsistent_minimiser_count':inconsistent}


def prepare(repo, selection, correction_zip, output):
    if (output/'PLAN.json').exists():
        verify(output,repo);print('PLAN: already complete');return
    if output.exists(): raise ValueError('Incomplete preparation directory exists; retain it and choose a new output path')
    if sha(correction_zip)!=ARCHIVE_SHA: raise ValueError('Correction archive hash mismatch')
    if git(repo,'merge-base','--is-ancestor',BASE_COMMIT,'HEAD')!='': raise ValueError('Unexpected baseline')
    tracked=git(repo,'status','--porcelain','--untracked-files=no')
    if tracked: raise ValueError('Commit the runner implementation before freezing the execution plan')
    output.mkdir(parents=True)
    code_files={p.relative_to(repo).as_posix():sha(p) for p in source_paths(repo)}
    for relative in code_files:
        dest=output/'execution_source'/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/relative,dest)
    for name in ['experiment_config_v2.yaml','four_part_addendum_v1.json','e6_noise_v1.json']:
        dest=output/'inputs/configs'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/'configs'/name,dest)
    for name in ['CHANGED_DESIGNS_AND_CONTROLS.json','SELECTED_RERUN_REQUIRED.csv','IMPACT_AUDIT.json','selector_repair_main.csv','targeted_selector_repair.csv']:
        dest=output/'inputs/selection'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(selection/name,dest)
    cfg=yaml.safe_load((repo/'configs/experiment_config_v2.yaml').read_text(encoding='utf-8-sig'))
    protocol=read_json(repo/'configs/e6_noise_v1.json')
    assert cfg['qaoa']['optimizer']['objective_evaluations']==60
    assert cfg['qaoa']['optimizer']['restarts']==3
    env=environment()
    if env['packages']['qiskit']!='2.4.2' or env['packages']['qiskit-aer']!='0.17.2': raise ValueError('Frozen compiler versions required')
    source_commit=git(repo,'rev-parse','HEAD')
    binding={'schema':'selector_changed_qaoa_v3','base_commit':BASE_COMMIT,'code_commit':source_commit,
        'code_files':code_files,'source_tree_sha256':identity(code_files),'environment':env,'archive_sha256':ARCHIVE_SHA,
        'created_utc':utc(),'instance_selection_changed':False,'LP_resolved':False,'optimizer_tuned':False,
        'policy':'recompile budgets and rerun changed designs; reuse immutable unchanged-design observations with source lineage'}
    write_json(output/'EXECUTION_BINDING.json',binding)
    frozen={};sources={};source_info={}
    with zipfile.ZipFile(correction_zip) as z:
        for name in z.namelist():
            if '/exec_20260912_v2/frozen_designs/' in name and name.endswith('.json'):
                raw=z.read(name);rec=json.loads(raw)
                frozen[(rec['study'],*group_key(rec))]=(rec,name,digest_bytes(raw))
            if '/exec_20260912_v2/' in name and name.endswith('/corrected_runs.csv'):
                study='E4_corrected_targeted' if '/targeted/' in name else 'E4_corrected_original'
                raw=z.read(name);dest=output/'inputs'/f'{study}.csv';dest.write_bytes(raw)
                sources[study]=read_csv(dest);source_info[study]={'source':name,'sha256':sha(dest)}
    for study,name in [('E3','e3_qaoa_runs.csv'),('E6','e6_noise_runs.csv')]:
        path=repo/'fibre_e1_e6_v2/results'/name;dest=output/'inputs'/f'{study}.csv';shutil.copyfile(path,dest)
        sources[study]=read_csv(dest);source_info[study]={'source':path.relative_to(repo).as_posix(),'sha256':sha(dest)}
    changes=read_json(selection/'CHANGED_DESIGNS_AND_CONTROLS.json')['records']
    change_index={(r['tier'],*group_key(r)):r for r in changes}
    declared=read_csv(selection/'SELECTED_RERUN_REQUIRED.csv')
    qrecords={r['instance_id']:r for r in read_json(repo/'fibre_selector_v2/qaoa_representation_designs_v2.json')['records']}
    expected_members={}
    designs={};jobs=[];budget_comparison=[];exact_rows=[];removed=[]
    for study in STUDIES:
        tier='targeted' if study=='E4_corrected_targeted' else 'qaoa'
        groups=defaultdict(list)
        for number,row in enumerate(sources[study],2):
            if row['status']!='pass': raise ValueError('Archived non-passing input')
            key=group_key(row)
            if (tier,*key) in change_index: groups[key].append((number,row))
        expected_rows={int(r['source_csv_row']) for r in declared if r['study']==study}
        actual_rows={number for rows in groups.values() for number,_ in rows}
        if expected_rows!=actual_rows: raise ValueError('Impact coverage differs for '+study)
        for key,entries in sorted(groups.items()):
            change=change_index[(tier,*key)];iid,rep,draw=key;first=entries[0][1]
            if any(r['source_sha256']!=source_info[study]['sha256'] for r in declared if r['study']==study and group_key(r)==key):
                raise ValueError('Impact source SHA mismatch')
            fstudy='targeted' if tier=='targeted' else 'original_e4'
            frozen_value=frozen.get((fstudy,*key))
            if frozen_value:
                oldrec,member,member_hash=frozen_value
                expected_members[member]=member_hash
                oldactions=oldrec['actions'];n=int(oldrec['n_original']);poly=polynomial(oldrec['original_terms']);family=oldrec['family'];moments=oldrec['moments']
                assert actions(oldactions)==actions(change['old_actions'])
            else:
                rec=qrecords[iid];path=repo/'data/canonical'/f'{iid}.json'
                if sha(path)!=rec['canonical_sha256']: raise ValueError('Canonical input changed')
                canonical=read_json(path);poly=polynomial(canonical['terms']);n=int(rec['n_original']);family=rec['family'];moments=None
                oldactions=change['old_actions']
                oldchoice=rec['selected'] if rep=='selective' else next(r for r in rec['matched_random'] if str(r['random_rep_seed'])==draw)
                if actions(oldchoice['actions'])!=actions(oldactions): raise ValueError('Old design differs from selector archive')
            oldeval=_evaluate_design(poly,n_original=n,actions=actions(oldactions),selector=cfg['selector'],apply_qaoa_hard_limits=True)
            olddesign=e3.QAOADesign(rep,int(draw) if draw else None,oldeval)
            if any(row['design_id']!=olddesign.design_id for _,row in entries): raise ValueError('Archived Hamiltonian identity mismatch')
            newactions=actions(change['new_actions'])
            if selector_id(newactions)!=change['new_design_id']: raise ValueError('Changed selector identity mismatch')
            evaluation=_evaluate_design(poly,n_original=n,actions=newactions,selector=cfg['selector'],apply_qaoa_hard_limits=True)
            if not evaluation.feasible: raise ValueError('New QAOA design violates frozen hard limits')
            design=e3.QAOADesign(rep,int(draw) if draw else None,evaluation)
            if design.design_id==olddesign.design_id: raise ValueError('Unchanged design included in changed set')
            optimum=min(float(sum(c*np.prod([bits[i-1] for i in support]) for support,c in poly.items())) for bits in __import__('itertools').product([0,1],repeat=n))
            if frozen_value and abs(optimum-float(oldrec['optimum_original']))>1e-10: raise ValueError('Archived ground truth mismatch')
            record={'tier':tier,'instance_id':iid,'family':family,'representation':rep,'random_rep_seed':draw,
                'n_original':n,'n_aux':evaluation.representation.n_auxiliary,'n_qubits':evaluation.representation.n_qubits,
                'actions':change['new_actions'],'old_actions':oldactions,'old_design_id':olddesign.design_id,
                'selector_design_id':change['new_design_id'],'design_id':design.design_id,
                'original_terms':terms(poly),'encoded_terms':terms(evaluation.representation.polynomial),
                'moments':moments,'optimum_original':optimum}
            did=identity(record);designs[did]=record
            data=e3.statevector_data(poly,evaluation.representation,optimum_original=optimum)
            exact=check_exact(data,evaluation.representation)
            null=strict_null(data)
            exact_rows.append(dict(study=study,instance_id=iid,design_id=design.design_id,**exact,null_max_l2=null['phase_aligned_l2_max']))
            plan=e3.compile_budget_plan(instance_id=iid,family=family,design=design,config=cfg,
                config_hash=first['config_hash'],manifest_hash=first.get('manifest_hash',first.get('noise_manifest_hash','')),code_commit=source_commit)
            specs={s.key:s for s in e3.budget_specs(int(plan['compiled_2q_gates_per_layer']),cfg['qaoa'])}
            extra={}
            if study=='E6':
                seed=e6.representative_transpiler_seed(cfg['compiler']['transpiler_seed_bundle'],json.loads(plan['compiled_2q_gates_by_seed_json']))
                initial=e6._selected_budget_spec(plan,protocol,cfg['qaoa'])
                realised,probe=e6.feasible_full_circuit_spec(evaluation,initial_spec=initial,compiler_config=cfg['compiler'],transpiler_seed=seed)
                specs={realised.key:realised};extra={'initial_p':initial.p,'transpiler_seed':seed,'probe_actual_2q_gates':probe}
            keys=sorted({r['budget_key'] for _,r in entries})
            if set(keys)-set(specs): raise ValueError('Frozen budget key missing')
            warm_specs=[]
            if study.startswith('E4'):
                m=e4.RelaxationMoments(moments['objective'],{int(k):v for k,v in moments['singles'].items()},
                    {tuple(r['pair']):r['value'] for r in moments['pairs']},moments['status'],'Archived; not resolved',moments['runtime_sec'])
                if any(e4._moment_digest(m)!=r['marginal_set_sha256'] for _,r in entries): raise ValueError('Frozen warm-start LP hash mismatch')
                warm_specs=e4.warm_start_specs(design,m,clipping_delta=cfg['qaoa']['warm_start']['clipping_delta'])
            for budget in keys:
                spec=specs[budget]
                oldgroup=[r for _,r in entries if r['budget_key']==budget]
                budget_comparison.append(dict(study=study,instance_id=iid,representation=rep,random_rep_seed=draw,
                    old_design_id=olddesign.design_id,new_design_id=design.design_id,budget_key=budget,
                    old_p=oldgroup[0]['p'],new_p=spec.p,old_layer_gates=oldgroup[0]['compiled_2q_gates_per_layer'],
                    new_layer_gates=spec.compiled_two_qubit_gates_per_layer,compiled_gates_by_seed=plan['compiled_2q_gates_by_seed_json'],**extra))
                policies=warm_specs if study.startswith('E4') else [None]
                for warm in policies:
                    for restart in range(3):
                        matches=[(num,r) for num,r in entries if r['budget_key']==budget and int(r['restart_id'])==restart and
                            (warm is None or (r['warm_start_policy'],r['pair_closure'])==(warm.policy,warm.pair_closure))]
                        if len(matches)!=(3 if study=='E6' else 1): raise ValueError('Source task pairing mismatch')
                        source=dict(matches[0][1]);seeds={k:int(cfg['qaoa'][k+'_bundle'][restart]) for k in ['circuit_seed','measurement_seed']}
                        seeds['optimizer_seed']=int(cfg['qaoa']['optimizer']['seed_bundle'][restart])
                        if any(any(int(r[k])!=v for k,v in seeds.items()) for _,r in matches): raise ValueError('Frozen seed mismatch')
                        job={'study':study,'design_record':did,'budget':asdict(spec),'warm':asdict(warm) if warm else None,
                            'restart_id':restart,'seeds':seeds,'source_rows':[num for num,_ in matches],'source_sha256':source_info[study]['sha256'],
                            'source_template':source,'source_tree_sha256':binding['source_tree_sha256'],**extra}
                        job['task_id']=identity(job);jobs.append(job)
            scheduled_policies={(w.policy,w.pair_closure) for w in warm_specs}
            for num,row in entries:
                if study.startswith('E4') and (row['warm_start_policy'],row['pair_closure']) not in scheduled_policies:
                    removed.append({'study':study,'source_row':num,'reason':'new_zero_aux_design_policy_deduplication'})
            print('PLAN DESIGN:',study,iid[-12:],rep,draw,'nq='+str(record['n_qubits']),flush=True)
    for did,record in designs.items(): write_json(output/'designs'/f'{did}.json',record)
    write_json(output/'TASKS.json',jobs)
    write_json(output/'SOURCE_INDEX.json',source_info)
    write_json(output/'ARCHIVED_DESIGN_MEMBERS.json',expected_members)
    write_csv(output/'BUDGET_CHANGES.csv',budget_comparison)
    write_csv(output/'EXACTNESS_AND_NULL_CONTROLS.csv',exact_rows)
    write_csv(output/'REMOVED_POLICY_ROWS.csv',removed)
    file_manifest={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()}
    plan={'status':'FROZEN_READY','jobs':len(jobs),'jobs_by_study':dict(Counter(j['study'] for j in jobs)),
        'expected_observations':sum(3 if j['study']=='E6' else 1 for j in jobs),'unique_design_records':len(designs),
        'positive_depth_jobs':sum(j['budget']['p']>0 for j in jobs),'zero_depth_jobs':sum(j['budget']['p']==0 for j in jobs),
        'source_tree_sha256':binding['source_tree_sha256'],'frozen_files':file_manifest}
    write_json(output/'PLAN.json',plan);print(json.dumps({k:v for k,v in plan.items() if k!='frozen_files'},indent=2),flush=True)


def verify(output, repo):
    plan=read_json(output/'PLAN.json')
    for name,digest in plan['frozen_files'].items():
        if sha(output/name)!=digest: raise ValueError('Frozen run input changed: '+name)
    binding=read_json(output/'EXECUTION_BINDING.json')
    for name,digest in binding['code_files'].items():
        if sha(repo/name)!=digest: raise ValueError('Execution source changed: '+name)
    if environment()['packages']!=binding['environment']['packages']: raise ValueError('Execution package versions changed')
    return plan,binding


@lru_cache(maxsize=64)
def load_design(output_string,did):
    output=Path(output_string);r=read_json(output/'designs'/f'{did}.json')
    cfg=yaml.safe_load((output/'inputs/configs/experiment_config_v2.yaml').read_text(encoding='utf-8'))
    poly=polynomial(r['original_terms'])
    ev=_evaluate_design(poly,n_original=r['n_original'],actions=actions(r['actions']),selector=cfg['selector'],apply_qaoa_hard_limits=True)
    if terms(ev.representation.polynomial)!=r['encoded_terms']: raise ValueError('Frozen new Hamiltonian changed')
    design=e3.QAOADesign(r['representation'],int(r['random_rep_seed']) if r['random_rep_seed'] else None,ev)
    if design.design_id!=r['design_id']: raise ValueError('Frozen design id changed')
    data=e3.statevector_data(poly,ev.representation,optimum_original=r['optimum_original'])
    m=r['moments'];moments=None if m is None else e4.RelaxationMoments(m['objective'],{int(k):v for k,v in m['singles'].items()},
        {tuple(x['pair']):x['value'] for x in m['pairs']},m['status'],'Restored archived moments; no LP solve',m['runtime_sec'])
    return r,cfg,poly,design,data,moments


def validate_metrics(row):
    for metric in METRICS:
        if not np.isfinite(float(row[metric])): raise ValueError('Nonfinite metric '+metric)
    for metric in ['optimum_hit_rate','auxiliary_inconsistency_rate']:
        if not -1e-10<=float(row[metric])<=1+1e-10: raise ValueError('Invalid probability')
    if row['status']!='pass': raise ValueError('Optimizer/simulator failure: '+str(row))
    if len(json.loads(row['optimized_parameters_json']))!=2*int(row['p']): raise ValueError('Parameter dimension mismatch')
    if 'statevector_norm' in row and row['statevector_norm']!='' and abs(float(row['statevector_norm'])-1)>1e-9: raise ValueError('State norm failure')


def task_worker(output_string,job):
    output=Path(output_string);started=time.perf_counter()
    trace=[]
    try:
        record,cfg,poly,design,data,moments=load_design(output_string,job['design_record'])
        binding=read_json(output/'EXECUTION_BINDING.json');source=job['source_template'];budget=e3.QAOABudgetSpec(**job['budget'])
        common=dict(instance_id=record['instance_id'],family=record['family'],design=design,data=data,
            restart_id=job['restart_id'],**job['seeds'],qaoa_config=cfg['qaoa'],config_hash=source['config_hash'],
            manifest_hash=source.get('manifest_hash',source.get('noise_manifest_hash','')),code_commit=binding['code_commit'])
        from unittest.mock import patch
        if job['study'].startswith('E4'):
            warm=e4.WarmStartSpec(**job['warm']);original=e4._simulate
            def traced(d,w,params,p):
                state=original(d,w,params,p);trace.append({'parameters':list(map(float,params)),'objective':float(np.abs(state)**2 @ d.original_energies)});return state
            with patch.object(e4,'_simulate',side_effect=traced):
                row=e4.optimize_warmstart_run(**common,budget=budget,warm_spec=warm,moments=moments,e3_summary_hash='NOT_USED_DIRECT_FROZEN_QAOA_PROTOCOL')
        else:
            original=e3.simulate_qaoa
            def traced(d,*,gammas,betas):
                state=original(d,gammas=gammas,betas=betas);trace.append({'parameters':list(map(float,gammas))+list(map(float,betas)),
                    'objective':float(np.abs(state)**2 @ d.original_energies)});return state
            with patch.object(e3,'simulate_qaoa',side_effect=traced):
                row=e3.optimize_qaoa_run(**common,spec=budget,e2_summary_hash='NOT_USED_DIRECT_NEW_DESIGN_COMPILATION')
        validate_metrics(row)
        if int(row['evaluations'])!=60 or len(trace)!=61: raise ValueError('Evaluation accounting changed')
        params=json.loads(row['optimized_parameters_json'])
        warm=e4.WarmStartSpec(**job['warm']) if job['warm'] else e4.WarmStartSpec('cold_start','not_applicable',None)
        replay=e3.statevector_metrics(e4._simulate(data,warm,params,budget.p),data)
        if any(abs(replay[k]-float(row[k]))>1e-10 for k in METRICS): raise ValueError('Optimized parameter replay mismatch')
        for item in trace[:-1]:item['role']='optimizer_objective_call'
        trace[-1]['role']='final_metric_call'
        rows=[row];noise_artifacts=[]
        if job['study']=='E6':
            protocol=read_json(output/'inputs/configs/e6_noise_v1.json')
            circuit=e6._build_compiled_qaoa_circuit(design.evaluation,gammas=params[:budget.p],betas=params[budget.p:],
                compiler_config=cfg['compiler'],transpiler_seed=job['transpiler_seed'])
            actual=sum(len(i.qubits)==2 for i in circuit.data)
            if actual>protocol['compiled_2q_budget']: raise ValueError('Full measured circuit exceeds E6 budget')
            rows=[]
            from qiskit_aer import AerSimulator
            for level in cfg['noise']['levels']:
                noise_started=time.perf_counter()
                model=e6.build_noise_model(level,measured_qubit_count=circuit.num_qubits,protocol=protocol)
                backend=AerSimulator(method='automatic',noise_model=model)
                result=backend.run(circuit,shots=protocol['shots'],seed_simulator=job['seeds']['measurement_seed']).result()
                counts=result.get_counts(circuit)
                if sum(counts.values())!=protocol['shots']:raise ValueError('Shot count mismatch')
                metrics=e6.metrics_from_counts(counts,original=poly,representation=design.evaluation.representation,optimum_original=record['optimum_original'])
                item=dict(row,**metrics)
                item.update(noise_level=level['id'],noise_model_id=cfg['noise']['model_id'],shots=protocol['shots'],
                    topology_id=protocol['topology_id'],transpiler_seed=job['transpiler_seed'],
                    optimized_parameters_sha256=e6._parameter_hash(params),initial_p=job['initial_p'],realised_p=budget.p,
                    depth_selection_rule='decrease_until_full_transpiled_measured_circuit_fits_budget',actual_2q_gates=actual,
                    optimizer_evaluations=row['evaluations'],simulation_runtime_sec=time.perf_counter()-noise_started,
                    noise_manifest_hash=source['noise_manifest_hash'],protocol_config_hash=source['protocol_config_hash'],
                    e3_validation_summary_hash='see_new_execution_audit',e5_validation_summary_hash='E5_update_pending_E2_recompilation',
                    objective_scoring=protocol['primary_score'],auxiliary_scoring_rule='discard_for_primary_score_and_report_inconsistency_diagnostic',
                    one_qubit_depolarizing_probability=level['parameters'].get('one_qubit_depolarizing_probability',0),
                    two_qubit_depolarizing_probability=level['parameters'].get('two_qubit_depolarizing_probability',0),
                    symmetric_readout_probability=level['parameters'].get('symmetric_readout_probability',0))
                rows.append(item)
                noise_artifacts.append({'noise_level':level['id'],'counts':counts,'backend_metadata':result.results[0].metadata,
                    'transpiled_circuit_num_qubits':circuit.num_qubits,'transpiled_circuit_depth':circuit.depth(),
                    'transpiled_circuit_operations':dict(circuit.count_ops())})
            e6.attach_paired_degradation(rows)
        for item in rows:
            validate_metrics(item)
            item.update(task_id=identity({'job_id':job['task_id'],'noise_level':item.get('noise_level','')}),job_id=job['task_id'],
                study='targeted' if job['study']=='E4_corrected_targeted' else 'original_e4' if job['study']=='E4_corrected_original' else job['study'],
                selector_design_id=record['selector_design_id'],source_design_id=record['old_design_id'],
                source_file_sha256=job['source_sha256'],source_csv_rows=json.dumps(job['source_rows']),
                source_code_commit=source['code_commit'],source_e3_summary_hash=source.get('e3_summary_hash',''),
                source_e2_summary_hash=source.get('e2_summary_hash',''),new_budget_plan_sha256=sha(output/'BUDGET_CHANGES.csv'),execution_source_sha256=binding['source_tree_sha256'],execution_plan_sha256=sha(output/'PLAN.json'),
                observation_origin='NEW_DESIGN_RERUN',task_outcome='RERUN_PASS',
                optimizer_calls_this_execution=60,trainable_optimization_this_execution=budget.p>0,
                completed_at_utc=utc(),n_original=record['n_original'],n_aux=record['n_aux'],n_qubits=record['n_qubits'])
        payload={'status':'PASS','task_id':job['task_id'],'rows':rows,'optimizer_trace':trace,'noise_artifacts':noise_artifacts,
            'independent_parameter_replay_max_error':max(abs(replay[k]-float(row[k])) for k in METRICS),
            'wall_time_sec':time.perf_counter()-started,'completed_at_utc':utc()}
        # Metadata may contain numpy values; preserve native values through a strict conversion.
        payload=json.loads(json.dumps(payload,default=lambda x:x.item() if hasattr(x,'item') else x.tolist()))
        return payload
    except Exception as error:
        return {'status':'FAILED','task_id':job['task_id'],'error':str(error),'traceback':traceback.format_exc(),'optimizer_trace':trace,'wall_time_sec':time.perf_counter()-started}


def run(output,repo,workers):
    plan,binding=verify(output,repo);jobs=read_json(output/'TASKS.json');completed={};pending=[]
    directory=output/'task_results';directory.mkdir(exist_ok=True)
    for job in jobs:
        path=directory/(job['task_id']+'.json');hashfile=path.with_suffix('.sha256')
        if path.exists():
            if not hashfile.exists() or sha(path)!=hashfile.read_text(encoding='utf-8').strip():raise ValueError('Checkpoint hash mismatch')
            result=read_json(path)
            if result['status']!='PASS' or result['task_id']!=job['task_id']:raise ValueError('Invalid checkpoint identity')
            completed[job['task_id']]=result
        else:pending.append(job)
    print('RUN:',len(completed),'verified checkpoints;',len(pending),'jobs pending',flush=True)
    failed=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_jobs={pool.submit(task_worker,str(output),job):job for job in pending}
        for future in as_completed(future_jobs):
            job=future_jobs[future];result=future.result()
            if result['status']=='PASS':
                path=directory/(job['task_id']+'.json');write_json(path,result);path.with_suffix('.sha256').write_text(sha(path)+'\n',encoding='utf-8')
                completed[job['task_id']]=result
            else:
                path=output/'failures'/(job['task_id']+'_'+str(time.time_ns())+'.json');write_json(path,result);failed.append(result)
                print('FAILED:',result['error'],flush=True)
            if len(completed)%24==0 or failed:print('COMPLETED:',len(completed),'/',len(jobs),'FAILED:',len(failed),flush=True)
    write_json(output/'RUN_STATUS.json',{'status':'COMPLETED' if len(completed)==len(jobs) else 'INCOMPLETE',
        'scheduled':len(jobs),'completed':len(completed),'failed':len(failed),'new_observations':sum(len(v['rows']) for v in completed.values())})
    if failed:raise ValueError('Task failures retained; inspect failures then resume')
    print('QAOA EXECUTION: PASS',flush=True)


def report(output,repo):
    plan,binding=verify(output,repo);jobs=read_json(output/'TASKS.json');by_study=defaultdict(list);replaced=defaultdict(set)
    for job in jobs:
        p=output/'task_results'/(job['task_id']+'.json')
        if sha(p)!=p.with_suffix('.sha256').read_text(encoding='utf-8').strip():raise ValueError('Result checkpoint changed')
        value=read_json(p)
        if value['status']!='PASS':raise ValueError('Incomplete execution')
        by_study[job['study']]+=value['rows'];replaced[job['study']].update(job['source_rows'])
    for row in read_csv(output/'REMOVED_POLICY_ROWS.csv'):
        replaced[row['study']].add(int(row['source_row']))
    all_warm=[];coverage=[];lineage=[]
    from run_review_postprocess import aggregate_qaoa,qaoa_summaries,audit_depth
    for study in STUDIES:
        sources=read_csv(output/'inputs'/f'{study}.csv');new=by_study[study]
        retained=[]
        for number,row in enumerate(sources,2):
            if number not in replaced[study]:
                lineage.append({'study':study,'source_row':number,'source_sha256':sha(output/'inputs'/f'{study}.csv'),
                    'source_design_id':row['design_id'],'source_task_id':row.get('task_id',''),'decision':'REUSE_UNCHANGED_DESIGN_ARCHIVE'})
                retained.append(dict(row,observation_origin='UNCHANGED_DESIGN_ARCHIVE'))
            else:lineage.append({'study':study,'source_row':number,'source_sha256':sha(output/'inputs'/f'{study}.csv'),
                'source_design_id':row['design_id'],'source_task_id':row.get('task_id',''),'decision':'REPLACED_BY_NEW_DESIGN_TASK_PLAN'})
        merged=retained+new
        keys=[row_key(row,study) for row in merged]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate output observation identity')
        write_csv(output/'results'/f'{study}_new_runs.csv',new)
        write_csv(output/'results'/f'{study}_merged_runs.csv',merged)
        if study.startswith('E4'):all_warm+=merged
        else:
            condition='noise_level' if study=='E6' else 'budget_key'
            instances=aggregate_qaoa(merged,condition);summary,paired=qaoa_summaries(instances,condition)
            write_csv(output/'analysis'/f'{study}_instance_means.csv',instances)
            write_csv(output/'analysis'/f'{study}_summary.csv',summary)
            for r in paired:
                if r['metric']=='optimum_hit_rate':r['wins'],r['losses']=r['losses'],r['wins']
                r['favorable_direction']='higher' if r['metric']=='optimum_hit_rate' else 'lower'
            write_csv(output/'analysis'/f'{study}_paired_vs_native.csv',paired)
            if study=='E6':audit_depth(merged,output/'analysis',sha(output/'results'/f'{study}_merged_runs.csv'))
        coverage.append({'study':study,'old_rows':len(sources),'replaced_old_rows':len(replaced[study]),'new_rows':len(new),'reused_rows':len(retained),'merged_rows':len(merged)})
    from postprocess_correction import aggregate
    draws,instances,paired,descriptive,summaries=aggregate(all_warm)
    for name,rows in [('warm_draw_means',draws),('warm_instance_policy_means',instances),('warm_paired_instance_differences',paired),('warm_descriptive_summary',descriptive),('warm_paired_summary',summaries)]:
        write_csv(output/'analysis'/f'{name}.csv',rows)
    primary=[r for r in summaries if r['scope']=='primary_selected_active_aux' and r['depth_stratum']=='all_scheduled' and r['metric']=='original_objective_mean']
    write_csv(output/'analysis/PRIMARY_WARMSTART_CONTRASTS.csv',primary)
    oldwarm=read_csv(output/'inputs/E4_corrected_original.csv')+read_csv(output/'inputs/E4_corrected_targeted.csv')
    *_,oldsummary=aggregate(oldwarm)
    key=lambda r:tuple(r[k] for k in ['scope','study','family','representation','budget_key','depth_stratum','contrast','metric'])
    oldindex={key(r):r for r in oldsummary}
    compare=[]
    for row in primary:
        old=oldindex.get(key(row));compare.append(dict(row,old_mean=old['mean'] if old else None,
            change_in_mean=row['mean']-old['mean'] if old else None,
            interpretation='lower_objective' if row['ci95_high'] is not None and row['ci95_high']<0 else 'higher_objective' if row['ci95_low'] is not None and row['ci95_low']>0 else 'unclear'))
    write_csv(output/'analysis/WARMSTART_BEFORE_AFTER.csv',compare)
    write_csv(output/'SOURCE_ROW_LINEAGE.csv',lineage);write_csv(output/'COVERAGE.csv',coverage)
    audit={'status':'QAOA_SELECTED_RERUN_COMPLETE','code_commit':binding['code_commit'],'source_tree_sha256':binding['source_tree_sha256'],
        'jobs_completed':len(jobs),'positive_depth_optimizations':plan['positive_depth_jobs'],'zero_depth_baseline_jobs':plan['zero_depth_jobs'],
        'new_observations':sum(len(v) for v in by_study.values()),'compiler_version':binding['environment']['packages']['qiskit'],
        'all_new_encodings_exact':True,'all_null_controls_passed':True,'new_parameter_replay_passed':True,
        'full_E6_measured_circuits_budget_checked':True,'new_E6_counts_archived':True,
        'unchanged_archive_reuse':'input-file SHA and unchanged design membership; old noisy trajectories not reexecuted',
        'old_source_files_overwritten':False,'new_instance_screening':False,'LP_resolved':False,'QAOA_advantage_required_for_pass':False,
        'coverage':coverage,'E2_E5_update_status':'PENDING_SEPARATE_RESOURCE_RERUN','latest_manuscript_source_merge':'WAITING_FOR_SOURCE_ZIP'}
    write_json(output/'EXECUTION_AUDIT.json',audit)
    file_manifest=[{'path':p.relative_to(output).as_posix(),'sha256':sha(p),'size_bytes':p.stat().st_size} for p in sorted(output.rglob('*'))
        if p.is_file() and p.name not in ['SHA256_MANIFEST.csv','SHA256_MANIFEST.sha256'] and '__pycache__' not in p.parts]
    write_csv(output/'SHA256_MANIFEST.csv',file_manifest);(output/'SHA256_MANIFEST.sha256').write_text(sha(output/'SHA256_MANIFEST.csv')+'\n',encoding='utf-8')
    print(json.dumps(audit,indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',choices=['prepare','run','report','all'],required=True)
    p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--selection',type=Path);p.add_argument('--correction-zip',type=Path)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();a.repo=a.repo.resolve();a.output=a.output.resolve()
    if not 1<=a.workers<=16:raise ValueError('Workers must be 1..16')
    for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[key]='1'
    if a.stage in ['prepare','all']:
        if a.selection is None or a.correction_zip is None:raise ValueError('Prepare requires --selection and --correction-zip')
        prepare(a.repo,a.selection.resolve(),a.correction_zip.resolve(),a.output)
    if a.stage in ['run','all']:run(a.output,a.repo,a.workers)
    if a.stage in ['report','all']:report(a.output,a.repo)
if __name__=='__main__':main()
