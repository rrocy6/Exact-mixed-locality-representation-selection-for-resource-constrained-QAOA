"""Independent frozen-manifest P1 oracle. No production task generator imports."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

REPEATS = ((1729, 'repeat_a'), (1729, 'repeat_b'), (2718, 'single'))
def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def key(r):
    repetition=r.get('repetition',r.get('repeat',''))
    if repetition=='seed_2718': repetition='single'
    return (r['instance_id'],r['candidate_id'],r['topology'],r['synthesis'],int(r['seed']),repetition)

def expected_from_frozen(source):
    cfg=read(source/'experiment_config.json'); samples=rows(source/'instance_manifest.csv'); candidates=rows(source/'candidate_manifest.csv')
    assert digest({k:v for k,v in cfg.items() if k!='config_hash'})==cfg['config_hash'], 'Frozen config hash'
    families=defaultdict(list)
    for r in samples:
        calculated=hashlib.sha256(('URSS_MULTISEED_V1|'+r['family_label']+'|'+r['instance_id']).encode()).hexdigest()
        assert calculated==r['selection_hash'], 'Selection hash mismatch'
        if r['selected'].lower()=='true': families[r['family']].append(r)
    first={f:min(rs,key=lambda r:(r['selection_hash'],r['instance_id'])) for f,rs in families.items()}
    ids={r['instance_id']:r for r in first.values()}
    chosen=[c for c in candidates if c['instance_id'] in ids]
    assert chosen and len({(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis']) for c in chosen})==len(chosen)
    for c in chosen:
        sample=ids[c['instance_id']]
        path=source/'inputs/experiments/compiled_results/instances'/f"{c['instance_id']}.json"
        assert sha(path)==sample['source_sha256'], 'Instance snapshot mismatch'
        expected=digest({'instance_sha256':sample['source_sha256'],'candidate_id':c['candidate_id'],
                         'actions':tuple(int(a) for a in c['actions'].split(',') if a), 'topology':c['topology'],'synthesis':c['synthesis']})
        assert expected==c['input_hash'], 'Candidate input hash mismatch'
    present={(c['instance_id'],c['topology'],c['synthesis']) for c in chosen}
    assert present==set(itertools.product(ids,cfg['topologies'],cfg['synthesis'])), 'Missing frozen setting'
    expected={(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis'],s,r) for c in chosen for s,r in REPEATS}
    return cfg,first,chosen,expected

def compare(expected, observed):
    counts=Counter(key(r) for r in observed)
    missing=sorted(expected-counts.keys()); extra=sorted(counts.keys()-expected)
    duplicate=[{'key':k,'count':v} for k,v in sorted(counts.items()) if v>1]
    groups=defaultdict(lambda:Counter())
    for k in expected:groups[(k[0],k[2],k[3],k[4],k[5])]['expected']+=1
    for k,n in counts.items():
        g=groups[(k[0],k[2],k[3],k[4],k[5])];g['actual']+=n;g['duplicate']+=max(0,n-1)
        if k not in expected:g['extra']+=n
    for k in missing:groups[(k[0],k[2],k[3],k[4],k[5])]['missing']+=1
    for r in observed:
        if r['status'] not in {'compiled','width_exceeded'}:
            k=key(r);groups[(k[0],k[2],k[3],k[4],k[5])]['failed']+=1
    summaries=[dict(zip(('instance_id','topology','synthesis','seed','repetition'),g),**{n:c[n] for n in ('expected','actual','missing','duplicate','extra','failed')}) for g,c in sorted(groups.items())]
    return {'expected_count':len(expected),'actual_count':len(observed),'missing_count':len(missing),
            'duplicate_count':sum(x['count']-1 for x in duplicate),'extra_count':sum(counts[k] for k in extra),
            'failed_count':sum(r['status'] not in {'compiled','width_exceeded'} for r in observed),
            'missing_keys':missing,'extra_keys':extra,'duplicate_keys':duplicate},summaries

def verify(source,run,strict=False):
    cfg,first,candidates,expected=expected_from_frozen(source)
    observed=rows(run/'p1_repetition_rows.csv'); report,summary=compare(expected,observed)
    lookup={c['candidate_id']:c for c in candidates}; errors=[]
    local=read(run/'experiment_config.json'); local_report=read(run/'P1_REPORT.json')
    if digest({k:v for k,v in local.items() if k!='config_hash'})!=local['config_hash']:errors.append('run config digest')
    local_candidates={c['candidate_id']:c for c in rows(run/'candidate_manifest.csv')}
    if any(local_candidates.get(cid)!=c for cid,c in lookup.items()):errors.append('frozen candidate provenance')
    for c in candidates:
        relative=Path('inputs/experiments/compiled_results/instances')/(c['instance_id']+'.json')
        if sha(run/relative)!=sha(source/relative):errors.append('input snapshot differs')
    index={key(r):r for r in observed}; ids=[]; semantic=0; callback=0; failures=[]
    for r in observed:
        c=lookup.get(r['candidate_id'])
        if c is None: continue
        try:
            if r['status']=='width_exceeded':assert int(c['logical_Q'])>12
            elif r['status']=='compiled':
                v=json.loads(r['resources_json'])
                assert all(isinstance(v[d],(int,float)) and not isinstance(v[d],bool) and math.isfinite(v[d]) and v[d]>=0 for d in ('Q','G','D','M'))
                assert all(int(v[d])==v[d] for d in ('Q','G','D')) and int(c['logical_Q'])<=v['Q']<=12
                assert v['M']==float(c['maximum_penalty'])
                assert abs(v['J']-(int(c['n_aux'])/4+v['G']/160+v['D']/120+v['M']/8)/4)<1e-12
                trace=json.loads(r.get('trace_json','{}'))
                if trace.get('observed_passes'):
                    callback+=1
                    assert not set(trace['observed_passes']) & {'SabreLayout','VF2Layout','VF2PostLayout'}
                    for actual in trace['observed_sabre']:assert actual=={'seed':int(r['seed']),'trials':local['compiler']['sabre_trials'],'heuristic':'decay'}
                elif strict: raise AssertionError('actual callback missing')
                if trace.get('semantic',{}).get('status')=='pass':semantic+=1
            if strict:
                assert r['input_hash']==c['input_hash'] and r['config_hash']==local['config_hash']
                assert r['compiler_hash']==local['compiler_implementation_hash']
                assert r['observation_id'] and r['worker_pid'] and r['worker_started_utc']
                ids.append(r['observation_id'])
        except (AssertionError,KeyError,ValueError,TypeError) as exc:failures.append({'key':key(r),'error':str(exc)})
    mismatches=[]
    for c in candidates:
        prefix=(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis'])
        a=index.get(prefix+(1729,'repeat_a'));b=index.get(prefix+(1729,'repeat_b'))
        if a and b and (a['status']!=b['status'] or json.loads(a['resources_json'] or '{}')!=json.loads(b['resources_json'] or '{}')):mismatches.append(prefix)
    if strict:
        if len(ids)!=len(set(ids)):errors.append('observations reused across tasks/repetitions')
        if local_report.get('scope')!='full' or not local_report.get('formal_gate_eligible'):errors.append('representative report cannot satisfy full gate')
        identity=local_report.get('identity',{})
        if identity.get('config_hash')!=local['config_hash'] or identity.get('compiler_hash')!=local['compiler_implementation_hash'] or identity.get('inputs_manifest_hash')!=sha(run/'INPUT_COPY_MANIFEST.json'):errors.append('P1 identity mismatch')
        if local_report.get('rows_sha256')!=sha(run/'p1_repetition_rows.csv'):errors.append('result row digest')
        env=read(run/'p1_environment.json')
        if env['packages']['qiskit']!=cfg['compiler']['qiskit_version_from_freeze']:errors.append('environment Qiskit version')
    classification_checks=[]
    if strict and not any(report[k] for k in ('missing_count','duplicate_count','extra_count','failed_count')) and not failures:
        import numpy as np
        budget=np.array(list(itertools.product(*(cfg['budget_grid'][d] for d in ('Q','G','D','M')))),float)
        settings=defaultdict(list)
        for c in candidates:settings[(c['instance_id'],c['topology'],c['synthesis'])].append(c)
        declared_checks={(r['instance_id'],r['topology'],r['synthesis']):r for r in local_report['budget_classification_checks']}
        for setting,cs in settings.items():
            arrays=[]
            for repetition in ('repeat_a','repeat_b'):
                mixed=np.zeros(len(budget),bool);other=mixed.copy()
                for c in cs:
                    k=(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis'],1729,repetition)
                    r=index[k]
                    if r['status']=='width_exceeded':continue
                    v=json.loads(r['resources_json'])
                    feasible=np.logical_and.reduce([v[d]<=budget[:,i]+(1e-9 if d=='M' else 0) for i,d in enumerate(('Q','G','D','M'))])
                    if c['category']=='strict_mixed':mixed|=feasible
                    else:other|=feasible
                arrays.append((mixed & ~other).astype(np.uint8))
            mismatch=int(np.count_nonzero(arrays[0]!=arrays[1]))
            actual_hash=hashlib.sha256(arrays[0].tobytes()).hexdigest()
            if mismatch or declared_checks[setting]['classification_sha256']!=actual_hash:errors.append('Independent classification mismatch: '+str(setting))
            classification_checks.append({'setting':setting,'mismatch_cells':mismatch,'classification_sha256':actual_hash})
        plan=rows(run/'P1_TASK_MANIFEST.csv')
        plan_comparison,_=compare(expected,[dict(r,status='compiled') for r in plan])
        if any(plan_comparison[k] for k in ('missing_count','duplicate_count','extra_count')):errors.append('Plan does not equal independent expectation')
        semantic_groups=defaultdict(list)
        for c in candidates:semantic_groups[(c['family'],c['topology'],c['synthesis'],c['category'])].append(c)
        semantic_ids={min(cs,key=lambda c:(int(c['logical_Q']),c['candidate_id']))['candidate_id'] for cs in semantic_groups.values()}
        for r in observed:
            wanted=r['candidate_id'] in semantic_ids and r['status']=='compiled'
            checked=json.loads(r.get('trace_json') or '{}').get('semantic',{}).get('status')=='pass'
            if wanted!=checked:errors.append('Finite semantic sample differs from predeclared rule')
    report['independent_budget_classification_checks']=classification_checks
    report.update(status='pass'  if not any(report[k] for k in ('missing_count','duplicate_count','extra_count','failed_count')) and not errors and not failures and not mismatches else 'fail',
        first_instance_by_family={f:r['instance_id'] for f,r in first.items()},distinct_frozen_candidates=len(candidates),
        valid_observed_count=len(observed)-len(failures)-report['failed_count'],resource_or_provenance_errors=failures,identity_errors=errors,
        repeat_resource_mismatches=mismatches,observed_callback_rows=callback,finite_semantic_rows=semantic,
        independent_observation_ids=len(set(ids)),source_config_hash=cfg['config_hash'],run_config_hash=local['config_hash'],
        expectation_source='original frozen instance hash order + complete candidate manifest; no production generator',
        source_hashes={n:sha(source/n) for n in ('instance_manifest.csv','candidate_manifest.csv','experiment_config.json')})
    return report,summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--csv',type=Path,required=True);p.add_argument('--strict',action='store_true')
    a=p.parse_args();report,summary=verify(a.source,a.run,a.strict)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    with a.csv.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summary[0]));w.writeheader();w.writerows(summary)
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('_keys')},indent=2))
    return 0 if report['status']=='pass' else 1
if __name__=='__main__':raise SystemExit(main())
