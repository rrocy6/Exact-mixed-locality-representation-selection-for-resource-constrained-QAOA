"""Frozen-input execution of warmstart_coordinate_correction_plan_v1.

No new instances, LP solutions, selector changes or experimental tuning.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback
import uuid

import numpy as np
import yaml

from urss_pipeline import e3_qaoa as e3, e4_warmstart as e4
from urss_pipeline.e2_resources import _evaluate_design, _full_actions
from urss_pipeline.fibre_selector import FibreMoments, beam_select_fibre_design, _moment_digest as fibre_digest
from urss_pipeline.four_part_addendum import read_csv, read_json, write_csv, write_json
from urss_pipeline.polynomial import canonicalize, cubic_supports, evaluate_pubo


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_task_inputs(path):
    entries = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(entries, list) or any(not isinstance(row, dict) or 'expected' not in row or 'source' not in row for row in entries):
        raise ValueError('Task inputs must be an array of expected/source records')
    return entries


def terms(poly):
    return [{'support': list(key), 'coefficient': str(value)} for key, value in sorted(poly.items())]


def polynomial(rows):
    return canonicalize({tuple(row['support']): Fraction(str(row['coefficient'])) for row in rows})


def deserialise_actions(actions):
    return tuple(tuple(action) if action is not None else None for action in actions)


def manifest(root: Path, paths, destination: Path):
    rows = [{'relative_path': path.relative_to(root).as_posix(), 'sha256': sha(path),
             'size_bytes': path.stat().st_size} for path in sorted(paths)]
    write_csv(destination, rows, ('relative_path', 'sha256', 'size_bytes'))
    return sha(destination)


def verify_manifest(root, rows):
    errors = []
    for row in rows:
        path = root / row['relative_path']
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            errors.append({'path': row['relative_path'], 'reason': 'missing_or_unsafe'})
        elif path.stat().st_size != int(row['size_bytes']) or sha(path) != row['sha256']:
            errors.append({'path': row['relative_path'], 'reason': 'hash_or_size_mismatch'})
    return errors


def restore_moments(rows, expected_hash, n):
    singles, pairs = {}, {}
    for row in rows:
        i = int(row['variable_i'])
        if row['moment_type'] == 'original_variable':
            if i in singles:
                raise ValueError('Duplicate single diagnostic')
            singles[i] = float(row['raw_single_moment'])
            if e4._clip(singles[i], 0.05) != float(row['clipped_single_moment']):
                raise ValueError('Clipped single diagnostic mismatch')
        elif row['moment_type'] == 'lifted_pair':
            key = (i, int(row['variable_j']))
            if key in pairs:
                raise ValueError('Duplicate pair diagnostic')
            pairs[key] = float(row['raw_pair_moment'])
            if e4._clip(pairs[key], 0.05) != float(row['clipped_pair_moment']):
                raise ValueError('Clipped pair diagnostic mismatch')
    if set(singles) != set(range(1, n+1)) or len(pairs) != n*(n-1)//2:
        raise ValueError('Incomplete archived moments')
    for row in rows:
        if row['moment_type'] == 'lifted_pair':
            value = e4._clip(singles[int(row['variable_i'])], 0.05)*e4._clip(singles[int(row['variable_j'])], 0.05)
            if value != float(row['independence_pair_moment']):
                raise ValueError('Independence diagnostic mismatch')
    first = rows[0]
    moments = e4.RelaxationMoments(float(first['solver_objective']), singles, pairs,
        first['solver_status'], 'Restored from archived diagnostics; LP not re-solved', float(first['solver_runtime_sec']))
    if e4._moment_digest(moments) != expected_hash:
        raise ValueError('Archived E4 moment hash cannot be reproduced')
    return moments


def strict_null(data):
    n = len(data.encoded_energies).bit_length()-1
    report = e4.require_uniform_null_control(data)
    maximum_l2 = 0.0
    maximum_probability_error = 0.0
    maximum_energy_error = 0.0
    count = 0
    for gammas, betas in (((0.7,), (0.3,)), ((-0.31,), (-0.67,)), ((0.3, -0.2), (-0.6, 0.17))):
        params = gammas+betas
        cold = e4._simulate(data, e4.WarmStartSpec('cold_start', 'not_applicable', None), params, len(gammas))
        for policy, closure in (('original_variables_only', 'auxiliary_cold_half'),
                               ('original_and_auxiliary_variables', 'sa_rlt_level_2_pair_moments'),
                               ('original_and_auxiliary_variables', 'independence_mu_product_ablation')):
            warm = e4._simulate(data, e4.WarmStartSpec(policy, closure, (0.5,)*n), params, len(gammas))
            overlap = np.vdot(cold, warm)
            if abs(overlap) == 0:
                raise ValueError('Zero overlap in null control')
            aligned = warm * np.exp(-1j*np.angle(overlap))
            l2 = float(np.linalg.norm(cold-aligned))
            probability_error = float(np.max(np.abs(np.abs(cold)**2-np.abs(warm)**2)))
            if l2 > 1e-12 or probability_error > 1e-12:
                raise ValueError(f'Plan null-control tolerance failed: {l2}, {probability_error}')
            cm, wm = e3.statevector_metrics(cold, data), e3.statevector_metrics(warm, data)
            for field in cm:
                if not math.isclose(cm[field], wm[field], abs_tol=1e-12, rel_tol=1e-12):
                    raise ValueError('Null metric mismatch: '+field)
            maximum_l2 = max(maximum_l2, l2)
            maximum_probability_error = max(maximum_probability_error, probability_error)
            maximum_energy_error = max(maximum_energy_error, abs(cm['original_objective_mean']-wm['original_objective_mean']))
            count += 1
    return dict(report, phase_aligned_l2_max=maximum_l2, plan_probability_max=maximum_probability_error,
                plan_energy_max=maximum_energy_error, plan_comparisons=count)


def replay_metrics(data, spec, source, *, legacy):
    p = int(source['p'])
    parameters = json.loads(source['optimized_parameters_json'])
    if len(parameters) != 2*p:
        raise ValueError('Archived parameter length mismatch')
    if legacy and spec.policy != 'cold_start':
        # Reproduce the archived +i mixer. This is INPUT VALIDATION only,
        # never a corrected optimization or a re-used positive-depth warm row.
        parameters = parameters[:p] + [-value for value in parameters[p:]]
    state = e4._simulate(data, spec, parameters, p)
    values = e3.statevector_metrics(state, data)
    errors, passed = {}, True
    for field, value in values.items():
        expected = float(source[field])
        errors[field] = abs(value-expected)
        relative = 1e-10 if 'objective' in field or 'energy' in field else 0
        passed &= math.isfinite(value) and math.isclose(value, expected, abs_tol=1e-10, rel_tol=relative)
    return bool(passed), errors, values


def prepare(repo: Path, plan_dir: Path, output: Path):
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(plan_dir, output/'plan')
    plan = read_json(plan_dir/'EXPERIMENT_PLAN.json')
    if verify_manifest(plan_dir, read_csv(plan_dir/'SHA256_MANIFEST.csv')):
        raise ValueError('Frozen plan package hash failure')
    if sha(plan_dir/'SHA256_MANIFEST.csv') != (plan_dir/'SHA256_MANIFEST.sha256').read_text().strip():
        raise ValueError('Frozen plan manifest sidecar mismatch')
    input_rows = read_csv(plan_dir/'SOURCE_INPUT_MANIFEST.csv')
    restored = []
    sources = output/'source_inputs'
    for row in input_rows:
        path = repo/row['relative_path']
        raw = path.read_bytes()
        expected = row['sha256']
        mode = 'byte_exact_copy'
        if hashlib.sha256(raw).hexdigest() != expected:
            lf = raw.replace(b'\r\n', b'\n')
            if hashlib.sha256(lf).hexdigest() != expected or len(lf) != int(row['size_bytes']):
                raise ValueError('Cannot materialize frozen input: '+row['relative_path'])
            mode = 'CRLF_transport_restored_to_exact_frozen_LF_bytes'
            destination_original = output/'transport_originals'/row['relative_path']
            destination_original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination_original)
            raw = lf
        destination = sources/row['relative_path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        restored.append({'relative_path': row['relative_path'], 'received_sha256': sha(path),
                         'materialized_sha256': sha(destination), 'mode': mode})
    write_csv(output/'INPUT_MATERIALIZATION.csv', restored)
    verify = subprocess.run([sys.executable, str(output/'plan/verify_plan.py'), '--repo', str(sources)], capture_output=True, text=True)
    (output/'PLAN_VERIFICATION.json').write_text(verify.stdout, encoding='utf-8')
    if verify.returncode:
        raise ValueError(verify.stdout+verify.stderr)
    config = yaml.safe_load((sources/'configs/experiment_config_v2.yaml').read_text(encoding='utf-8-sig'))
    schedule = read_csv(output/'plan/EXPECTED_RUNS.csv')
    source_rows = {study: read_csv(sources/spec['raw_source']) for study, spec in plan['studies'].items()}
    all_tasks = []
    groups = defaultdict(list)
    for task in schedule:
        source = source_rows[task['study']][int(task['source_csv_row_number'])-2]
        if source['config_hash'] != task['source_config_hash'] or source['code_commit'] != task['source_code_commit']:
            raise ValueError('Source provenance mismatch')
        item = {'expected': task, 'source': source}
        all_tasks.append(item)
        groups[(task['study'],task['instance_id'],task['representation'],task['random_rep_seed'],task['design_id'])].append(item)
    diagnostics = {}
    for study, path in [('targeted','four_part_addendum_v1/strong_bias/strong_bias_marginal_diagnostics.csv'),
                        ('original_e4','fibre_e1_e6_v2/results/e4_marginal_diagnostics.csv')]:
        by_instance = defaultdict(list)
        for row in read_csv(sources/path):
            by_instance[row['instance_id']].append(row)
        diagnostics[study] = by_instance
    design_records = {row['instance_id']: row for row in read_json(sources/'fibre_e1_e6_v2/frozen_selector_v2/qaoa_representation_designs_v2.json')['records']}
    selected = {row['instance_id']: row for row in read_csv(sources/'four_part_addendum_v1/strong_bias/strong_bias_selected_instances.csv')}
    budget_plans = {
        'targeted': read_csv(sources/'four_part_addendum_v1/strong_bias/strong_bias_budget_plan.csv'),
        'original_e4': read_csv(sources/'fibre_e1_e6_v2/results/e3_budget_plan.csv'),
    }
    design_map, moment_cache, replay_rows, null_rows = {}, {}, [], []
    for ordinal, (key, tasks) in enumerate(groups.items(), start=1):
        study, instance, rep_label, draw, design_id = key
        frozen_task = tasks[0]['expected']
        n = int(frozen_task['n_original'])
        if (study, instance) not in moment_cache:
            moment_cache[(study, instance)] = restore_moments(diagnostics[study][instance], frozen_task['marginal_set_sha256'], n)
        moments = moment_cache[(study, instance)]
        path = (sources/f'four_part_addendum_v1/strong_bias/selected_instances/canonical/{instance}.json'
                if study == 'targeted' else sources/f'data/canonical/{instance}.json')
        poly = polynomial(read_json(path)['terms'])
        if study == 'targeted':
            fm_hash = fibre_digest(moments.objective, moments.singles, moments.pairs)
            if fm_hash != selected[instance]['moment_sha256']:
                raise ValueError('Targeted screening moment hash mismatch')
            fm = FibreMoments(moments.objective, moments.singles, moments.pairs, moments.status,
                             moments.solver_message, moments.runtime_sec, 0, fm_hash)
            print(f'RESTORE TARGETED ACTIONS {ordinal}/{len(groups)}: {instance}', flush=True)
            # Plan explicitly permits original selector recovery if archived
            # actions are missing. No LP or instance screening is run.
            selection = beam_select_fibre_design(poly, n_original=n, selector=config['selector'],
                                                 moments=fm, apply_qaoa_hard_limits=True)
            actions = selection.actions
            recovery_method = 'frozen_selector_recovery_with_archived_moments_and_exact_design_id_gate'
        else:
            record = design_records[instance]
            if rep_label == 'all_native':
                actions = (None,)*len(cubic_supports(poly))
            elif rep_label == 'fully_quadratized':
                actions = _full_actions(poly)
            elif rep_label == 'selective':
                actions = deserialise_actions(record['selected']['actions'])
            else:
                matches = [row for row in record['matched_random'] if str(row['random_rep_seed']) == draw]
                if len(matches) != 1:
                    raise ValueError('Ambiguous matched draw')
                actions = deserialise_actions(matches[0]['actions'])
            recovery_method = 'archived_actions_or_frozen_deterministic_endpoint'
        evaluation = _evaluate_design(poly, n_original=n, actions=actions,
                                      selector=config['selector'], apply_qaoa_hard_limits=True)
        design = e3.QAOADesign(rep_label, int(draw) if draw else None, evaluation)
        if design.design_id != design_id or evaluation.representation.n_auxiliary != int(frozen_task['n_aux']):
            raise ValueError(f'Design recovery mismatch {key}: {design.design_id}')
        optimum = min(float(evaluate_pubo(poly, tuple((i>>bit)&1 for bit in range(n)))) for i in range(1<<n))
        data = e3.statevector_data(poly, evaluation.representation, optimum_original=optimum)
        specs = {(spec.policy,spec.pair_closure):spec for spec in e4.warm_start_specs(design, moments, clipping_delta=0.05)}
        null_rows.append(dict(study=study,instance_id=instance,representation=rep_label,random_rep_seed=draw,design_id=design_id,**strict_null(data)))
        budgets = []
        for entry in tasks:
            task, source = entry['expected'], entry['source']
            spec = specs[(task['warm_start_policy'],task['pair_closure'])]
            initial, seed = e3._initial_parameters(instance_id=instance, design_id=design_id,
                representation=rep_label, random_rep_seed=design.random_rep_seed, budget_key=task['budget_key'],
                restart_id=int(task['restart_id']), optimizer_seed=int(task['optimizer_seed']),p=int(task['p']),qaoa_config=config['qaoa'])
            if e3._hash_parameters(initial) != task['initial_parameters_sha256'] or seed != int(task['initialization_seed']):
                raise ValueError('Initial parameters changed: '+task['task_id'])
            if e4._moment_digest(moments) != task['marginal_set_sha256']:
                raise ValueError('Task moment mismatch')
            per_layer = int(task['compiled_2q_gates_per_layer'])
            plans = [row for row in budget_plans[study] if row['instance_id']==instance and
                     (study=='targeted' or (row['representation']==rep_label and row['random_rep_seed']==draw and row['design_id']==design_id))]
            if len(plans)!=1 or int(plans[0]['compiled_2q_gates_per_layer'])!=per_layer:
                raise ValueError('Frozen layer budget mismatch')
            p = int(task['p'])
            expected_p = int(task['compiled_2q_budget'])//per_layer if task['compiled_2q_budget'] else int(task['budget_key'].split('_p')[1])
            if p!=expected_p or int(task['actual_2q_gates'])!=p*per_layer:
                raise ValueError('Budget depth mismatch')
            ok, errors, _ = replay_metrics(data,spec,source,legacy=True)
            replay_rows.append(dict(task_id=task['task_id'],study=study,status='PASS' if ok else 'FAIL',**errors))
            if not ok:
                raise ValueError('Archived parameter replay failed '+task['task_id']+': '+str(errors))
            entry['design_key'] = '|'.join(key)
            entry['initial_parameters'] = initial
            budgets.append({field:task[field] for field in ('budget_key','p','compiled_2q_budget','compiled_2q_gates_per_layer','actual_2q_gates')})
        representation = evaluation.representation
        record = {'study':study,'instance_id':instance,'family':frozen_task['family'],'representation':rep_label,
            'random_rep_seed':draw,'design_id':design_id,'n_original':n,'n_aux':representation.n_auxiliary,
            'actions':[list(a) if a is not None else None for a in actions], 'original_terms':terms(poly),
            'encoded_terms':terms(representation.polynomial),'auxiliary_mapping':[{'pair':list(pair),'variable':idx} for pair,idx in representation.auxiliary_indices.items()],
            'penalties':[{'pair':list(pair),'penalty':str(value)} for pair,value in representation.penalties.items()],
            'moments':{'objective':moments.objective,'singles':{str(k):v for k,v in moments.singles.items()},
                       'pairs':[{'pair':list(k),'value':v} for k,v in moments.pairs.items()], 'status':moments.status,'runtime_sec':moments.runtime_sec},
            'policies':[{'policy':spec.policy,'pair_closure':spec.pair_closure,'probabilities':spec.probabilities} for spec in specs.values()],
            'optimum_original':optimum, 'budget_records':list({json.dumps(row,sort_keys=True):json.dumps(row,sort_keys=True) for row in budgets}),
            'recovery_method':recovery_method}
        design_key = '|'.join(key)
        filename = hashlib.sha256(design_key.encode()).hexdigest()+'.json'
        write_json(output/'frozen_designs'/filename, record)
        design_map[design_key] = filename
        print(f'FROZEN {ordinal}/{len(groups)}: {study} {rep_label} {design_id}; {len(tasks)} old rows replayed', flush=True)
    write_json(output/'DESIGN_INDEX.json', design_map)
    write_json(output/'TASK_INPUTS.json', all_tasks)
    write_csv(output/'ARCHIVE_REPLAY.csv', replay_rows)
    write_json(output/'NULL_CONTROL_DESIGNS.json', null_rows)
    manifest(output, list((output/'frozen_designs').glob('*.json'))+[output/'DESIGN_INDEX.json',output/'TASK_INPUTS.json'],output/'FROZEN_DESIGN_MANIFEST.csv')
    write_json(output/'PREPARATION_AUDIT.json', {'status':'PASS','prepared_at_utc':utc(), 'input_count':len(input_rows),
        'design_count':len(design_map),'task_count':len(all_tasks),'archive_replay_failures':sum(row['status']!='PASS' for row in replay_rows),
        'null_control_design_count':len(null_rows),'new_optimization_runs':0,'new_LP_solves':0,'new_instance_screening':False})
    print('PREPARATION COMPLETE '+str(output),flush=True)


def source_paths(root):
    return sorted([*root.glob('*.py'), *root.glob('urss_pipeline/*.py'), *root.glob('tests/*.py'),
                   *root.glob('configs/*'), *root.glob('golden_example/src/*.py'),
                   *root.glob('golden_example/tests/*.py'), *root.glob('golden_example/*.py')])


def environment_snapshot():
    packages={}
    for name in ('numpy','scipy','qiskit','qiskit-aer','PyYAML','matplotlib','reportlab'):
        packages[name]=importlib.metadata.version(name)
    return {'time_utc':utc(),'python':sys.version,'python_executable':sys.executable,
            'platform':platform.platform(),'packages':packages,
            'thread_settings':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')},
            'cpu_count':os.cpu_count()}


def bind(output, workers):
    root=Path(__file__).resolve().parent
    if (output/'EXECUTION_BINDING.json').exists():
        raise FileExistsError('Execution is already bound')
    if read_json(output/'PREPARATION_AUDIT.json')['status']!='PASS':
        raise ValueError('Preparation did not pass')
    if verify_manifest(output,read_csv(output/'FROZEN_DESIGN_MANIFEST.csv')):
        raise ValueError('Frozen designs changed')
    subprocess.run(['git','-C',str(root),'diff','--exit-code','HEAD'],check=True)
    commit=subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    manifest(root,source_paths(root),output/'SOURCE_TREE_MANIFEST.csv')
    source_zip=subprocess.run(['git','-C',str(root),'archive','--format=zip','HEAD'],capture_output=True,check=True).stdout
    (output/'EXECUTION_SOURCE.zip').write_bytes(source_zip)
    env=environment_snapshot()
    write_json(output/'ENVIRONMENT.json',env)
    freeze=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True)
    (output/'EXECUTION_DEPENDENCIES.txt').write_text(freeze.stdout,encoding='utf-8')
    tests=subprocess.run([sys.executable,'-m','unittest','tests.test_mixer_null_control','tests.test_correction_executor','-v'],
                         cwd=root,capture_output=True,text=True)
    (output/'NULL_REGRESSION_TEST_OUTPUT.txt').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    if tests.returncode:
        raise ValueError('Bound code regression failed; inspect NULL_REGRESSION_TEST_OUTPUT.txt')
    evidence_hash=manifest(output,[output/'NULL_CONTROL_DESIGNS.json',output/'NULL_REGRESSION_TEST_OUTPUT.txt'],output/'NULL_EVIDENCE_MANIFEST.csv')
    binding={
        'schema_version':'warmstart_execution_binding_v1','execution_id':output.name,'created_at_utc':utc(),
        'plan_id':'warmstart_coordinate_correction_plan_v1',
        'plan_sha256':sha(output/'plan/EXPERIMENT_PLAN.json'),'plan_markdown_sha256':sha(output/'plan/PLAN.md'),
        'source_input_manifest_sha256':sha(output/'plan/SOURCE_INPUT_MANIFEST.csv'),
        'expected_runs_sha256':sha(output/'plan/EXPECTED_RUNS.csv'),
        'corrected_code_commit':commit,'source_tree_manifest_sha256':sha(output/'SOURCE_TREE_MANIFEST.csv'),
        'source_archive_sha256':sha(output/'EXECUTION_SOURCE.zip'),'code_dirty':False,
        'commit_provenance':'local execution snapshot; not a commit on the external GitHub repository',
        'historical_snapshot_commit_declared_by_upload':'1cd4036a85abb93ebf8fe32a0db2dd4078627342',
        'environment_snapshot_sha256':sha(output/'ENVIRONMENT.json'),'dependency_snapshot_sha256':sha(output/'EXECUTION_DEPENDENCIES.txt'),
        'environment_equivalent_to_archive':False,
        'environment_difference':'Linux/Python 3.12.14/NumPy 2.3.5/SciPy 1.17.0 versus archived Windows/Python 3.12.10/NumPy 2.5.2/SciPy 1.18.1; see snapshots',
        'original_e4_cold_decision':'rerun ALL 1221 positive-depth cold rows; no outcome-based reuse selection',
        'original_e4_zero_depth_decision':'replay all 468 initial-state rows; retain historical 60 evaluations only as labelled accounting',
        'null_control_evidence_manifest_sha256':evidence_hash,
        'null_control_independently_verified_here':True,
        'windows_166_test_report_independently_verified':False,
        'frozen_materialized_inputs_manifest_sha256':sha(output/'FROZEN_DESIGN_MANIFEST.csv'),
        'observed_mixer_convention':e4.MIXER_CONVENTION,
        'coordinate_mapping':'warm exp(-i optimizer_beta B) = physical exp(+i physical_beta B) with physical_beta=-optimizer_beta at every evaluation',
        'corrected_formal_results_viewed_before_binding':False,
        'previously_viewed':'Historical performance summaries and synthetic mixer tests; no corrected formal 480/4320 outcomes',
        'preregistration_description':'Execution plan fixed after inspecting historical results; exploratory correction study, not outcome-blind confirmatory preregistration',
        'workers':workers,'gate_status':'PASS',
        'scope_excluded':read_json(output/'plan/EXPERIMENT_PLAN.json')['scope_excluded'],
    }
    write_json(output/'EXECUTION_BINDING.json',binding)
    print('EXECUTION BOUND '+commit,flush=True)


_CACHE={}


def load_design(output, entry, config):
    key=entry['design_key']
    if key in _CACHE:
        return _CACHE[key]
    index=read_json(output/'DESIGN_INDEX.json')
    record=read_json(output/'frozen_designs'/index[key])
    poly=polynomial(record['original_terms'])
    evaluation=_evaluate_design(poly,n_original=record['n_original'],actions=deserialise_actions(record['actions']),
                                selector=config['selector'],apply_qaoa_hard_limits=True)
    design=e3.QAOADesign(record['representation'],int(record['random_rep_seed']) if record['random_rep_seed'] else None,evaluation)
    if design.design_id!=record['design_id'] or terms(evaluation.representation.polynomial)!=record['encoded_terms']:
        raise ValueError('Reconstructed encoding differs from frozen materialization')
    m=record['moments']
    moments=e4.RelaxationMoments(m['objective'],{int(k):v for k,v in m['singles'].items()},
        {tuple(row['pair']):row['value'] for row in m['pairs']},m['status'],'Restored archived moments',m['runtime_sec'])
    data=e3.statevector_data(poly,evaluation.representation,optimum_original=record['optimum_original'])
    specs={(row['policy'],row['pair_closure']):e4.WarmStartSpec(row['policy'],row['pair_closure'],
           tuple(row['probabilities']) if row['probabilities'] is not None else None) for row in record['policies']}
    _CACHE[key]=(design,moments,data,specs)
    return _CACHE[key]


def task_worker(output_string,entry,config,binding):
    from unittest.mock import patch
    output=Path(output_string)
    task,source=entry['expected'],entry['source']
    attempts=[]
    for attempt in (1,2):
        started=time.perf_counter()
        trace=[]
        try:
            design,moments,data,specs=load_design(output,entry,config)
            spec=specs[(task['warm_start_policy'],task['pair_closure'])]
            p=int(task['p'])
            if task['study']=='original_e4' and p==0:
                ok,errors,metrics=replay_metrics(data,spec,source,legacy=False)
                if not ok:
                    raise ValueError('Zero-depth archive replay failed '+str(errors))
                row=dict(source,**metrics,task_outcome='REUSED_VALIDATED',validation_commit=binding['corrected_code_commit'],
                         current_evaluations=1,effective_optimization_evaluations=0,
                         evaluation_accounting='source 60 repeated initial-state evaluations; current replay 1; no optimization',
                         reuse_metric_errors_json=json.dumps(errors,sort_keys=True),mixer_convention=e4.MIXER_CONVENTION)
            else:
                original_simulate=e4._simulate
                def traced(data_arg,spec_arg,parameters,depth):
                    state=original_simulate(data_arg,spec_arg,parameters,depth)
                    trace.append({'parameters':[float(value) for value in parameters],
                                  'original_objective':float(np.abs(state)**2 @ data_arg.original_energies)})
                    return state
                with patch.object(e4,'_simulate',side_effect=traced):
                    row=e4.optimize_warmstart_run(instance_id=task['instance_id'],family=task['family'],design=design,
                        budget=e3.QAOABudgetSpec(task['budget_mode'],task['budget_key'],p,int(task['compiled_2q_budget']) if task['compiled_2q_budget'] else None,
                                               int(task['compiled_2q_gates_per_layer']),int(task['actual_2q_gates'])),
                        data=data,warm_spec=spec,moments=moments,restart_id=int(task['restart_id']),
                        optimizer_seed=int(task['optimizer_seed']),circuit_seed=int(task['circuit_seed']),measurement_seed=int(task['measurement_seed']),
                        qaoa_config=config['qaoa'],config_hash=task['source_config_hash'],manifest_hash=source['manifest_hash'],
                        e3_summary_hash=source['e3_summary_hash'],code_commit=binding['corrected_code_commit'])
                if row['status']!='pass' or row['evaluations']!=60:
                    raise ValueError('Optimization technical failure: '+str(row))
                for field in ('initial_parameters_sha256','initialization_seed','design_id','marginal_set_sha256','p'):
                    if str(row[field])!=str(task[field]):
                        raise ValueError('Task identity changed at execution: '+field)
                if len(trace)!=61:
                    raise ValueError('Unexpected objective trace count '+str(len(trace)))
                trace[-1]['role']='final_metric_evaluation_not_counted_as_optimizer_call'
                for point in trace[:-1]:
                    point['role']='objective_evaluation'
                row.update(task_outcome='RERUN_PASS',validation_commit=binding['corrected_code_commit'],
                           current_evaluations=60,effective_optimization_evaluations=60,
                           evaluation_accounting='fresh COBYLA run with the unchanged historical early-stop padding rule')
            row.update(task_id=task['task_id'],study=task['study'],source_relative_path=task['source_relative_path'],
                source_csv_row_number=task['source_csv_row_number'],source_code_commit=task['source_code_commit'],
                source_file_sha256=read_json(output/'plan/EXPERIMENT_PLAN.json')['studies'][task['study']]['raw_source_sha256'],
                execution_id=output.name,execution_binding_sha256=sha(output/'EXECUTION_BINDING.json'),
                source_original_objective_mean=source['original_objective_mean'],
                delta_vs_historical_original_objective=float(row['original_objective_mean'])-float(source['original_objective_mean']),
                attempt=attempt,completed_at_utc=utc())
            attempts.append({'attempt':attempt,'status':row['task_outcome'],'runtime_sec':time.perf_counter()-started,
                             'task_id':task['task_id'],'trace':trace,'result':row})
            return row,attempts
        except Exception as error:
            attempts.append({'attempt':attempt,'status':'FAILED','runtime_sec':time.perf_counter()-started,
                             'task_id':task['task_id'],'trace':trace,'error':str(error),'traceback':traceback.format_exc()})
    return dict(task,task_outcome='FAILED',failure_message=attempts[-1]['error'],execution_id=output.name),attempts


def verify_binding(output):
    binding=read_json(output/'EXECUTION_BINDING.json')
    root=Path(__file__).resolve().parent
    for name,field in [('SOURCE_TREE_MANIFEST.csv','source_tree_manifest_sha256'),
                       ('FROZEN_DESIGN_MANIFEST.csv','frozen_materialized_inputs_manifest_sha256'),
                       ('ENVIRONMENT.json','environment_snapshot_sha256')]:
        if sha(output/name)!=binding[field]:
            raise ValueError('Binding file changed: '+name)
    errors=verify_manifest(root,read_csv(output/'SOURCE_TREE_MANIFEST.csv'))
    errors+=verify_manifest(output,read_csv(output/'FROZEN_DESIGN_MANIFEST.csv'))
    errors+=verify_manifest(output/'source_inputs',read_csv(output/'plan/SOURCE_INPUT_MANIFEST.csv'))
    if errors:
        raise ValueError('Binding input hash check failed: '+str(errors))
    env=read_json(output/'ENVIRONMENT.json')
    now=environment_snapshot()
    for field in ('python','packages','platform','thread_settings'):
        if env[field]!=now[field]:
            raise ValueError('Environment changed; a new binding is required: '+field)
    return binding


def run_study(output,study):
    binding=verify_binding(output)
    if study=='original_e4':
        checkpoint=read_json(output/'targeted/STUDY_AUDIT.json')
        if checkpoint['status']!='COMPLETE':
            raise ValueError('Targeted technical completion is required before B; effect significance is not a gate')
    config=yaml.safe_load((output/'source_inputs/configs/experiment_config_v2.yaml').read_text())
    entries=[row for row in read_task_inputs(output/'TASK_INPUTS.json') if row['expected']['study']==study]
    directory=output/study
    directory.mkdir(exist_ok=False)
    outcomes=[]
    with ProcessPoolExecutor(max_workers=binding['workers']) as pool:
        futures={pool.submit(task_worker,str(output),entry,config,binding):entry for entry in entries}
        for future in as_completed(futures):
            entry=futures[future]
            try:
                row,attempts=future.result()
            except Exception as error:
                row=dict(entry['expected'],task_outcome='FAILED',failure_message=str(error))
                attempts=[{'status':'FAILED','error':str(error),'kind':'worker_process_failure'}]
            for attempt_no,attempt in enumerate(attempts,start=1):
                path=directory/'attempts'/f"{entry['expected']['task_id']}_attempt{attempt_no}.json"
                if path.exists():
                    raise FileExistsError('Attempt overwrite forbidden')
                write_json(path,attempt)
            write_json(directory/'task_results'/f"{entry['expected']['task_id']}.json",row)
            outcomes.append(row)
            if len(outcomes)%24==0 or len(outcomes)==len(entries):
                print(study.upper(),f'{len(outcomes)}/{len(entries)}',dict(Counter(r['task_outcome'] for r in outcomes)),flush=True)
    index={row['task_id']:row for row in outcomes}
    rows=[index.get(entry['expected']['task_id'],dict(entry['expected'],task_outcome='MISSING')) for entry in entries]
    fields=list(dict.fromkeys(key for row in rows for key in row))
    write_csv(directory/'corrected_runs.csv',rows,fields)
    counts=Counter(row['task_outcome'] for row in rows)
    complete=not counts['FAILED'] and not counts['MISSING'] and len(index)==len(entries)
    write_json(directory/'STUDY_AUDIT.json',{'status':'COMPLETE' if complete else 'INCOMPLETE',
        'study':study,'expected_tasks':len(entries),'actual_unique_tasks':len(index),'task_outcomes':dict(counts),
        'advantage_required_for_completion':False,'completed_at_utc':utc(),
        'binding_sha256':sha(output/'EXECUTION_BINDING.json'),'raw_sha256':sha(directory/'corrected_runs.csv')})
    if not complete:
        raise ValueError('Study incomplete; inspect task failures')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare','bind','run'])
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--study',choices=['targeted','original_e4'])
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    try:
        if args.phase=='prepare':
            prepare(args.repo.resolve(), args.plan.resolve(), args.output.resolve())
        elif args.phase=='bind':
            bind(args.output.resolve(),args.workers)
        else:
            if not args.study:
                parser.error('--study is required for run')
            run_study(args.output.resolve(),args.study)
    except Exception as error:
        if args.output.is_dir():
            failure_path=args.output/('BLOCKER_'+args.phase+'_'+uuid.uuid4().hex+'.json')
            write_json(failure_path,{'status':'BLOCKED','phase':args.phase,'time':utc(),'error':str(error),'traceback':traceback.format_exc()})
        raise


if __name__=='__main__':
    main()
