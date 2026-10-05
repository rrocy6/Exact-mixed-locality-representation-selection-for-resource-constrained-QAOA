"""Instance-level analysis; no pooled compiler cells or optimizer evaluations as N."""
from __future__ import annotations
import argparse,collections,itertools,json,math
from pathlib import Path
import numpy as np
import study as s

def interval(values,level=.95,seed=84123):
 a=np.asarray(values,dtype=float)
 if not len(a):return {'n':0,'mean':None,'low':None,'high':None}
 rng=np.random.default_rng(seed);means=a[rng.integers(0,len(a),size=(10000,len(a)))].mean(1)
 tail=(1-level)/2;lo,hi=np.quantile(means,[tail,1-tail])
 return {'n':len(a),'mean':float(a.mean()),'low':float(lo),'high':float(hi),'confidence_level':level,'bootstrap_unit':'instance'}

def lookup(r,cid,method):return r['rows'][cid][method] if cid is not None else None
def qualifies(r,cid,method,target):return cid is not None and lookup(r,cid,method)['normalized_gap']<=target+1e-9

def prediction(data):
 probes=[]
 for r in data:
  if r['family']=='constructed':continue
  span=r['maximum']-r['optimum']
  for cid in r['diagnostic_probes']:
   row=r['rows'][cid];res=row['resources'];out=row['equal_effort']
   probes.append({'instance':r['id'],'family':r['family'],'base':[1.,float(r['family']=='spin_glass'),res['aux'],res['J'],res['reduced'],(row['p0']-r['optimum'])/span],'raw':row['raw_diagnostic']['normalized'],'prepared':row['prepared_diagnostic']['normalized'],'gap':out['normalized_gap'],'inconsistency':out['auxiliary_inconsistency']})
 identifiers=sorted({p['instance'] for p in probes});b=np.array([p['base'] for p in probes]);raw=np.array([p['raw'] for p in probes])[:,None];prepared=np.array([p['prepared'] for p in probes])[:,None]
 ids=np.array([p['instance'] for p in probes]);output={}
 for outcome in ['gap','inconsistency']:
  y=np.array([p[outcome] for p in probes]);errors={label:[] for label in ['base','raw','prepared','both']}
  for iid in identifiers:
   train=ids!=iid;test=~train
   for label,x in [('base',b),('raw',np.c_[b,raw]),('prepared',np.c_[b,prepared]),('both',np.c_[b,raw,prepared])]:
    # Fit scaling using training inputs only; preserve the intercept.
    x=x.copy();mean=x[train,1:].mean(0);scale=x[train,1:].std(0);scale[scale<1e-12]=1.
    x[:,1:]=(x[:,1:]-mean)/scale
    coef=np.linalg.lstsq(x[train],y[train],rcond=None)[0]
    errors[label].append(float(np.mean((x[test]@coef-y[test])**2)))
  output[outcome]={'held_out_instances':len(identifiers),'probe_rows':len(probes),'mean_squared_error':{k:float(np.mean(v)) for k,v in errors.items()},'incremental_mse_improvement':{k:interval(np.array(errors['base'])-np.array(errors[k])) for k in ['raw','prepared','both']},'instance_errors':[{'instance':iid,**{k:errors[k][j] for k in errors}} for j,iid in enumerate(identifiers)]}
 return {'scope':'secondary descriptive leave-one-instance-out; controls include auxiliary count and compiled score; predictive, not causal','outcomes':output}

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 s.validate_freeze();s.checked(not a.output.exists(),'Choose new analysis file')
 context=s.io.read(a.run/'RUN_CONTEXT.json');s.checked(context['status']=='COMPLETED','Run not complete')
 data=[s.io.read(f) for f in sorted((a.run/'results').glob('*.json'))];s.checked(len(data)==sum(s.CFG['families'].values()),'Missing instances')
 families={};total=collections.Counter();witnesses=[]
 for r in data:total.update(r['calls'])
 for fam,n in s.CFG['families'].items():
  group=[r for r in data if r['family']==fam];s.checked(len(group)==n,'Wrong family size')
  primary={domain:{'resource_feasible':0,'joint_pass':0,'quality_conditional':[]} for domain in ['native','full','mixed']};mixedonly=[];guard={p:{'available':0,'joint_pass':0,'gap':[],'inconsistency':[],'selection_changes':0} for p in ['none','raw','prepared']};jointdiff={p:[] for p in ['raw','prepared']};paired={p:{'gap':[],'inconsistency':[]} for p in ['raw','prepared']}
  secondary={str(t):{'instances_with_mixed_only_selected_baselines':0,'instances_with_full_endpoint_resource_certificate':0,'cells_with_mixed_only_selected_baselines':0} for t in s.CFG['secondary_quality_targets']}
  retained=[]
  for r in group:
   selection=r['primary_selection'];passed={}
   for domain,cid in selection.items():
    passed[domain]=qualifies(r,cid,'scan_refined',s.CFG['primary_quality_target'])
    primary[domain]['resource_feasible']+=cid is not None;primary[domain]['joint_pass']+=passed[domain]
    if cid is not None:primary[domain]['quality_conditional'].append(r['rows'][cid]['scan_refined']['normalized_gap'])
   only=passed['mixed'] and not passed['native'] and not passed['full'];mixedonly.append(float(only))
   retained.append({'id':r['id'],'selection':selection,'pass':passed,'mixed_only':only})
   for policy,cid in r['guardrail_selection'].items():
    guard[policy]['available']+=cid is not None
    guard[policy]['joint_pass']+=qualifies(r,cid,'scan_refined',s.CFG['primary_quality_target'])
    guard[policy]['selection_changes']+=cid!=r['guardrail_selection']['none']
    if cid is not None:
     guard[policy]['gap'].append(r['rows'][cid]['scan_refined']['normalized_gap']);guard[policy]['inconsistency'].append(r['rows'][cid]['scan_refined']['auxiliary_inconsistency'])
   for policy in ['raw','prepared']:
    c0=r['guardrail_selection']['none'];c1=r['guardrail_selection'][policy]
    jointdiff[policy].append(float(qualifies(r,c1,'scan_refined',.2))-float(qualifies(r,c0,'scan_refined',.2)))
    if c0 is not None and c1 is not None:
     for metric,key in [('gap','normalized_gap'),('inconsistency','auxiliary_inconsistency')]:paired[policy][metric].append(r['rows'][c1]['scan_refined'][key]-r['rows'][c0]['scan_refined'][key])
   for target in s.CFG['secondary_quality_targets']:
    found=False;certified=False
    for cell in r['secondary_grid']:
     sel=cell['selected'];flags={d:qualifies(r,cid,'equal_effort',target) for d,cid in sel.items()}
     if flags['mixed'] and not flags['native'] and not flags['full']:
      found=True;secondary[str(target)]['cells_with_mixed_only_selected_baselines']+=1
      native_resource_absent=sel['native'] is None
      certificate=cell['full_endpoint_resource_excluded'] and native_resource_absent
      certified|=certificate
      if len([w for w in witnesses if w['family']==fam and w['quality_target']==target])<5:
       cid=sel['mixed'];witnesses.append({'instance':r['id'],'family':fam,'quality_target':target,'budget':cell['budget'],'selected':sel,'mixed_gap':r['rows'][cid]['equal_effort']['normalized_gap'],'mixed_p0_gap':(r['rows'][cid]['p0']-r['optimum'])/(r['maximum']-r['optimum']),'all_full_resource_excluded':cell['full_endpoint_resource_excluded'],'both_endpoints_resource_excluded':certificate,'basis':'secondary prespecified grid, equal-effort, explanatory witness not independent trial'})
    secondary[str(target)]['instances_with_mixed_only_selected_baselines']+=found;secondary[str(target)]['instances_with_full_endpoint_resource_certificate']+=certified
  for d in primary:primary[d]['quality_conditional']=interval(primary[d]['quality_conditional'])
  for policy in guard:
   for metric in ['gap','inconsistency']:guard[policy][metric+'_conditional']=interval(guard[policy].pop(metric))
  families[fam]={'instances':n,'primary_joint_resource_quality':{'budget':s.CFG['primary_budget'],'quality_target':.2,'method':'scan_refined','arms':primary,'mixed_only_rate':interval(mixedonly),'instance_results':retained},'guardrail':{'policies':guard,'paired_joint_pass_gain':{k:interval(v,.975 if fam!='constructed' else .95) for k,v in jointdiff.items()},'paired_conditional_differences':{p:{k:interval(v) for k,v in metrics.items()} for p,metrics in paired.items()},'interpretation':'negative conditional gap difference favors guardrail; availability losses remain explicit'},'secondary_grid':secondary}
 total['total_objective_evaluations']=sum(total[k] for k in ['equal_effort_calls','scan_grid_calls','scan_refinement_calls'])
 result={'protocol_id':s.CFG['id'],'freeze_sha256':s.io.sha(s.ROOT/'freeze.json'),'families':families,'prediction':prediction(data),'calls':dict(total),'secondary_witnesses':witnesses,'scientific_claim_status':'Evaluate individual contrasts; completion is not evidence of a positive advantage'}
 s.io.atomic_json(a.output,result);print(json.dumps({'calls':dict(total),'families':{fam:{'primary_mixed_only':obj['primary_joint_resource_quality']['mixed_only_rate'],'guardrail_available':{p:r['available'] for p,r in obj['guardrail']['policies'].items()},'guardrail_joint_gain':obj['guardrail']['paired_joint_pass_gain'],'secondary_grid':obj['secondary_grid']} for fam,obj in families.items()}},indent=2))
if __name__=='__main__':main()
