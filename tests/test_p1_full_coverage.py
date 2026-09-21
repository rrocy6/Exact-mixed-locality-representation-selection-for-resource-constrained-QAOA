"""Regression for full-library coverage, repetition independence and formal gate."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts import multiseed_experiment as m
from scripts import multiseed_p1 as p
from scripts.check_p1_coverage import compare, key
from tests.test_multiseed_repairs import candidate, result

class FullP1Tests(unittest.TestCase):
    def setUp(self):
        self.samples=[{'selected':'true','family':'max3sat','instance_id':'i','selection_hash':'0'}]
        self.cs=[candidate('a'),candidate('b'),{**candidate('c'),'topology':'ring12'}]
        self.rows=[]
        for rep,seed in p.REPETITIONS:
            for c in self.cs:
                r=result(c['candidate_id'],seed);r['topology']=c['topology'];r['task_id']=m.task_id(r)
                r.update(repetition=rep,observation_id=rep+c['candidate_id'],worker_pid=123,worker_started_utc='2026-01-01T00:00:00Z',
                    trace_json=json.dumps({'declared':{'seed':seed,'trials':8,'heuristic':'decay'},'observed_passes':['SabreSwap'],
                        'observed_sabre':[{'seed':seed,'trials':8,'heuristic':'decay'}],'semantic':{'status':'pass'}}))
                self.rows.append(r)
        # Independent test oracle specifies the required Cartesian keys directly.
        self.expected={(c['instance_id'],c['candidate_id'],c['topology'],c['synthesis'],seed,rep) for c in self.cs for seed,rep in [(1729,'repeat_a'),(1729,'repeat_b'),(2718,'single')]}

    def test_complete_valid_full_library_passes(self):
        r=p.validate(m,self.samples,self.cs,self.rows)
        self.assertTrue(r['formal_gate_eligible']);self.assertEqual(r['expected_record_count'],len(self.expected))
        self.assertEqual(compare(self.expected,self.rows)[0]['missing_count'],0)

    def test_missing_candidate_setting_second_repeat_and_duplicate_rejected(self):
        variants=[self.rows[1:],[r for r in self.rows if r['topology']!='ring12'],
                  [r for r in self.rows if r['repetition']!='repeat_b'],self.rows+[self.rows[0]],
                  [r for r in self.rows if r['candidate_id']!='b']]
        for rows in variants:
            with self.subTest(keys=[key(r) for r in rows]):
                with self.assertRaises(ValueError):p.validate(m,self.samples,self.cs,rows)
                check,_=compare(self.expected,rows)
                self.assertGreater(check['missing_count']+check['duplicate_count'],0)

    def test_copied_observation_not_independent_repeat(self):
        rows=[dict(r) for r in self.rows];rows[3]['observation_id']=rows[0]['observation_id']
        with self.assertRaisesRegex(ValueError,'Observation reused'):p.validate(m,self.samples,self.cs,rows)

    def test_representative_report_cannot_satisfy_formal_gate(self):
        report={'status':'pass','scope':'representative','formal_gate_eligible':False}
        with patch.object(m,'read_json',return_value=report):
            with self.assertRaisesRegex(RuntimeError,'Full-candidate P1'):p.require_full_gate(m,Path('unused'),{},self.samples,self.cs)

    def test_forged_full_report_with_representative_rows_rejected(self):
        import io,csv
        subset=[r for r in self.rows if r['candidate_id']!='b']
        data=io.StringIO();w=csv.DictWriter(data,fieldnames=list(subset[0]));w.writeheader();w.writerows(subset)
        report={'status':'pass','scope':'full','formal_gate_eligible':True,'identity':{},'rows_sha256':'hash'}
        with patch.object(m,'read_json',return_value=report),patch.object(m,'sha256_file',return_value='hash'),patch.object(m,'execution_identity',return_value={}),patch.object(Path,'open',return_value=io.StringIO(data.getvalue())):
            with self.assertRaises(ValueError):p.require_full_gate(m,Path('unused'),{'p1_protocol':p.PROTOCOL},self.samples,self.cs)

    def test_repeated_resource_change_fails(self):
        rows=[dict(r) for r in self.rows];v=json.loads(rows[3]['resources_json']);v['G']+=4;v['J']=(v['G']/160+v['D']/120)/4;rows[3]['resources_json']=json.dumps(v)
        with self.assertRaisesRegex(ValueError,'resource repeat mismatch'):p.validate(m,self.samples,self.cs,rows)

if __name__=='__main__':unittest.main()
