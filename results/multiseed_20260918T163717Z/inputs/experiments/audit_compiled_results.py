"""Independent delivery checks and illustrative witness search (post-hoc)."""
import json,itertools
from pathlib import Path
import numpy as np
from compiled_study import OUT,CONFIG,dump,compile_one
from analyse_compiled_study import classify,Q,G,D,M

def main():
    payloads=[json.loads(p.read_text()) for p in sorted((OUT/'instances').glob('*.json'))]
    clean=[];family_counts={};anysets={};allsets={};allbothsets={}
    for payload in payloads:
        ins=payload['instance'];statuses=[]
        for result in payload['results']:
            classes,cert=classify(payload,result);statuses.append(bool(cert.any()))
            # Seek the stronger explanatory witness: a full candidate passes
            # both compiled cost bounds, but every full assignment violates Q/M.
            for k in result['full_keys']:
                f=result['candidates'][k]
                valid=cert & (G[None,:,None,None]>=f['G']) & (D[None,None,:,None]>=f['D'])
                if not valid.any():continue
                qi,gi,di,mi=map(int,np.argwhere(valid)[0])
                budget={'Q':int(Q[qi]),'G':int(G[gi]),'D':int(D[di]),'M':float(M[mi])}
                candidates=[result['candidates'][k] for k in result['mixed_keys']]
                feasible=[r for r in candidates if 0<r['reduced']<5 and all(r[x]<=v+1e-9 for x,v in budget.items())]
                mixed=min(feasible,key=lambda r:r['J'])
                native=result['baselines']['native']
                assert native['Q']<=budget['Q'] and (native['G']>budget['G'] or native['D']>budget['D'])
                assert f['G']<=budget['G'] and f['D']<=budget['D']
                assert all(r['Q']>budget['Q'] or r['M']>budget['M']+1e-9 for r in payload['full_logical_enumeration'])
                clean.append({'id':ins['id'],'topology':result['topology'],'strategy':result['strategy'],
                    'budget':budget,'native':native,'full_cost_feasible':f,'mixed':mixed,
                    'illustration_selection':'post-hoc explanatory example within the unchanged frozen grid',
                    'min_full_logical_width':min(r['Q'] for r in payload['full_logical_enumeration'])})
                break
        family_counts[ins['family']]=family_counts.get(ins['family'],0)+1
        anysets.setdefault(ins['family'],[])
        allsets.setdefault(ins['family'],[])
        if any(statuses):anysets[ins['family']].append(ins['id'])
        if all(statuses):allsets[ins['family']].append(ins['id'])
    # Independently recompile one selected clean witness to verify stored metrics.
    selected=next(x for x in clean if x['id'].startswith('pair_star'))
    payload=next(x for x in payloads if x['instance']['id']==selected['id'])
    comparisons=[]
    for name in ['native','full_cost_feasible','mixed']:
        record=selected[name];fresh=compile_one(payload['instance'],tuple(record['actions']),selected['topology'],selected['strategy'])
        assert all(abs(fresh[k]-record[k])<1e-9 for k in ['Q','logical_Q','G','D','M','J'])
        comparisons.append(name)
    dump(OUT/'clean_endpoint_witnesses.json',clean)
    dump(OUT/'audit.json',{'family_instances':family_counts,'certified_in_any_setting':{k:len(v) for k,v in anysets.items()},
        'certified_in_all_six_settings':{k:len(v) for k,v in allsets.items()},
        'all_settings_instance_ids':allsets,'selected_clean_witness':selected,
        'stored_resource_recompilation_passed':comparisons,'clean_witness_count':len(clean)})
    print(json.dumps(selected,indent=2))
    print('ANY', {k:len(v) for k,v in anysets.items()},'ALL', {k:len(v) for k,v in allsets.items()})

if __name__=='__main__':main()
