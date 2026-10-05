"""Rebuild updated manuscript figures from included frozen summaries; no experiments run.
Requires numpy, scipy, matplotlib. Run from any directory with Python 3.
"""
from pathlib import Path
import csv,json,string
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.colors import TwoSlopeNorm
from scipy.stats import t
ROOT=Path(__file__).resolve().parent
F=['cubic_spin_glass','max3sat']; FL=['Cubic spin glass','Max-3SAT']
B=['equal_layer_p1','equal_layer_p2','equal_2q_budget_128','equal_2q_budget_256']; BL=['p=1','p=2','B=128','B=256']
C=['#315b88','#bc6636','#168b83','#7956a2']
plt.rcParams.update({'font.size':10,'axes.titlesize':11,'axes.labelsize':10,'legend.fontsize':9,'xtick.labelsize':9,'ytick.labelsize':9,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'axes.axisbelow':True})
def read(n):
 with (ROOT/'data'/n).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(fig,n):
 fig.savefig(ROOT/'figures'/n,bbox_inches='tight',pad_inches=.05);plt.close(fig)
def ci(ax,x,y,lo,hi,**kw):
 ax.errorbar(x,y,yerr=[[y-lo],[hi-y]],capsize=3,**kw)
# Figure 8: frozen original LP information with current selected-design status.
rows=read('e4_marginal_diagnostics.csv');status={r['instance_id']:r for r in json.loads((ROOT/'data/selected_auxiliary_status.json').read_text())}
points=[]
for iid in sorted(status):
 rr=[r for r in rows if r['instance_id']==iid]
 bias=np.median([float(r['abs_single_margin_from_half']) for r in rr if r['moment_type']=='original_variable'])
 dep=np.median([float(r['abs_pair_vs_independence']) for r in rr if r['moment_type']!='original_variable' and r['abs_pair_vs_independence']!=''])
 points.append(dict(instance_id=iid,family=status[iid]['family'],n_aux=status[iid]['n_aux'],bias=float(bias),dependence=float(dep)))
assert len(points)==14 and sum(p['n_aux']>0 for p in points)==8
assert sum(p['bias']>.05+1e-10 and p['n_aux']>0 for p in points)==2
fig,axs=plt.subplots(1,2,figsize=(7.2,3.6),layout='constrained')
for j,(ax,key,title,ylabel) in enumerate(zip(axs,['bias','dependence'],['(a) Single-variable signal','(b) Pair information'],[r'Median $|\mu_i-1/2|$',r'Median $|q_{ij}-\mu_i\mu_j|$'])):
 for fi,f in enumerate(F):
  pp=[p for p in points if p['family']==f]
  for i,p in enumerate(pp):
   ax.scatter(fi+(i-(len(pp)-1)/2)*.035,p[key],marker='o' if p['n_aux']>0 else 'x',s=36,color=C[fi],linewidths=1.1,zorder=3)
 ax.set_xticks([0,1],['Spin glass','Max-3SAT']);ax.set_xlim(-.4,1.4);ax.set_ylim(bottom=-.008);ax.set_ylabel(ylabel);ax.set_title(title);ax.grid(axis='y',alpha=.2)
