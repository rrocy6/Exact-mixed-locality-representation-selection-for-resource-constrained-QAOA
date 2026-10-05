"""Read-only recheck of saved acceptance, historical preservation and replay."""
import ast
import csv
import json
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import multiseed_experiment as m

def csvrows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
    root=m.ROOT;session=m.read_json(root/'P1_PACKAGING_SESSION.json');out=root/session['coverage_dir'];cor=root/'corrections/review_v2_20260920'
    old=root/'results/multiseed_20260918T163717Z';final=cor/'final_analysis'
    cfg,_,candidates,tasks=m.load_run(final);compiled=csvrows(final/'compilation_rows.csv')
    audit=m.validate_rows(tasks,compiled,candidates,final)
    raw=m.load_raw_rows(final,cfg);m.validate_rows(tasks,raw,candidates,final)
    assert {m.natural_key(r):{k:str(v) for k,v in r.items()} for r in raw}=={m.natural_key(r):r for r in compiled}
    state=m.read_json(final/'ANALYSIS_STATE.json')
    for relative,sha in state['artifact_hashes'].items():assert m.sha256_file(final/relative)==sha,relative
    assert state['compilation_sha256']==m.sha256_file(final/'compilation_rows.csv')==m.sha256_file(old/'compilation_rows.csv')
    previous=out/'prior_source/scripts'
    def functions(path):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    before=functions(previous/'multiseed_experiment.py');after=functions(root/'scripts/multiseed_experiment.py')
    scientific_names=['analyse','classify_layer','candidate_states','feasible_slice','pooled_layer','frontier_ids','generate_figures']
    unchanged=all(before[n]==after[n] for n in scientific_names)
    unchanged &= all(m.sha256_file(previous/n)==m.sha256_file(root/'scripts'/n) for n in ('multiseed_validation.py','verify_multiseed_correction.py'))
    assert unchanged,'Numerical implementation changed; independent reconstruction must be rerun'
    bindings=csvrows(cor/'REPAIR_MANIFEST.csv');bound={r['path']:r['sha256'] for r in bindings}
    independent=cor/'evidence/correction_verification.json'
    assert bound[independent.relative_to(root).as_posix()]==m.sha256_file(independent)
    numerical=m.read_json(independent);assert numerical['status']=='pass' and not numerical['differences']
    historical=[];changed=[]
    for record in csvrows(root/'BASE_FILE_MANIFEST.csv'):
        if record['path'].startswith(('results/','audit/','configs/','evidence/')):
            historical.append(record['path'])
            if m.sha256_file(root/record['path'])!=record['sha256']:changed.append(record['path'])
    assert not changed,changed
    replay=cor/'replay';plan=m.read_json(replay/'REPLAY_PLAN.json');replay_rows=[]
    for path in sorted(replay.glob('attempt_*.json')):replay_rows.extend(m.read_json(path)['rows'])
    original={m.natural_key(r):r for r in csvrows(old/'compilation_rows.csv')}
    selected=set(plan['selected_candidates']);observed=set();trace_count=semantic_count=0
    for r in replay_rows:
        assert r['candidate_id'] in selected and r['status']=='compiled'
        observed.add((r['candidate_id'],int(r['seed']),r['attempt_id']))
        trace=json.loads(r['trace_json']);assert trace['observed_passes']
        assert trace['semantic']['status']=='pass' and max(trace['semantic']['max_errors'])<1e-9
        assert all(s==trace['declared'] for s in trace['observed_sabre'])
        oldr=json.loads(original[m.natural_key(r)]['resources_json']);v=json.loads(r['resources_json'])
        assert all(abs(oldr[d]-v[d])<1e-12 for d in ('Q','G','D','M','J'))
        trace_count+=1;semantic_count+=1
    assert observed=={(cid,seed,attempt) for cid in selected for seed,attempt in ((1729,'repeat_a'),(1729,'repeat_b'),(2718,'seed_2718'))}
    old_env=m.read_json(old/'environment.json')['packages'];rep_env=m.read_json(replay/'environment.json')['packages']
    assert all(old_env[n]==rep_env[n] for n in ('qiskit','numpy','scipy'))
    replay_summary={'records':len(replay_rows),'distinct_candidates':len(selected),'callbacks':trace_count,'finite_semantic_checks':semantic_count,
        'matching_historical_packages':True,'resource_differences':0,'historical_compiler_hash':plan['compiler_identity'],
        'current_compiler_hash':m.compiler_identity(old),'reuse_scope':'historical bounded replay evidence; not reused as observations for new full P1'}
    result={'status':'pass','saved_compilation_audit':audit,'analysis_artifacts_bound':True,
        'independent_numerical_evidence':{'reused':True,'source':independent.relative_to(root).as_posix(),'sha256':m.sha256_file(independent),
        'numerical_functions_unchanged':scientific_names,'baseline':numerical['baseline'],'common':numerical['common'],'retention':numerical['retention']},
        'historical_files_checked':len(historical),'historical_changed':changed,'replay_recheck':replay_summary,
        'original_fix_report_sha256':m.sha256_file(root/'FIX_REPORT.md')}
    m.atomic_json(out/'ACCEPTANCE_RECHECK.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
