"""Create manuscript-ready QAOA tables/figures from verified rerun outputs."""
from pathlib import Path
import argparse,csv,math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

FAMILIES=['cubic_spin_glass','max3sat'];FLABEL=['Cubic spin glass','Max-3SAT']
REPS=['all_native','fully_quadratized','selective','matched_random_selective']
LABELS=['Native','Full','Selective','Matched random'];COLORS=['#567089','#c06c35','#168b83','#805bab']
BUDGETS=['equal_layer_p1','equal_layer_p2','equal_2q_budget_128','equal_2q_budget_256']
BLABEL=['p=1','p=2','B=128','B=256']
def read(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def number(s):return float(s) if s not in [None,''] else None
def save(fig,path):
    fig.savefig(path.with_suffix('.pdf'));fig.savefig(path.with_suffix('.png'),dpi=160);plt.close(fig)
def main(root):
    out=root/'paper_updates';out.mkdir(exist_ok=True)
    primary=read(root/'analysis/PRIMARY_WARMSTART_CONTRASTS.csv')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    for study in ['original_e4','targeted']:
        fig,axes=plt.subplots(1,2,figsize=(10.5,4.4),layout='constrained')
        for ax,family,label in zip(axes,FAMILIES,FLABEL):
            rows=sorted([r for r in primary if r['study']==study and r['family']==family and r['contrast']=='pair_minus_cold'],key=lambda r:BUDGETS.index(r['budget_key']))
            for y,r in enumerate(rows):
                value=float(r['mean']);low=number(r['ci95_low']);high=number(r['ci95_high'])
                if low is None:ax.plot(value,y,'x',color=COLORS[2],markersize=8)
                else:ax.errorbar(value,y,xerr=[[value-low],[high-value]],fmt='o',color=COLORS[2],capsize=4)
            ax.axvline(0,color='#777777',ls='--',lw=1);ax.grid(axis='x',alpha=.2)
            ax.set_yticks(range(len(rows)),[BLABEL[BUDGETS.index(r['budget_key'])]+f" (n={r['n_instances']})" for r in rows]);ax.invert_yaxis()
            ax.set_title(label);ax.set_xlabel('Pair minus cold: original objective\nNegative favors pair warm start')
            if rows and rows[0]['n_instances']=='1':ax.text(.03,.97,'Cross: one instance; CI unavailable',transform=ax.transAxes,va='top',fontsize=9)
            ax.margins(y=.3)
        fig.suptitle(('Fixed targeted cohort' if study=='targeted' else 'Original E4: updated active-auxiliary subset')+'\nExploratory instance-level 95% Student-t intervals',fontsize=12)
        save(fig,out/('figure_'+study+'_selector_rerun_v3'))
        rows=[r for r in primary if r['study']==study and r['contrast']=='pair_minus_cold']
        lines=[r'\begin{table}[tb]',r'\centering\small',r'\begin{tabular}{llrrrr}',r'\hline',r'Family & Budget & $n$ & Pair $-$ cold & CI low & CI high \\',r'\hline']
        fmt=lambda x:'--' if x=='' else f'{float(x):.4f}'
        for family,label in zip(FAMILIES,['Spin glass','Max-3SAT']):
            for r in sorted([r for r in rows if r['family']==family],key=lambda r:BUDGETS.index(r['budget_key'])):
                lines.append(' & '.join([label,BLABEL[BUDGETS.index(r['budget_key'])],r['n_instances'],fmt(r['mean']),fmt(r['ci95_low']),fmt(r['ci95_high'])])+r' \\')
        caption=('Fixed targeted instances after the selector repair; 10 instances per family.' if study=='targeted' else 'Updated original E4 active-auxiliary subset; one spin-glass and seven Max-3SAT instances. A Student-t interval cannot be estimated for the single spin-glass instance.')
        caption+=' All three restarts are averaged within each raw instance. Negative differences favor pair warm starts. Intervals are unadjusted exploratory 95\\% Student-t intervals; no advantage was required for execution success.'
        lines += [r'\hline',r'\end{tabular}',r'\caption{'+caption+'}',r'\label{tab:'+study.replace('_','-')+'-selector-rerun-v3}',r'\end{table}']
        (out/('table_'+study+'_selector_rerun_v3.tex')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    rows=read(root/'analysis/E3_summary.csv')
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for i,(family,flabel) in enumerate(zip(FAMILIES,FLABEL)):
        for j,(metric,mlabel) in enumerate([('original_objective_mean','Original objective'),('optimum_hit_rate','P(opt)')]):
            ax=axes[i,j]
            for k,(rep,label,color) in enumerate(zip(REPS,LABELS,COLORS)):
                group=sorted([r for r in rows if r['family']==family and r['representation']==rep and r['metric']==metric],key=lambda r:BUDGETS.index(r['budget_key']))
                means=np.array([float(r['mean']) for r in group]);lo=np.array([float(r['ci95_low']) for r in group]);hi=np.array([float(r['ci95_high']) for r in group])
                ax.errorbar(np.arange(4)+(k-1.5)*.16,means,yerr=[means-lo,hi-means],fmt='o',markersize=4,capsize=3,color=color,label=label)
            ax.set_xticks(range(4),BLABEL);ax.set_title(flabel+' | '+mlabel);ax.set_ylabel('Mean and 95% interval');ax.grid(axis='y',alpha=.18)
    handles,labels=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
    fig.suptitle('E3 after selector repair | instance-level Student-t summaries',fontsize=12)
    save(fig,out/'figure_e3_selector_rerun_v3')
    rows=read(root/'analysis/E6_summary.csv');levels=['noiseless','realistic_low','realistic_high']
    fig,axes=plt.subplots(1,2,figsize=(10.5,4.8),layout='constrained')
    for ax,family,flabel in zip(axes,FAMILIES,FLABEL):
        for k,(rep,label,color) in enumerate(zip(REPS,LABELS,COLORS)):
            group=sorted([r for r in rows if r['family']==family and r['representation']==rep and r['metric']=='original_objective_mean'],key=lambda r:levels.index(r['noise_level']))
            means=np.array([float(r['mean']) for r in group]);lo=np.array([float(r['ci95_low']) for r in group]);hi=np.array([float(r['ci95_high']) for r in group])
            ax.errorbar(np.arange(3)+(k-1.5)*.025,means,yerr=[means-lo,hi-means],fmt='o-',markersize=4,capsize=3,color=color,label=label)
        ax.set_xticks(range(3),['Noiseless','Low','High']);ax.set_title(flabel+' | n=9');ax.set_ylabel('Original objective: mean and 95% interval');ax.grid(axis='y',alpha=.18)
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
    fig.suptitle('E6 after selector repair | fixed synthetic noise protocol',fontsize=12)
    save(fig,out/'figure_e6_selector_rerun_v3')
    text=r'''% Integration fragment. Requires the CURRENT Overleaf source project.
% Historical E2/E5 resource-dependent results still require a separate update.
\paragraph{Execution after the selector repair.}
We retained all frozen instance cohorts, optimizer budgets, seed bundles, and
archived relaxation vectors. Changed selected representations and their changed
matched-random controls were rebuilt before downstream execution. The selective
QAOA update performed 420 independent positive-depth optimizations (60 objective
calls per restart under the frozen early-stop padding rule), producing 492 new
observations: 72 for E3, 144 for the original E4 study, 168 for the fixed targeted
study, and 108 for E6. E6 used 36 noiseless optimizations and evaluated each
parameter vector at all three frozen noise levels with 4096 shots per level.
Unchanged archived observations retain their original provenance.

\paragraph{Changes in design eligibility and depth.}
One original E4 spin-glass instance now has no active auxiliary variables.
Its pair-auxiliary policies coincide with already scheduled policies and are
therefore deduplicated under the frozen protocol, removing 144 obsolete rows
across its selected representation and five matched-random draws.
The original E4 active-auxiliary analysis consequently contains one spin-glass
and seven Max-3SAT instances. No Student-t confidence interval is estimable for
the single spin-glass instance; changes in active-subset composition must not
be interpreted as an improvement on an unchanged cohort.
All new encodings passed exhaustive checks over their original/auxiliary bit
assignments, and all uniform-marginal cold/warm null controls passed.
E3 and E4 budgets were recomputed from the median of the five frozen compiler
seeds. E6 additionally checked the complete transpiled measured circuit: six
of the twelve changed design/draw groups required reduction from initial
$p=2$ to realised $p=1$; the other six retained $p=2$.

\paragraph{Updated warm-start evidence.}
On the unchanged fixed targeted Max-3SAT cohort of ten instances, the
pair-minus-cold original-objective difference is $-6.7614$
(95\% Student-t interval $[-9.2630,-4.2599]$) at $p=1$, and $-6.7120$
($[-9.1440,-4.2801]$) at $p=2$. Lower objective values favor pair warm starts.
The corresponding targeted spin-glass intervals include zero at both depths.
These are unadjusted exploratory instance-level intervals, not evidence of a
universal warm-start advantage. The original E4 Max-3SAT intervals also include
zero; the remaining active spin-glass subset has insufficient size for an interval.

% Suggested insertion, adapting paths and labels to the current project:
% \input{paper_updates/table_targeted_selector_rerun_v3}
% \input{paper_updates/table_original_e4_selector_rerun_v3}
'''
    (out/'PAPER_QAOA_UPDATE_V3.tex').write_text(text,encoding='utf-8')
    (out/'README_ZH.md').write_text('这些表、图和正文片段来自已完成的定向 QAOA 重跑。\n\n当前新版论文只有 PDF，尚未提供对应 Source ZIP，因此此目录不是完整 Overleaf 项目。收到当前源码后，再按现有宏、标签、图表编号合并。\n\nE2 编译实验和依赖资源结果的 E5 仍需另行更新；本目录不能用于声称全部 E1-E6 已采用新选择器。\n',encoding='utf-8')
    print('PAPER UPDATE FIGURES AND TABLES: COMPLETE')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.output.resolve())
