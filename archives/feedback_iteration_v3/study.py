"""Fresh joint resource/quality and guardrail study, isolated from prior archives."""
from __future__ import annotations
import argparse,concurrent.futures,hashlib,importlib.util,itertools,json,math,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','RAYON_NUM_THREADS']:os.environ[name]='1'
os.environ['QISKIT_PARALLEL']='FALSE'
sys.path.insert(0,str(ROOT/'vendor'))
import numpy as np
import qaoa as q
import compiler as comp
import runtime_support as io
from urss_pipeline.e1_exactness import build_mixed_representation
from urss_pipeline.e4_warmstart import solve_sa_rlt_level2,product_state
CFG=io.read(ROOT/'protocol.json')
OUT=None

def checked(ok,msg):io.require(bool(ok),msg)
def key(codes):return ','.join(map(str,codes))
def signature(poly):return hashlib.sha256(json.dumps([[list(s),float(c)] for s,c in sorted(poly.items())],separators=(',',':')).encode()).hexdigest()
def source_files():return [ROOT/'protocol.json',ROOT/'study.py',ROOT/'analyse.py',ROOT/'audit.py',ROOT/'historical_signatures.json',ROOT/'requirements.txt',*sorted((ROOT/'vendor').rglob('*.py'))]
def validate_freeze():
 checked(not sys.flags.optimize,'Run without -O')
 f=io.read(ROOT/'freeze.json')
 for name,h in f['source_hashes'].items():checked(io.sha(ROOT/name)==h,'Frozen source changed: '+name)
 checked(sys.version_info[:2]==(3,12),'Requires Python 3.12')
 import importlib.metadata
 for line in (ROOT/'requirements.txt').read_text().splitlines():
  if '==' in line:
   name,v=line.strip().split('==');checked(importlib.metadata.version(name)==v,'Dependency mismatch: '+line)
 return f

def initialise(output):
 global OUT
 OUT=Path(output)

def generate(family,number):
 if family!='constructed':
  config={**CFG['random_generator'],'master_seed':CFG['master_seed']}
  ins,poly,seed,rejections=q.generate(family,number,config)
  return ins,poly,seed,rejections
 seed=q.derive_seed(CFG['master_seed'],'constructed',number);rng=np.random.default_rng(seed)
 order=rng.permutation(9)+1;poly={}
 for edge in [(0,1,k) for k in range(2,6)]+[(6,7,8)]:poly[tuple(sorted(int(order[i]) for i in edge))]=int(rng.integers(1,4))
 for i in range(1,10):
  c=int(rng.integers(-2,3))
  if c:poly[(i,)]=c
 ins={'instance_id':signature(poly),'family':family,'n':9,'terms':[[list(s),float(c)] for s,c in sorted(poly.items())]}
 return ins,poly,seed,[]

def actions_for(poly,codes):
 cubics=sorted(s for s in poly if len(s)==3)
 return tuple(None if code<0 else tuple(itertools.combinations(s,2))[code] for s,code in zip(cubics,codes))

def logical(poly,n,codes):
 actions=actions_for(poly,codes);buckets={}
 for s,p in zip(sorted(s for s in poly if len(s)==3),actions):
  if p is not None:buckets.setdefault(p,[]).append(float(poly[s]))
 penalties=[max(sum(max(c,0) for c in v),sum(max(-c,0) for c in v))+CFG['penalty_margin'] for v in buckets.values()]
 return {'logical_Q':n+len(buckets),'aux':len(buckets),'M':max(penalties,default=0.),'reduced':sum(c>=0 for c in codes)}

def banks(poly,n,seed):
 cubics=sorted(s for s in poly if len(s)==3);m=len(cubics)
 full_all=[(a,logical(poly,n,a)) for a in itertools.product(range(3),repeat=m)]
 full=[a for a,r in full_all if r['logical_Q']<=12]
 mixed=[a for a in itertools.product(range(-1,3),repeat=m) if 0<sum(c>=0 for c in a)<m and logical(poly,n,a)['logical_Q']<=12]
 budget=min(CFG['candidate_budget_per_domain'],len(full),len(mixed));checked(budget>0,'Insufficient representation domains')
 options=[list(itertools.combinations(s,2)) for s in cubics]
 freq={p:sum(set(p)<=set(s) for s in cubics) for opts in options for p in opts}
 reuse=tuple(min(range(3),key=lambda j:(-freq[opts[j]],opts[j])) for opts in options)
 distance=comp.distances(CFG['compiler']['topology'])
 hardware=tuple(min(range(3),key=lambda j:(distance[opts[j][0]-1][opts[j][1]-1],-freq[opts[j]],opts[j])) for opts in options)
 minaux=min(full,key=lambda a:(logical(poly,n,a)['aux'],logical(poly,n,a)['M'],a))
 def fill(initial,pool,label):
  rng=np.random.default_rng(q.derive_seed(seed,label));perm=rng.permutation(len(pool))
  poolset=set(pool);chosen=list(dict.fromkeys(a for a in initial if a in poolset))
  for i in perm:
   a=pool[int(i)]
   if a not in chosen:chosen.append(a)
   if len(chosen)>=budget:break
  return chosen[:budget]
 fullbank=fill([minaux,reuse,hardware],full,'full_bank')
 prefixes=[tuple(a if j<k else -1 for j,a in enumerate(reuse)) for k in range(1,m)]
 buckets0=[tuple(opts.index(p) if p in opts else -1 for opts in options) for p in sorted(freq,key=lambda p:(-freq[p],p)) if freq[p]>1]
 mixedbank=fill([*buckets0,*prefixes],mixed,'mixed_bank')
 return {'native':[(-1,)*m],'full':fullbank,'mixed':mixedbank},[{'actions':list(a),**r} for a,r in full_all]

