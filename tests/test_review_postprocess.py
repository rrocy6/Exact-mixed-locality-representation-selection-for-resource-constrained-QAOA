import unittest
from run_review_postprocess import resource_instances,aggregate_qaoa,stats,RESOURCE,METRICS

class ReviewPostprocessTests(unittest.TestCase):
    def resources(self):
        rows=[]
        for draw,values in enumerate([[0,0,100,100,100],[1]*5,[2]*5,[3]*5,[4]*5]):
            for seed,v in enumerate(values):
                rows.append(dict(topology_id='t',family='f',instance_id='i',representation='matched_random_selective',
                    random_rep_seed=str(draw),design_id=str(draw),transpiler_seed=str(seed),status='pass',failure_kind='',**{k:str(v) for k in RESOURCE}))
        return rows
    def test_seed_median_precedes_design_mean(self):
        _,instances=resource_instances(self.resources())
        self.assertEqual(instances[0]['two_qubit_gates'],22)
    def test_missing_compiler_seed_cannot_silently_change_mean(self):
        with self.assertRaises(ValueError):resource_instances(self.resources()[:-1])
    def test_duplicate_seed_rejected(self):
        rows=self.resources();rows[0]['transpiler_seed']=rows[1]['transpiler_seed']
        with self.assertRaises(ValueError):resource_instances(rows)
    def test_restart_draw_aggregation_keeps_one_instance(self):
        rows=[]
        for draw in range(5):
            for restart in range(3):
                rows.append(dict(family='f',instance_id='i',representation='matched_random_selective',budget_key='b',random_rep_seed=str(draw),
                    design_id=str(draw),restart_id=str(restart),status='pass',**{k:draw+restart for k in METRICS}))
        result=aggregate_qaoa(rows,'budget_key')
        self.assertEqual(len(result),1);self.assertEqual(result[0]['original_objective_mean'],3)
    def test_student_t_uses_instance_df(self):
        s=stats([1,2,3]);self.assertEqual(s['df'],2);self.assertEqual(s['mean'],2)
        self.assertAlmostEqual(s['ci95_high'],4.484137711719546,places=10)
    def test_single_instance_interval_is_unestimable(self):
        self.assertIsNone(stats([1])['ci95_low'])

if __name__=='__main__':unittest.main()
