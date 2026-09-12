"""Rebuild D01, D04-D06 and D08 from immutable, explicitly named input records.

This is the authoritative instance-level Student-t postprocessing entrypoint.
It does not generate optimizer observations or overwrite historical CSV files.
"""
from __future__ import annotations
import argparse,csv,json,hashlib,math,statistics
from pathlib import Path
from collections import defaultdict
from dataclasses import replace
import yaml
from scipy.stats import t
from urss_pipeline.four_part_addendum import load_fibre_moments
from urss_pipeline.fibre_selector import fibre_risk
from urss_pipeline.e1_exactness import _canonical_polynomial

REPS=['all_native','fully_quadratized','selective','matched_random_selective']
LABELS=['Native','Full','Selective','Matched random']
RESOURCE=['two_qubit_gates','two_qubit_depth','swap_count','routing_overhead']
METRICS=['original_objective_mean','optimum_hit_rate','encoded_energy_mean','auxiliary_inconsistency_rate']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_csv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write_csv(p,rows):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=sorted({k for row in rows for k in row}));w.writeheader();w.writerows(rows)
def write_json(p,x):Path(p).write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def stats(values):
    n=len(values)
    if not n:raise ValueError('Empty statistical sample')
    mean=statistics.fmean(values);sd=statistics.stdev(values) if n>1 else None
    half=float(t.ppf(.975,n-1))*sd/math.sqrt(n) if n>1 else None
    return dict(n_instances=n,mean=mean,ci95_low=mean-half if half is not None else None,
        ci95_high=mean+half if half is not None else None,sd=sd,df=n-1)


def resource_instances(rows):
    """Median seeds per draw/design, then equal-weight mean across five draws."""
    groups=defaultdict(list)
    for i,r in enumerate(rows,2):
        key=tuple(r[k] for k in ['topology_id','family','instance_id','representation','random_rep_seed','design_id'])
        groups[key].append((i,r))
    designs=[]
    for key,group in sorted(groups.items()):
        if len(group)!=5 or len({r['transpiler_seed'] for _,r in group})!=5:raise ValueError('Expected five unique compiler seeds')
        status={r['status'] for _,r in group}
        if status!={'pass'}:
            if all(r['failure_kind']=='expected_width_infeasible' for _,r in group):continue
            if all('width' in r['failure_kind'].lower() or 'capacity' in r['failure_kind'].lower() for _,r in group):continue
            raise ValueError('Unexpected or partial compiler failure: '+str(key)+str(status))
        row=dict(zip(['topology_id','family','instance_id','representation','random_rep_seed','design_id'],key))
        row.update({m:statistics.median(float(r[m]) for _,r in group) for m in RESOURCE})
        row['source_csv_rows']=','.join(str(i) for i,_ in group);designs.append(row)
    groups=defaultdict(list)
    for r in designs:groups[tuple(r[k] for k in ['topology_id','family','instance_id','representation'])].append(r)
    instances=[]
    for key,group in sorted(groups.items()):
        expected=5 if key[-1]=='matched_random_selective' else 1
        if len(group)!=expected or len({r['random_rep_seed'] for r in group})!=expected:raise ValueError('Missing random draw or design')
        row=dict(zip(['topology_id','family','instance_id','representation'],key));row['n_design_draws']=len(group)
        row.update({m:statistics.fmean(r[m] for r in group) for m in RESOURCE});instances.append(row)
    return designs,instances


def resource_summary(instances):
    groups=defaultdict(dict)
    for r in instances:groups[(r['topology_id'],r['family'],r['instance_id'])][r['representation']]=r
    paired=[]
    for (topology,family,iid),reps in sorted(groups.items()):
        if set(REPS)-set(reps):continue
        for rep in REPS[1:]:
            row=dict(topology_id=topology,family=family,instance_id=iid,representation=rep)
            row.update({m:reps[rep][m]-reps['all_native'][m] for m in RESOURCE});paired.append(row)
    summary=[]
    for topology,family,rep in sorted({(r['topology_id'],r['family'],r['representation']) for r in paired}):
        g=[r for r in paired if (r['topology_id'],r['family'],r['representation'])==(topology,family,rep)]
        summary.append(dict(topology_id=topology,family=family,representation=rep,n_instances=len(g),
            **{m:statistics.median(r[m] for r in g) for m in RESOURCE}))
    return paired,summary


