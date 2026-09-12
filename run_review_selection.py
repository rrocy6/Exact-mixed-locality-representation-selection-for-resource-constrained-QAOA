"""Re-evaluate repaired selector and sensitivity; frozen designs remain immutable."""
from __future__ import annotations
import argparse,csv,json,hashlib,os,statistics,time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import yaml
from urss_pipeline.e1_exactness import _canonical_polynomial
from urss_pipeline.fibre_selector import FibreSelectorError,design_id
from urss_pipeline.four_part_addendum import load_fibre_moments,selector_ablation_variants,_selector_variant
from urss_pipeline.review_search import beam_select_fibre_design


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=sorted({k for r in rows for k in r}));w.writeheader();w.writerows(rows)
def task(job):
    root=Path(job['root']);selector=job['selector'];rec=job['record'];tier=job['tier'];variant=job['variant']
    _,poly=_canonical_polynomial(root/'data/canonical'/f"{rec['instance_id']}.json")
    moments=load_fibre_moments(root/'fibre_selector_v2/sa_rlt_moments_v2.json',tier=tier)[rec['instance_id']]
    base=dict(tier=tier,variant_id=variant,instance_id=rec['instance_id'],family=rec['family'],
        historical_design_id=rec['selected']['design_id'],historical_actions_json=json.dumps(rec['selected']['actions'],separators=(',',':')),
        selector_parameters_json=json.dumps(selector,sort_keys=True,separators=(',',':')))
    started=time.perf_counter()
    try:
        result=beam_select_fibre_design(poly,n_original=rec['n_original'],selector=selector,moments=moments,apply_qaoa_hard_limits=tier!='compilation')
        actions=[list(a) if a else None for a in result.actions]
        return dict(base,status='pass',new_design_id=design_id(result.actions),new_actions_json=json.dumps(actions,separators=(',',':')),
            changed_from_frozen=actions!=rec['selected']['actions'],resource_score=float(result.evaluation.score),
            normalised_raw_fibre_excess=result.risk.normalised_excess,n_aux=result.evaluation.representation.n_auxiliary,
            two_qubit_gates=result.evaluation.reference.two_qubit_gate_count,two_qubit_depth=result.evaluation.reference.two_qubit_depth,
            candidate_evaluations=result.candidate_evaluations,runtime_sec=time.perf_counter()-started)
    except FibreSelectorError as e:return dict(base,status='heuristic_no_feasible_incumbent',error=str(e),runtime_sec=time.perf_counter()-started)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=min(4,os.cpu_count() or 1));p.add_argument('--scope',choices=['main','sensitivity','all'],default='all')
    a=p.parse_args();root=Path(__file__).resolve().parent;out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    checkpoints=out/'selection_checkpoints';checkpoints.mkdir(exist_ok=True)
    cfg=yaml.safe_load((root/'configs/experiment_config_v2.yaml').read_text());base=cfg['selector']
    signature=hashlib.sha256(''.join(sha(root/f) for f in ['urss_pipeline/review_search.py','urss_pipeline/fibre_selector.py','urss_pipeline/four_part_addendum.py','configs/experiment_config_v2.yaml']).encode()).hexdigest()
    jobs=[];inputs=[]
    for tier in ['oracle','qaoa','compilation']:
        source=root/f'fibre_selector_v2/{tier}_representation_designs_v2.json';inputs.append(source)
        records=json.loads(source.read_text())['records']
        for rec in records:
            if a.scope in ['all','main']:jobs.append(dict(root=str(root),selector=base,record=rec,tier=tier,variant='main'))
            if tier=='oracle' and a.scope in ['all','sensitivity']:
                variants=selector_ablation_variants(json.loads((root/'configs/four_part_addendum_v1.json').read_text()))
                for var in variants:
                    if var['variant_id']=='main' and a.scope=='all':continue
                    selector=_selector_variant(base,{'weights':var['weights'],'search_settings.beam_width':var['beam_width'],
                        'fibre_risk.threshold_tau':var['fibre_threshold'],'fibre_risk.positive_penalty_margin':var['penalty_margin']})
                    jobs.append(dict(root=str(root),selector=selector,record=rec,tier=tier,variant=var['variant_id']))
    rows=[];pending=[]
    for job in jobs:
        f=checkpoints/(job['tier']+'_'+job['record']['instance_id']+'_'+job['variant']+'.json')
        if f.exists():
            record=json.loads(f.read_text())
            if record.get('implementation_sha256')!=signature:raise ValueError('Checkpoint code differs; use a new output directory')
            rows.append(record)
        else:pending.append((job,f))
    print(f'SELECTION: {len(jobs)} scheduled; {len(rows)} existing checkpoints; {a.workers} workers',flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        futures={pool.submit(task,j):f for j,f in pending}
        for future in as_completed(futures):
            row=future.result();row['implementation_sha256']=signature;f=futures[future]
            f.write_text(json.dumps(row,indent=2)+'\n');rows.append(row)
            if len(rows)%25==0 or len(rows)==len(jobs):print(f'SELECTION: {len(rows)}/{len(jobs)} complete',flush=True)
    rows.sort(key=lambda r:(r['tier'],r['instance_id'],r['variant_id']))
    write_csv(out/'selector_repair_all.csv',rows)
    main=[r for r in rows if r['variant_id']=='main'];write_csv(out/'selector_repair_main.csv',main)
    oracle_old=list(csv.DictReader((root/'fibre_selector_v2/oracle_selector_validation_v2.csv').open()))
    optima={r['instance_id']:float(r['certified_optimum_objective']) for r in oracle_old if r['method']=='full_space_optimum'}
    for r in main:
        if r['tier']=='oracle' and r['status']=='pass':r['regret_to_frozen_optimum']=r['resource_score']-optima[r['instance_id']]
    write_csv(out/'oracle_repaired_validation.csv',[r for r in main if r['tier']=='oracle'])
    old=list(csv.DictReader((root/'four_part_addendum_v1/selector_ablation/selector_ablation_raw.csv').open()))
    oldmap={(r['instance_id'],r['variant_id']):r for r in old}
    sensitivity=[]
    for r in rows:
        if r['tier']!='oracle':continue
        prev=oldmap.get((r['instance_id'],r['variant_id']))
        if prev is None:continue
        item={**r,'previous_variant_status':prev['status']}
        if r['status']=='pass' and prev['status']=='pass':
            item.update(changed_from_previous_variant=json.loads(r['new_actions_json'])!=json.loads(prev['actions_json']),
                score_change_from_previous_variant=r['resource_score']-float(prev['resource_score']))
        sensitivity.append(item)
    write_csv(out/'sensitivity_repaired.csv',sensitivity)
    summary=[]
    for variant in sorted({r['variant_id'] for r in sensitivity}):
        for family in ['cubic_spin_glass','max3sat']:
            group=[r for r in sensitivity if r['variant_id']==variant and r['family']==family];ok=[r for r in group if r['status']=='pass']
            summary.append(dict(variant_id=variant,family=family,n=len(group),passing=len(ok),changed=sum(r.get('changed_from_previous_variant',False) for r in group),
                mean_score=statistics.fmean(r['resource_score'] for r in ok) if ok else ''))
    write_csv(out/'sensitivity_repaired_summary.csv',summary)
    impacts=[]
    for r in main:
        if r['status']!='pass' or not r['changed_from_frozen']:continue
        impacts.append({k:r[k] for k in ['tier','instance_id','family','historical_design_id','new_design_id','historical_actions_json','new_actions_json']}|
            {'action_required':{'oracle':'update_selector_validation_only','compilation':'recompile_selected_and_regenerate_aux_count_matched_random_then_E2_E5','qaoa':'join_actual_E3_E4_E6_task_ids_before_selected_and_matched_random_reruns'}[r['tier']]})
    write_csv(out/'DOWNSTREAM_DESIGN_CHANGES.csv',impacts)
    audit=dict(status='COMPLETED',scheduled=len(jobs),completed=len(rows),failed=sum(r['status']!='pass' for r in rows),
        main_changes={t:sum(r['tier']==t and r.get('changed_from_frozen',False) for r in main) for t in ['oracle','qaoa','compilation']},
        oracle_zero_regret=sum(abs(r.get('regret_to_frozen_optimum',1))<1e-10 for r in main if r['tier']=='oracle'),
        historical_input_files_overwritten=False,qaoa_runs_executed=0,implementation_sha256=signature)
    (out/'SELECTION_REPAIR_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(audit),flush=True)
if __name__=='__main__':main()
