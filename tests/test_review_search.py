import math,unittest
from pathlib import Path
from itertools import combinations
from fractions import Fraction
from unittest.mock import patch
import yaml
from urss_pipeline.fibre_selector import FibreMoments,enumerate_fibre_candidates
from urss_pipeline.review_search import beam_select_fibre_design,branch_and_bound_fibre_optimum,_rank_group,ranking,_setup

class ReviewSearchTests(unittest.TestCase):
    def setUp(self):
        self.selector=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/experiment_config_v2.yaml').read_text())['selector']
        self.selector['fibre_risk']['threshold_tau']=1
        self.selector['feasibility_limits']['maximum_two_qubit_gates_per_cost_layer']=16
        self.poly={(1,2,3):Fraction(1),(1,2,4):Fraction(1)}
        self.m=FibreMoments(0,{i:.5 for i in range(1,5)},{p:.25 for p in combinations(range(1,5),2)},'test','test',0,0,'test')
        self.kw=dict(n_original=4,selector=self.selector,moments=self.m,apply_qaoa_hard_limits=True)
    def optimum(self):
        return min(c.score for c in enumerate_fibre_candidates(self.poly,**self.kw) if c.feasible)
    def test_native_infeasible_certifier_finds_reduced_optimum(self):
        c=branch_and_bound_fibre_optimum(self.poly,**self.kw)
        self.assertTrue(c.proof_complete);self.assertEqual(c.final_lower_bound,self.optimum())
        self.assertEqual(c.final_upper_bound,self.optimum());self.assertTrue(math.isinf(c.trace[0]['upper_bound']))
    def test_wide_beam_matches_exhaustive_when_native_is_infeasible(self):
        self.selector['search_settings']['beam_width']=64
        self.assertEqual(beam_select_fibre_design(self.poly,**self.kw).evaluation.score,self.optimum())
    def test_interrupted_frontiers_bracket_exhaustive_optimum(self):
        exact=self.optimum()
        for limit in [0,1,2,4,8,12,20]:
            c=branch_and_bound_fibre_optimum(self.poly,**self.kw,max_nodes=limit)
            self.assertLessEqual(c.final_lower_bound,exact);self.assertGreaterEqual(c.final_upper_bound,exact)
            if not c.proof_complete:self.assertGreater(len(c.frontier),0)
    def test_evaluation_budget_and_zero_evaluations_keep_frontier(self):
        for limit in [0,1,2,3]:
            c=branch_and_bound_fibre_optimum(self.poly,**self.kw,max_evaluations=limit)
            self.assertLessEqual(c.final_lower_bound,self.optimum());self.assertGreaterEqual(c.final_upper_bound,self.optimum())
        c=branch_and_bound_fibre_optimum(self.poly,**self.kw,max_evaluations=0)
        self.assertIsNone(c.result);self.assertFalse(c.proof_complete)
    def test_stop_callback_and_zero_time_return_no_false_certificate(self):
        for controls in [dict(stop_requested=lambda:True),dict(time_limit_sec=0)]:
            c=branch_and_bound_fibre_optimum(self.poly,**self.kw,**controls)
            self.assertFalse(c.proof_complete);self.assertIsNone(c.result);self.assertTrue(math.isinf(c.final_upper_bound))
    def test_all_infeasible_reports_no_result(self):
        self.selector['feasibility_limits']['maximum_qubits']=3
        c=branch_and_bound_fibre_optimum(self.poly,**self.kw)
        self.assertTrue(c.proof_complete);self.assertEqual(c.termination_reason,'infeasible');self.assertIsNone(c.result)
    def test_empty_design_space_native_case(self):
        c=branch_and_bound_fibre_optimum({},**self.kw)
        self.assertTrue(c.proof_complete);self.assertEqual(c.final_upper_bound,0)
        self.assertEqual(beam_select_fibre_design({},**self.kw).actions,())
    def test_zero_range_coordinates_add_no_arbitrary_boundary_priority(self):
        from types import SimpleNamespace
        items=[SimpleNamespace(actions=(a,),pareto_vector=(0,0,0,0,0)) for a in [None,(1,2),(1,3)]]
        self.assertEqual(set(_rank_group(items).values()),{(0,0.0)})
    def test_precompilation_ranking_uses_unscaled_capacity(self):
        self.selector['feasibility_limits']['maximum_qubits']=4
        _,_,_,_,_,_,evaluate=_setup(self.poly,**self.kw)
        c=evaluate(((1,2),None));r,rejected=ranking([c],self.selector,4,True)
        self.assertIn(c.actions,rejected);self.assertTrue(math.isinf(r[c.actions][0]))
    def test_certificate_bounds_monotone_and_tolerance_reported(self):
        c=branch_and_bound_fibre_optimum(self.poly,**self.kw,trace_interval_nodes=1)
        self.assertTrue(all(a['lower_bound']<=b['lower_bound'] for a,b in zip(c.trace,c.trace[1:])))
        self.assertTrue(all(a['upper_bound']>=b['upper_bound'] for a,b in zip(c.trace,c.trace[1:])))
        self.assertEqual(c.numeric_tolerance,1e-9)
    def test_negative_resource_weight_rejected(self):
        self.selector['weights']['two_qubit_gate_count']=-1
        with self.assertRaises(ValueError):branch_and_bound_fibre_optimum(self.poly,**self.kw)
    def test_keyboard_interrupt_restores_frontier(self):
        from urss_pipeline import review_search
        original=review_search._candidate;calls=0
        def interrupted(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise KeyboardInterrupt()
            return original(*args,**kwargs)
        with patch.object(review_search,'_candidate',interrupted):c=branch_and_bound_fibre_optimum(self.poly,**self.kw)
        self.assertEqual(c.termination_reason,'keyboard_interrupt');self.assertTrue(c.frontier)
        self.assertLessEqual(c.final_lower_bound,self.optimum());self.assertGreaterEqual(c.final_upper_bound,self.optimum())

if __name__=='__main__':unittest.main()