def aggregate_qaoa(rows,condition):
    groups=defaultdict(list)
    for r in rows:
        if r['status']!='pass':raise ValueError('Unsuccessful QAOA row')
        groups[tuple(r[k] for k in ['family','instance_id','representation',condition,'random_rep_seed','design_id'])].append(r)
    design=[]
    for key,g in sorted(groups.items()):
        if len(g)!=3 or len({r['restart_id'] for r in g})!=3:raise ValueError('Expected three unique restarts')
        row=dict(zip(['family','instance_id','representation',condition,'random_rep_seed','design_id'],key))
        row.update({m:statistics.fmean(float(r[m]) for r in g) for m in METRICS});design.append(row)
    groups=defaultdict(list)
    for r in design:groups[tuple(r[k] for k in ['family','instance_id','representation',condition])].append(r)
    instances=[]
    for key,g in sorted(groups.items()):
        expected=5 if key[2]=='matched_random_selective' else 1
        if len(g)!=expected or len({r['random_rep_seed'] for r in g})!=expected:raise ValueError('QAOA draw count mismatch')
        row=dict(zip(['family','instance_id','representation',condition],key))
        row.update({m:statistics.fmean(r[m] for r in g) for m in METRICS});instances.append(row)
    return instances


def qaoa_summaries(instances,condition):
    summaries=[];paired=[]
    lookup={(r['family'],r['instance_id'],r['representation'],r[condition]):r for r in instances}
    for family,rep,cond in sorted({(r['family'],r['representation'],r[condition]) for r in instances}):
        group=[r for r in instances if (r['family'],r['representation'],r[condition])==(family,rep,cond)]
        for metric in METRICS:
            summaries.append(dict(family=family,representation=rep,**{condition:cond},metric=metric,**stats([r[metric] for r in group])))
            if rep!='all_native':
                diffs=[r[metric]-lookup[(family,r['instance_id'],'all_native',cond)][metric] for r in group]
                st=stats(diffs)
                paired.append(dict(family=family,representation=rep,**{condition:cond},metric=metric,**st,
                    dz=st['mean']/st['sd'] if st['sd'] else None,wins=sum(v<-.01 for v in diffs),
                    ties=sum(abs(v)<=.01 for v in diffs),losses=sum(v>.01 for v in diffs)))
    return summaries,paired


def audit_risk(root,out,cfg):
    selector=cfg['selector'];tau=float(selector['fibre_risk']['threshold_tau']);tol=float(selector['fibre_risk']['numeric_tolerance'])
    delta=float(cfg['qaoa']['warm_start']['clipping_delta']);rows=[]
    clip=lambda x:min(1-delta,max(delta,float(x)))
    for tier in ['oracle','compilation','qaoa']:
        moments=load_fibre_moments(root/'fibre_selector_v2/sa_rlt_moments_v2.json',tier=tier)
        records=json.loads((root/f'fibre_selector_v2/{tier}_representation_designs_v2.json').read_text())['records']
        for rec in records:
            _,poly=_canonical_polynomial(root/'data/canonical'/f"{rec['instance_id']}.json")
            m=moments[rec['instance_id']];actions=tuple(tuple(a) if a else None for a in rec['selected']['actions'])
            singles={i:clip(x) for i,x in m.singles.items()}
            policies={'raw_selection':m,
                'prepared_pair_clipped_on_selector_LP':replace(m,singles=singles,pairs={p:clip(x) for p,x in m.pairs.items()}),
                'prepared_independence_on_selector_LP':replace(m,singles=singles,pairs={p:singles[p[0]]*singles[p[1]] for p in m.pairs}),
                'prepared_original_only_on_selector_LP':replace(m,singles=singles,pairs={p:.5 for p in m.pairs})}
            for policy,vector in policies.items():
                risk=fibre_risk(poly,n_original=rec['n_original'],actions=actions,moments=vector,
                    positive_margin=float(selector['fibre_risk']['positive_penalty_margin']))
                rows.append(dict(tier=tier,instance_id=rec['instance_id'],family=rec['family'],policy=policy,
                    moment_sha256=m.moment_sha256,design_id=rec['selected']['design_id'],normalised_excess=risk.normalised_excess,
                    excess=risk.excess,normalisation=risk.normalisation,threshold=tau,numeric_tolerance=tol,exceeds_threshold=risk.normalised_excess>tau+tol))
    write_csv(out/'D01_raw_vs_prepared_diagnostic.csv',rows)
    summary=[]
    for tier in ['oracle','compilation','qaoa']:
        for policy in policies:
            g=[r for r in rows if r['tier']==tier and r['policy']==policy]
            summary.append(dict(tier=tier,policy=policy,n=len(g),exceedances=sum(r['exceeds_threshold'] for r in g),maximum=max(r['normalised_excess'] for r in g)))
    write_csv(out/'D01_risk_summary.csv',summary)
    return summary