axs[0].axhline(.05,color='#666',ls='--',lw=.9);axs[0].text(.02,.05,'  Weak-signal threshold',transform=axs[0].get_yaxis_transform(),va='bottom',fontsize=8)
fig.legend(handles=[Line2D([],[],color='#555',marker='o',ls='',label='Active selected auxiliaries'),Line2D([],[],color='#555',marker='x',ls='',label='Native selected design')],loc='outside upper center',ncol=2,frameon=False)
save(fig,'figure_e4_signal_diagnostics.pdf')
(ROOT/'data/figure8_instance_diagnostics.json').write_text(json.dumps(points,indent=2))
# Figure 9: rebuilt paired estimates and n0 labels, no CI with n=1.
rows=read('PRIMARY_WARMSTART_CONTRASTS.csv');fig,axs=plt.subplots(1,2,figsize=(7.2,3.7),layout='constrained')
for ax,f,label in zip(axs,F,FL):
 rr=sorted([r for r in rows if r['study']=='original_e4' and r['family']==f and r['contrast']=='pair_minus_cold'],key=lambda r:B.index(r['budget_key']))
 for y,r in enumerate(rr):
  val=float(r['mean'])
  if r['ci95_low']=='':ax.plot(val,y,'x',color=C[2],ms=7)
  else:ax.errorbar(val,y,xerr=[[val-float(r['ci95_low'])],[float(r['ci95_high'])-val]],fmt='o',color=C[2],capsize=3)
 ax.set_yticks(range(4),[BL[B.index(r['budget_key'])]+f"  n={r['n_instances']}"+(f", n0={r['zero_depth_instance_count']}" if int(r['zero_depth_instance_count']) else '') for r in rr]);ax.invert_yaxis();ax.set_title(label);ax.axvline(0,color='#777',ls='--',lw=.8);ax.grid(axis='x',alpha=.2);ax.margins(y=.2);ax.set_xlabel('Pair minus cold\nOriginal objective')
save(fig,'figure_original_e4_warmstart_corrected.pdf')
# Figure 11: all three policies on the fixed targeted cohort.
fig,axs=plt.subplots(1,2,figsize=(7.2,3.7),layout='constrained')
for ax,f,label in zip(axs,F,FL):
 for k,(contrast,pol) in enumerate(zip(['original_only_minus_cold','pair_minus_cold','independence_minus_cold'],['Original-only','Pair','Independence'])):
  rr=sorted([r for r in rows if r['study']=='targeted' and r['family']==f and r['contrast']==contrast],key=lambda r:B.index(r['budget_key']))
  for j,r in enumerate(rr):ci(ax,j+(k-1)*.15,float(r['mean']),float(r['ci95_low']),float(r['ci95_high']),fmt='o',color=C[k],label=pol if j==0 else None,ms=4)
 ax.set_xticks([0,1],BL[:2]);ax.set_xlim(-.45,1.45);ax.set_title(label+' (n=10)');ax.set_ylabel('Warm minus cold: original objective');ax.axhline(0,color='#777',ls='--',lw=.8);ax.grid(axis='y',alpha=.2)
fig.legend(*axs[0].get_legend_handles_labels(),loc='outside upper center',ncol=3,frameon=False)
save(fig,'figure_strong_bias_warmstart.pdf')
# Figure 7: rebuilt secondary E3 summaries; unclipped statistical intervals.
rows=read('E3_summary.csv');fig,axs=plt.subplots(2,3,figsize=(8.8,5.8),layout='constrained')
for i,(f,fl) in enumerate(zip(F,FL)):
 for j,(metric,title) in enumerate(zip(['optimum_hit_rate','encoded_energy_mean','auxiliary_inconsistency_rate'],['Optimal-solution probability','Encoded energy','Auxiliary inconsistency'])):
  ax=axs[i,j]
  for k,(rep,label) in enumerate(zip(['all_native','fully_quadratized','selective','matched_random_selective'],['Native','Full','Selective','Matched random'])):
   rr=sorted([r for r in rows if r['family']==f and r['representation']==rep and r['metric']==metric],key=lambda r:B.index(r['budget_key']))
   vals=np.array([float(r['mean']) for r in rr]);lo=np.array([float(r['ci95_low']) for r in rr]);hi=np.array([float(r['ci95_high']) for r in rr])
   ax.errorbar(np.arange(4)+(k-1.5)*.055,vals,yerr=[vals-lo,hi-vals],fmt='o-',ms=3,capsize=2,color=C[k],lw=.8,label=label)
  ax.set_xticks(range(4),BL,rotation=20);ax.set_title('('+string.ascii_lowercase[i*3+j]+') '+title,fontsize=9);ax.grid(axis='y',alpha=.18)
  if j==0:ax.set_ylabel(fl)
