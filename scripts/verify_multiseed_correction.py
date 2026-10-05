"""Independent acceptance of corrected saved-resource artifacts (no compiler)."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
import yaml

def readcsv(path):
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def layer(r): return (r['instance_id'],r['topology'],r['synthesis'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--corrected',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); source=args.source; corrected=args.corrected
    cfg=read(source/'experiment_config.json')
    budgets=np.array(list(itertools.product(*(cfg['budget_grid'][d] for d in ('Q','G','D','M')))),float)
    rows=readcsv(source/'compilation_rows.csv')
    layers=defaultdict(list); by_seed=defaultdict(dict)
    for c in readcsv(source/'candidate_manifest.csv'): layers[layer(c)].append(c)
    for r in rows:
        assert r['status']=='compiled'
        r['resources']=json.loads(r['resources_json'])
        by_seed[layer(r)+(int(r['seed']),)][r['candidate_id']]=r
    selectors={layer(r)+(int(r['seed']),):r for r in readcsv(corrected/'selector_stability.csv')}
    index={layer(r)+(int(r['seed']),):r for r in readcsv(corrected/'budget_classification.csv')}
    flips={layer(r):r for r in readcsv(corrected/'classification_flips.csv')}
    arrays=np.load(corrected/'classification_arrays.npz',allow_pickle=False)
    differences=[]; base_total=common_total=0; seed_totals=Counter(); presence=Counter(); classes=Counter()
    def mask(r):
        v=r['resources']
        assert all(np.isfinite(v[d]) and v[d]>=0 for d in ('Q','G','D','M'))
        return np.logical_and.reduce([v[d]<=budgets[:,i]+(1e-9 if d=='M' else 0) for i,d in enumerate(('Q','G','D','M'))])
    for setting,cs in sorted(layers.items()):
        baseline=by_seed[setting+(1729,)]
        winner=min((r['resources']['J'],cid) for cid,r in baseline.items())[1]
        baseline_mask=mask(baseline[winner]); denominator=int(baseline_mask.sum()); seed_masks=[]
        for seed in cfg['seeds']:
            current=by_seed[setting+(seed,)]; mixed=np.zeros(len(budgets),bool); nonmixed=mixed.copy()
            for c in cs:
                if c['category']=='strict_mixed': mixed |= mask(current[c['candidate_id']])
                else: nonmixed |= mask(current[c['candidate_id']])
            truth=mixed & ~nonmixed; seed_masks.append(truth)
            if not np.array_equal(truth.astype(np.uint8),arrays[index[setting+(seed,)]['array_key']].ravel()): differences.append(['classification',setting,seed])
            seed_totals[seed]+=int(truth.sum()); presence[seed]+=bool(truth.any())
            x=selectors[setting+(seed,)]; kept=int(np.sum(baseline_mask & mask(current[winner])))
            expected_status='N/A' if not denominator else ('TRUE' if kept==denominator else 'FALSE')
            current_winner=min((r['resources']['J'],cid) for cid,r in current.items())[1]
            if x['baseline_selected_candidate_id']!=winner or x['selected_candidate_id']!=current_winner or int(x['baseline_budget_cells'])!=denominator or int(x['retained_baseline_budget_cells'])!=kept or x['baseline_selected_feasible']!=expected_status or x['baseline_resource_task_id']!=baseline[winner]['task_id'] or x['current_resource_task_id']!=current[winner]['task_id']:
                differences.append(['selector',setting,seed])
        b=seed_masks[0]; common=np.logical_and.reduce(seed_masks); n=int(b.sum()); k=int(common.sum())
        base_total+=n; common_total+=k
        label='empty_baseline' if not n else ('stable' if n==k else ('partial' if k else 'disappeared'))
        classes[label]+=1
        f=flips[setting]
        all_loss=int(np.sum(b & ~np.logical_or.reduce(seed_masks[1:])))
        if f['classification']!=label or int(f['lost_in_any_other_seed'])!=n-k or int(f['lost_in_all_other_seeds'])!=all_loss:
            differences.append(['retention',setting])
    for r in readcsv(corrected/'seed_region_presence.csv'):
        seed=int(r['seed'])
        if int(r['nonempty_settings'])!=presence[seed] or int(r['total_settings'])!=len(layers) or float(r['fraction'])!=presence[seed]/len(layers): differences.append(['presence',seed])
    yaml_equal=yaml.safe_load((corrected/'experiment_config.yaml').read_text(encoding='utf-8'))==cfg
    source_unchanged=sha(source/'compilation_rows.csv')==read(corrected/'CORRECTION_SOURCE.json')['source_compilation_sha256']
    out={'status':'pass' if not differences and yaml_equal and source_unchanged else 'fail',
         'method':'direct complete-vector inequalities, no production classification/selector helpers or saved arrays used as inputs',
         'baseline':base_total,'common':common_total,'retention':common_total/base_total,'arrays_checked':len(index),
         'selector_rows_checked':len(selectors),'seed_true_totals':dict(seed_totals),'seed_nonempty_settings':dict(presence),
         'retention_classes':dict(classes),'differences':differences,'yaml_json_equal':yaml_equal,'source_resources_unchanged':source_unchanged}
    args.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(out,indent=2))
    return 0 if out['status']=='pass' else 1
if __name__=='__main__': raise SystemExit(main())
