"""Full-library P1 protocol; representative smoke is never a formal gate."""
from collections import defaultdict
import csv
import json
import time

REPETITIONS=(('repeat_a',1729),('repeat_b',1729),('single',2718))
PROTOCOL={'version':'P1_FULL_LIBRARY_V2','default_scope':'full',
          'selection':'first selected instance per family by frozen selection_hash, then instance_id; all setting candidates',
          'semantic_selection':'minimum logical_Q then candidate_id per family/topology/synthesis/category; three repetitions',
          'repetitions':[{'repetition':r,'seed':s} for r,s in REPETITIONS]}

def selection(samples,candidates):
    families=defaultdict(list)
    for row in samples:
        if str(row['selected']).lower()=='true': families[row['family']].append(row)
    first={f:min(group,key=lambda r:(r['selection_hash'],r['instance_id']))['instance_id'] for f,group in families.items()}
    full=[c for c in candidates if c['instance_id'] in first.values()]
    groups=defaultdict(list)
    for c in full: groups[(c['family'],c['topology'],c['synthesis'],c['category'])].append(c)
    semantic={min(group,key=lambda c:(int(c['logical_Q']),c['candidate_id']))['candidate_id'] for group in groups.values()}
    return first,full,semantic

def validate(m,samples,candidates,rows,scope='full',config=None):
    first,full,semantic=selection(samples,candidates)
    selected=full if scope=='full' else [c for c in full if c['candidate_id'] in semantic]
    if not selected: raise ValueError('Empty P1 candidate library')
    if any(r.get('repetition',r.get('repeat')) not in dict(REPETITIONS) for r in rows):raise ValueError('Unexpected repetition')
    groups={}; observations=[]; semantic_count=0; callback_count=0
    for repetition,seed in REPETITIONS:
        tasks=[]
        for c in selected:
            key={k:c[k] for k in ('instance_id','candidate_id','topology','synthesis')};key['seed']=seed
            tasks.append({'task_id':m.task_id(key),**key})
        part=[r for r in rows if r.get('repetition',r.get('repeat'))==repetition]
        m.validate_rows(tasks,part,selected,require_success=True)
        groups[repetition]={m.natural_key(r)[:-1]:r for r in part}
        for r in part:
            observations.append(r['observation_id'])
            if not r['observation_id'] or not r['worker_pid'] or not r['worker_started_utc']:raise ValueError('Independent worker observation missing')
            if config:
                c=next(c for c in selected if c['candidate_id']==r['candidate_id'])
                if r['input_hash']!=c['input_hash'] or r['config_hash']!=config['config_hash'] or r['compiler_hash']!=config['compiler_implementation_hash']:raise ValueError('P1 row provenance mismatch')
            if r['status']=='compiled':
                trace=json.loads(r['trace_json'])
                if not trace.get('observed_passes'):raise ValueError('Observed callback missing')
                if set(trace['observed_passes']) & {'SabreLayout','VF2Layout','VF2PostLayout'}:raise ValueError('Unexpected placement search')
                declared=trace['declared']
                if declared['seed']!=seed or (config and declared['trials']!=config['compiler']['sabre_trials']):raise ValueError('Routing declaration mismatch')
                if any(s!=declared for s in trace['observed_sabre']):raise ValueError('Observed routing mismatch')
                callback_count+=1
                if r['candidate_id'] in semantic:
                    if trace.get('semantic',{}).get('status')!='pass':raise ValueError('Required finite semantic check missing')
                    semantic_count+=1
    if len(observations)!=len(set(observations)):raise ValueError('Observation reused across independent repetitions/tasks')
    for key,a in groups['repeat_a'].items():
        b=groups['repeat_b'][key]
        if a['status']!=b['status'] or json.loads(a['resources_json'] or '{}')!=json.loads(b['resources_json'] or '{}'):raise ValueError('1729 resource repeat mismatch')
    settings=defaultdict(list)
    for c in selected:settings[(c['instance_id'],c['topology'],c['synthesis'])].append(c)
    import numpy as np
    classifications=[]; budgets=m.budgets_array()
    for setting,cs in settings.items():
        arrays=[]
        for rep in ('repeat_a','repeat_b'):
            by_candidate={c['candidate_id']:[groups[rep][(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis'])]] for c in cs}
            arrays.append(m.classify_layer(cs,by_candidate,budgets)[0])
        if not np.array_equal(*arrays):raise ValueError('1729 budget classification repeat mismatch')
        classifications.append({'instance_id':setting[0],'topology':setting[1],'synthesis':setting[2],
            'cells':len(budgets),'classification_sha256':m.sha256_bytes(arrays[0].tobytes()),'mismatch_cells':0})
    return {'status':'pass','scope':scope,'formal_gate_eligible':scope=='full','first_instance_by_family':first,
            'expected_candidate_count':len(selected),'expected_record_count':len(selected)*len(REPETITIONS),
            'repeat_rows':len(rows),'compiled_count':sum(r['status']=='compiled' for r in rows),
            'capacity_excluded_count':sum(r['status']=='width_exceeded' for r in rows),
            'observed_callback_rows':callback_count,'finite_semantic_rows':semantic_count,
            'repeatability_mismatch_count':0,'budget_classification_checks':classifications,
            'new_executions':len(rows),'reused_observations':0,'protocol':PROTOCOL}

def run_p1(m,run,scope='full'):
    config,samples,candidates,_=m.load_run(run);m.require_current_compiler(run,config)
    if config.get('p1_protocol')!=PROTOCOL:raise RuntimeError('New frozen P1 protocol config required; legacy representative report is not a full gate')
    if (run/'P1_REPORT.json').exists() or (run/'p1_attempts').exists():raise RuntimeError('Preserve P1 history: use a new run directory')
    first,full,semantic=selection(samples,candidates)
    selected=full if scope=='full' else [c for c in full if c['candidate_id'] in semantic]
    rows=[];plan=[];jobs=[]
    for rep,seed in REPETITIONS:
        grouped=defaultdict(list)
        for c in selected:
            key={k:c[k] for k in ('instance_id','candidate_id','topology','synthesis')};key['seed']=seed
            task={'task_id':m.task_id(key),**key,'candidate':c,'repetition':rep,'semantic':c['candidate_id'] in semantic}
            grouped[(c['instance_id'],c['topology'],c['synthesis'])].append(task)
            plan.append({**key,'task_id':task['task_id'],'repetition':rep,'input_hash':c['input_hash'],'semantic':task['semantic']})
        for setting,tasks in sorted(grouped.items()):jobs.append((rep,setting,(str(run),tasks,seed,config['compiler']['sabre_trials'],'p1_'+rep+'_attempt_1')))
    m.write_csv(run/'P1_TASK_MANIFEST.csv',plan,plan[0].keys())
    m.atomic_json(run/'P1_PLAN.json',{'scope':scope,'protocol':PROTOCOL,'first_instance_by_family':first,'identity':m.execution_identity(run,config),'task_manifest_sha256':m.sha256_file(run/'P1_TASK_MANIFEST.csv')})
    m.atomic_json(run/'p1_environment.json',m.environment_payload(run,config))
    started=time.perf_counter();error=None
    try:
        for number,(rep,setting,job) in enumerate(jobs,1):
            result=m.preflight_job(job,config)
            for row in result['rows']:
                c=next(t['candidate'] for t in job[1] if t['candidate_id']==row['candidate_id'])
                row.update(repetition=rep,repeat=rep,input_hash=c['input_hash'],config_hash=config['config_hash'],compiler_hash=config['compiler_implementation_hash'])
            m.atomic_json(run/'p1_attempts'/f'{number:03d}_{rep}.json',result)
            rows.extend(result['rows'])
            print(f'P1 {scope}: {number}/{len(jobs)} batches, {len(rows)}/{len(plan)} records; {time.perf_counter()-started:.1f}s',flush=True)
        report=validate(m,samples,candidates,rows,scope,config)
    except Exception as exc:
        error=exc;report={'status':'fail','scope':scope,'formal_gate_eligible':False,'error':f'{type(exc).__name__}: {exc}','repeat_rows':len(rows),'expected_record_count':len(plan)}
    m.write_csv(run/'p1_repetition_rows.csv',rows,sorted({k for r in rows for k in r}) or ['task_id','status'])
    report.update(identity=m.execution_identity(run,config),rows_sha256=m.sha256_file(run/'p1_repetition_rows.csv'),
                  task_manifest_sha256=m.sha256_file(run/'P1_TASK_MANIFEST.csv'),elapsed_seconds=time.perf_counter()-started)
    m.atomic_json(run/'P1_REPORT.json',report);m.atomic_json(run/'P1_FULL_REPORT.json' if scope=='full' else run/'P1_REPRESENTATIVE_REPORT.json',report)
    m.atomic_json(run/'RUN_STATE.json',{'stage':'p1_complete','status':report['status'],'formal_gate_eligible':report['formal_gate_eligible']})
    if error:raise RuntimeError('P1 acceptance failed; evidence retained') from error

def require_full_gate(m,run,config,samples,candidates):
    report=m.read_json(run/'P1_REPORT.json')
    if report.get('status')!='pass' or report.get('scope')!='full' or not report.get('formal_gate_eligible'):raise RuntimeError('Full-candidate P1 required; representative smoke is insufficient')
    if config.get('p1_protocol')!=PROTOCOL or report.get('identity')!=m.execution_identity(run,config):raise RuntimeError('P1 protocol or identity mismatch')
    if report.get('rows_sha256')!=m.sha256_file(run/'p1_repetition_rows.csv'):raise RuntimeError('P1 evidence changed')
    with (run/'p1_repetition_rows.csv').open(encoding='utf-8-sig',newline='') as f:result_rows=list(csv.DictReader(f))
    validate(m,samples,candidates,result_rows,'full',config)