def audit_depth(rows,out,source_hash):
    records=[];groups=defaultdict(list)
    for row_number,r in enumerate(rows,2):
        initial=int(r['compiled_2q_budget'])//int(r['compiled_2q_gates_per_layer']);realised=int(r['p'])
        if not 0<realised<=initial or int(r['actual_2q_gates'])>int(r['compiled_2q_budget']):raise ValueError('Invalid realised E6 depth/budget')
        if len(json.loads(r['optimized_parameters_json']))!=2*realised:raise ValueError('E6 parameter dimension differs from realised depth')
        records.append(dict(source_sha256=source_hash,source_row=row_number,instance_id=r['instance_id'],representation=r['representation'],
            random_rep_seed=r['random_rep_seed'],design_id=r['design_id'],restart_id=r['restart_id'],noise_level=r['noise_level'],
            initial_p_reconstructed=initial,realised_p=realised,reduction=initial-realised,actual_2q_gates=int(r['actual_2q_gates']),
            budget=int(r['compiled_2q_budget']),initial_depth_provenance='floor(recorded_budget/recorded_per_layer_gates)',
            realised_depth_provenance='archived_p_column'))
        groups[(r['instance_id'],r['representation'],r['design_id'],r['random_rep_seed'],r['restart_id'])].append(r)
    for key,g in groups.items():
        if len(g)!=3 or {r['noise_level'] for r in g}!={'noiseless','realistic_low','realistic_high'}:raise ValueError('E6 noise pairing missing')
        for field in ['p','actual_2q_gates','transpiler_seed','optimized_parameters_sha256']:
            if len({r[field] for r in g})!=1:raise ValueError('E6 pairing uses different '+field)
        base=next(r for r in g if r['noise_level']=='noiseless')
        for r in g:
            actual=float(r['original_objective_mean'])-float(base['original_objective_mean'])
            if abs(actual-float(r['paired_degradation_vs_noiseless']))>1e-10:raise ValueError('E6 archived degradation mismatch')
    write_csv(out/'D08_e6_initial_and_realised_depth.csv',records)
    designs={ (r['instance_id'],r['representation'],r['design_id'],r['random_rep_seed']):r for r in records }
    return dict(raw_rows=len(rows),paired_restart_groups=len(groups),design_draw_groups=len(designs),
        reduced_design_draws=sum(r['reduction']>0 for r in designs.values()),maximum_reduction=max(r['reduction'] for r in records),
        reconstructed_initial_depth=True,full_circuit_recompilation_performed=False,paired_depth_and_parameters_verified=True)


def latex_table(path,headers,rows):
    def escape(x):return str(x).replace('_',r'\_')
    lines=[r'\begin{tabular}{'+'l'*len(headers)+'}',r'\hline',' & '.join(map(escape,headers))+r' \\',r'\hline']
    lines+=[' & '.join(map(escape,row))+r' \\' for row in rows];lines += [r'\hline',r'\end{tabular}','']
    path.write_text('\n'.join(lines))


