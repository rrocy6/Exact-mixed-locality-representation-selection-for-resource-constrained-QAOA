"""Post-run validation of labelled secondary examples, not a new outcome search."""
from pathlib import Path
import itertools,json
import numpy as np
from qiskit.quantum_info import Statevector
import study as s
B=Path(__file__).resolve().parent;s.validate_freeze();explanation=s.io.read(B/'explanation.json');verified=[]
for w in explanation['certified_witnesses']:
 r=s.io.read(B/'execution/results'/(w['instance']+'.json'));poly={tuple(k):v for k,v in r['polynomial']};n=r['n'];cid=w['selected_mixed_id'];row=r['rows'][cid];rep=s.representation(poly,n,row['actions'])
 resources,circuit=s.compile_candidate(rep,row['probabilities'],True);s.checked(resources==w['mixed_resources'],'Mixed recompilation changed')
 native_id=r['candidate_ids']['native'][0];native=r['rows'][native_id];nr=s.compile_candidate(s.representation(poly,n,native['actions']),native['probabilities']);s.checked(nr==w['native_resources'],'Native recompilation changed')
 angles=row['equal_effort']['parameters'];bound=circuit.assign_parameters({p:angles[0] if p.name=='gamma' else angles[1] for p in circuit.parameters});state=np.asarray(Statevector.from_instruction(bound).data);mapping=circuit.layout.final_index_layout(filter_ancillas=True)
 idx=np.arange(len(state));original_idx=sum(((idx>>mapping[i])&1)*(1<<i) for i in range(n));values=s.q.truth_values(poly,n);mean=float(np.abs(state)**2@values[original_idx]);gap=(mean-r['optimum'])/(r['maximum']-r['optimum']);s.checked(abs(gap-w['mixed_equal_effort_gap'])<1e-9,'Physical-circuit objective mismatch')
 checked_full=0
 for codes in itertools.product(range(3),repeat=len(rep.cubic_order)):
  full=s.representation(poly,n,codes);s.checked(full.n_qubits>w['budget']['Q'] or float(max(full.penalties.values()))>w['budget']['M'],'Unexcluded full endpoint');checked_full+=1
 s.checked(not s.feasible(nr,w['budget']) and s.feasible(resources,w['budget']) and gap<=.2,'Witness feasibility/quality failed')
 verified.append({'instance':w['instance'],'budget':w['budget'],'mixed_resources':resources,'native_resources':nr,'compiled_saved_angle_original_mean':mean,'compiled_saved_angle_normalized_gap':gap,'full_assignments_independently_excluded':checked_full,'main_primary_result_unchanged':True})
s.io.atomic_json(B/'witness_audit.json',{'status':'PASS','additional_recompilations':2*len(verified),'examples':verified,'scope':'Post-run numerical verification of labelled secondary witnesses; no new scientific success threshold'})
print('WITNESS_AUDIT: PASS;',len(verified),'examples')
