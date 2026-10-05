import copy
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scripts import multiseed_experiment as m
from scripts.multiseed_validation import validate_rows, validate_resources, retention_metrics, selector_metrics, task_id
from scripts.multiseed_scheduler import execute_batches

def hung_worker(connection, *args):
    time.sleep(10)

def candidate(cid='a', category='native', width=6):
    return {'candidate_id':cid, 'instance_id':'i', 'topology':'line12', 'synthesis':'canonical',
            'logical_Q':str(width), 'n_aux':'0', 'maximum_penalty':'0', 'category':category,
            'family':'max3sat', 'input_hash':'input'}

def task(cid='a', seed=1729):
    t = {k:v for k,v in candidate(cid).items() if k in ('candidate_id','instance_id','topology','synthesis')}
    t['seed'] = seed
    t['task_id'] = task_id(t)
    t['candidate'] = candidate(cid)
    return t

def result(cid='a', seed=1729, g=4, status='compiled'):
    r = {k:v for k,v in task(cid,seed).items() if k != 'candidate'}
    resources = {'Q':6,'G':g,'D':24,'M':0,'J':(g/160+24/120)/4}
    r.update(status=status, resources_json=json.dumps(resources), circuit_sha256='a'*64)
    return r

class RepairRegressionTests(unittest.TestCase):
    def test_coverage_missing_duplicate_extra_nonterminal(self):
        tasks = [task('a'), task('b')]
        for rows in ([result('a')], [result('a'),result('a')], [result('x'),result('y')], [result('a'), result('b',status='pending')]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_rows(tasks,rows,[candidate('a'),candidate('b')])
        self.assertTrue(validate_rows(tasks,[result('a'),result('b')],[candidate('a'),candidate('b')])['coverage_complete'])

    def test_wrong_id_rejected(self):
        r=result(); r['task_id']='wrong'
        with self.assertRaises(ValueError): validate_rows([task()],[r],[candidate()])

    def test_cache_running_and_pending_rejected(self):
        cfg={'config_hash':'c','implementation_hash':'i'}
        for state, rowstatus in [('running','compiled'),('pass','pending')]:
            payload={**cfg,'status':state,'rows':[result(status=rowstatus)]}
            with self.assertRaises((RuntimeError,ValueError)):
                m.validate_cached_batch(payload,cfg,tasks=[task()],candidates=[candidate()])

    def test_invalid_resources_never_certify_true(self):
        budgets=np.array([[6,4,24,0]],float)
        for d, value in [('G',float('nan')),('M',float('inf')),('D',-1),('Q',6.5),('G',1.5),('Q',13)]:
            r=result(); v=json.loads(r['resources_json']); v[d]=value; r['resources_json']=json.dumps(v)
            with self.subTest(d=d,value=value):
                with self.assertRaises(ValueError): validate_resources(v)
                classes,_=m.classify_layer([candidate('m','strict_mixed'),candidate()],{'m':[result('m')],'a':[r]},budgets)
                self.assertEqual(classes[0],m.UNKNOWN)

    def test_capacity_requires_evidence(self):
        for width, expected in [(13,m.TRUE),(6,m.UNKNOWN)]:
            classes,_=m.classify_layer([candidate('m','strict_mixed'),candidate(width=width)],
                {'m':[result('m')],'a':[result(status='width_exceeded')]}, np.array([[6,4,24,0]],float))
            self.assertEqual(classes[0],expected)

    def test_retention_set_definitions(self):
        base=np.ones(654,dtype=np.uint8)
        others=np.zeros(654,dtype=np.uint8); others[:36]=1
        metrics=retention_metrics({1729:base,2718:others,31415:base,57721:base,65537:base})
        self.assertEqual(metrics['classification'],'partial')
        self.assertEqual(metrics['lost_in_any_other_seed'],618)
        self.assertEqual(metrics['lost_in_all_other_seeds'],0)
        self.assertEqual(retention_metrics({1729:np.zeros(1),2718:np.ones(1)})['classification'],'empty_baseline')

    def test_selector_fixed_winner_coverage_and_missing(self):
        cs=[candidate('a'),candidate('b')]; budgets=np.array([[6,4,24,0],[6,8,24,0]],float)
        base={'a':[result('a',g=4)],'b':[result('b',g=8)]}
        current={'a':[result('a',g=4)],'b':[result('b',g=0)]}
        x=selector_metrics(cs,base,current,budgets)
        self.assertEqual((x['selected_candidate_id'],x['baseline_selected_candidate_id'],x['baseline_selected_feasible']),('b','a','TRUE'))
        current['a']=[result('a',g=8)]
        self.assertEqual(selector_metrics(cs,base,current,budgets)['baseline_coverage_retention'],0.5)
        current.pop('a')
        self.assertEqual(selector_metrics(cs,base,current,budgets)['baseline_selected_feasible'],'UNKNOWN')
        self.assertEqual(selector_metrics(cs,base,current,np.array([[6,0,24,0]]))['baseline_selected_feasible'],'N/A')

    def test_config_tampering_rejected_before_files_read(self):
        from scripts.multiseed_validation import validate_config
        from scripts.multiseed_p1 import PROTOCOL
        cfg={'compiler':{'sabre_trials':8},'config_hash':'cfg','compiler_implementation_hash':'compiler','p1_protocol':PROTOCOL}; cfg['config_hash']=m.stable_digest(cfg)
        cfg['compiler']['sabre_trials']=999
        with self.assertRaisesRegex(ValueError,'content hash'):
            validate_config(Path('absent'),cfg)

    def test_p1_actual_entry_rejects_errors_missing_repeat_seed_and_invalid(self):
        cs=[candidate('a'),{**candidate('b'),'instance_id':'j','family':'pair_star_isolated'}]
        samples=[{'selected':'true','family':c['family'],'instance_id':c['instance_id'],'selection_hash':'0'} for c in cs]
        from scripts.multiseed_p1 import PROTOCOL
        cfg={'compiler':{'sabre_trials':8},'config_hash':'cfg','compiler_implementation_hash':'compiler','p1_protocol':PROTOCOL}
        def worker(job):
            _,tasks,seed,_,attempt=job
            rows=[]
            for t in tasks:
                r=result(t['candidate_id'],seed)
                r.update({k:t[k] for k in ('instance_id','task_id')})
                r.update(observation_id=attempt+'_'+t['task_id'],worker_pid='123',worker_started_utc='2026-01-01T00:00:00Z',trace_json=json.dumps({'declared':{'seed':seed,'trials':8,'heuristic':'decay'},'observed_passes':['SabreSwap'],'observed_sabre':[{'seed':seed,'trials':8,'heuristic':'decay'}],'semantic':{'status':'pass'}}))
                if mode=='errors': r['status']='compile_error'
                if mode=='invalid': r['resources_json']=r['resources_json'].replace('"G": 4','"G": NaN')
                if mode=='repeat' and 'repeat_b' in attempt: continue
                if mode=='seed' and seed==2718: continue
                rows.append(r)
            return {'rows':rows}
        for mode in ('errors','invalid','repeat','seed','good'):
            with self.subTest(mode=mode), patch.object(m,'load_run',return_value=(cfg,samples,cs,[])), patch.object(m,'require_current_compiler'), patch.object(m,'preflight_job',side_effect=lambda job,cfg:worker(job)), patch.object(m,'write_csv'), patch.object(m,'atomic_json'), patch.object(m,'sha256_file',return_value='hash'), patch.object(m,'execution_identity',return_value={}):
                if mode=='good': m.p1(Path('nonexistent_p1'))
                else:
                    with self.assertRaises(RuntimeError): m.p1(Path('nonexistent_p1'))

    def test_formal_entry_rejects_poisoned_cache(self):
        cfg={'config_hash':'c','implementation_hash':'i'}
        payload={**cfg,'status':'running','rows':[result(status='pending')]}
        with patch.object(m,'load_run',return_value=(cfg,[],[candidate()],[task()])), patch.object(m,'candidate_batches',return_value=[('batch',[task()],1729,8,'formal')]), patch.object(Path,'is_file',return_value=True), patch.object(m,'read_json',return_value=payload):
            with self.assertRaises(RuntimeError): m.run_formal(Path('unused'))

    def test_live_task_timeout_is_killed(self):
        started=time.monotonic()
        rows=list(execute_batches(Path('.'),[('batch',[task()],1729,8,'test')],1,0.3,target=hung_worker))
        self.assertEqual(rows[0][1]['rows'][0]['status'],'timeout')
        self.assertLess(time.monotonic()-started,5)

    def test_audit_entry_rejects_missing_duplicate_and_unexpected(self):
        import io
        import csv
        for observed in ([result('a')],[result('a'),result('a')],[result('x'),result('y')]):
            buffer=io.StringIO(); writer=csv.DictWriter(buffer,fieldnames=list(observed[0])); writer.writeheader(); writer.writerows(observed)
            writes={}
            with self.subTest(observed=observed), patch.object(m,'load_run',return_value=({},[],[candidate('a'),candidate('b')],[task('a'),task('b')])), patch.object(Path,'open',side_effect=lambda *a,**k:io.StringIO(buffer.getvalue())), patch.object(Path,'is_file',return_value=True), patch.object(Path,'rglob',return_value=[]), patch.object(m,'read_json',return_value={'status':'pass'}), patch.object(m,'atomic_json',side_effect=lambda path,value:writes.update({path.name:value})), patch.object(m,'atomic_write'), patch.object(m,'write_csv'), patch.object(m,'sha256_file',return_value='hash'):
                with self.assertRaises(RuntimeError): m.audit(Path('unused'))
            self.assertEqual(writes['AUDIT.json']['status'],'fail')
            self.assertFalse(writes['AUDIT.json']['coverage_complete'])

    def test_seed_figure_uses_corresponding_seed_details(self):
        summaries=[{'seed':s,'true_cells':int(i<j)} for j,s in enumerate(m.SEEDS,1) for i in range(5)]
        with patch.object(m,'svg_bar_chart') as chart, patch.object(m,'write_csv'), patch.object(Path,'mkdir'):
            m.generate_figures(Path('unused'),summaries,[],[])
        presence=chart.call_args_list[1].args
        self.assertEqual(presence[1],[str(s) for s in m.SEEDS])
        self.assertEqual(presence[2],[0.2,0.4,0.6,0.8,1.0])

    def test_yaml_contains_entire_config(self):
        writes={}
        with patch.object(m,'read_json',return_value={'qiskit':'2.5.2'}), patch.object(m,'sha256_file',return_value='hash'), patch.object(m,'implementation_hash',return_value='impl'), patch.object(m,'compiler_identity',return_value='compiler'), patch.object(m,'git_head',return_value=None), patch.object(m,'atomic_json',side_effect=lambda path,value:writes.update({path.name:value})):
            m.write_config(Path('unused'),Path('source'),[],[])
        self.assertEqual(writes['experiment_config.json'],writes['experiment_config.yaml'])

    def test_changed_compiler_cannot_create_legacy_tasks(self):
        import importlib.metadata
        with patch.object(importlib.metadata,'version',return_value='2.5.2'), patch.object(m,'compiler_identity',return_value='new'):
            with self.assertRaisesRegex(RuntimeError,'implementation changed'):
                m.require_current_compiler(Path('unused'),{'compiler':{'qiskit_version_from_freeze':'2.5.2'},'compiler_implementation_hash':'old'})

if __name__=='__main__': unittest.main()
