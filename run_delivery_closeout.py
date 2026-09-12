"""Read frozen URSS inputs and write a new, non-experimental closeout audit.

Python 3.12+, numpy, scipy, PyYAML and matplotlib. No Qiskit or optimiser run.
Historical results/configs/manifests are read only. Existing output is refused.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from fractions import Fraction
import hashlib
import io
from itertools import combinations
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import zipfile

import yaml

from urss_pipeline.e1_exactness import build_mixed_representation
from urss_pipeline.e2_resources import _canonical_polynomial, _evaluate_design, _design_id
from urss_pipeline.e5_regime import (
    compiled_instance_rows, qaoa_instance_rows, summarise_regime_rows,
)
from urss_pipeline.fibre_selector import FibreMoments, _candidate, fibre_normalisation
from urss_pipeline.polynomial import cubic_supports
from urss_pipeline.reference_compiler import compile_reference

BASE_COMMIT = "0c647125a4bb1e5096bb101a611a7a92019db905"
RAW_ZIP_SHA256 = "9e539a0aa387393e482e5ac0f186ace9695af39d05017fe3bc90eefefe5dd5e5"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        raise ValueError(f'Unexpected empty output: {path}')
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def independent_pauli(polynomial):
    """Separate exact implementation for checking the compiler expansion."""
    totals = defaultdict(Fraction)
    for support, value in polynomial.items():
        for mask in range(1 << len(support)):
            z = tuple(support[i] for i in range(len(support)) if mask & (1 << i))
            totals[z] += Fraction(value) * (-1 if len(z) % 2 else 1) / (1 << len(support))
    return {key: value for key, value in totals.items() if value}


def kappa(pauli, identity=False):
    values = [abs(v) for s, v in pauli.items() if v and (s or identity)]
    return float(max(values)/min(values)) if values else 0.0


def source(path, records, root):
    records[str(path.relative_to(root))] = sha(path)
    return path


def audit_kappa(root, out, sources):
    cfgpath = source(root/'configs/experiment_config_v2.yaml', sources, root)
    selector = yaml.safe_load(cfgpath.read_text(encoding='utf-8'))['selector']
    bundlepath = source(root/'fibre_selector_v2/compilation_representation_designs_v2.json', sources, root)
    bundle = json.loads(bundlepath.read_text(encoding='utf-8'))['records']
    manifest = {r['instance_id']: r for r in read_csv(source(root/'data/manifests/compilation_v1.csv', sources, root))}
    selected_rows, diagnostics = [], []
    for rec in bundle:
        path = source(root/'data'/manifest[rec['instance_id']]['canonical_file'], sources, root)
        if sha(path) != rec['canonical_sha256']:
            raise ValueError('Canonical frozen design hash mismatch')
        _, polynomial = _canonical_polynomial(path)
        designs = [('selective', '', rec['selected']['actions'])]
        designs += [('matched_random_selective', item['random_rep_seed'], item['actions']) for item in rec['matched_random']]
        designs += [('all_native', '', [None]*len(rec['cubic_supports']))]
        for representation, seed, actions in designs:
            actions = tuple(tuple(a) if a is not None else None for a in actions)
            ev = _evaluate_design(polynomial, n_original=rec['n_original'], actions=actions,
                                  selector=selector, apply_qaoa_hard_limits=False)
            independent = independent_pauli(ev.representation.polynomial)
            if independent != ev.reference.pauli:
                raise ValueError('Independent Pauli expansion mismatch')
            corrected = kappa(independent)
            if corrected != ev.reference.coefficient_dynamic_range:
                raise ValueError('Compiler kappa differs from independent reconstruction')
            row = dict(instance_id=rec['instance_id'], family=rec['family'], split=rec['split'],
                       representation=representation, random_rep_seed=seed, design_id=_design_id(actions),
                       canonical_sha256=sha(path), old_identity_inclusive_kappa=kappa(independent, True),
                       corrected_nonidentity_kappa=corrected,
                       historical_addendum_misnamed_max_abs_pubo=float(max(map(abs, ev.representation.polynomial.values()), default=0)),
                       nonidentity_term_count=sum(bool(s) for s in independent),
                       identity_coefficient=str(independent.get((), Fraction(0))),
                       resource_score=float(ev.score), gates=ev.reference.two_qubit_gate_count,
                       depth=ev.reference.two_qubit_depth)
            diagnostics.append(row)
            if representation == 'selective':
                old = rec['selected']
                for key, value in [('resource_score', float(ev.score)), ('two_qubit_gate_count', row['gates']), ('two_qubit_depth', row['depth'])]:
                    if not math.isclose(float(old[key]), value, abs_tol=1e-12, rel_tol=1e-12):
                        raise ValueError(f'Frozen selection resource changed: {key}')
                selected_rows.append(row)
    if len(selected_rows) != 180:
        raise ValueError('Expected exactly 180 frozen compilation selective designs')
    write_csv(out/'kappa_frozen_designs.csv', diagnostics)
    medians = []
    for family in sorted({r['family'] for r in selected_rows}):
        group = [r for r in selected_rows if r['family'] == family]
        medians.append(dict(family=family, n=len(group),
                            old_median=statistics.median(r['old_identity_inclusive_kappa'] for r in group),
                            corrected_median=statistics.median(r['corrected_nonidentity_kappa'] for r in group)))
    write_csv(out/'kappa_table16_medians.csv', medians)
    lookup = {(r['instance_id'],r['representation'],str(r['random_rep_seed'])):r for r in diagnostics}
    references = []
    for rel in ['fibre_e1_e6_v2/results/e2_compiled_resources_by_seed.csv',
                'four_part_addendum_v1/topologies/additional_topology_compiled_by_seed.csv']:
        path=root/rel
        if not path.exists():
            raise FileNotFoundError(path)
        for line,row in enumerate(read_csv(source(path,sources,root)),start=2):
            match=lookup.get((row['instance_id'],row['representation'],str(row['random_rep_seed'])))
            if match:
                references.append(dict(source_file=rel,source_csv_line=line,instance_id=row['instance_id'],
                    design_id=row['design_id'],representation=row['representation'],
                    historical_field=row['coefficient_dynamic_range'],
                    corrected_nonidentity_kappa=match['corrected_nonidentity_kappa']))
    if references:
        write_csv(out/'kappa_archived_row_amendments.csv',references)
    return dict(status='PASS', selected_designs=180, diagnostic_design_records=len(diagnostics),
                medians=medians, amended_row_references=len(references),
                design_selection_changed=False, new_qaoa_runs=0,
                scope='Compilation native/selective/matched-random diagnostics; full-reduction historical rows not amended.',
                downstream_use='Read-only diagnostic fields; selector score and limits use auxiliary count, gates, depth and maximum penalty, not kappa.')


def audit_e5(root, out, sources):
    base = root/'fibre_e1_e6_v2/results'
    analysis = json.loads(source(root/'configs/e5_analysis_v1.json',sources,root).read_text(encoding='utf-8'))
    metadata={r['instance_id']:r for r in read_csv(source(root/'data/metadata/metadata_v1.csv',sources,root))}
    truth={r['instance_id']:float(r['optimum_original']) for r in read_csv(source(root/'data/ground_truth/ground_truth_v1.csv',sources,root)) if r['exact_truth']=='True'}
    ids=[r['instance_id'] for r in read_csv(source(root/'data/manifests/compilation_v1.csv',sources,root)) if r['split']=='test']
    archived=read_csv(source(base/'e5_regime_instance_level.csv',sources,root))
    kwargs=dict(config_hash=archived[0]['config_hash'],manifest_hash=archived[0]['manifest_hash'],
                analysis_config_hash=sha(root/'configs/e5_analysis_v1.json'),code_commit='delivery_closeout_postprocessing')
    rows=compiled_instance_rows(read_csv(source(base/'e2_compiled_resources_by_seed.csv',sources,root)),ids,metadata,analysis,**kwargs)
    rows+=qaoa_instance_rows(read_csv(source(base/'e3_qaoa_runs.csv',sources,root)),metadata,truth,analysis,**kwargs)
    key=lambda r:tuple(r[k] for k in ['instance_id','metric','budget_mode','budget_key','topology_id'])
    old={key(r):r for r in archived}
    if len(old)!=len(archived) or {key(r) for r in rows}!=set(old):
        raise ValueError('E5 endpoint set changed or duplicated')
    for r in rows:
        a=old[key(r)]
        for field in ['status','classification']:
            if str(r[field])!=a[field]:raise ValueError(f'E5 classification mismatch: {key(r)}')
        for field in ['effect','effect_ci95_low','effect_ci95_high','effect_tolerance']:
            if r[field]!='' and not math.isclose(float(r[field]),float(a[field]),rel_tol=1e-10,abs_tol=1e-12):
                raise ValueError(f'E5 numeric mismatch: {key(r)} {field}')
    write_csv(out/'e5_regenerated_instance_level.csv',rows)
    write_csv(out/'e5_regenerated_summary.csv',summarise_regime_rows(rows))
    counts=[]
    for family in sorted({r['family'] for r in rows}):
        for metric in sorted({r['metric'] for r in rows}):
            group=[r for r in rows if r['family']==family and r['metric']==metric and r['status']=='pass']
            c=Counter(r['classification'] for r in group)
            counts.append(dict(family=family,metric=metric,n=len(group),help=c['help'],little_effect=c['little_effect'],hurt=c['hurt']))
    write_csv(out/'e5_table20_counts.csv',counts)
    # Independently check the dimensions against the manuscript's frozen totals.
    c=Counter(r['classification'] for r in rows)
    if c != Counter(help=53,little_effect=121,hurt=17,not_estimable=81):
        raise ValueError(f'Unexpected E5 totals: {c}')
    figure_rows=[r for r in rows if r['source_tier']=='compilation' and r['status']=='pass']
    write_csv(out/'figure1_inputs.csv',figure_rows)
    make_regime_figure(figure_rows,out/'figure_e5_regime_map_2d.pdf')
    ambiguous=sum(r['status']=='pass' and r['classification']=='little_effect' and
                  (float(r['effect_ci95_low']) < -float(r['effect_tolerance']) or
                   float(r['effect_ci95_high']) > float(r['effect_tolerance'])) for r in rows)
    return dict(status='PASS',scheduled_endpoints=len(rows),counts=dict(c),
                little_effect_intervals_extending_outside_band=ambiguous,
                raw_objective_denominator='max(1, abs(exact optimum))',
                resource_denominator='max(1, abs(matched-random mean for paired compiler seed))',
                direction='control_minus_selective; positive means selective helps',
                classification='low > tolerance: help; high < -tolerance: hurt; otherwise: historical little_effect including uncertainty',
                table_counts=counts,figure_panel_counts=[36,36,36,9,9,9],new_experiments=0)


def make_regime_figure(rows,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.lines import Line2D
    limit=max(abs(float(r['effect'])) for r in rows) or 1
    norm=TwoSlopeNorm(vmin=-limit,vcenter=0,vmax=limit)
    fig,axes=plt.subplots(2,3,figsize=(11.5,6.2),sharex=True,sharey=True)
    labels=[('compiled_two_qubit_gates','Two-qubit gates'),('compiled_two_qubit_depth','Two-qubit depth'),('routing_overhead','Routing overhead')]
    for i,(topology,title) in enumerate([('all_to_all_reference','All-to-all'),('device_sparse_v1','12-qubit grid')]):
        for j,(metric,label) in enumerate(labels):
            ax=axes[i,j];group=[r for r in rows if r['topology_id']==topology and r['metric']==metric]
            for family,marker in [('cubic_spin_glass','o'),('max3sat','^')]:
                part=[r for r in group if r['family']==family]
                artist=ax.scatter([r['pair_reuse_score'] for r in part],[r['canonical_cubic_sparsity'] for r in part],
                                  c=[r['effect'] for r in part],marker=marker,s=42,cmap='RdBu',norm=norm,edgecolors='#263238',linewidths=.4)
            ax.set_title(f'{title}: {label}',fontsize=10)
            ax.text(.98,.96,f'N={len(group)}',ha='right',va='top',transform=ax.transAxes,fontsize=9)
            ax.grid(alpha=.18);ax.set_axisbelow(True)
            if i==1:ax.set_xlabel('Pair-reuse score')
            if j==0:ax.set_ylabel('Canonical cubic sparsity')
    fig.suptitle('Representation-regime map from frozen E5 inputs',y=.985,fontsize=14)
    fig.legend(handles=[Line2D([],[],marker='o',color='none',markerfacecolor='#bbb',markeredgecolor='#263238',label='Cubic spin glass'),
                        Line2D([],[],marker='^',color='none',markerfacecolor='#bbb',markeredgecolor='#263238',label='Max-3SAT')],loc='upper center',bbox_to_anchor=(.5,.951),ncol=2,frameon=False)
    fig.subplots_adjust(left=.075,right=.975,top=.855,bottom=.24,hspace=.30,wspace=.12)
    cax=fig.add_axes((.24,.11,.52,.025))
    cb=fig.colorbar(artist,cax=cax,orientation='horizontal')
    cb.set_label('Normalised control-minus-selective effect; positive favours selective',fontsize=9)
    fig.text(.5,.018,'Each point is an estimable instance-endpoint. Colours show continuous effects, not equivalence or significance.',ha='center',fontsize=9)
    fig.savefig(path)
    plt.close(fig)


def beam_counterexample(selector):
    selector=deepcopy(selector)
    selector['feasibility_limits']['maximum_two_qubit_gates_per_cost_layer']=16
    selector['fibre_risk']['threshold_tau']=1.0
    polynomial={(1,2,3):Fraction(1),(1,2,4):Fraction(1)}
    moments=FibreMoments(0.0,{i:.5 for i in range(1,5)},{p:.25 for p in combinations(range(1,5),2)},'fixture','fixture',0,0,'fixture')
    opts=dict(n_original=4,selector=selector,moments=moments,normalisation=fibre_normalisation(polynomial,positive_margin=1),tau=1,positive_margin=1,apply_qaoa_hard_limits=True)
    early=_candidate(polynomial,tuple(sorted(polynomial)),actions=(None,None),**opts)
    late=_candidate(polynomial,tuple(sorted(polynomial)),actions=(None,(1,2)),**opts)
    if early.resources.feasible or not late.feasible:
        raise ValueError('Beam counterexample did not reproduce')
    return dict(polynomial='x1*x2*x3 + x1*x2*x4',n_original=4,prefix=[None],
                native_completion=[None,None],feasible_completion=[None,[1,2]],
                gate_limit=16,native_completion_gates=early.resources.two_qubit_gate_count,
                feasible_completion_gates=late.resources.two_qubit_gate_count,
                native_completion_feasible=early.resources.feasible,completion_feasible=late.feasible,
                interpretation='Resource-infeasible native completion is not a safe subtree rejection. This fixture uses an altered gate cap, not the frozen production cap.')


def audit_beam(root,out,sources):
    selector=yaml.safe_load((root/'configs/experiment_config_v2.yaml').read_text(encoding='utf-8'))['selector']
    example=beam_counterexample(selector)
    write_json(out/'beam_counterexample.json',example)
    results=[]
    for tier in ['oracle','qaoa','compilation']:
        p=source(root/f'fibre_selector_v2/{tier}_representation_designs_v2.json',sources,root)
        for rec in json.loads(p.read_text(encoding='utf-8'))['records']:
            canonical=source(root/'data/canonical'/f"{rec['instance_id']}.json",sources,root)
            _,poly=_canonical_polynomial(canonical)
            actions=tuple(tuple(a) if a else None for a in rec['selected']['actions'])
            failures=[]
            for depth in range(1,len(actions)+1):
                prefix=actions[:depth]+(None,)*(len(actions)-depth)
                ev=_evaluate_design(poly,n_original=rec['n_original'],actions=prefix,selector=selector,apply_qaoa_hard_limits=tier!='compilation')
                if not ev.feasible:failures.append(depth)
            results.append(dict(tier=tier,instance_id=rec['instance_id'],selected_design_id=rec['selected']['design_id'],
                                selected_prefixes=len(actions),resource_limits_applied=tier!='compilation',
                                resource_infeasible_selected_prefixes=len(failures),depths=json.dumps(failures)))
    write_csv(out/'beam_frozen_selected_prefix_check.csv',results)
    return dict(status='PASS_HISTORICAL_PATH_RECHECK',counterexample_reproduced=True,
                frozen_designs_checked=len(results),infeasible_selected_prefixes=sum(r['resource_infeasible_selected_prefixes'] for r in results),
                scope='Selected archived paths only, not all discarded prefixes or a rerun of Algorithm 3.',
                algorithm_behavior_changed=True,repaired_entrypoint="urss_pipeline.review_search",selected_designs_replaced=0,
                general_algorithm_equivalence_claimed=False,new_qaoa_runs=0)


def audit_correction(root,out,archive):
    if archive is None:
        return dict(status='BLOCKED',reason='Supply --correction-zip with the original complete archive.')
    digest=sha(archive)
    if digest!=RAW_ZIP_SHA256:
        raise ValueError('Correction ZIP differs from manuscript SHA-256')
    with zipfile.ZipFile(archive) as z:
        base='URSS_WARMSTART_CORRECTION_EXECUTED_v1/'
        manifest_name=base+'SHA256_MANIFEST.csv'
        declared=z.read(base+'SHA256_MANIFEST.sha256').decode().strip().split()[0]
        if hashlib.sha256(z.read(manifest_name)).hexdigest()!=declared:raise ValueError('Archive manifest hash mismatch')
        manifest=list(csv.DictReader(io.StringIO(z.read(manifest_name).decode('utf-8-sig'))))
        for row in manifest:
            blob=z.read(base+row['relative_path'])
            if len(blob)!=int(row['size_bytes']) or hashlib.sha256(blob).hexdigest()!=row['sha256']:
                raise ValueError('Archive file hash mismatch: '+row['relative_path'])
        execution=base+'corrections/warmstart_coordinate_correction_v1/exec_20260912_v2/'
        read=lambda name:list(csv.DictReader(io.StringIO(z.read(execution+name).decode('utf-8-sig'))))
        rows=read('targeted/corrected_runs.csv')+read('original_e4/corrected_runs.csv')
        expected=read('plan/EXPECTED_RUNS.csv')
        if len(rows)!=4800 or len({r['task_id'] for r in rows})!=4800 or {r['task_id'] for r in rows}!={r['task_id'] for r in expected}:
            raise ValueError('Correction task identity set mismatch')
        counts=Counter(r['task_outcome'] for r in rows)
        if counts!=Counter(RERUN_PASS=4332,REUSED_VALIDATED=468):raise ValueError('Correction outcomes mismatch')
        from postprocess_correction import aggregate
        draws,instances,paired,desc,summary=aggregate(rows)
        for name,values in [('draw_means.csv',draws),('instance_policy_means.csv',instances),('instance_paired_differences.csv',paired),('descriptive_summary.csv',desc),('paired_summary.csv',summary)]:
            write_csv(out/('correction_'+name),values)
        primary=[r for r in summary if r['scope']=='primary_selected_active_aux' and r['depth_stratum']=='all_scheduled' and r['metric']=='original_objective_mean']
        old=read('analysis/primary_contrasts.csv')
        key=lambda r:tuple(r[k] for k in ['scope','study','family','representation','budget_key','depth_stratum','contrast','metric'])
        lookup={key(r):r for r in old}
        if len(primary)!=60 or {key(r) for r in primary}!=set(lookup):raise ValueError('Primary contrast set mismatch')
        max_error=0.
        for row in primary:
            for field in ['mean','ci95_low','ci95_high','n_instances']:
                err=abs(float(row[field])-float(lookup[key(row)][field]));max_error=max(max_error,err)
                if err>1e-10:raise ValueError('Reconstructed primary contrast differs')
        write_csv(out/'correction_primary_contrasts.csv',primary)
    return dict(status='PASS',zip_sha256=digest,verified_files=len(manifest),raw_tasks=len(rows),
                outcomes=dict(counts),primary_contrasts_reconstructed=60,max_numeric_error=max_error,
                quantum_trajectories_reexecuted=False,public_release_status='NOT_PUBLISHED_BY_THIS_RUN')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--correction-zip',type=Path)
    args=p.parse_args()
    root=Path(__file__).resolve().parent
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    sources={}
    report=dict(baseline_commit=BASE_COMMIT,python=platform.python_version(),scope='Frozen-input postprocessing and historical implementation disclosure',new_qaoa_runs=0)
    try:
        for name in ['run_delivery_closeout.py','urss_pipeline/reference_compiler.py','urss_pipeline/four_part_addendum.py','urss_pipeline/fibre_selector.py','urss_pipeline/e5_regime.py','postprocess_correction.py']:
            source(root/name,sources,root)
        for name,func in [('kappa',audit_kappa),('e5',audit_e5),('beam',audit_beam)]:
            print(f'Running {name} audit...',flush=True)
            report[name]=func(root,out,sources)
        print('Verifying full correction archive and rebuilding summaries...',flush=True)
        report['correction_archive']=audit_correction(root,out,args.correction_zip)
        report['author_declarations']=dict(status='BLOCKED',reason='Authors must supply verified contributions, acknowledgements/funding and software licence choice.')
        report['public_release']=dict(status='BLOCKED',reason='No verified public release URL/tag exists in this local audit.')
        report['status']='POSTPROCESSING_PASS_FINAL_DELIVERY_BLOCKED'
    except Exception as error:
        report.update(status='FAILED',error=f'{type(error).__name__}: {error}')
        raise
    finally:
        write_csv(out/'SOURCE_INPUT_MANIFEST.csv',[dict(relative_path=k,sha256=v) for k,v in sorted(sources.items())])
        write_json(out/'CLOSEOUT_AUDIT.json',report)
        files=[dict(relative_path=str(f.relative_to(out)),sha256=sha(f),size_bytes=f.stat().st_size) for f in sorted(out.rglob('*')) if f.is_file() and f.name not in ['SHA256_MANIFEST.csv','SHA256_MANIFEST.sha256']]
        write_csv(out/'SHA256_MANIFEST.csv',files)
        (out/'SHA256_MANIFEST.sha256').write_text(sha(out/'SHA256_MANIFEST.csv')+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['correction_archive']['status']=='PASS' else 2


if __name__=='__main__':
    sys.exit(main())
