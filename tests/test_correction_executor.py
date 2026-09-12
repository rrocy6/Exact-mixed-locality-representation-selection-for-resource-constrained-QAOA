import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import yaml

import warmstart_correction as executor
from postprocess_correction import aggregate, interval, tex_table, METRICS
from urss_pipeline import e3_qaoa as e3, e4_warmstart as e4
from urss_pipeline.e2_resources import _evaluate_design


class CorrectionExecutorTests(unittest.TestCase):
    def test_serialized_task_array_is_accepted_and_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'TASK_INPUTS.json'
            entries = [{'expected': {'study': 'targeted'}, 'source': {}}]
            path.write_text(json.dumps(entries), encoding='utf-8')
            self.assertEqual(executor.read_task_inputs(path), entries)
            path.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                executor.read_task_inputs(path)

    @classmethod
    def setUpClass(cls):
        cls.config=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/experiment_config_v2.yaml').read_text())
        poly={(1,):-1,(1,2,3):2}
        cls.design=e3.QAOADesign('selective',None,_evaluate_design(poly,n_original=3,actions=((1,2),),
            selector=cls.config['selector'],apply_qaoa_hard_limits=True))
        cls.data=e3.statevector_data(poly,cls.design.evaluation.representation,optimum_original=-1)
        cls.moments=e4.RelaxationMoments(-1,{1:.2,2:.7,3:.4},{(1,2):.1,(1,3):.1,(2,3):.3},'optimal','synthetic',0)
        cls.spec=e4.warm_start_specs(cls.design,cls.moments,clipping_delta=.05)[2]

    def entry(self,p=1):
        spec=self.spec
        initial,seed=e3._initial_parameters(instance_id='synthetic',design_id=self.design.design_id,
            representation='selective',random_rep_seed=None,budget_key='equal_layer_p'+str(p),restart_id=0,
            optimizer_seed=2026082731,p=p,qaoa_config=self.config['qaoa'])
        task={'instance_id':'synthetic','family':'max3sat','study':'targeted' if p else 'original_e4',
              'design_id':self.design.design_id,'representation':'selective','random_rep_seed':'',
              'p':str(p),'budget_mode':'equal_layer','budget_key':'equal_layer_p'+str(p),
              'compiled_2q_budget':'','compiled_2q_gates_per_layer':'8','actual_2q_gates':str(8*p),
              'warm_start_policy':spec.policy,'pair_closure':spec.pair_closure,'restart_id':'0',
              'optimizer_seed':'2026082731','circuit_seed':'2026082741','measurement_seed':'2026082751',
              'initialization_seed':str(seed),'initial_parameters_sha256':e3._hash_parameters(initial),
              'marginal_set_sha256':e4._moment_digest(self.moments),'task_id':'synthetic_task',
              'source_config_hash':'source_cfg','source_code_commit':'source_commit',
              'source_relative_path':'synthetic.csv','source_csv_row_number':'2'}
        source=dict(task,code_commit='source_commit',manifest_hash='old_manifest',e3_summary_hash='old_summary',
                    optimized_parameters_json=json.dumps(initial),status='pass',evaluations=60)
        source.update(e3.statevector_metrics(e4._simulate(self.data,spec,initial,p),self.data))
        return {'expected':task,'source':source,'design_key':'synthetic'}

    def worker(self,entry,optimize=None):
        binding={'corrected_code_commit':'new_commit'}
        resolved=(self.design,self.moments,self.data,{(self.spec.policy,self.spec.pair_closure):self.spec})
        with patch.object(executor,'load_design',return_value=resolved), \
             patch.object(executor,'read_json',return_value={'studies':{'targeted':{'raw_source_sha256':'old_hash'},'original_e4':{'raw_source_sha256':'old_hash'}}}), \
             patch.object(executor,'sha',return_value='binding_hash'):
            if optimize is not None:
                with patch.object(e4,'optimize_warmstart_run',side_effect=optimize):
                    return executor.task_worker('/synthetic',entry,self.config,binding)
            return executor.task_worker('/synthetic',entry,self.config,binding)

    def test_fresh_task_keeps_full_trace_and_new_provenance(self):
        row,attempts=self.worker(self.entry())
        self.assertEqual(row['task_outcome'],'RERUN_PASS')
        self.assertEqual(row['code_commit'],'new_commit')
        self.assertEqual(row['source_code_commit'],'source_commit')
        self.assertEqual(len(attempts[0]['trace']),61)

    def test_zero_layer_retains_source_commit_and_accounting(self):
        row,attempts=self.worker(self.entry(0))
        self.assertEqual(row['task_outcome'],'REUSED_VALIDATED')
        self.assertEqual(row['code_commit'],'source_commit')
        self.assertEqual(row['validation_commit'],'new_commit')
        self.assertEqual(row['current_evaluations'],1)
        self.assertEqual(row['effective_optimization_evaluations'],0)

    def test_retry_exact_input_once_preserves_both_attempts(self):
        original=e4.optimize_warmstart_run
        calls=[]
        def fail_once(**kwargs):
            calls.append(kwargs)
            if len(calls)==1:raise RuntimeError('injected technical failure')
            return original(**kwargs)
        row,attempts=self.worker(self.entry(),fail_once)
        self.assertEqual(row['task_outcome'],'RERUN_PASS')
        self.assertEqual([a['status'] for a in attempts],['FAILED','RERUN_PASS'])
        self.assertEqual(calls[0],calls[1])

    def test_two_failures_are_not_hidden(self):
        def failed(**kwargs):raise RuntimeError('injected permanent failure')
        row,attempts=self.worker(self.entry(),failed)
        self.assertEqual(row['task_outcome'],'FAILED')
        self.assertEqual(len(attempts),2)

    def test_strict_l2_null_control_and_wrong_sign_rejection(self):
        result=executor.strict_null(self.data)
        self.assertLessEqual(result['phase_aligned_l2_max'],1e-12)
        original=e4._apply_matched_mixer
        with patch.object(e4,'_apply_matched_mixer',side_effect=lambda state,beta,prob:original(state,-beta,prob)):
            with self.assertRaises(e4.E4WarmStartError):executor.strict_null(self.data)


