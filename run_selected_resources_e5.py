"""Recompile changed selector designs and rebuild frozen E5 endpoints.

All historical inputs are read-only. Checkpoints bind the design, source files,
compiler configuration and seed bundle. Expected capacity failures remain rows.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import time
import traceback

import yaml
from urss_pipeline import e2_resources as e2, e5_regime as e5
from urss_pipeline.four_part_addendum import compile_topology_design, topology_definitions
from urss_pipeline.fibre_selector import matched_random_fibre_designs, design_id as selector_design_id
from run_review_postprocess import resource_instances, resource_summary
from run_selected_qaoa_rerun import (
    actions, terms, polynomial, group_key, sha, identity, read_json, read_csv,
    write_json, write_csv, git, environment, utc,
)
from verify_selected_qaoa_results import verify as verify_qaoa

BASE = 'bcf47285d474a4bffb863984340978aa10816f80'
SOURCES = {
    'E2': 'fibre_e1_e6_v2/results/e2_compiled_resources_by_seed.csv',
    'E2_added_topologies': 'four_part_addendum_v1/topologies/additional_topology_compiled_by_seed.csv',
    'logical': 'fibre_e1_e6_v2/results/e2_logical_resources.csv',
    'old_E5': 'fibre_e1_e6_v2/results/e5_regime_instance_level.csv',
    'old_E3': 'fibre_e1_e6_v2/results/e3_qaoa_runs.csv',
    'metadata': 'data/metadata/metadata_v1.csv',
    'truth': 'data/ground_truth/ground_truth_v1.csv',
    'compilation_manifest': 'data/manifests/compilation_v1.csv',
    'qaoa_manifest': 'data/manifests/qaoa_v1.csv',
}
RESOURCE_FIELDS = ('two_qubit_gates', 'two_qubit_depth', 'swap_count', 'routing_overhead')
E5_KEY = ('instance_id', 'metric', 'budget_mode', 'budget_key', 'topology_id')
EXPECTED = 'infeasible_width_exceeds_topology'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def key(row):
    return group_key(row) + (str(row['topology_id']), str(row['transpiler_seed']))


def source_paths(repo):
    names = ['run_selected_resources_e5.py', 'run_selected_qaoa_rerun.py',
             'run_review_postprocess.py', 'warmstart_correction.py',
             'postprocess_correction.py', 'verify_selected_qaoa_results.py']
    return sorted([*repo.glob('urss_pipeline/*.py'), *(repo / n for n in names)])


def copy_input(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


def prepare(repo, selection, qaoa, output):
    if (output / 'PLAN.json').exists():
        verify_inputs(output, repo)
        print('PLAN: verified existing plan', flush=True)
        return
    require(not output.exists(), 'Incomplete output exists; retain it and choose a new output path')
    git(repo, 'merge-base', '--is-ancestor', BASE, 'HEAD')
    require(not git(repo, 'status', '--porcelain', '--untracked-files=no'), 'Commit implementation before preparation')
    qcheck = verify_qaoa(qaoa)
    env = environment()
    require(env['packages']['qiskit'] == '2.4.2', 'Frozen Qiskit 2.4.2 required')
    require(sha(qaoa / 'inputs/E3.csv') == sha(repo / SOURCES['old_E3']), 'QAOA source archive differs')
    for name in ['CHANGED_DESIGNS_AND_CONTROLS.json', 'selector_repair_main.csv']:
        require(sha(qaoa / 'inputs/selection' / name) == sha(selection / name), 'QAOA and E2 selector repairs differ')
    output.mkdir(parents=True)
    for name, source in SOURCES.items():
        copy_input(repo / source, output / 'inputs' / (name + '.csv'))
    for name in ['experiment_config_v2.yaml', 'four_part_addendum_v1.json', 'e5_analysis_v1.json']:
        copy_input(repo / 'configs' / name, output / 'inputs/configs' / name)
    for name in ['CHANGED_DESIGNS_AND_CONTROLS.json', 'SELECTED_RERUN_REQUIRED.csv', 'selector_repair_main.csv']:
        copy_input(selection / name, output / 'inputs/selection' / name)
    copy_input(repo / 'fibre_selector_v2/compilation_representation_designs_v2.json', output / 'inputs/old_designs.json')
    copy_input(qaoa / 'results/E3_merged_runs.csv', output / 'inputs/E3_merged_runs.csv')
    for name in ['EXECUTION_BINDING.json', 'EXECUTION_AUDIT.json', 'COVERAGE.csv']:
        copy_input(qaoa / name, output / 'inputs/qaoa_provenance' / name)
    write_json(output / 'inputs/qaoa_provenance/INPUT_VERIFICATION.json', qcheck)
    cfg = yaml.safe_load((output / 'inputs/configs/experiment_config_v2.yaml').read_text(encoding='utf-8'))
    configs = read_json(output / 'inputs/configs/four_part_addendum_v1.json')
    binding = {'schema': 'selected_resource_e5_v4', 'created_utc': utc(), 'code_commit': git(repo, 'rev-parse', 'HEAD'),
               'base_commit': BASE, 'environment': env,
               'code_files': {p.relative_to(repo).as_posix(): sha(p) for p in source_paths(repo)},
               'qaoa_result_source': str(qaoa), 'qaoa_input_verified': qcheck,
               'qaoa_optimizations_executed_in_this_stage': 0,
               'input_repository_files': {p: sha(repo / p) for p in SOURCES.values()}}
    binding['source_tree_sha256'] = identity(binding['code_files'])
    for name in binding['code_files']:
        copy_input(repo / name, output / 'execution_source' / name)
    write_json(output / 'EXECUTION_BINDING.json', binding)
    changes = {group_key(r): r for r in read_json(selection / 'CHANGED_DESIGNS_AND_CONTROLS.json')['records'] if r['tier'] == 'compilation'}
    require(len(changes) == 285 and len({k[0] for k in changes}) == 65, 'Unexpected frozen impact set')
    repaired = {r['instance_id']: r for r in read_csv(selection / 'selector_repair_main.csv') if r['tier'] == 'compilation'}
    old_designs = read_json(output / 'inputs/old_designs.json')['records']
    old_logical = {group_key(r): r for r in read_csv(output / 'inputs/logical.csv')}
    sources = {study: read_csv(output / 'inputs' / (study + '.csv')) for study in ['E2', 'E2_added_topologies']}
    source_lookup = {study: {key(r): (i, r) for i, r in enumerate(rows, 2)} for study, rows in sources.items()}
    for study in sources:
        require(len(source_lookup[study]) == len(sources[study]), 'Duplicate source resource row')
    controls = cfg['representations']['matched_random']
    seeds = [int(s) for s in cfg['compiler']['transpiler_seed_bundle']]
    require(len(seeds) == len(set(seeds)) == 5, 'Expected five frozen transpiler seeds')
    extra_topologies = topology_definitions(configs)
    plans, diagnostics, all_records = [], [], []
    for count, rec in enumerate(old_designs, 1):
        iid = rec['instance_id']
        canonical = repo / 'data/canonical' / (iid + '.json')
        require(sha(canonical) == rec['canonical_sha256'], 'Canonical source mismatch')
        copy_input(canonical, output / 'inputs/canonical' / canonical.name)
        family, poly = e2._canonical_polynomial(canonical)
        new_selected = actions(json.loads(repaired[iid]['new_actions_json']))
        old_selected = actions(rec['selected']['actions'])
        kwargs = dict(instance_id=iid, seed_bundle=controls['seed_bundle'], maximum_pair_set_attempts=controls['maximum_pair_set_attempts'])
        old_random = {int(r['random_rep_seed']): actions(r['actions']) for r in rec['matched_random']}
        require(dict(matched_random_fibre_designs(poly, selected_actions=old_selected, **kwargs)) == old_random, 'Historical random controls not reproducible')
        new_random = dict(matched_random_fibre_designs(poly, selected_actions=new_selected, **kwargs))
        variants = [('all_native', '', (None,) * len(old_selected), (None,) * len(old_selected)),
                    ('selective', '', old_selected, new_selected)]
        variants += [('matched_random_selective', str(s), old_random[s], new_random[s]) for s in sorted(old_random)]
        expected_aux = None
        for rep, draw, old_actions, new_actions in variants:
            gkey = (iid, rep, draw)
            template = old_logical[gkey]
            require(e2._design_id(old_actions) == template['design_id'], 'Archived design actions differ')
            change = changes.get(gkey)
            require((old_actions != new_actions) == (change is not None), 'Impact membership differs from repaired selection')
            if change:
                require(actions(change['old_actions']) == old_actions and actions(change['new_actions']) == new_actions, 'Impact actions differ')
                require(selector_design_id(new_actions) == change['new_design_id'], 'New selector ID mismatch')
            ev = e2._evaluate_design(poly, n_original=rec['n_original'], actions=new_actions,
                                     selector=cfg['selector'], apply_qaoa_hard_limits=False)
            if rep == 'selective':
                expected_aux = ev.representation.n_auxiliary
            if rep == 'matched_random_selective':
                require(ev.representation.n_auxiliary == expected_aux, 'New random control has unmatched auxiliary count')
            corrected_kappa = ev.reference.coefficient_dynamic_range
            diagnostics.append({'instance_id': iid, 'family': family, 'representation': rep, 'random_rep_seed': draw,
                                'old_design_id': template['design_id'], 'design_id': e2._design_id(new_actions),
                                'coefficient_dynamic_range_corrected': corrected_kappa,
                                'definition': 'collected_nonzero_nonidentity_Pauli_max_abs_over_min_abs',
                                'resource_design_changed': bool(change)})
            record = {'instance_id': iid, 'family': family, 'representation': rep, 'random_rep_seed': draw,
                      'n_original': rec['n_original'], 'split': rec['split'], 'old_actions': e2._serialise_actions(old_actions),
                      'actions': e2._serialise_actions(new_actions), 'original_terms': terms(poly),
                      'encoded_terms': terms(ev.representation.polynomial), 'old_design_id': template['design_id'],
                      'design_id': e2._design_id(new_actions), 'selector_design_id': selector_design_id(new_actions), 'changed': bool(change),
                      'coefficient_dynamic_range_corrected': corrected_kappa}
            record['record_id'] = identity(record)
            all_records.append(record)
            if not change:
                continue
            logical = e2.logical_resource_record(instance_id=iid, family=family, split=rec['split'],
                representation_name=rep, random_rep_seed=int(draw) if draw else None, evaluation=ev,
                selector_status='review_repaired_selection' if rep == 'selective' else 'matched_on_repaired_auxiliary_count',
                selector_compiler_calls=int(repaired[iid]['candidate_evaluations']) if rep == 'selective' else 0,
                config_hash=template['config_hash'], manifest_hash=template['manifest_hash'], code_commit=binding['code_commit'])
            job = {'record': record, 'logical': logical, 'source_tree_sha256': binding['source_tree_sha256'], 'source_rows': {}}
            for study, topologies in [('E2', ['all_to_all_reference', 'device_sparse_v1']), ('E2_added_topologies', sorted(extra_topologies))]:
                chosen = []
                for topology in topologies:
                    for seed in seeds:
                        i, row = source_lookup[study][gkey + (topology, str(seed))]
                        require(row['design_id'] == template['design_id'], 'Source compiled design mismatch')
                        chosen.append({'source_row': i, 'template': row})
                job['source_rows'][study] = chosen
            job['task_id'] = identity(job)
            plans.append(job)
        if count % 20 == 0:
            print(f'PREPARED INSTANCES: {count}/{len(old_designs)}', flush=True)
    require(len(plans) == len(changes), 'Missing changed resource design')
    expected_rows = read_csv(selection / 'SELECTED_RERUN_REQUIRED.csv')
    expected_refs = {(r['study'], int(r['source_csv_row']), r['source_sha256']) for r in expected_rows if r['study'] in sources}
    source_hashes = {study: sha(output / 'inputs' / (study + '.csv')) for study in sources}
    actual_refs = {(study, x['source_row'], source_hashes[study]) for j in plans for study, group in j['source_rows'].items() for x in group}
    require(actual_refs == expected_refs and len(actual_refs) == 7125, 'Exact row-level impact plan mismatch')
    write_json(output / 'TASKS.json', plans)
    write_json(output / 'CURRENT_DESIGNS.json', all_records)
    write_csv(output / 'DIAGNOSTIC_COEFFICIENT_RANGES.csv', diagnostics)
    frozen = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()}
    plan = {'schema': 'selected_resource_e5_plan_v4', 'jobs': len(plans), 'affected_instances': 65,
            'scheduled_resource_rows': len(actual_refs), 'frozen_files': frozen,
            'source_tree_sha256': binding['source_tree_sha256'],
            'compiler_seeds': seeds, 'topology_ids': ['all_to_all_reference', 'device_sparse_v1', *sorted(extra_topologies)],
            'QAOA_optimizations_scheduled': 0, 'E5_frozen_rules_retained': True}
    write_json(output / 'PLAN.json', plan)
    print(json.dumps({k: v for k, v in plan.items() if k != 'frozen_files'}, indent=2), flush=True)


def verify_inputs(output, repo=None):
    plan = read_json(output / 'PLAN.json')
    for name, expected in plan['frozen_files'].items():
        path = (output / name).resolve()
        require(path.is_relative_to(output.resolve()) and sha(path) == expected, 'Frozen input changed: ' + name)
    binding = read_json(output / 'EXECUTION_BINDING.json')
    if repo is not None:
        for name, expected in binding['code_files'].items():
            require(sha(repo / name) == expected, 'Execution source changed: ' + name)
        require(environment()['packages'] == binding['environment']['packages'], 'Package versions changed')
    return plan, binding


@lru_cache(maxsize=2)
def runtime_config(output_string):
    output = Path(output_string)
    cfg = yaml.safe_load((output / 'inputs/configs/experiment_config_v2.yaml').read_text(encoding='utf-8'))
    extra = topology_definitions(read_json(output / 'inputs/configs/four_part_addendum_v1.json'))
    return cfg, extra


def compile_job(output_string, job):
    output = Path(output_string)
    cfg, extra = runtime_config(output_string)
    r = job['record']
    started = time.perf_counter()
    try:
        ev = e2._evaluate_design(polynomial(r['original_terms']), n_original=r['n_original'], actions=actions(r['actions']),
                                 selector=cfg['selector'], apply_qaoa_hard_limits=False)
        require(terms(ev.representation.polynomial) == r['encoded_terms'], 'Execution Hamiltonian differs')
        rows = e2.compile_design_rows(job['logical'], ev, compiler_config=cfg['compiler'],
                                      protocol_id=job['source_rows']['E2'][0]['template']['compiler_protocol_id'])
        bykey = {key(row): row for row in rows}
        output_rows = []
        source_hashes = {study: sha(output / 'inputs' / (study + '.csv')) for study in job['source_rows']}
        for study, group in job['source_rows'].items():
            for item in group:
                old = item['template']
                if study == 'E2':
                    row = dict(bykey[key(old)])
                else:
                    top = extra[old['topology_id']]
                    measured = compile_topology_design(ev, compiler_config=cfg['compiler'], topology_id=old['topology_id'],
                        capacity=top['capacity'], coupling_map=top['coupling_map'], transpiler_seed=int(old['transpiler_seed']))
                    row = {**old, **{k: v for k, v in job['logical'].items() if k in old}, **measured,
                           'config_hash': old['config_hash'], 'compiler_protocol_id': old['compiler_protocol_id']}
                require(row['status'] in ['pass', EXPECTED], 'Unexpected compiler failure: ' + str(row))
                row.update({'study': study, 'observation_origin': 'CHANGED_DESIGN_RECOMPILED',
                            'resource_task_id': job['task_id'], 'source_csv_row': item['source_row'],
                            'source_sha256': source_hashes[study],
                            'source_design_id': old['design_id'], 'source_code_commit': old['code_commit'],
                            'execution_source_sha256': job['source_tree_sha256'],
                            'coefficient_dynamic_range_corrected': r['coefficient_dynamic_range_corrected']})
                output_rows.append(row)
        require(len(output_rows) == 25 and len({(x['study'], *key(x)) for x in output_rows}) == 25, 'Resource task coverage differs')
        record = {'status': 'PASS', 'task_id': job['task_id'], 'job_sha256': identity(job), 'rows': output_rows,
                  'duration_seconds': time.perf_counter() - started, 'finished_utc': utc()}
        path = output / 'task_results' / (job['task_id'] + '.json')
        write_json(path, record)
        path.with_suffix('.sha256').write_text(sha(path) + '\n', encoding='utf-8')
        return job['task_id'], dict(Counter(row['status'] for row in output_rows))
    except Exception:
        write_json(output / 'failed_attempts' / (job['task_id'] + '_' + str(time.time_ns()) + '.json'),
                   {'task_id': job['task_id'], 'traceback': traceback.format_exc(), 'utc': utc()})
        raise


def checkpoint(output, job):
    path = output / 'task_results' / (job['task_id'] + '.json')
    if not path.exists():
        return None
    require(sha(path) == path.with_suffix('.sha256').read_text(encoding='utf-8').strip(), 'Checkpoint hash mismatch')
    record = read_json(path)
    require(record['status'] == 'PASS' and record['task_id'] == job['task_id'] and record['job_sha256'] == identity(job), 'Checkpoint identity mismatch')
    return record


def run(repo, output, workers):
    verify_inputs(output, repo)
    jobs = read_json(output / 'TASKS.json')
    pending = [j for j in jobs if checkpoint(output, j) is None]
    print(f'CHECKPOINTS: {len(jobs)-len(pending)} verified; PENDING: {len(pending)}', flush=True)
    done = len(jobs) - len(pending)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(compile_job, str(output), j): j['task_id'] for j in pending}
        for future in as_completed(futures):
            _, statuses = future.result()
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f'COMPLETED: {done}/{len(jobs)} resource design groups; last={statuses}', flush=True)


def validate_pairs(rows, repetition_field, repetitions, draws):
    groups = defaultdict(list)
    for r in rows:
        if r['split'] != 'test' or r['representation'] not in ['selective', 'matched_random_selective']:
            continue
        condition = r['topology_id'] if repetition_field == 'transpiler_seed' else r['budget_key']
        groups[(r['instance_id'], condition)].append(r)
    for k, group in groups.items():
        expected = {('selective', '', str(seed)) for seed in repetitions}
        expected |= {('matched_random_selective', str(draw), str(seed)) for draw in draws for seed in repetitions}
        actual = {(r['representation'], str(r['random_rep_seed']), str(r[repetition_field])) for r in group}
        require(actual == expected and len(group) == len(expected), 'Missing or duplicate paired input: ' + str(k))


def compute_e5(output, main_rows, extra_rows, qaoa_rows, code_commit):
    # New checkpoints use JSON numbers; archived CSV uses strings. The frozen
    # E5 pairing API expects CSV string keys, so normalise at this boundary.
    main_rows = [{k: str(v) for k, v in r.items()} for r in main_rows]
    extra_rows = [{k: str(v) for k, v in r.items()} for r in extra_rows]
    qaoa_rows = [{k: str(v) for k, v in r.items()} for r in qaoa_rows]
    analysis = read_json(output / 'inputs/configs/e5_analysis_v1.json')
    e5._validate_analysis_config(analysis)
    metadata = {r['instance_id']: r for r in read_csv(output / 'inputs/metadata.csv')}
    truth = {r['instance_id']: float(r['optimum_original']) for r in read_csv(output / 'inputs/truth.csv') if r['exact_truth'] == 'True'}
    test_ids = [r['instance_id'] for r in read_csv(output / 'inputs/compilation_manifest.csv') if r['split'] == 'test']
    old = read_csv(output / 'inputs/old_E5.csv')[0]
    args = dict(config_hash=old['config_hash'], manifest_hash=sha(output / 'inputs/compilation_manifest.csv'),
                analysis_config_hash=sha(output / 'inputs/configs/e5_analysis_v1.json'), code_commit=code_commit)
    cfg, topologies = runtime_config(str(output))
    seeds = cfg['compiler']['transpiler_seed_bundle']
    draws = cfg['representations']['matched_random']['seed_bundle']
    validate_pairs(main_rows, 'transpiler_seed', seeds, draws)
    validate_pairs(extra_rows, 'transpiler_seed', seeds, draws)
    validate_pairs(qaoa_rows, 'restart_id', range(3), draws)
    primary = e5.compiled_instance_rows(main_rows, test_ids, metadata, analysis, **args)
    primary += e5.qaoa_instance_rows(qaoa_rows, metadata, truth, analysis,
                                    **{**args, 'manifest_hash': sha(output / 'inputs/qaoa_manifest.csv')})
    supplementary = e5.compiled_instance_rows(extra_rows, test_ids, metadata, analysis, **args, topology_ids=sorted(topologies))
    return primary, supplementary


def build_report(output):
    plan, binding = verify_inputs(output)
    jobs = read_json(output / 'TASKS.json')
    new = []
    for job in jobs:
        result = checkpoint(output, job)
        require(result is not None, 'Resource tasks still incomplete')
        new.extend(result['rows'])
    require(len(new) == plan['scheduled_resource_rows'], 'Resource observation count differs')
    diag = {group_key(r): r for r in read_csv(output / 'DIAGNOSTIC_COEFFICIENT_RANGES.csv')}
    replacement = {(r['study'], int(r['source_csv_row'])): r for r in new}
    require(len(replacement) == len(new), 'Duplicate replacement resource row')
    merged, coverage, transitions = {}, [], []
    for study in ['E2', 'E2_added_topologies']:
        source = read_csv(output / 'inputs' / (study + '.csv'))
        rows = []
        source_hash = sha(output / 'inputs' / (study + '.csv'))
        for num, old in enumerate(source, 2):
            r = replacement.get((study, num))
            if r is None:
                r = {**old, 'study': study, 'observation_origin': 'UNCHANGED_DESIGN_ARCHIVE',
                     'source_csv_row': num, 'source_sha256': source_hash,
                     'source_design_id': old['design_id'], 'source_code_commit': old['code_commit']}
                if group_key(old) in diag:
                    r['coefficient_dynamic_range_corrected'] = diag[group_key(old)]['coefficient_dynamic_range_corrected']
            else:
                require(key(old) == key(r) and old['design_id'] != r['design_id'], 'Replacement identity error')
                transitions.append({'study': study, 'instance_id': old['instance_id'], 'representation': old['representation'],
                    'random_rep_seed': old['random_rep_seed'], 'topology_id': old['topology_id'], 'transpiler_seed': old['transpiler_seed'],
                    'old_status': old['status'], 'new_status': r['status'], 'old_n_qubits': old['n_qubits'], 'new_n_qubits': r['n_qubits']})
            rows.append(r)
        merged[study] = rows
        changed = [r for r in new if r['study'] == study]
        write_csv(output / 'results' / (study + '_new_rows.csv'), changed)
        write_csv(output / 'results' / (study + '_merged_rows.csv'), rows)
        coverage.append({'study': study, 'original_rows': len(source), 'new_rows': len(changed),
                         'reused_rows': len(source) - len(changed), 'merged_rows': len(rows),
                         'new_pass_rows': sum(r['status'] == 'pass' for r in changed),
                         'new_expected_capacity_rows': sum(r['status'] == EXPECTED for r in changed)})
    logical_updates = {group_key(j['logical']): j['logical'] for j in jobs}
    logical_rows = []
    for old in read_csv(output / 'inputs/logical.csv'):
        r = dict(logical_updates.get(group_key(old), old))
        r['resource_origin'] = 'CHANGED_DESIGN_REBUILT' if group_key(old) in logical_updates else 'UNCHANGED_DESIGN_ARCHIVE'
        if group_key(r) in diag:
            r['coefficient_dynamic_range_corrected'] = diag[group_key(r)]['coefficient_dynamic_range_corrected']
        logical_rows.append(r)
    write_csv(output / 'results/E2_logical_merged.csv', logical_rows)
    write_csv(output / 'COVERAGE.csv', coverage)
    write_csv(output / 'analysis/CAPACITY_TRANSITIONS.csv', transitions)
    designs, instances = resource_instances(merged['E2'] + merged['E2_added_topologies'])
    paired, summary = resource_summary(instances)
    write_csv(output / 'analysis/E2_seed_median_per_design.csv', designs)
    write_csv(output / 'analysis/E2_instance_resources.csv', instances)
    write_csv(output / 'analysis/E2_paired_vs_native.csv', paired)
    write_csv(output / 'analysis/E2_summary_vs_native.csv', summary)
    instance_groups = defaultdict(dict)
    for r in instances:
        instance_groups[(r['topology_id'], r['family'], r['instance_id'])][r['representation']] = r
    control_pairs = []
    for (topology, family, iid), reps in sorted(instance_groups.items()):
        if {'selective', 'matched_random_selective'} <= set(reps):
            control_pairs.append({'topology_id': topology, 'family': family, 'instance_id': iid,
                **{m: reps['selective'][m] - reps['matched_random_selective'][m] for m in RESOURCE_FIELDS}})
    control_summary = []
    for topology, family in sorted({(r['topology_id'], r['family']) for r in control_pairs}):
        group = [r for r in control_pairs if (r['topology_id'], r['family']) == (topology, family)]
        control_summary.append({'topology_id': topology, 'family': family, 'n_instances': len(group),
            **{m: statistics.median(r[m] for r in group) for m in RESOURCE_FIELDS},
            **{m + '_selected_lower_count': sum(r[m] < -1e-10 for r in group) for m in RESOURCE_FIELDS}})
    write_csv(output / 'analysis/E2_selected_minus_random_pairs.csv', control_pairs)
    write_csv(output / 'analysis/E2_selected_minus_random_summary.csv', control_summary)
    capacity = []
    all_rows = merged['E2'] + merged['E2_added_topologies']
    for topology, family, rep in sorted({(r['topology_id'], r['family'], r['representation']) for r in all_rows}):
        group = [r for r in all_rows if (r['topology_id'], r['family'], r['representation']) == (topology, family, rep)]
        ids = {r['instance_id'] for r in group}
        success = {r['instance_id'] for r in instances if (r['topology_id'], r['family'], r['representation']) == (topology, family, rep)}
        capacity.append({'topology_id': topology, 'family': family, 'representation': rep, 'scheduled_instances': len(ids),
                         'feasible_instances': len(success), 'infeasible_instances': len(ids - success)})
    write_csv(output / 'analysis/E2_capacity_by_instance.csv', capacity)
    qrows = read_csv(output / 'inputs/E3_merged_runs.csv')
    primary, supplementary = compute_e5(output, *[merged[k] for k in ['E2', 'E2_added_topologies']], qrows, binding['code_commit'])
    old_e5 = {tuple(r[k] for k in E5_KEY): r for r in read_csv(output / 'inputs/old_E5.csv')}
    require({tuple(r[k] for k in E5_KEY) for r in primary} == set(old_e5) and len(primary) == len(old_e5) == 272, 'Frozen E5 endpoint membership changed')
    require(all(r['status'] in ['pass', 'expected_infeasible'] for r in primary + supplementary), 'Unexpected E5 unpaired failures')
    e5changes = []
    for r in primary:
        old = old_e5[tuple(r[k] for k in E5_KEY)]
        e5changes.append({**{k: r[k] for k in E5_KEY}, 'old_classification': old['classification'],
                         'new_classification': r['classification'], 'old_effect': old['effect'], 'new_effect': r['effect'],
                         'old_status': old['status'], 'new_status': r['status']})
    write_csv(output / 'analysis/E5_instance_level.csv', primary)
    write_csv(output / 'analysis/E5_summary.csv', e5.summarise_regime_rows(primary))
    write_csv(output / 'analysis/E5_additional_topologies_instance_level.csv', supplementary)
    write_csv(output / 'analysis/E5_additional_topologies_summary.csv', e5.summarise_regime_rows(supplementary))
    write_csv(output / 'analysis/E5_before_after.csv', e5changes)
    counts = dict(Counter(r['classification'] for r in primary))
    ambiguous = sum(r['classification'] == 'little_effect' and
                    (r['effect_ci95_low'] < -r['effect_tolerance'] or r['effect_ci95_high'] > r['effect_tolerance']) for r in primary)
    qchanged = {r['instance_id'] for r in qrows if r.get('observation_origin') == 'NEW_DESIGN_RERUN'}
    rchanged = {j['record']['instance_id'] for j in jobs}
    for r in primary:
        old = old_e5[tuple(r[k] for k in E5_KEY)]
        if r['instance_id'] not in (qchanged if r['source_tier'] == 'qaoa' else rchanged):
            require(r['classification'] == old['classification'], 'Unaffected E5 classification changed')
            if r['status'] == 'pass':
                for field in ['effect', 'effect_ci95_low', 'effect_ci95_high']:
                    require(math.isclose(float(r[field]), float(old[field]), rel_tol=1e-10, abs_tol=1e-12), 'Unaffected E5 endpoint changed')
    audit = {'status': 'E2_E5_SELECTED_UPDATE_COMPLETE', 'code_commit': binding['code_commit'],
             'source_tree_sha256': binding['source_tree_sha256'], 'resource_design_groups': len(jobs),
             'resource_rows_processed': len(new), 'new_resource_statuses': dict(Counter(r['status'] for r in new)),
             'unexpected_compiler_failures': 0, 'coverage': coverage, 'E5_primary_endpoints': len(primary),
             'E5_primary_counts': counts, 'E5_additional_endpoints': len(supplementary),
             'E5_additional_counts': dict(Counter(r['classification'] for r in supplementary)),
             'E5_classification_changes': sum(r['old_classification'] != r['new_classification'] for r in e5changes),
             'little_effect_intervals_outside_tolerance': ambiguous, 'E5_frozen_normal_intervals_preserved': True,
             'E2_resource_aggregation': 'median over five seeds per design, then mean over five draws, then paired instance median',
             'QAOA_optimizations_executed_in_this_stage': 0, 'QAOA_input_sha256': sha(output / 'inputs/E3_merged_runs.csv'),
             'historical_input_files_overwritten': False, 'latest_Overleaf_merge': 'WAITING_FOR_CURRENT_SOURCE_ZIP',
             'kappa_policy': 'Use coefficient_dynamic_range_corrected for native/selective/random; original fields preserved on reused observations; full historical diagnostic outside this correction scope'}
    write_json(output / 'EXECUTION_AUDIT.json', audit)
    write_manifest(output)
    print(json.dumps(audit, indent=2), flush=True)
    return audit


def write_manifest(output):
    skip = {'SHA256_MANIFEST.csv', 'SHA256_MANIFEST.sha256'}
    rows = [{'path': p.relative_to(output).as_posix(), 'size_bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(output.rglob('*')) if p.is_file() and p.name not in skip and '__pycache__' not in p.parts]
    write_csv(output / 'SHA256_MANIFEST.csv', rows)
    (output / 'SHA256_MANIFEST.sha256').write_text(sha(output / 'SHA256_MANIFEST.csv') + '\n', encoding='utf-8')


def verify_results(output):
    plan, _ = verify_inputs(output)
    require(sha(output / 'SHA256_MANIFEST.csv') == (output / 'SHA256_MANIFEST.sha256').read_text(encoding='utf-8').strip(), 'Result manifest hash differs')
    for r in read_csv(output / 'SHA256_MANIFEST.csv'):
        p = (output / r['path']).resolve()
        require(p.is_relative_to(output.resolve()) and sha(p) == r['sha256'] and p.stat().st_size == int(r['size_bytes']), 'Result changed: ' + r['path'])
    count, reused = 0, 0
    all_new = {}
    for job in read_json(output / 'TASKS.json'):
        cp = checkpoint(output, job)
        require(cp is not None, 'Missing checkpoint')
        for r in cp['rows']:
            all_new[(r['study'], int(r['source_csv_row']))] = r
    for study in ['E2', 'E2_added_topologies']:
        old = read_csv(output / 'inputs' / (study + '.csv'))
        merged = read_csv(output / 'results' / (study + '_merged_rows.csv'))
        require(len(old) == len(merged) and len({key(r) for r in merged}) == len(merged), 'Merged coverage mismatch')
        for num, (a, b) in enumerate(zip(old, merged), 2):
            require(key(a) == key(b), 'Merged row order or key differs')
            new = all_new.get((study, num))
            if new is None:
                require(all(b[k] == v for k, v in a.items()), 'Reused archived field changed')
                reused += 1
            else:
                require(all(b[k] == str(v) for k, v in new.items()), 'Merged row differs from checkpoint')
                count += 1
    require(count == plan['scheduled_resource_rows'], 'Executed row coverage mismatch')
    return {'status': 'PASS', 'resource_design_groups': plan['jobs'], 'new_resource_rows': count,
            'unchanged_resource_rows_field_verified': reused, 'all_checkpoint_hashes_valid': True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', choices=['prepare', 'run', 'report', 'verify', 'all'], required=True)
    p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--selection', type=Path)
    p.add_argument('--qaoa-results', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, default=4)
    a = p.parse_args()
    require(1 <= a.workers <= 16, 'workers must be 1..16')
    repo, output = a.repo.resolve(), a.output.resolve()
    if a.stage in ['prepare', 'all']:
        require(a.selection is not None and a.qaoa_results is not None, 'Provide --selection and --qaoa-results')
        prepare(repo, a.selection.resolve(), a.qaoa_results.resolve(), output)
    if a.stage in ['run', 'all']:
        run(repo, output, a.workers)
    if a.stage in ['report', 'all']:
        verify_inputs(output, repo)
        build_report(output)
    if a.stage in ['verify', 'all']:
        print(json.dumps(verify_results(output), indent=2), flush=True)


if __name__ == '__main__':
    main()