def representation(poly,n,codes):return build_mixed_representation(poly,n_original=n,actions=actions_for(poly,codes),default_margin=CFG['penalty_margin'])
def probabilities(rep,moments,clipped=True):
 values=[float(moments.singles[i]) for i in range(1,rep.original_width+1)]+[float(moments.pairs[p]) for p in rep.active_pairs]
 if clipped:values=np.clip(values,CFG['clipping_delta'],1-CFG['clipping_delta']).tolist()
 return values

def diagnostic(poly,rep,probs):
 # Closed form; independently enumerate the full product distribution in audit.
 eta=probs[:rep.original_width];excess=0.
 for p,y in rep.auxiliary_indices.items():
  i,j=p;t=eta[i-1]*eta[j-1];xi=probs[y-1]
  A=sum(float(poly[s])*math.prod(eta[k-1] for k in s if k not in p) for s,a in zip(rep.cubic_order,rep.actions) if a==p)
  excess+=(xi-t)*A+float(rep.penalties[p])*(t+xi*(3-2*eta[i-1]-2*eta[j-1]))
 pairs={p for s in rep.cubic_order for p in itertools.combinations(s,2)}
 scale=4*sum(sum(abs(float(poly[s])) for s in rep.cubic_order if set(p)<=set(s))+CFG['penalty_margin'] for p in pairs)
 return {'excess':excess,'normalization':scale,'normalized':excess/scale if scale else 0.}

def full_circuit(rep,probs,strategy=None):
 from qiskit import QuantumCircuit
 from qiskit.circuit import Parameter
 qc=QuantumCircuit(rep.n_qubits);angles=2*np.arcsin(np.sqrt(probs))
 for i,a in enumerate(angles):qc.ry(float(a),i)
 encoded={tuple(i-1 for i in s):float(c) for s,c in rep.polynomial.items()}
 qc.compose(comp.cost_circuit(encoded,rep.n_qubits,strategy or CFG['compiler']['strategy']),inplace=True)
 beta=Parameter('beta')
 for i,a in enumerate(angles):qc.ry(-float(a),i);qc.rz(2*beta,i);qc.ry(float(a),i)
 return qc

def compile_candidate(rep,probs,return_circuit=False):
 from qiskit import transpile
 from qiskit.transpiler import CouplingMap
 c=CFG['compiler'];compiled=transpile(full_circuit(rep,probs),basis_gates=c['basis'],coupling_map=CouplingMap(comp.topology(c['topology'])),initial_layout=list(range(rep.n_qubits)),routing_method='sabre',seed_transpiler=c['seed'],optimization_level=c['optimization_level'])
 active=set(range(rep.n_qubits))
 for ins in compiled.data:active.update(compiled.find_bit(x).index for x in ins.qubits)
 r={'Q':len(active),'logical_Q':rep.n_qubits,'aux':rep.n_auxiliary,'G':int(compiled.count_ops().get('cx',0)),'D':int(compiled.depth(filter_function=lambda i:len(i.qubits)==2)),'M':float(max(rep.penalties.values(),default=0)),'reduced':sum(p is not None for p in rep.actions),'total_gates':compiled.size()}
 r['J']=(r['aux']/4+r['G']/160+r['D']/120+r['M']/8)/4
 return (r,compiled) if return_circuit else r

def feasible(r,budget):return all(r[k]<=v+1e-9 for k,v in budget.items())
def choose(rows,ids,budget,policy='none'):
 possible=[i for i in ids if feasible(rows[i]['resources'],budget) and (policy=='none' or rows[i][policy+'_diagnostic']['normalized']<=CFG['guardrail']['tau']+1e-9)]
 return min(possible,key=lambda i:(rows[i]['resources']['J'],tuple(rows[i]['actions']))) if possible else None

