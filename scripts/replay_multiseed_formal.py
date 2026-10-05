"""Predeclared small replay through the production worker, never a full rerun."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import multiseed_experiment as m

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.output.resolve().is_relative_to(m.ROOT) or args.output.exists():
        raise ValueError('A new output directory inside project is required')
    cfg,_,candidates,tasks=m.load_run(args.source)
    groups=defaultdict(list)
    for c in candidates:
        if int(c['logical_Q'])<=12:
            groups[(c['family'],c['topology'],c['synthesis'],c['category'])].append(c)
    selected=[min(cs,key=lambda c:(int(c['logical_Q']),c['instance_id'],c['candidate_id'])) for _,cs in sorted(groups.items())]
    args.output.mkdir(parents=True)
    env=m.environment_payload(args.source,cfg)
    m.atomic_json(args.output/'environment.json',env)
    jobs=[]
    for c in selected:
        for attempt,seed in [('repeat_a',1729),('repeat_b',1729),('seed_2718',2718)]:
            key={k:c[k] for k in ('instance_id','candidate_id','topology','synthesis')}
            key['seed']=seed
            task={**key,'task_id':m.task_id(key),'candidate':c,'semantic':True}
            jobs.append((str(args.source),[task],seed,cfg['compiler']['sabre_trials'],attempt))
    m.atomic_json(args.output/'REPLAY_PLAN.json',{'selection':'minimum logical width, then instance_id and candidate_id in each family/topology/synthesis/category group',
        'selected_candidates':[c['candidate_id'] for c in selected],'task_count':len(jobs),
        'compiler_identity':m.compiler_identity(args.source),'source_config_hash':cfg['config_hash'],
        'source_compilation_sha256':m.sha256_file(args.source/'compilation_rows.csv')})
    with (args.source/'compilation_rows.csv').open(encoding='utf-8-sig',newline='') as f:
        original={m.natural_key(r):r for r in csv.DictReader(f)}
    results=[]; changes=[]; repeats={}; failures=[]
    for i,job in enumerate(jobs):
        result=m.compile_batch_worker(job)
        m.atomic_json(args.output/f'attempt_{i:03d}.json',result)
        try:
            m.validate_rows(job[1],result['rows'],selected,require_success=True)
        except (ValueError,KeyError) as exc:
            failures.append(str(exc))
        for row in result['rows']:
            results.append(row)
            key=m.natural_key(row)
            if row['status']!='compiled': continue
            old=json.loads(original[key]['resources_json']); new=json.loads(row['resources_json'])
            delta={d:new[d]-old[d] for d in (*m.DIMENSIONS,'J')}
            if any(abs(x)>1e-12 for x in delta.values()):
                changes.append({'key':key,'attempt':row['attempt_id'],'delta':delta})
            if key in repeats and repeats[key]!=new:
                failures.append('Repeat mismatch: '+str(key))
            repeats[key]=new
        if (i+1)%12==0: print(f'Replay {i+1}/{len(jobs)}',flush=True)
    matching=all(env['packages'].get(p)==m.read_json(args.source/'environment.json')['packages'].get(p) for p in ('qiskit','numpy','scipy'))
    report={'status':'pass' if not failures and not changes and matching else 'BLOCKED',
            'task_count':len(results),'compiled_count':sum(r['status']=='compiled' for r in results),
            'matching_historical_packages':matching,'resource_differences':changes,'failures':failures,
            'scope':'small predeclared replay; observed callbacks and finite-angle formal path semantics, not all historical circuit contents'}
    m.atomic_json(args.output/'REPLAY_REPORT.json',report)
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='pass' else 1

if __name__=='__main__': raise SystemExit(main())
