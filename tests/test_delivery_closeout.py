"""Regression checks for the concrete closeout defects and disclosure."""
import unittest
from fractions import Fraction
from pathlib import Path

import yaml

from run_delivery_closeout import beam_counterexample, independent_pauli, kappa
from urss_pipeline.reference_compiler import compile_reference
from urss_pipeline.e5_regime import classify_effect


class DeliveryCloseoutTests(unittest.TestCase):
    def test_kappa_excludes_identity_and_is_constant_shift_invariant(self):
        p={(1,):Fraction(2),(2,):Fraction(8)}
        base=compile_reference(p,n_qubits=2)
        shifted=compile_reference({**p,():Fraction(10000)},n_qubits=2)
        self.assertEqual(base.coefficient_dynamic_range,4)
        self.assertEqual(shifted.coefficient_dynamic_range,4)
        self.assertEqual(base.cnot_stream,shifted.cnot_stream)
        self.assertEqual(base.two_qubit_depth,shifted.two_qubit_depth)

    def test_exact_cancellation_and_constant_operator(self):
        p={(1,):Fraction(2),(1,2):Fraction(-4),():Fraction(300)}
        ref=compile_reference(p,n_qubits=2)
        self.assertEqual(ref.pauli,independent_pauli(p))
        self.assertNotIn((1,),ref.pauli)
        self.assertEqual(ref.coefficient_dynamic_range,kappa(independent_pauli(p)))
        self.assertEqual(compile_reference({():8},n_qubits=1).coefficient_dynamic_range,0)
        self.assertEqual(compile_reference({},n_qubits=1).coefficient_dynamic_range,0)

    def test_kappa_invariant_under_nonzero_global_rescaling(self):
        p={(1,):Fraction(2),(2,):Fraction(8),(1,2,3):Fraction(4)}
        a=compile_reference(p,n_qubits=3).coefficient_dynamic_range
        b=compile_reference({s:-7*v for s,v in p.items()},n_qubits=3).coefficient_dynamic_range
        self.assertEqual(a,b)

    def test_little_effect_includes_large_uncertainty(self):
        self.assertEqual(classify_effect(-2,3,.01),'little_effect')
        self.assertEqual(classify_effect(.01,.3,.01),'little_effect')
        self.assertEqual(classify_effect(.011,.3,.01),'help')
        self.assertEqual(classify_effect(-.3,-.011,.01),'hurt')

    def test_infeasible_native_completion_has_feasible_descendant(self):
        root=Path(__file__).resolve().parents[1]
        selector=yaml.safe_load((root/'configs/experiment_config_v2.yaml').read_text())['selector']
        result=beam_counterexample(selector)
        self.assertFalse(result['native_completion_feasible'])
        self.assertTrue(result['completion_feasible'])
        self.assertEqual((result['native_completion_gates'],result['feasible_completion_gates']),(18,16))


if __name__=='__main__':
    unittest.main()
