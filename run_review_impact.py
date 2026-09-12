"""Join actual archived rows to changed selected/random designs; no QAOA reruns."""
from __future__ import annotations
import argparse,csv,io,json,zipfile,hashlib
from pathlib import Path
from fractions import Fraction
import yaml
from urss_pipeline.fibre_selector import FibreMoments,matched_random_fibre_designs,design_id
from urss_pipeline.review_search import beam_select_fibre_design
from urss_pipeline.e1_exactness import _canonical_polynomial
from run_review_postprocess import read_csv,write_csv,write_json,sha


def actions(v):return tuple(tuple(a) if a else None for a in v)
def payload(v):return [list(a) if a else None for a in v]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--selection',type=Path,required=True);p.add_argument('--correction-zip',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent;out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    cfg=yaml.safe_load((root/'configs/experiment_config_v2.yaml').read_text());controls=cfg['representations']['matched_random'];selector=cfg['selector']
    if sha(a.correction_zip)!='9e539a0aa387393e482e5ac0f186ace9695af39d05017fe3bc90eefefe5dd5e5':raise ValueError('Original correction archive hash differs')
    changed=[r for r in read_csv(a.selection/'selector_repair_main.csv') if r.get('changed_from_frozen')=='True']
    designs=[]
    for tier in ['oracle','qaoa','compilation']:
        old={r['instance_id']:r for r in json.loads((root/f'fibre_selector_v2/{tier}_representation_designs_v2.json').read_text())['records']}
        for row in changed:
            if row['tier']!=tier:continue
            iid=row['instance_id'];rec=old[iid];_,poly=_canonical_polynomial(root/'data/canonical'/f'{iid}.json')
            new=actions(json.loads(row['new_actions_json']))
            designs.append(dict(tier=tier,instance_id=iid,representation='selective',random_rep_seed='',old_actions=rec['selected']['actions'],new_actions=payload(new),new_design_id=design_id(new)))
            kwargs=dict(instance_id=iid,seed_bundle=controls['seed_bundle'],maximum_pair_set_attempts=controls['maximum_pair_set_attempts'])
            original=dict(matched_random_fibre_designs(poly,selected_actions=actions(rec['selected']['actions']),**kwargs))
            old_controls={int(r['random_rep_seed']):actions(r['actions']) for r in rec['matched_random']}
            if original!=old_controls:raise ValueError('Cannot reproduce frozen control construction: '+iid)
            new_controls=dict(matched_random_fibre_designs(poly,selected_actions=new,**kwargs))
            for seed,value in new_controls.items():
                if value!=old_controls[seed]:designs.append(dict(tier=tier,instance_id=iid,representation='matched_random_selective',random_rep_seed=str(seed),
                    old_actions=payload(old_controls[seed]),new_actions=payload(value),new_design_id=design_id(value)))
    target_results=[];raw_studies={}
    with zipfile.ZipFile(a.correction_zip) as z:
        for name in z.namelist():
            if '/exec_20260912_v2/' in name and name.endswith('/corrected_runs.csv'):
                raw_studies['E4_corrected_targeted' if '/targeted/' in name else 'E4_corrected_original']=(name,list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig')))),hashlib.sha256(z.read(name)).hexdigest())
            if '/exec_20260912_v2/frozen_designs/' not in name or not name.endswith('.json'):continue
            rec=json.loads(z.read(name))
            if rec['study']!='targeted':continue
            m=rec['moments'];moment=FibreMoments(float(m['objective']),{int(i):float(v) for i,v in m['singles'].items()},
                {tuple(r['pair']):float(r['value']) for r in m['pairs']},m['status'],'archived_targeted_vector',0,0,hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest())
            poly={tuple(t['support']):Fraction(t['coefficient']) for t in rec['original_terms']}
            result=beam_select_fibre_design(poly,n_original=rec['n_original'],selector=selector,moments=moment,apply_qaoa_hard_limits=True)
            different=result.actions!=actions(rec['actions'])
            target_results.append(dict(instance_id=rec['instance_id'],family=rec['family'],changed=different,old_actions_json=json.dumps(rec['actions']),
                new_actions_json=json.dumps(payload(result.actions)),new_score=float(result.evaluation.score),new_n_aux=result.evaluation.representation.n_auxiliary,
                source_member=name,source_member_sha256=hashlib.sha256(z.read(name)).hexdigest(),lp_resolved=False))
            if different:designs.append(dict(tier='targeted',instance_id=rec['instance_id'],representation='selective',random_rep_seed='',old_actions=rec['actions'],new_actions=payload(result.actions),new_design_id=design_id(result.actions)))
    if len(target_results)!=20:raise ValueError('Expected 20 archived targeted designs')
    write_csv(out/'targeted_selector_repair.csv',target_results)
    write_json(out/'CHANGED_DESIGNS_AND_CONTROLS.json',dict(records=designs,frozen_instances_preserved=True,changed_designs_executed=False))
    index={(r['tier'],r['instance_id'],r['representation'],str(r['random_rep_seed'])):r for r in designs}
    sources={}
    for study,file,tier in [('E2','e2_compiled_resources_by_seed.csv','compilation'),('E3','e3_qaoa_runs.csv','qaoa'),('E6','e6_noise_runs.csv','qaoa')]:
        path=root/'fibre_e1_e6_v2/results'/file;sources[study]=(str(path.relative_to(root)),read_csv(path),sha(path),tier)
    added=root/'four_part_addendum_v1/topologies/additional_topology_compiled_by_seed.csv'
    sources['E2_added_topologies']=(str(added.relative_to(root)),read_csv(added),sha(added),'compilation')
    for study,(name,rows,digest) in raw_studies.items():sources[study]=(name,rows,digest,'targeted' if study.endswith('targeted') else 'qaoa')
    affected=[];summary=[]
    for study,(source,rows,digest,tier) in sources.items():
        current=[]
        for number,r in enumerate(rows,2):
            key=(tier,r['instance_id'],r['representation'],r['random_rep_seed'])
            change=index.get(key)
            if change is None:continue
            item=dict(study=study,source=source,source_sha256=digest,source_csv_row=number,
                instance_id=r['instance_id'],representation=r['representation'],random_rep_seed=r['random_rep_seed'],
                old_design_id=r['design_id'],new_design_id=change['new_design_id'],
                old_task_id=r.get('task_id',''),old_p=r.get('p',''),noise_level=r.get('noise_level',''),
                restart_id=r.get('restart_id',''),budget_key=r.get('budget_key',''),warm_start_policy=r.get('warm_start_policy',''),
                pair_closure=r.get('pair_closure',''),topology_id=r.get('topology_id',''),transpiler_seed=r.get('transpiler_seed',''),
                action='Rebuild the changed design task plan and recompute; archived observation is not transferable to a new Hamiltonian.')
            current.append(item)
        affected+=current;summary.append(dict(study=study,source_rows=len(rows),affected_old_rows=len(current),
            affected_instances=len({r['instance_id'] for r in current}),affected_design_draws=len({(r['instance_id'],r['representation'],r['random_rep_seed']) for r in current})))
    write_csv(out/'SELECTED_RERUN_REQUIRED.csv',affected);write_csv(out/'DOWNSTREAM_IMPACT_SUMMARY.csv',summary)
    audit=dict(status='IMPACT_PLAN_READY_NOT_EXECUTED',changed_design_draws=len(designs),targeted_designs_checked=20,
        targeted_designs_changed=sum(r['changed'] for r in target_results),screening_instances_reselected=False,lp_resolved=False,
        original_archives_modified=False,new_qaoa_runs=0,downstream=summary,
        interpretation='Counts identify obsolete archived rows, not the final size of new task plans; depth/capacity and warm-policy counts can change.')
    write_json(out/'IMPACT_AUDIT.json',audit);print(json.dumps(audit,indent=2),flush=True)
if __name__=='__main__':main()
