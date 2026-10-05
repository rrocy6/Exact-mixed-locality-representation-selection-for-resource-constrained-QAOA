import math,tempfile,unittest
from pathlib import Path
import numpy as np
import study as s
from audit import circuit_check
class Tests(unittest.TestCase):
 def setUp(self):self.poly={():2,(1,):-1,(1,2,3):2,(1,2,4):-3};self.rep=s.representation(self.poly,4,(0,-1));self.probs=[.2,.3,.4,.5,.21]
 def test_product_formula_and_exact_lift(self):
  rep=self.rep;idx=np.arange(1<<rep.n_qubits);bits=(idx[:,None]>>np.arange(rep.n_qubits))&1
  enc=s.q.truth_values(rep.polynomial,rep.n_qubits);original=np.tile(s.q.truth_values(self.poly,4),1<<rep.n_auxiliary)
  for probabilities in [self.probs,[0.,1.,.5,.7,1.]]:
   probabilities=np.array(probabilities);weights=np.prod(np.where(bits,probabilities,1-probabilities),1)
   self.assertAlmostEqual(float(weights@(enc-original)),s.diagnostic(self.poly,rep,probabilities)['excess'],places=12)
  self.assertTrue(np.array_equal(enc.reshape((-1,16)).min(0),original[:16]))
 def test_compiled_full_ansatz_layout_and_mixer(self):
  for codes in [(-1,-1),(0,-1),(0,0)]:
   rep=s.representation(self.poly,4,codes);probs=[.2,.3,.4,.5]+[.21]*rep.n_auxiliary
   fidelity,_=circuit_check(self.poly,rep,probs);self.assertGreater(fidelity,1-1e-9)
 def test_small_domains_equal_budget(self):
  bank,allfull=s.banks(self.poly,4,73)
  self.assertEqual(len(bank['full']),len(bank['mixed']));self.assertEqual(len(bank['full']),6);self.assertEqual(len(allfull),9)
 def test_guardrail_no_fallback(self):
  rows={'a':{'resources':{'Q':8,'J':1},'actions':[0,-1],'raw_diagnostic':{'normalized':.03},'prepared_diagnostic':{'normalized':.01}}}
  self.assertIsNone(s.choose(rows,['a'],{'Q':12},'raw'));self.assertEqual(s.choose(rows,['a'],{'Q':12},'prepared'),'a')
  self.assertIsNone(s.choose(rows,['a'],{'Q':7},'none'))
 def test_optimization_budget_and_saved_parameters(self):
  sim=s.q.Simulation(self.poly,self.rep,self.probs);out=s.q.optimise(sim,[[.2,.3],[.7,.4],[1.,.2]],'Nelder-Mead',20,19)
  self.assertEqual(out['calls'],60);self.assertAlmostEqual(sim.objective(out['parameters']),out['objective'],places=12)
  self.assertTrue(all(len(t['parameters'])==2 for t in out['trace']))
if __name__=='__main__':unittest.main(verbosity=2)