def figures(out,resource,e3,e6):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    colors=['#596b80','#bd6c39','#168478','#8255a4'];families=['cubic_spin_glass','max3sat'];fn=['Cubic spin glass','Max-3SAT']
    fig,axs=plt.subplots(2,2,figsize=(10,6),layout='constrained')
    for row,family in enumerate(families):
        for col,topo in enumerate(['all_to_all_reference','device_sparse_v1']):
            ax=axs[row,col];g=[r for r in resource if r['family']==family and r['topology_id']==topo]
            x=np.arange(3)
            for j,metric in enumerate(RESOURCE[:2]):
                vals=[next(r[metric] for r in g if r['representation']==rep) for rep in REPS[1:]]
                ax.bar(x+(j-.5)*.32,vals,.32,color=colors[j+1],label=['Gates','Depth'][j])
            ax.axhline(0,c='black',lw=.7);ax.set_xticks(x,LABELS[1:]);ax.set_ylabel('Median paired difference vs native')
            ax.set_title(fn[row]+' | '+['All-to-all','12-qubit grid'][col]+f" | n={g[0]['n_instances']}")
    axs[0,0].legend(frameon=False);fig.savefig(out/'D04_D05_resources_corrected.pdf');fig.savefig(out/'D04_D05_resources_corrected.png',dpi=140);plt.close(fig)
    budgets=['equal_layer_p1','equal_layer_p2','equal_2q_budget_128','equal_2q_budget_256']
    fig,axs=plt.subplots(2,3,figsize=(12,6),layout='constrained')
    for row,family in enumerate(families):
        for col,metric in enumerate(METRICS[1:]):
            ax=axs[row,col]
            for j,rep in enumerate(REPS):
                g=[next(r for r in e3 if (r['family'],r['representation'],r['metric'],r['budget_key'])==(family,rep,metric,b)) for b in budgets]
                ax.errorbar(np.arange(4)+(j-1.5)*.14,[r['mean'] for r in g],yerr=[[r['mean']-r['ci95_low'] for r in g],[r['ci95_high']-r['mean'] for r in g]],fmt='o',ms=3,capsize=2,color=colors[j],label=LABELS[j])
            ax.set_xticks(range(4),['p=1','p=2','B=128','B=256']);ax.set_title(fn[row]+' | '+['P(opt)','Encoded energy','Auxiliary inconsistency'][col]);ax.set_ylabel('Mean and instance-level 95% t interval')
    axs[0,0].legend(frameon=False,fontsize=7);fig.savefig(out/'D08_e3_diagnostics.pdf');fig.savefig(out/'D08_e3_diagnostics.png',dpi=140);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    for i,family in enumerate(families):
        for j,rep in enumerate(REPS):
            g=[next(r for r in e6 if (r['family'],r['representation'],r['metric'],r['noise_level'])==(family,rep,'original_objective_mean',n)) for n in ['noiseless','realistic_low','realistic_high']]
            axs[i].errorbar(np.arange(3)+(j-1.5)*.06,[r['mean'] for r in g],yerr=[[r['mean']-r['ci95_low'] for r in g],[r['ci95_high']-r['mean'] for r in g]],fmt='o-',ms=3,capsize=2,color=colors[j],label=LABELS[j])
        axs[i].set_xticks(range(3),['Noiseless','Low','High']);axs[i].set_title(fn[i]+' | n=9');axs[i].set_ylabel('Original objective; mean and 95% t interval')
    axs[0].legend(frameon=False,fontsize=8);fig.savefig(out/'D08_e6_noise.pdf');fig.savefig(out/'D08_e6_noise.png',dpi=140);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parent;out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    cfg=yaml.safe_load((root/'configs/experiment_config_v2.yaml').read_text())
    risks=audit_risk(root,out,cfg)
    rp=root/'fibre_e1_e6_v2/results/e2_compiled_resources_by_seed.csv';resources=read_csv(rp)
    designs,instances=resource_instances(resources);paired,summary=resource_summary(instances)
    write_csv(out/'D04_D05_seed_median_per_design.csv',designs);write_csv(out/'D04_D05_instance_resources.csv',instances)
    write_csv(out/'D04_D05_paired_resources.csv',paired);write_csv(out/'D04_D05_resource_summary.csv',summary)
    ep=root/'fibre_e1_e6_v2/results/e3_qaoa_runs.csv';np=root/'fibre_e1_e6_v2/results/e6_noise_runs.csv'
    erows=read_csv(ep);nrows=read_csv(np);ei=aggregate_qaoa(erows,'budget_key');ni=aggregate_qaoa(nrows,'noise_level')
    es,epa=qaoa_summaries(ei,'budget_key');ns,npa=qaoa_summaries(ni,'noise_level')
    for name,rows in [('E3_instance_means',ei),('E3_student_t_summary',es),('E3_paired_student_t',epa),('E6_instance_means',ni),('E6_student_t_summary',ns),('E6_paired_student_t',npa)]:write_csv(out/(name+'.csv'),rows)
    depth=audit_depth(nrows,out,sha(np))
    noisy={(r['family'],r['instance_id'],r['representation'],r['noise_level']):r for r in ni}
    degradation=[]
    for family,rep in sorted({(r['family'],r['representation']) for r in ni}):
        g=[r for r in ni if r['family']==family and r['representation']==rep and r['noise_level']=='realistic_high']
        degradation.append(dict(family=family,representation=rep,**stats([r['original_objective_mean']-noisy[(family,r['instance_id'],rep,'noiseless')]['original_objective_mean'] for r in g])))
    write_csv(out/'E6_high_noise_degradation_student_t.csv',degradation)
    for topology,label in [('all_to_all_reference','D04_table3'),('device_sparse_v1','D05_table5')]:
        g=[r for r in summary if r['topology_id']==topology]
        latex_table(out/(label+'.tex'),['Family','Representation','N','Gates','Depth','SWAP','Routing'],
            [[r['family'],r['representation'],r['n_instances']]+[f'{r[m]:.6g}' for m in RESOURCE] for r in g])
    g=[r for r in npa if r['representation']=='selective' and r['metric']=='original_objective_mean']
    latex_table(out/'D08_table23.tex',['Family','Noise','N','Mean','95 percent interval','W/T/L'],[[r['family'],r['noise_level'],r['n_instances'],f"{r['mean']:.3f}",f"[{r['ci95_low']:.3f}, {r['ci95_high']:.3f}]",f"{r['wins']}/{r['ties']}/{r['losses']}"] for r in g])
    figures(out,summary,es,ns)
    audit=dict(status='PASS',risk_choice='Retain explicit raw-moment guardrail; report prepared-state risk separately. No change of LP representative.',
        raw_compiler_rows=len(resources),resource_common_n={str((r['topology_id'],r['family'])):r['n_instances'] for r in summary},
        e3_raw_rows=len(erows),e3_instances=len({r['instance_id'] for r in erows}),e6_depth_audit=depth,
        original_e4_initial_state_claim='D01 uses selector LP vectors; original E4 first-optimum vectors are a distinct archive and are not identified with these vectors.',
        statistical_unit='raw instance; three restart means then five random-draw means; Student t n-1',qaoa_optimisations_executed=0,
        risk_exceedances={r['tier']:r['exceedances'] for r in risks if r['policy']=='prepared_pair_clipped_on_selector_LP'})
    write_json(out/'POSTPROCESS_REVIEW_AUDIT.json',audit)
    files=[root/'configs/experiment_config_v2.yaml',rp,ep,np,root/'fibre_selector_v2/sa_rlt_moments_v2.json']
    files+=list((root/'fibre_selector_v2').glob('*_representation_designs_v2.json'))
    write_csv(out/'SOURCE_MANIFEST.csv',[dict(path=str(f.relative_to(root)),sha256=sha(f)) for f in files])
    print(json.dumps(audit,indent=2),flush=True)
if __name__=='__main__':main()
