"""Independent saved-resource review; never writes to the supplied project.
Usage: python -B recheck.py /path/to/extracted/project
Requires NumPy and PyYAML. No quantum compilation or optimization is run.
"""
from pathlib import Path
from collections import Counter, defaultdict
import csv, hashlib, itertools, json, sys
import numpy as np
import yaml

P = Path(sys.argv[1]).resolve()
R = P / 'results/multiseed_20260918T163717Z'
O = Path(__file__).resolve().parent
def readcsv(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))
def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))
def key(r):
    return (r['instance_id'], r['candidate_id'], r['topology'], r['synthesis'], int(r['seed']))
def layer(r):
    return (r['instance_id'], r['topology'], r['synthesis'])

out = {'scope':'Independent reconstruction from saved resources, no Qiskit recompilation'}
manifest = readcsv(P / 'FILE_MANIFEST.csv')
bad = [r['path'] for r in manifest if not (P/r['path']).is_file() or (P/r['path']).stat().st_size != int(r['size_bytes']) or sha(P/r['path']) != r['sha256']]
out['manifest'] = {'files':len(manifest), 'mismatches':bad}
cfg = read(R/'experiment_config.json')
y = yaml.safe_load((R/'experiment_config.yaml').read_text())
raw_cfg = {k:v for k,v in cfg.items() if k!='config_hash'}
digest = hashlib.sha256(json.dumps(raw_cfg,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
out['config'] = {'stored_digest_valid':digest==cfg['config_hash'], 'yaml_semantically_equal':y==cfg,
                 'missing_yaml_keys': sorted(cfg.keys()-y.keys())}
seeds = cfg['seeds']
dims = ('Q','G','D','M')
budgets = np.array(list(itertools.product(*(cfg['budget_grid'][d] for d in dims))),float)
tasks = readcsv(R/'task_manifest.csv')
rows = readcsv(R/'compilation_rows.csv')
cands = readcsv(R/'candidate_manifest.csv')
lookup = {c['candidate_id']:c for c in cands}
tk = Counter(key(r) for r in tasks); rk = Counter(key(r) for r in rows)
out['coverage'] = {'planned':len(tasks),'observed':len(rows),'missing':len(tk.keys()-rk.keys()),
 'unexpected':len(rk.keys()-tk.keys()),'duplicate_planned':len(tasks)-len(tk),'duplicate_observed':len(rows)-len(rk),
 'shared_task_ids':len({r['task_id'] for r in tasks}&{r['task_id'] for r in rows}), 'statuses':dict(Counter(r['status'] for r in rows))}
by_layer = defaultdict(list); by_seed = defaultdict(dict)
for c in cands: by_layer[layer(c)].append(c)
nonfinite=[]; invalid=[]; jbad=[]; digestbad=[]; tracebad=[]; digests={}
for r in rows:
    by_seed[layer(r)+(int(r['seed']),)][r['candidate_id']]=r
    if r['status']!='compiled': continue
    v=json.loads(r['resources_json']); r['_resources']=v
    if not all(np.isfinite(float(v[d])) for d in dims): nonfinite.append(r['task_id'])
    if any(v[d]<0 for d in dims) or any(int(v[d])!=v[d] for d in ('Q','G','D')) or not int(lookup[r['candidate_id']]['logical_Q'])<=v['Q']<=12: invalid.append(r['task_id'])
    c=lookup[r['candidate_id']]
    score=(int(c['n_aux'])/4+v['G']/160+v['D']/120+v['M']/8)/4
    if abs(v['J']-score)>1e-12: jbad.append(r['task_id'])
    path=r['circuit_path']
    if path not in digests: digests[path]=read(R/path) if (R/path).is_file() else {}
    if digests[path].get(r['task_id'],{}).get('sha256')!=r['circuit_sha256']: digestbad.append(r['task_id'])
    trace=json.loads(r['trace_json'])
    if trace!={'pass_manager':'explicit_sabre_swap','heuristic':'decay','trials':8,'seed':int(r['seed']),'identity_initial_layout':True}: tracebad.append(r['task_id'])
out['resource_checks']={'nonfinite':len(nonfinite),'invalid':len(invalid),'J_mismatches':len(jbad),'digest_link_mismatches':len(digestbad),'declared_trace_mismatches':len(tracebad), 'note':'Digest linkage and declared traces do not independently prove circuit semantics or executed passes.'}
assert not nonfinite and not invalid and set(r['status'] for r in rows)=={'compiled'}, 'Independent fast classifier below requires complete valid saved rows'

# Direct complete-vector inequalities: deliberately no production classifier,
# threshold slicing, or saved classification arrays in the calculation.
def masks(cs, rs):
    mixed=np.zeros(len(budgets),bool); other=mixed.copy(); candidate_masks={}
    for c in cs:
        feasible=np.zeros(len(budgets),bool)
        for r in rs[c['candidate_id']]:
            v=r['_resources']; one=np.ones(len(budgets),bool)
            for i,d in enumerate(dims): one &= v[d] <= budgets[:,i]+(1e-9 if d=='M' else 0)
            feasible |= one
        candidate_masks[c['candidate_id']]=feasible
        if c['category']=='strict_mixed': mixed |= feasible
        else: other |= feasible
    return (mixed & ~other).astype(np.uint8),candidate_masks

index={layer(r)+(int(r['seed']),):r for r in readcsv(R/'budget_classification.csv')}
saved=np.load(R/'classification_arrays.npz',allow_pickle=False)
flips={layer(r):r for r in readcsv(R/'classification_flips.csv')}
selectors={layer(r)+(int(r['seed']),):r for r in readcsv(R/'selector_stability.csv')}
pooled={layer(r):r for r in readcsv(R/'pooled_seed_summary.csv')}
base=common=oldloss=loss=0; bad_arrays=[]; bad_counts=[]; bad_pooled=[]; bad_selected=[]; mislabel=[]; seed_totals=Counter(); seed_presence=Counter(); class_counts=Counter(); loss_differ=0
for li,(l,cs) in enumerate(sorted(by_layer.items()),1):
    aa={}
    for seed in seeds:
        rs={cid:[r] for cid,r in by_seed[l+(seed,)].items()}
        a,_=masks(cs,rs); aa[seed]=a.astype(bool)
        ix=index[l+(seed,)]; st=saved[ix['array_key']].ravel()
        if not np.array_equal(a,st): bad_arrays.append({'layer':l,'seed':seed,'mismatch_cells':int(np.sum(a!=st))})
        counts=[int((a==v).sum()) for v in (1,0,2)]
        if counts!=[int(ix[k]) for k in ('true_cells','false_cells','unknown_cells')]: bad_counts.append(ix['array_key'])
        seed_totals[seed]+=counts[0]; seed_presence[seed]+=bool(counts[0])
        chosen=min((r['_resources']['J'],cid,lookup[cid]['category']) for cid,r in by_seed[l+(seed,)].items())
        if selectors[l+(seed,)]['selected_candidate_id']!=chosen[1]: bad_selected.append([l,seed])
    b=aa[1729]; inter=np.logical_and.reduce(list(aa.values()))
    nb=int(b.sum()); nc=int(inter.sum()); lo=int((b & ~np.logical_or.reduce([aa[s] for s in seeds if s!=1729])).sum())
    base+=nb; common+=nc; oldloss+=lo; loss+=nb-nc
    if nb-nc!=lo: loss_differ+=1
    if flips[l]['classification']=='stable' and nc<nb: mislabel.append({'layer':l,'baseline':nb,'common':nc,'lost_in_any':nb-nc})
    label='baseline_empty' if nb==0 else ('no_common' if nc==0 else ('all_baseline_retained' if nb==nc else 'partial_retention'))
    class_counts[label]+=1
    pp,_=masks(cs,{c['candidate_id']:[by_seed[l+(s,)][c['candidate_id']] for s in seeds] for c in cs})
    if int(pp.sum())!=int(pooled[l]['true_cells']): bad_pooled.append(l)
    if li%60==0: print(f'Rebuilt {li}/{len(by_layer)} settings',flush=True)
out['independent_reconstruction']={'arrays':len(index),'budget_cells_per_array':len(budgets),'total_classified_cells':len(index)*len(budgets),
 'array_mismatches':bad_arrays,'summary_mismatches':bad_counts,'pooled_mismatches':bad_pooled,'selected_id_mismatches':bad_selected,
 'baseline':base,'common':common,'retention':common/base,'seed_true_totals':dict(seed_totals),'seed_nonempty_settings':dict(seed_presence),
 'old_loss_all_other_seeds':oldloss,'loss_any_other_seed':loss,'settings_with_loss_definition_difference':loss_differ,
 'stable_but_baseline_lost':len(mislabel),'example':mislabel[0], 'baseline_retention_classes':dict(class_counts)}
out['selector_fields']={'rows':len(selectors),'empty_baseline_ids':sum(not r['baseline_selected_candidate_id'] for r in selectors.values()),'not_computed':sum(r['baseline_selected_feasible']=='not_computed' for r in selectors.values())}
out['candidate_evidence']={'rows':len(cands),'categories':dict(Counter(c['category'] for c in cands)),
 'invalid_strict_mixed':[c['candidate_id'] for c in cands if c['category']=='strict_mixed' and not (int(c['n_aux'])>0 and int(c['retained_cubic'])>0 and json.loads(c['evidence_json']).get('applicable') and json.loads(c['evidence_json']).get('mismatch_count')==0 and json.loads(c['evidence_json']).get('inconsistent_minimiser_count')==0)]}
(O/'recheck_results.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(out,indent=2,ensure_ascii=False),flush=True)
