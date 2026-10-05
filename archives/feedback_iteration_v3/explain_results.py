"""Post-run descriptive checks and witness extraction; not a new hypothesis test."""
from pathlib import Path
import collections,json,math
import numpy as np
import study as s
B=Path(__file__).resolve().parent;data=[s.io.read(p) for p in sorted((B/'execution/results').glob('*.json'))]
result={'stage':'post-run descriptive explanation, original frozen analysis unchanged','families':{},'certified_witnesses':[]}
for family in s.CFG['families']:
 group=[r for r in data if r['family']==family];counts=collections.Counter();values={p:[] for p in ['raw','prepared']};selected_values={p:[] for p in ['raw','prepared']};classical=collections.Counter();witnesses=[]
 for r in group:
  span=r['maximum']-r['optimum'];counts['instances']+=1
  for field in ['p0','rounding','sampling_mean','sampling_best']:classical[field]+=((r['classical'][field]-r['optimum'])/span<=.2+1e-9)
  for cid in r['candidate_ids']['mixed']:
   row=r['rows'][cid];counts['mixed_candidates']+=1
   flags={p:row[p+'_diagnostic']['normalized']<=.02+1e-9 for p in values}
   for p in values:
    values[p].append(row[p+'_diagnostic']['normalized']);counts[p+'_rejected_candidates']+=not flags[p]
   counts['raw_prepared_eligibility_disagreements']+=flags['raw']!=flags['prepared']
  for p in values:
   cid=r['guardrail_selection']['none'];selected_values[p].append(r['rows'][cid][p+'_diagnostic']['normalized'])
   counts[p+'_selected_changed']+=r['guardrail_selection'][p]!=cid
  for cell in r['secondary_grid']:
   cid=cell['selected']['mixed']
   if cid is None or not cell['full_endpoint_resource_excluded'] or cell['selected']['native'] is not None:continue
   row=r['rows'][cid]
   if row['equal_effort']['normalized_gap']>.2+1e-9:continue
   native=r['rows'][r['candidate_ids']['native'][0]]
   tight_full=sorted(r['full_logical_enumeration'],key=lambda f:(f['logical_Q'],f['M'],f['actions']))
   width_ok=[f for f in tight_full if f['logical_Q']<=cell['budget']['Q']]
   witnesses.append({'instance':r['id'],'family':family,'budget':cell['budget'],'selected_mixed_id':cid,'mixed_resources':row['resources'],'native_resources':native['resources'],'mixed_equal_effort_gap':row['equal_effort']['normalized_gap'],'mixed_scan_gap_if_prespecified':row.get('scan_refined',{}).get('normalized_gap'),'p0_gap':(row['p0']-r['optimum'])/span,'rounding_gap':(r['classical']['rounding']-r['optimum'])/span,'best_classical_sample_gap':(r['classical']['sampling_best']-r['optimum'])/span,'all_full_assignments':len(tight_full),'full_logical_width_minimum':min(f['logical_Q'] for f in tight_full),'minimum_full_penalty_within_width':min((f['M'] for f in width_ok),default=None),'certificate':'all full assignments fail logical width or fixed-rule penalty; native fails compiled resources; mixed has independently replayed qualifying original objective','scope':'secondary-grid explanatory witness; no quantum advantage claim'})
 result['families'][family]={'counts':dict(counts),'candidate_diagnostic_ranges':{p:{'min':min(v),'max':max(v)} for p,v in values.items()},'unguarded_selected_diagnostic_ranges':{p:{'min':min(v),'max':max(v)} for p,v in selected_values.items()},'classical_quality_target_pass':dict(classical),'zero_primary_mixed_only_one_sided_95pct_binomial_upper':1-.05**(1/len(group)),'guardrail_interpretation':'Identical selected actions imply no treatment contrast. Zero observed difference does not establish efficacy or a population-zero effect.'}
 # Choose one small-budget, highest-p0-gap explanatory example; selection is post hoc and labelled.
 if witnesses:
  witnesses.sort(key=lambda w:(-w['p0_gap'],w['instance'],tuple(w['budget'][k] for k in ['Q','G','D','M'])))
  chosen=[]
  for w in witnesses:
   if w['instance'] not in {z['instance'] for z in chosen}:chosen.append(w)
  result['certified_witnesses'].extend(chosen[:3])
s.io.atomic_json(B/'explanation.json',result)
print(json.dumps(result,indent=2))
