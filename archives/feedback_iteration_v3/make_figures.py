from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
B=Path(__file__).resolve().parent;a=json.loads((B/'analysis.json').read_text());out=B/'figures';out.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
labels={'max3sat':'Max-3SAT (n=30)','spin_glass':'Cubic spin glass (n=30)','constructed':'Constructed cohort (n=12)'}
fig,axes=plt.subplots(1,3,figsize=(11.5,3.7),sharey=True)
for ax,(fam,label) in zip(axes,labels.items()):
 f=a['families'][fam];n=f['instances'];domains=['native','full','mixed'];arms=f['primary_joint_resource_quality']['arms'];resource=[arms[d]['resource_feasible']/n for d in domains];joint=[arms[d]['joint_pass']/n for d in domains];x=np.arange(3)
 ax.bar(x,resource,color='#cbd5e1',width=.62);ax.bar(x,joint,color='#0f766e',width=.62)
 for i,d in enumerate(domains):ax.text(i,max(resource[i],joint[i])+.035,f"{arms[d]['joint_pass']}/{n}",ha='center',fontsize=10)
 ax.set_xticks(x,['Native','Full','Mixed']);ax.set_ylim(0,1.14);ax.set_title(label,fontsize=11,fontweight='bold');ax.grid(axis='y',alpha=.16);ax.set_axisbelow(True)
axes[0].set_ylabel('Fraction of independent instances')
fig.legend(handles=[Patch(color='#cbd5e1',label='Resource feasible'),Patch(color='#0f766e',label='Resource feasible and quality target met')],loc='upper center',bbox_to_anchor=(.5,.89),ncol=2,frameon=False)
fig.suptitle('Primary joint resource–quality test: no mixed-only success',fontsize=14,fontweight='bold',y=1.02)
fig.text(.5,-.015,'Fixed budget: Q ≤ 12, CX ≤ 96, CX depth ≤ 64, penalty ≤ 16. Quality: normalized gap ≤ 0.2; scan + refinement.',ha='center',fontsize=9)
fig.subplots_adjust(top=.70,bottom=.13,wspace=.14)
for ext in ['png','svg']:fig.savefig(out/f'primary_joint_results.{ext}',dpi=240,bbox_inches='tight')
plt.close(fig)
fig,axes=plt.subplots(1,2,figsize=(10.5,3.6))
for ax,outcome,title in zip(axes,['gap','inconsistency'],['Prediction of solution-quality gap','Prediction of auxiliary inconsistency']):
 d=a['prediction']['outcomes'][outcome];base=d['mean_squared_error']['base']
 for j,label in enumerate(['raw','prepared','both']):
  v=d['incremental_mse_improvement'][label];mean=100*v['mean']/base;lo=100*v['low']/base;hi=100*v['high']/base
  ax.errorbar(mean,j,xerr=[[mean-lo],[hi-mean]],fmt='o',color='#0f766e' if outcome=='inconsistency' else '#b45309',capsize=4,markersize=6)
 ax.axvline(0,color='#64748b',linestyle='--',linewidth=1);ax.set_yticks(range(3),['Raw diagnostic','Prepared diagnostic','Both']);ax.invert_yaxis();ax.set_title(title,fontsize=11,fontweight='bold');ax.set_xlabel('Held-out MSE reduction relative to controls (%)');ax.grid(axis='x',alpha=.15)
fig.suptitle('Diagnostic value differs from selection benefit',fontsize=14,fontweight='bold',y=1.05)
fig.text(.5,-.08,'60 independent instances; 480 prespecified probes. Leave-one-instance-out linear models. Descriptive 95% instance-bootstrap intervals.',ha='center',fontsize=9)
fig.tight_layout(w_pad=2.7)
for ext in ['png','svg']:fig.savefig(out/f'diagnostic_prediction.{ext}',dpi=240,bbox_inches='tight')
plt.close(fig)
print('FIGURES: 2 PNG + 2 SVG')