def measure_instance(family,number):
 validate_freeze();stem=f'{family}_{number:02d}';path=OUT/'results'/(stem+'.json')
 marker=OUT/'completed'/(stem+'.json')
 if marker.exists():
  record=io.read(marker)
  checked(record['freeze_sha256']==io.sha(ROOT/'freeze.json'),'Wrong completion freeze')
  for name,h in record['files'].items():checked(io.sha(OUT/name)==h,'Changed completed result '+name)
  return {'id':stem,'resumed':True}
 start=time.perf_counter();ins,poly,seed,rejected=generate(family,number);n=9 if family=='constructed' else 6
 original=q.truth_values(poly,n);checked(original.max()>original.min(),'Constant objective')
 moments=solve_sa_rlt_level2(poly,n_original=n);bank,fullmeta=banks(poly,n,seed);rows={};representations={}
 for domain,candidates in bank.items():
  for codes in candidates:
   cid=key(codes);rep=representation(poly,n,codes);probs=probabilities(rep,moments)
   encoded=q.truth_values(rep.polynomial,rep.n_qubits).reshape((-1,1<<n))
   checked(np.max(abs(encoded.min(0)-original))<1e-10,'Pointwise exactness')
   checked(np.all(np.sum(np.isclose(encoded,original[None,:],atol=1e-10,rtol=0),axis=0)==1),'Unique lift')
   checked(np.max(abs(encoded-np.rint(encoded)))<1e-10,'Integer energy required for gamma period')
   rows[cid]={'id':cid,'domain':domain,'actions':list(codes),'resources':compile_candidate(rep,probs),'probabilities':probs,'raw_probabilities':probabilities(rep,moments,False),'raw_diagnostic':diagnostic(poly,rep,probabilities(rep,moments,False)),'prepared_diagnostic':diagnostic(poly,rep,probs)}
   representations[cid]=rep
 ids={k:[key(a) for a in v] for k,v in bank.items()}
 primary={domain:choose(rows,ids[domain],CFG['primary_budget']) for domain in ids}
 guard={policy:choose(rows,ids['mixed'],{'Q':12},policy) for policy in CFG['guardrail']['policies']}
 capacity={domain:choose(rows,ids[domain],{'Q':12}) for domain in ids}
 gridselections=[];required={x for x in [*primary.values(),*guard.values(),*capacity.values()] if x is not None}
 for values in itertools.product(*[CFG['secondary_budgets'][k] for k in ['Q','G','D','M']]):
  budget=dict(zip(['Q','G','D','M'],values));selected={d:choose(rows,ids[d],budget) for d in ids}
  required.update(x for x in selected.values() if x is not None)
  full_excluded=all(f['logical_Q']>budget['Q']+1e-9 or f['M']>budget['M']+1e-9 for f in fullmeta)
  gridselections.append({'budget':budget,'selected':selected,'full_endpoint_resource_excluded':full_excluded})
 rng=np.random.default_rng(q.derive_seed(seed,'diagnostic_probes'));probes=[ids['mixed'][int(i)] for i in rng.choice(len(ids['mixed']),min(CFG['diagnostic_probe_count'],len(ids['mixed'])),replace=False)]
 required.update(probes)
 scan_ids={x for x in [*capacity.values(),*guard.values(),*primary.values()] if x is not None}
 starts=np.random.default_rng(q.derive_seed(seed,'common_parameter_starts')).uniform([0,0],[2*math.pi,math.pi],size=(3,2))
 scan_cfg={'scan_gamma_points':65,'scan_beta_points':65,'scan_refinement_starts':4,'scan_refinement_max_evaluations':240}
 names=[];counts={'compiler_calls':len(rows),'equal_effort_calls':0,'scan_grid_calls':0,'scan_refinement_calls':0}
 for cid in sorted(required):
  row=rows[cid];sim=q.Simulation(poly,representations[cid],row['probabilities']);row['p0']=sim.p0
  result=q.optimise(sim,starts,'Nelder-Mead',120,q.derive_seed(seed,'completion'))
  result['normalized_gap']=(result['objective']-float(original.min()))/float(np.ptp(original));row['equal_effort']=result;counts['equal_effort_calls']+=result['calls']
  if cid in scan_ids:
   result,grid=q.scanned_refinement(sim,scan_cfg);result['normalized_gap']=(result['objective']-float(original.min()))/float(np.ptp(original));row['scan_refined']=result
   gridname=f'grids/{stem}_{hashlib.sha256(cid.encode()).hexdigest()[:16]}.npz';io.atomic_grid(OUT/gridname,grid);row['grid_file']=gridname;names.append(gridname)
   counts['scan_grid_calls']+=result['grid_calls'];counts['scan_refinement_calls']+=result['calls']
 p0=rows[ids['native'][0]]['p0'];originalp=rows[ids['native'][0]]['probabilities']
 rounded=[int(moments.singles[i]>.5) for i in range(1,n+1)]
 samplebits=np.random.default_rng(q.derive_seed(seed,'classical_sampling')).random((2048,n))<np.asarray(originalp)
 samplevals=original[samplebits.astype(int)@(2**np.arange(n))]
 data={'id':stem,'family':family,'number':number,'seed':seed,'signature':signature(poly),'n':n,'instance':ins,'rejected_generation_attempts':rejected,'polynomial':[[list(s),float(c)] for s,c in sorted(poly.items())],'optimum':float(original.min()),'maximum':float(original.max()),'freeze_sha256':io.sha(ROOT/'freeze.json'),'moments':{'singles':{str(k):float(v) for k,v in moments.singles.items()},'pairs':{str(k):float(v) for k,v in moments.pairs.items()},'status':moments.status,'objective':float(moments.objective)},'classical':{'p0':p0,'rounding':float(q.evaluate_pubo(poly,rounded)),'sampling_mean':float(samplevals.mean()),'sampling_best':float(samplevals.min()),'sample_count':2048},'candidate_ids':ids,'full_logical_enumeration':fullmeta,'primary_selection':primary,'capacity_selection':capacity,'guardrail_selection':guard,'secondary_grid':gridselections,'diagnostic_probes':probes,'rows':rows,'calls':counts,'elapsed_seconds':time.perf_counter()-start}
 io.atomic_json(path,data);names.append(path.relative_to(OUT).as_posix())
 io.atomic_json(marker,{'freeze_sha256':data['freeze_sha256'],'files':{name:io.sha(OUT/name) for name in names}})
 return {'id':stem,'evaluated_candidates':len(required),'scanned_candidates':len(scan_ids),'seconds':round(data['elapsed_seconds'],2),'calls':counts}

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['freeze','run']);p.add_argument('--output',type=Path);p.add_argument('--workers',type=int,default=4);p.add_argument('--resume',action='store_true');a=p.parse_args()
 if a.command=='freeze':
  checked(not (ROOT/'freeze.json').exists(),'Freeze exists')
  checked(not (ROOT/'results').exists(),'Do not freeze after result generation')
  io.atomic_json(ROOT/'freeze.json',{'utc':io.utc(),'protocol_id':CFG['id'],'source_hashes':{x.relative_to(ROOT).as_posix():io.sha(x) for x in source_files()},'environment':io.runtime_environment(),'note':'Locally prospective. Tests use only predetermined synthetic fixtures, not new cohort outcomes.'});print('FROZEN: '+io.sha(ROOT/'freeze.json'));return
 f=validate_freeze();checked(a.output is not None,'--output required');out=a.output.resolve()
 checked(out!=ROOT and not out.is_relative_to(ROOT/'vendor'),'Choose separate output directory')
 descriptor={'freeze_sha256':io.sha(ROOT/'freeze.json'),'runtime':io.runtime_environment(),'jobs':CFG['families']}
 if out.exists():
  checked(a.resume,'Output exists; use --resume');checked(io.read(out/'RUN_CONTEXT.json')['descriptor']==descriptor,'Different code/scope/environment')
 else:
  checked(not a.resume,'Missing resume directory');out.mkdir(parents=True);io.atomic_json(out/'RUN_CONTEXT.json',{'descriptor':descriptor,'started_utc':io.utc(),'status':'PREPARED'})
 checked(a.workers>0,'workers must be positive')
 with io.exclusive_lock(out/'RUNNING.lock'):
  context=io.read(out/'RUN_CONTEXT.json');context['status']='RUNNING';io.atomic_json(out/'RUN_CONTEXT.json',context)
  try:
   jobs=[(family,i) for family,n in CFG['families'].items() for i in range(n)]
   with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers,initializer=initialise,initargs=(str(out),)) as pool:
    fs=[pool.submit(measure_instance,*job) for job in jobs]
    for future in concurrent.futures.as_completed(fs):print(json.dumps(future.result()),flush=True)
   context.update(status='COMPLETED',completed_utc=io.utc());io.atomic_json(out/'RUN_CONTEXT.json',context)
  except BaseException as exc:
   context.update(status='INTERRUPTED',error=f'{type(exc).__name__}: {exc}');io.atomic_json(out/'RUN_CONTEXT.json',context);raise
 print('ITERATION_EXECUTION: COMPLETED')
if __name__=='__main__':main()
