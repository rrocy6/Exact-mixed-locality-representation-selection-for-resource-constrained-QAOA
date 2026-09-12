import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from urss_pipeline import e2_resources as e2, e5_regime as e5
from urss_pipeline.four_part_addendum import topology_definitions
import run_selected_resources_e5 as update

ROOT = Path(__file__).resolve().parents[1]


class SelectedResourceUpdateTests(unittest.TestCase):
    def test_missing_or_duplicate_random_draw_cannot_be_averaged_away(self):
        rows = []
        for seed in [1, 2]:
            for rep, draw in [('selective', ''), ('matched_random_selective', '11'), ('matched_random_selective', '12')]:
                rows.append(dict(instance_id='i', split='test', topology_id='grid', representation=rep,
                                 random_rep_seed=draw, transpiler_seed=str(seed)))
        update.validate_pairs(rows, 'transpiler_seed', [1, 2], [11, 12])
        with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
            update.validate_pairs(rows[:-1] + [rows[0]], 'transpiler_seed', [1, 2], [11, 12])

    def test_checkpoint_cannot_be_reused_for_changed_job(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            job = {'task_id': 'task', 'actions': [None]}
            path = out / 'task_results/task.json'
            update.write_json(path, {'status': 'PASS', 'task_id': 'task', 'job_sha256': update.identity(job)})
            path.with_suffix('.sha256').write_text(update.sha(path), encoding='utf-8')
            self.assertIsNotNone(update.checkpoint(out, job))
            with self.assertRaisesRegex(ValueError, 'identity'):
                update.checkpoint(out, {**job, 'actions': [[1, 2]]})

    def test_additional_topology_uses_frozen_e5_effect_and_capacity_rule(self):
        analysis = update.read_json(ROOT / 'configs/e5_analysis_v1.json')
        metadata = {'i': dict(family='max3sat', n='4', cubic_density='0.1', pair_reuse_score='0.4')}
        args = dict(config_hash='c', manifest_hash='m', analysis_config_hash='a', code_commit='test')
        rows = []
        for seed in range(5):
            for rep, draw in [('selective', '')] + [('matched_random_selective', str(d)) for d in range(5)]:
                rows.append(dict(instance_id='i', family='max3sat', split='test', topology_id='line_12',
                                 representation=rep, random_rep_seed=draw, transpiler_seed=str(seed), status='pass',
                                 two_qubit_gates=10 if rep == 'selective' else 20,
                                 two_qubit_depth=5 if rep == 'selective' else 10,
                                 routing_overhead=0))
        out = e5.compiled_instance_rows(rows, ['i'], metadata, analysis, **args, topology_ids=['line_12'])
        self.assertEqual(len(out), 3)
        gates = next(r for r in out if r['metric'] == 'compiled_two_qubit_gates')
        self.assertEqual(gates['effect'], 0.5)
        self.assertEqual(gates['classification'], 'help')
        failed = [{**r, 'status': update.EXPECTED} for r in rows]
        out = e5.compiled_instance_rows(failed, ['i'], metadata, analysis, **args, topology_ids=['line_12'])
        self.assertTrue(all(r['classification'] == 'not_estimable' for r in out))
        self.assertTrue(all(r['paired_observation_count'] == 0 for r in out))

    def test_partial_capacity_failure_is_not_success(self):
        analysis = update.read_json(ROOT / 'configs/e5_analysis_v1.json')
        metadata = {'i': dict(family='max3sat', n='4', cubic_density='0.1', pair_reuse_score='0.4')}
        rows = [dict(instance_id='i', split='test', topology_id='grid', representation=rep,
                     status='pass' if rep == 'selective' else update.EXPECTED)
                for rep in ['selective', 'matched_random_selective']]
        out = e5.compiled_instance_rows(rows, ['i'], metadata, analysis, config_hash='c', manifest_hash='m',
                                       analysis_config_hash='a', code_commit='test', topology_ids=['grid'])
        self.assertTrue(all(r['status'] == 'unpaired_failure' for r in out))

    def test_actual_compilation_keeps_five_topologies_and_all_seeds(self):
        cfg = yaml.safe_load((ROOT / 'configs/experiment_config_v2.yaml').read_text())
        extra = update.read_json(ROOT / 'configs/four_part_addendum_v1.json')
        poly = {(1, 2, 3): 1, (1, 2, 4): -1}
        acts = ((1, 2), None)
        ev = e2._evaluate_design(poly, n_original=4, actions=acts, selector=cfg['selector'], apply_qaoa_hard_limits=False)
        logical = e2.logical_resource_record(instance_id='fixture', family='cubic_spin_glass', split='test',
            representation_name='selective', random_rep_seed=None, evaluation=ev, selector_status='fixture',
            selector_compiler_calls=0, config_hash='cfg', manifest_hash='manifest', code_commit='new')
        record = dict(instance_id='fixture', family='cubic_spin_glass', representation='selective', random_rep_seed='',
            n_original=4, original_terms=update.terms(poly), encoded_terms=update.terms(ev.representation.polynomial),
            actions=e2._serialise_actions(acts), coefficient_dynamic_range_corrected=ev.reference.coefficient_dynamic_range)
        job = dict(record=record, logical=logical, source_tree_sha256='fixture', source_rows={})
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            update.copy_input(ROOT / 'configs/experiment_config_v2.yaml', out / 'inputs/configs/experiment_config_v2.yaml')
            update.copy_input(ROOT / 'configs/four_part_addendum_v1.json', out / 'inputs/configs/four_part_addendum_v1.json')
            for study, tops in [('E2', ['all_to_all_reference', 'device_sparse_v1']),
                                ('E2_added_topologies', sorted(topology_definitions(extra)))]:
                (out / 'inputs' / (study + '.csv')).write_text('fixture\n', encoding='utf-8')
                job['source_rows'][study] = []
                for top in tops:
                    for seed in cfg['compiler']['transpiler_seed_bundle']:
                        row = {**logical, 'design_id': 'old', 'code_commit': 'old_commit', 'topology_id': top,
                               'transpiler_seed': seed, 'compiler_protocol_id': 'fixture'}
                        job['source_rows'][study].append({'source_row': len(job['source_rows'][study]) + 2, 'template': row})
            job['task_id'] = update.identity(job)
            _, counts = update.compile_job(str(out), job)
            self.assertEqual(counts, {'pass': 25})
            result = update.checkpoint(out, job)
            self.assertEqual(len({r['topology_id'] for r in result['rows']}), 5)
            self.assertTrue(all(r['design_id'] == logical['design_id'] and r['source_design_id'] == 'old' for r in result['rows']))
            self.assertTrue(all(r['two_qubit_gates'] >= 0 for r in result['rows']))


if __name__ == '__main__':
    unittest.main()
