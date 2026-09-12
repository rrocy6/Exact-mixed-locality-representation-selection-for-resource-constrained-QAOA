"""Pre-specified instance-level warm-start summaries and correction figures."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json
import math
import statistics

import numpy as np
from scipy.stats import t

from urss_pipeline.four_part_addendum import read_csv, read_json, write_csv, write_json
from warmstart_correction import read_task_inputs

METRICS=('original_objective_mean','encoded_energy_mean','optimum_hit_rate','auxiliary_inconsistency_rate','statevector_norm')
CONTRASTS=(('pair_minus_cold','pair','cold'),('original_only_minus_cold','original_only','cold'),
           ('independence_minus_cold','independence','cold'),('pair_minus_original_only','pair','original_only'),
           ('pair_minus_independence','pair','independence'))


def policy(row):
    if row['warm_start_policy']=='cold_start':return 'cold'
    if row['warm_start_policy']=='original_variables_only':return 'original_only'
    return {'sa_rlt_level_2_pair_moments':'pair','independence_mu_product_ablation':'independence'}[row['pair_closure']]


def interval(values):
    values=[float(x) for x in values]
    n=len(values)
    mean=statistics.fmean(values)
    if n<2:
        return {'n_instances':n,'mean':mean,'sd':None,'ci95_low':None,'ci95_high':None,'df':n-1,'ci_status':'not_estimable'}
    sd=statistics.stdev(values)
    half=float(t.ppf(0.975,n-1))*sd/math.sqrt(n)
    return {'n_instances':n,'mean':mean,'sd':sd,'ci95_low':mean-half,'ci95_high':mean+half,'df':n-1,'ci_status':'estimated'}


def aggregate(rows):
    """3 restarts -> each archived draw -> raw instance; never pool studies."""
    draw_groups=defaultdict(list)
    active=defaultdict(set)
    for row in rows:
        if row.get('task_outcome','RERUN_PASS') not in ('RERUN_PASS','REUSED_VALIDATED'):
            raise ValueError('Incomplete rows cannot enter full-study aggregation')
        if row['representation']=='selective' and int(row['n_aux'])>0:
            active[(row['study'],row['family'])].add(row['instance_id'])
        key=(row['study'],row['family'],row['instance_id'],row['representation'],row['budget_key'],policy(row),row['random_rep_seed'])
        draw_groups[key].append(row)
    draws=[]
    for key,group in draw_groups.items():
        if len(group)!=3 or {int(r['restart_id']) for r in group}!={0,1,2}:
            raise ValueError('Each draw must retain all three restarts')
        depths={int(r['p']) for r in group}
        if len(depths)!=1:raise ValueError('Depth varies across a draw')
        row=dict(zip(('study','family','instance_id','representation','budget_key','policy','random_rep_seed'),key))
        row.update(p=depths.pop(),restart_count=3)
        row.update({metric:statistics.fmean(float(r[metric]) for r in group) for metric in METRICS})
        draws.append(row)
    instance_groups=defaultdict(list)
    for row in draws:
        for stratum in ('all_scheduled','positive_depth_only' if row['p']>0 else 'zero_depth_only'):
            key=tuple(row[k] for k in ('study','family','instance_id','representation','budget_key','policy'))+(stratum,)
            instance_groups[key].append(row)
    instances=[]
    for key,group in instance_groups.items():
        study,family,instance,rep,budget,pol,stratum=key
        if stratum=='all_scheduled' and len(group)!=(5 if rep=='matched_random_selective' else 1):
            raise ValueError('Missing archived matched draw identity')
        row=dict(zip(('study','family','instance_id','representation','budget_key','policy','depth_stratum'),key))
        row.update({metric:statistics.fmean(r[metric] for r in group) for metric in METRICS})
        row.update(draw_count=len(group),restart_count=3*len(group),
                   zero_depth_draw_count=sum(r['p']==0 for r in group),
                   draw_ids=json.dumps(sorted(r['random_rep_seed'] for r in group)),
                   depths=json.dumps([r['p'] for r in group]))
        instances.append(row)
    index=defaultdict(dict)
    for row in instances:
        key=tuple(row[k] for k in ('study','family','instance_id','representation','budget_key','depth_stratum'))
        index[key][row['policy']]=row
    paired=[]
    for key,policies in index.items():
        for label,a,b in CONTRASTS:
            if a not in policies or b not in policies:continue
            left,right=policies[a],policies[b]
            if left['draw_ids']!=right['draw_ids']:raise ValueError('Paired policies use different draw sets')
            row=dict(zip(('study','family','instance_id','representation','budget_key','depth_stratum'),key))
            row.update(contrast=label,draw_count=left['draw_count'],zero_depth_draw_count=left['zero_depth_draw_count'])
            row.update({metric:left[metric]-right[metric] for metric in METRICS})
            paired.append(row)
    def summarise(source,label_key):
        groups=defaultdict(list)
        for row in source:
            scopes=['all_designs_diagnostic']
            if row['representation']=='selective' and row['instance_id'] in active[(row['study'],row['family'])]:
                scopes.append('primary_selected_active_aux')
            for scope in scopes:
                key=(scope,)+tuple(row[k] for k in ('study','family','representation','budget_key','depth_stratum',label_key))
                groups[key].append(row)
        result=[]
        for key,group in sorted(groups.items()):
            for metric in METRICS:
                row=dict(zip(('scope','study','family','representation','budget_key','depth_stratum',label_key),key))
                row.update(metric=metric,**interval([r[metric] for r in group]),
                           zero_depth_instance_count=sum(r['zero_depth_draw_count']>0 for r in group),
                           ci_unit='raw_instance',ci_method='two_sided_Student_t_95_df_n_minus_1',
                           multiplicity='unadjusted_exploratory')
                result.append(row)
        return result
    return draws,instances,paired,summarise(instances,'policy'),summarise(paired,'contrast')


def tex_table(rows,label,caption):
    def fmt(value):return '--' if value is None else f'{value:.4f}'
    lines=[r'\begin{table}[tb]',r'\centering',r'\small',r'\begin{tabular}{llrrrr}',
           r'\hline',r'Family & Budget & $n$ & Mean difference & 95\% CI low & 95\% CI high \\',r'\hline']
    for row in rows:
        family={'cubic_spin_glass':'Spin glass','max3sat':'Max-3SAT'}[row['family']]
        budget=row['budget_key'].replace('equal_layer_p','$p=')+'$' if row['budget_key'].startswith('equal_layer_p') else '$B='+row['budget_key'].split('_')[-1]+'$'
        lines.append(f"{family} & {budget} & {row['n_instances']} & {fmt(row['mean'])} & {fmt(row['ci95_low'])} & {fmt(row['ci95_high'])} " + r"\\")
    lines += [r'\hline',r'\end{tabular}',r'\caption{'+caption+'}',r'\label{'+label+'}',r'\end{table}']
    return '\n'.join(lines)+'\n'


def postprocess(output):
    target=output/'analysis'
    target.mkdir(exist_ok=False)
    rows=[]
    for study in ('targeted','original_e4'):
        if read_json(output/study/'STUDY_AUDIT.json')['status']!='COMPLETE':raise ValueError('Study incomplete')
        rows+=read_csv(output/study/'corrected_runs.csv')
    draws,instances,paired,descriptive,summaries=aggregate(rows)
    for name,records in [('draw_means.csv',draws),('instance_policy_means.csv',instances),('instance_paired_differences.csv',paired),
                         ('descriptive_summary.csv',descriptive),('paired_summary.csv',summaries)]:
        write_csv(target/name,records)
    old=[dict(entry['source'],study=entry['expected']['study'],task_id=entry['expected']['task_id']) for entry in read_task_inputs(output/'TASK_INPUTS.json')]
    *_,oldsummary=aggregate(old)
    write_csv(target/'historical_paired_summary_same_statistics.csv',oldsummary)
    main=[r for r in summaries if r['scope']=='primary_selected_active_aux' and r['depth_stratum']=='all_scheduled' and r['metric']=='original_objective_mean']
    write_csv(target/'primary_contrasts.csv',main)
    effect=[]
    for row in main:
        decision=('evidence_unclear' if row['ci95_low'] is None or row['ci95_low']<=0<=row['ci95_high']
                  else 'lower_objective_for_first_policy' if row['ci95_high']<0 else 'higher_objective_for_first_policy')
        effect.append(dict(row,interpretation=decision))
    write_json(target/'CLAIM_ASSESSMENT.json',{'exploratory':True,'advantage_required_for_pass':False,'results':effect})
    for study in ('targeted','original_e4'):
        subset=[r for r in main if r['study']==study and r['contrast']=='pair_minus_cold']
        caption=('Corrected pair-minus-cold original-objective differences on the fixed signal-enriched targeted set (10 raw instances per family). '
                 if study=='targeted' else 'Corrected pair-minus-cold original-objective differences on the original selected active-auxiliary subset (2 spin-glass and 7 Max-3SAT instances). ')
        caption+=r'Means first average all three restarts. Negative differences favor pair warm starts. Intervals are unadjusted exploratory instance-level Student-t 95\% intervals. All scheduled depths are retained, including zero-layer rows where applicable.'
        (target/f'table_{study}_warmstart_corrected.tex').write_text(tex_table(subset,f'tab:{study}-warmstart-coordinate-corrected',caption),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for study in ('targeted','original_e4'):
        fig,axes=plt.subplots(1,2,figsize=(11,5.3),layout='constrained')
        for ax,family in zip(axes,('cubic_spin_glass','max3sat')):
            subset=[r for r in main if r['study']==study and r['family']==family and r['contrast']=='pair_minus_cold']
            for i,r in enumerate(subset):
                ax.errorbar(r['mean'],i,xerr=[[r['mean']-r['ci95_low']],[r['ci95_high']-r['mean']]],fmt='o',color='#156b70',capsize=4)
            ax.axvline(0,color='gray',linestyle='--',linewidth=1)
            ax.set_yticks(range(len(subset)),[r['budget_key'].replace('equal_layer_','').replace('equal_2q_budget_','B=')+f" (n={r['n_instances']})" for r in subset])
            ax.set_title('Spin glass' if family=='cubic_spin_glass' else 'Max-3SAT')
            ax.set_xlabel('Pair minus cold: original objective\nNegative favors pair warm start')
            ax.grid(axis='x',alpha=0.2)
        fig.suptitle(('Fixed targeted set' if study=='targeted' else 'Original E4: selected active auxiliaries')+'\nInstance-level means and exploratory 95% Student-t intervals')
        fig.savefig(target/f'figure_{study}_warmstart_corrected.pdf')
        fig.savefig(target/f'figure_{study}_warmstart_corrected.png',dpi=160)
        plt.close(fig)
    print(json.dumps([r for r in main if r['contrast']=='pair_minus_cold'],indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    postprocess(parser.parse_args().output.resolve())