class CorrectionStatisticsTests(unittest.TestCase):
    def rows(self):
        result=[]
        for instance,offset in [('a',0),('b',2)]:
            for draw in range(5):
                for restart in range(3):
                    for policy,closure,shift in [('cold_start','not_applicable',0),('original_and_auxiliary_variables','sa_rlt_level_2_pair_moments',-1-offset)]:
                        row={'study':'original_e4','family':'max3sat','instance_id':instance,
                             'representation':'matched_random_selective','random_rep_seed':str(draw),
                             'budget_key':'equal_2q_budget_128','n_aux':'1','restart_id':str(restart),
                             'p':str(draw%2),'warm_start_policy':policy,'pair_closure':closure,'task_outcome':'RERUN_PASS'}
                        row.update({metric:10+draw+restart+shift for metric in METRICS})
                        result.append(row)
        return result

    def test_hierarchy_keeps_two_instances_not_thirty_restarts(self):
        draws,instances,paired,desc,summary=aggregate(self.rows())
        chosen=next(r for r in summary if r['depth_stratum']=='all_scheduled' and r['metric']=='original_objective_mean')
        self.assertEqual(chosen['n_instances'],2)
        self.assertAlmostEqual(chosen['mean'],-2)
        self.assertAlmostEqual(chosen['ci95_high'],-2+12.706204736432095,places=7)
        self.assertEqual({r['draw_count'] for r in instances if r['depth_stratum']=='all_scheduled'},{5})
        self.assertEqual({r['draw_count'] for r in instances if r['depth_stratum']=='positive_depth_only'},{2})

    def test_duplicate_restart_blocks_aggregation(self):
        rows=self.rows();rows.append(rows[0])
        with self.assertRaises(ValueError):aggregate(rows)

    def test_one_instance_ci_is_not_estimable(self):
        result=interval([1])
        self.assertEqual(result['n_instances'],1)
        self.assertIsNone(result['ci95_low'])

    def test_tex_rows_have_two_backslashes(self):
        table=tex_table([dict(family='max3sat',budget_key='equal_layer_p1',n_instances=10,mean=-1,ci95_low=-2,ci95_high=0)],'tab:test','Test')
        row=next(line for line in table.splitlines() if line.startswith('Max-3SAT'))
        self.assertTrue(row.endswith('\\\\'))


if __name__=='__main__':unittest.main(verbosity=2)
