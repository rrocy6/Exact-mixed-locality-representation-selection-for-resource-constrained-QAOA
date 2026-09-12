"""Read-only, independent consistency checks for an executed selected-rerun bundle."""
import argparse,csv,json,hashlib,math
from pathlib import Path
from collections import Counter


def read_csv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(root):
    manifest=root/'SHA256_MANIFEST.csv'
    if manifest.exists():
        if digest(manifest)!=(root/'SHA256_MANIFEST.sha256').read_text(encoding='utf-8').strip():raise ValueError('Manifest digest mismatch')
        entries=read_csv(manifest)
        if len({r['path'] for r in entries})!=len(entries):raise ValueError('Duplicate manifest path')
        for item in entries:
            path=(root/item['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('Missing or unsafe artifact path')
            if digest(path)!=item['sha256'] or path.stat().st_size!=int(item['size_bytes']):raise ValueError('Artifact changed: '+item['path'])
    plan=json.loads((root/'PLAN.json').read_text(encoding='utf-8'))
    for name,value in plan['frozen_files'].items():
        if digest(root/name)!=value:raise ValueError('Frozen input mismatch: '+name)
    jobs=json.loads((root/'TASKS.json').read_text(encoding='utf-8'))
    if len({j['task_id'] for j in jobs})!=len(jobs):raise ValueError('Duplicate planned job')
    count=0;optimizer_calls=0;shots=0;rows=[];outcomes=Counter()
    for job in jobs:
        p=root/'task_results'/(job['task_id']+'.json')
        if digest(p)!=p.with_suffix('.sha256').read_text(encoding='utf-8').strip():raise ValueError('Result digest mismatch')
        result=json.loads(p.read_text(encoding='utf-8'))
        if result['status']!='PASS' or result['task_id']!=job['task_id']:raise ValueError('Checkpoint status/identity mismatch')
        traces=result['optimizer_trace']
        if len(traces)!=61 or sum(t['role']=='optimizer_objective_call' for t in traces)!=60:raise ValueError('Optimizer trace accounting')
        if result['independent_parameter_replay_max_error']>1e-10:raise ValueError('Parameter replay failure')
        for row in result['rows']:
            if len(json.loads(row['optimized_parameters_json']))!=2*int(row['p']):raise ValueError('Parameter width')
            if row['design_id']==row['source_design_id']:raise ValueError('New row reuses old design identity')
            if row['status']!='pass':raise ValueError('Non-passing observation')
            count+=1;rows.append(row);outcomes[job['study']]+=1
        if job['study']=='E6':
            if len(result['rows'])!=3:raise ValueError('Noise-level coverage')
            group=result['rows']
            if len({(r['p'],r['optimized_parameters_sha256'],r['transpiler_seed'],r['measurement_seed']) for r in group})!=1:raise ValueError('Noise pairing changed')
            base=next(r for r in group if r['noise_level']=='noiseless')
            for r,artifact in zip(group,result['noise_artifacts']):
                if r['noise_level']!=artifact['noise_level']:raise ValueError('Counts level mismatch')
                if int(r['actual_2q_gates'])>int(r['compiled_2q_budget']):raise ValueError('Full E6 gate budget exceeded')
                if sum(artifact['counts'].values())!=4096:raise ValueError('Shot accounting')
                if abs(float(r['original_objective_mean'])-float(base['original_objective_mean'])-float(r['paired_degradation_vs_noiseless']))>1e-10:raise ValueError('Noise degradation mismatch')
                shots+=sum(artifact['counts'].values())
        optimizer_calls+=60
    if count!=plan['expected_observations']:raise ValueError('Observation coverage mismatch')
    if len({r['task_id'] for r in rows})!=len(rows):raise ValueError('Duplicate new observation')
    a=read_csv(root/'results/E3_new_runs.csv');b=read_csv(root/'results/E4_corrected_original_new_runs.csv')
    key=lambda r:tuple(r[k] for k in ['instance_id','representation','random_rep_seed','budget_key','restart_id'])
    lookup={key(r):r for r in a};maximum=0.;paired=0
    for r in b:
        if r['warm_start_policy']!='cold_start':continue
        old=lookup[key(r)]
        for field in ['design_id','initial_parameters_sha256','initialization_seed','p']:
            if old[field]!=r[field]:raise ValueError('E3/E4 cold-start identity mismatch: '+field)
        for field in ['original_objective_mean','encoded_energy_mean','optimum_hit_rate','auxiliary_inconsistency_rate']:
            error=abs(float(old[field])-float(r[field]));maximum=max(maximum,error)
            if error>1e-10:raise ValueError('E3/E4 cold-start score mismatch')
        paired+=1
    for item in read_csv(root/'COVERAGE.csv'):
        study=item['study'];source=read_csv(root/'inputs'/f'{study}.csv');merged=read_csv(root/'results'/f'{study}_merged_runs.csv')
        origin=Counter(r['observation_origin'] for r in merged)
        if origin['NEW_DESIGN_RERUN']!=int(item['new_rows']) or origin['UNCHANGED_DESIGN_ARCHIVE']!=int(item['reused_rows']):raise ValueError('Reuse accounting mismatch')
        bykey={tuple(r.get(k,'') for k in ['instance_id','representation','random_rep_seed','budget_key','restart_id','warm_start_policy','pair_closure','noise_level']):r for r in source}
        for row in merged:
            if row['observation_origin']!='UNCHANGED_DESIGN_ARCHIVE':continue
            old=bykey[tuple(row.get(k,'') for k in ['instance_id','representation','random_rep_seed','budget_key','restart_id','warm_start_policy','pair_closure','noise_level'])]
            for k,v in old.items():
                if row[k]!=v:raise ValueError('Historical field was altered: '+study+' '+k)
    return {'status':'PASS','jobs':len(jobs),'new_observations':count,'new_rows_by_study':dict(outcomes),
            'objective_calls':optimizer_calls,'final_statevector_metric_calls':len(jobs),'E6_shots':shots,
            'E3_E4_cold_pairs':paired,'E3_E4_cold_max_difference':maximum,
            'unchanged_archive_field_values_preserved':True,'all_checkpoint_hashes_valid':True}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(verify(a.output.resolve()),indent=2))