fig.legend(*axs[0,0].get_legend_handles_labels(),loc='outside upper center',ncol=4,frameon=False)
save(fig,'figure_e3_secondary_metrics.pdf')
# Figure 6: paired device resource means and Student-t intervals.
rows=read('E2_selected_minus_random_pairs.csv');tops=['line_12','ring_12','heavy_hex_d3_19'];fig,axs=plt.subplots(1,2,figsize=(7.4,3.9),layout='constrained')
for ax,f,fl in zip(axs,F,FL):
 for k,(metric,label) in enumerate(zip(['two_qubit_gates','two_qubit_depth','routing_overhead'],['2q gates','2q depth','Routing'])):
  for j,top in enumerate(tops):
   vals=np.array([float(r[metric]) for r in rows if r['family']==f and r['topology_id']==top]);mean=vals.mean();err=t.ppf(.975,len(vals)-1)*vals.std(ddof=1)/np.sqrt(len(vals))
   ci(ax,j+(k-1)*.16,mean,mean-err,mean+err,fmt='o',color=C[k],ms=4,label=label if j==0 else None)
 ax.set_xticks(range(3),[n+'\n(n='+str(sum(r['family']==f and r['topology_id']==top for r in rows))+')' for n,top in zip(['Line-12','Ring-12','Heavy-hex-19'],tops)]);ax.set_ylabel('Selective minus matched random');ax.set_title(fl);ax.axhline(0,color='#777',ls='--',lw=.8);ax.grid(axis='y',alpha=.18)
fig.legend(*axs[0].get_legend_handles_labels(),loc='outside upper center',ncol=3,frameon=False);save(fig,'figure_additional_topologies.pdf')
# Figure 1: fixed eligible E5 endpoints, retaining latest continuous effects.
rows=[r for r in read('E5_instance_level.csv') if r['source_tier']=='compilation' and r['status']=='pass'];lim=max(abs(float(r['effect'])) for r in rows);norm=TwoSlopeNorm(vmin=-lim,vcenter=0,vmax=lim)
fig,axs=plt.subplots(2,3,figsize=(8.5,5.4),sharex=True,sharey=True,layout='constrained')
for i,(top,tl) in enumerate(zip(['all_to_all_reference','device_sparse_v1'],['All-to-all','Grid-12'])):
 for j,(m,ml) in enumerate(zip(['compiled_two_qubit_gates','compiled_two_qubit_depth','routing_overhead'],['Gates','Depth','Routing'])):
  ax=axs[i,j];rr=[r for r in rows if r['topology_id']==top and r['metric']==m]
  for f,marker in zip(F,['o','s']):
   pp=[r for r in rr if r['family']==f]
   art=ax.scatter([float(r['pair_reuse_score']) for r in pp],[float(r['canonical_cubic_sparsity']) for r in pp],c=[float(r['effect']) for r in pp],norm=norm,cmap='RdBu',marker=marker,s=30,edgecolors='#555',linewidths=.5)
  ax.set_title(f'({string.ascii_lowercase[i*3+j]}) {tl}: {ml}',fontsize=10);ax.text(.03,.95,f'n={len(rr)}',transform=ax.transAxes,va='top',fontsize=9);ax.grid(alpha=.18)
  if i==1:ax.set_xlabel('Pair-reuse score')
  if j==0:ax.set_ylabel('Cubic sparsity')
cb=fig.colorbar(art,ax=axs,orientation='horizontal',shrink=.7,aspect=35,pad=.03);cb.set_label('Relative saving versus matched random (positive favours selective)',fontsize=9)
fig.legend(handles=[Line2D([],[],marker=m,ls='',color='#555',label=l) for m,l in zip(['o','s'],FL)],loc='outside upper center',ncol=2,frameon=False);save(fig,'figure_e5_regime_map_2d.pdf')
print('Rebuilt Figures 1, 6, 7, 8, 9, 11 from frozen summaries.')
