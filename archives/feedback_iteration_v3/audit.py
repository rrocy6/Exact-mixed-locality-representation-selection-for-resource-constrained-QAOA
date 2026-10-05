"""Independent state/moment checks plus a sample of actual transpiled circuits."""
import argparse,collections,json,math,sys
from pathlib import Path
import numpy as np
import study as s
from legacy_verifier import independent_state

def circuit_check(poly,rep,probs):
 from qiskit.quantum_info import Statevector
 metrics,circuit=s.compile_candidate(rep,probs,True);angles=[.671,.391]
 circuit=circuit.assign_parameters({p:angles[0] if p.name=='gamma' else angles[1] for p in circuit.parameters})
 state=np.asarray(Statevector.from_instruction(circuit).data)
 mapping=circuit.layout.final_index_layout(filter_ancillas=True)
 desired=s.q.Simulation(poly,rep,probs).state(angles);embedded=np.zeros(len(state),complex)
 idx=np.arange(len(desired));targets=sum(((idx>>i)&1)*(1<<mapping[i]) for i in range(rep.n_qubits));embedded[targets]=desired
 fidelity=float(abs(np.vdot(embedded,state))**2)
 s.checked(abs(1-fidelity)<1e-9,'Transpiled state/layout/mixer mismatch')
 return fidelity,metrics

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 s.validate_freeze();s.checked(not a.output.exists(),'Choose new audit file');context=s.io.read(a.run/'RUN_CONTEXT.json');s.checked(context['status']=='COMPLETED','Incomplete run')
 history=s.io.read(s.ROOT/'historical_signatures.json');known=set(history['signatures']);seen=set();counts=collections.Counter();maximum=0.;circuits=[]
 data=[s.io.read(f) for f in sorted((a.run/'results').glob('*.json'))]
 s.checked(len(data)==sum(s.CFG['families'].values()),'Missing result files')
 for r in data:
  stem=r['id'];marker=s.io.read(a.run/'completed'/(stem+'.json'));s.checked(marker['freeze_sha256']==s.io.sha(s.ROOT/'freeze.json'),'Wrong freeze')
  expected={f'results/{stem}.json'}|{row['grid_file'] for row in r['rows'].values() if 'grid_file' in row};s.checked(set(marker['files'])==expected,'Incomplete manifest')
  for name,h in marker['files'].items():s.checked(s.io.sha(a.run/name)==h,'Changed result')
  ins,poly,seed,rejected=s.generate(r['family'],r['number']);s.checked(s.signature(poly)==r['signature'] and seed==r['seed'] and ins==r['instance'],'Generator replay')
  s.checked(r['signature'] not in seen and r['signature'] not in known,'Objective duplicate/overlap');seen.add(r['signature'])
  bank,fullmeta=s.banks(poly,r['n'],seed);s.checked(fullmeta==r['full_logical_enumeration'],'Full logical replay')
  s.checked({k:[s.key(x) for x in v] for k,v in bank.items()}==r['candidate_ids'],'Candidate bank replay');s.checked(len(bank['full'])==len(bank['mixed']),'Unequal candidate budgets')
  original=s.q.truth_values(poly,r['n']);counts['instances']+=1
  for cid,row in r['rows'].items():
   rep=s.representation(poly,r['n'],row['actions']);encoded=s.q.truth_values(rep.polynomial,rep.n_qubits);orig=np.tile(original,1<<rep.n_auxiliary)
   e=encoded.reshape((-1,len(original)));s.checked(np.max(abs(e.min(0)-original))<1e-10 and np.all(np.sum(np.isclose(e,original[None,:],atol=1e-10,rtol=0),axis=0)==1),'Exactness/lift');counts['exact_representations']+=1
   idx=np.arange(len(encoded));bits=(idx[:,None]>>np.arange(rep.n_qubits))&1
   for label,values in [('raw',row['raw_probabilities']),('prepared',row['probabilities'])]:
    probs=np.asarray(values);product=np.prod(np.where(bits,probs,1-probs),axis=1);direct=float(product@(encoded-orig));error=abs(direct-row[label+'_diagnostic']['excess']);maximum=max(maximum,error);s.checked(error<1e-9,'Diagnostic formula differs from product enumeration');counts['product_law_checks']+=1
   for method,quota in [('equal_effort',360),('scan_refined',960)]:
    if method not in row:continue
    out=row[method];trace=out['trace'];s.checked(len(trace)==out['calls']==quota,'Unequal optimization effort');counts[method+'_calls']+=quota
    vals=np.array([t['objective'] for t in trace]);inc=np.array([t['incumbent'] for t in trace]);s.checked(np.max(abs(np.minimum.accumulate(vals)-inc))<1e-10 and abs(inc[-1]-out['objective'])<1e-10,'Trace incumbent')
    fresh=independent_state(poly,rep,row['probabilities'],out['parameters']);error=max(abs(fresh[k]-out[k]) for k in fresh if k!='p0');maximum=max(maximum,error);s.checked(error<1e-9,'Final state replay');counts['saved_parameter_replays']+=1
    for t in [trace[0],trace[-1]]:
     val=independent_state(poly,rep,row['probabilities'],t['parameters'])['original_mean'];error=abs(val-t['objective']);maximum=max(maximum,error);s.checked(error<1e-9,'Trace angle replay');counts['trace_samples']+=1
    gap=(out['objective']-r['optimum'])/(r['maximum']-r['optimum']);s.checked(abs(gap-out['normalized_gap'])<1e-12,'Gap normalization')
   if 'grid_file' in row:
    with np.load(a.run/row['grid_file']) as f:grid=f['objective']
    s.checked(grid.shape==(65,65) and np.isfinite(grid).all(),'Grid shape');s.checked(abs(grid.min()-row['scan_refined']['grid_minimum'])<1e-10,'Grid minimum');counts['scan_grid_calls']+=grid.size
    for i,j in [(0,0),(0,38),(1,3),(11,19),(37,61),(64,64)]:
     val=independent_state(poly,rep,row['probabilities'],[2*math.pi*i/65,math.pi*j/65])['original_mean'];error=abs(val-grid[i,j]);maximum=max(maximum,error);s.checked(error<1e-9,'Grid sample replay');counts['grid_samples']+=1
  for domain,ids in r['candidate_ids'].items():s.checked(s.choose(r['rows'],ids,s.CFG['primary_budget'])==r['primary_selection'][domain],'Primary selection differs')
  for policy in ['none','raw','prepared']:s.checked(s.choose(r['rows'],r['candidate_ids']['mixed'],{'Q':12},policy)==r['guardrail_selection'][policy],'Guardrail selection differs')
  if r['number']==0:
   for domain,cid in r['capacity_selection'].items():
    if cid is None:continue
    row=r['rows'][cid];rep=s.representation(poly,r['n'],row['actions']);fidelity,resources=circuit_check(poly,rep,row['probabilities']);s.checked(resources==row['resources'],'Recompiled resources differ');circuits.append({'instance':stem,'domain':domain,'state_fidelity':fidelity})
 for r in data:counts['recorded_compiler_calls']+=r['calls']['compiler_calls']
 counts['total_actual_objective_evaluations']=sum(counts[k] for k in ['equal_effort_calls','scan_refined_calls','scan_grid_calls'])
 s.validate_freeze();result={'status':'PASS','counts':dict(counts),'maximum_numeric_error':maximum,'new_unique_objectives':len(seen),'historical_unique_objectives_checked':len(known),'exact_overlap':0,'compiled_statevector_checks':circuits,'freeze_sha256':s.io.sha(s.ROOT/'freeze.json'),'scope':'record integrity, independent exact states/product moments; optimizer trajectories not reoptimized by this audit'}
 s.io.atomic_json(a.output,result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
