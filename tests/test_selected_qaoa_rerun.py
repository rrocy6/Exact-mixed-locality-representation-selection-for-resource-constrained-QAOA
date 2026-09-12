import tempfile,unittest
from pathlib import Path
import numpy as np
import run_selected_qaoa_rerun as r
from urss_pipeline.e3_qaoa import StatevectorData

class SelectedRerunTests(unittest.TestCase):
    def test_task_identity_changes_with_hamiltonian_and_budget(self):
        old={'hamiltonian':'a','budget':{'p':2},'policy':'pair'}
        self.assertNotEqual(r.identity(old),r.identity(dict(old,hamiltonian='b')))
        self.assertNotEqual(r.identity(old),r.identity(dict(old,budget={'p':1})))
        self.assertEqual(r.identity(old),r.identity(dict(reversed(list(old.items())))))

    def test_pair_identity_retains_draw_restart_and_policy(self):
        row=dict(instance_id='i',representation='matched_random_selective',random_rep_seed='2',budget_key='b',restart_id='0',warm_start_policy='cold_start')
        original=r.row_key(row,'E4')
        for key,value in [('random_rep_seed','3'),('restart_id','1'),('warm_start_policy','pair')]:
            self.assertNotEqual(original,r.row_key(dict(row,**{key:value}),'E4'))

    def test_exactness_checks_every_original_assignment(self):
        from types import SimpleNamespace
        rep=SimpleNamespace(original_width=1)
        data=StatevectorData(np.array([0.,1.,2.,3.]),np.array([0.,1.,0.,1.]),np.array([0.,0.,1.,1.]),np.array([1.,0.,1.,0.]))
        self.assertEqual(r.check_exact(data,rep)['mismatch_count'],0)
        bad=StatevectorData(np.array([0.,1.,-1.,3.]),data.original_energies,data.inconsistent,data.optimum_mask)
        with self.assertRaises(ValueError):r.check_exact(bad,rep)

    def test_inconsistent_minimizer_tie_rejected(self):
        from types import SimpleNamespace
        data=StatevectorData(np.array([0.,1.,0.,3.]),np.array([0.,1.,0.,1.]),np.array([0.,0.,1.,1.]),np.array([1.,0.,1.,0.]))
        with self.assertRaises(ValueError):r.check_exact(data,SimpleNamespace(original_width=1))

    def test_resume_rejects_modified_frozen_input(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'input.json').write_bytes(b'original')
            r.write_json(root/'PLAN.json',{'frozen_files':{'input.json':r.sha(root/'input.json')}})
            (root/'input.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Frozen run input changed'):r.verify(root,root)

    def test_state_and_probability_invalid_results_rejected(self):
        row={m:0. for m in r.METRICS};row.update(status='pass',p=1,optimized_parameters_json='[0.1,0.2]',statevector_norm=1.)
        r.validate_metrics(row)
        for key,value in [('statevector_norm',0.8),('optimum_hit_rate',1.5),('original_objective_mean',float('nan')),('optimized_parameters_json','[]')]:
            with self.assertRaises(ValueError):r.validate_metrics(dict(row,**{key:value}))

    def test_utf8_state_paths_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';record={'source_repo':'C:/Users/rocyz/协作'}
            r.write_json(path,record);self.assertEqual(record,r.read_json(path))

if __name__=='__main__':unittest.main()
