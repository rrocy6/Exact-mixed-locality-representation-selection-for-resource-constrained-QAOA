"""Auditable postprocessing of the frozen compiled study; no experimental edits."""
import itertools,json,math,hashlib
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
from scipy.stats import spearmanr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap,BoundaryNorm
from matplotlib.patches import Patch
from compiled_study import CONFIG,OUT,dump,sha

LABELS=["Both endpoints","Native endpoint only","Full endpoint only","Strict mixed only","None found"]
COLORS=["#476c9b","#e0ad42","#b37493","#6c8b57","#e5e5e5"]
Q=np.array(CONFIG["budgets"]["Q"]);G=np.array(CONFIG["budgets"]["G"])
D=np.array(CONFIG["budgets"]["D"]);M=np.array(CONFIG["budgets"]["M"])
SHAPE=(len(Q),len(G),len(D),len(M))

def feasible(r):
    return ((Q[:,None,None,None]>=r["Q"])&(G[None,:,None,None]>=r["G"])&
            (D[None,None,:,None]>=r["D"])&(M[None,None,None,:]+1e-9>=r["M"]))

def classify(payload,result):
    f=np.zeros(SHAPE,dtype=bool);s=f.copy(); native=feasible(result["baselines"]["native"])
    for k in result["full_keys"]: f|=feasible(result["candidates"][k])
    for k in result["mixed_keys"]:
        r=result["candidates"][k]
        if 0<r["reduced"]<5:s|=feasible(r)
    classes=np.full(SHAPE,4,dtype=np.uint8)
    classes[s]=3;classes[f]=2;classes[native]=1;classes[f&native]=0
    logicalfull=np.zeros((len(Q),len(M)),dtype=bool)
    for r in payload["full_logical_enumeration"]:
        logicalfull|=(Q[:,None]>=r["Q"])&(M[None,:]+1e-9>=r["M"])
    # Native must fail a compiled G or D constraint, not merely physical width.
    nr=result["baselines"]["native"]
    native_cost_fail=(G[None,:,None,None]<nr["G"])|(D[None,None,:,None]<nr["D"])
    native_width_ok=Q[:,None,None,None]>=nr["Q"]
    certified=(classes==3)&~logicalfull[:,None,None,:]&native_cost_fail&native_width_ok
    return classes,certified

def frontier(result):
    keys=sorted(set(result["full_keys"]+result["mixed_keys"]))
    rows=np.array([[result["candidates"][k][x] for x in ["Q","G","D","M"]] for k in keys])
    return {keys[j] for j,row in enumerate(rows) if not np.any(np.all(rows<=row+1e-10,axis=1)&np.any(rows<row-1e-10,axis=1))}

def compare(left,right):
    keys=sorted(set(left["full_keys"]+left["mixed_keys"])&set(right["full_keys"]+right["mixed_keys"]))
    rho=float(spearmanr([left["candidates"][k]["J"] for k in keys],[right["candidates"][k]["J"] for k in keys]).statistic)
    a=frontier(left);b=frontier(right)
    return {"rho":rho,"frontier_jaccard":len(a&b)/len(a|b),"common_designs":len(keys),
       "mixed_selection_changed":left["baselines"]["resource_mixed"]["actions"]!=right["baselines"]["resource_mixed"]["actions"],
       "full_selection_changed":left["baselines"]["resource_full"]["actions"]!=right["baselines"]["resource_full"]["actions"]}

def main():
    frozen=json.loads((OUT/"freeze.json").read_text())
    if frozen["source_sha256"]!=sha(Path(__file__).with_name("compiled_study.py")):
        assert frozen["source_sha256"]==sha(Path(__file__).with_name("compiled_study_frozen_v1.py"))
        assert json.loads((OUT/"amendment_01.json").read_text())["amended_source_sha256"]==sha(Path(__file__).with_name("compiled_study.py"))
    expected=json.loads((OUT/"instances_frozen.json").read_text())
    paths=sorted((OUT/"instances").glob("*.json"));assert len(paths)==len(expected)==90
    data=[json.loads(p.read_text()) for p in paths]
    assert {p["instance"]["id"] for p in data}=={p["id"] for p in expected}
    aggregate=defaultdict(lambda:{"instances":0,"cells":[0]*5,"mixed_only_instances":0,"certified_instances":0,
       "certified_cells":0,"mix_full_deltas":[],"strict_full_deltas":[],"matched_deltas":[],"penalty_matches":0,
       "mixed_endpoint_selected":0,"match_degenerate":0})
    phase_counts={};cert_counts={};perstudy=[];stability=[];witnesses=[];firstmap={}
    checks={"scheduled_candidates_equal":True,"random_matches_aux_and_reduced":True,"minimum_aux_certified":True}
    for payload in data:
        iid=payload["instance"]["id"];family=payload["instance"]["family"]
        exactmin=min(r["Q"] for r in payload["full_logical_enumeration"])
        for result in payload["results"]:
            topo=result["topology"];strategy=result["strategy"];group=(family,topo,strategy)
            assert len(result["full_keys"])==len(result["mixed_keys"])==result["scheduled_evaluations_per_space"]
            b=result["baselines"]
            assert b["matched_random"]["aux"]==b["best_strict_mixed"]["aux"]
            assert b["matched_random"]["reduced"]==b["best_strict_mixed"]["reduced"]
            assert b["min_aux_full"]["logical_Q"]==exactmin
            classes,cert=classify(payload,result)
            if group not in phase_counts: phase_counts[group]=np.zeros((*SHAPE,5),dtype=np.uint8);cert_counts[group]=np.zeros(SHAPE,dtype=np.uint8)
            for i in range(5):phase_counts[group][...,i]+=(classes==i)
            cert_counts[group]+=cert
            if iid=="pair_star_isolated_000":firstmap[(topo,strategy)]=classes
            counts=np.bincount(classes.ravel(),minlength=5)
            row={"id":iid,"family":family,"topology":topo,"strategy":strategy,
                 "class_cells":list(map(int,counts)),"certified_cells":int(cert.sum())}
            perstudy.append(row);a=aggregate[group];a["instances"]+=1
            a["cells"]=[int(x+y) for x,y in zip(a["cells"],counts)]
            a["mixed_only_instances"]+=bool(counts[3]);a["certified_instances"]+=bool(cert.any());a["certified_cells"]+=int(cert.sum())
            a["mix_full_deltas"].append(b["resource_mixed"]["J"]-b["resource_full"]["J"])
            a["strict_full_deltas"].append(b["best_strict_mixed"]["J"]-b["resource_full"]["J"])
            a["matched_deltas"].append(b["best_strict_mixed"]["J"]-b["matched_random"]["J"])
            a["penalty_matches"]+=result["matched_random_penalty_exact"]
            a["mixed_endpoint_selected"]+=b["resource_mixed"]["reduced"] in [0,5]
            a["match_degenerate"]+=result["matched_random_degenerate"]
            if cert.any():
                # The first certified fixed-grid cell is an illustration only.
                qi,gi,di,mi=map(int,np.argwhere(cert)[0]);budget={"Q":int(Q[qi]),"G":int(G[gi]),"D":int(D[di]),"M":float(M[mi])}
                feasible_mixed=[]
                for k in result["mixed_keys"]:
                    r=result["candidates"][k]
                    if 0<r["reduced"]<5 and all(r[x]<=v+1e-9 for x,v in budget.items()): feasible_mixed.append(r)
                assert feasible_mixed
                witness=min(feasible_mixed,key=lambda r:r["J"])
                witnesses.append({"id":iid,"topology":topo,"strategy":strategy,"budget":budget,
                    "native":b["native"],"mixed":witness,"resource_full":b["resource_full"],
                    "min_full_logical_width":exactmin,"full_exclusion":"exhaustive logical width/penalty enumeration",
                    "illustration_selection":"first certified frozen-grid cell, not a separately tested hypothesis"})
        lookup={(r["topology"],r["strategy"]):r for r in payload["results"]}
        for topo in CONFIG["topologies"]:
            left=lookup[(topo,"canonical")];right=lookup[(topo,"reuse")]
            stability.append({"id":iid,"family":family,"comparison":"synthesis","target":topo,**compare(left,right)})
        for strategy in CONFIG["strategies"]:
            for t1,t2 in itertools.combinations(CONFIG["topologies"],2):
                stability.append({"id":iid,"family":family,"comparison":"topology","target":t1+":"+t2+":"+strategy,**compare(lookup[(t1,strategy)],lookup[(t2,strategy)])})
    summaries=[]
    for group,a in aggregate.items():
        for field in ["mix_full_deltas","strict_full_deltas","matched_deltas"]:
            vals=a.pop(field);a[field]={"mean":float(np.mean(vals)),"median":float(np.median(vals)),
              "wins":int(sum(v<-1e-10 for v in vals)),"ties":int(sum(abs(v)<=1e-10 for v in vals)),"losses":int(sum(v>1e-10 for v in vals))}
        summaries.append(dict(zip(["family","topology","strategy"],group),**a))
    stablegroups=defaultdict(list)
    for r in stability: stablegroups[(r["family"],r["comparison"],r["target"])].append(r)
    stable_summary=[]
    for group,rows in stablegroups.items():
        stable_summary.append(dict(zip(["family","comparison","target"],group),instances=len(rows),
            median_rho=float(np.median([r["rho"] for r in rows])),minimum_rho=min(r["rho"] for r in rows),
            median_frontier_jaccard=float(np.median([r["frontier_jaccard"] for r in rows])),
            mixed_selection_changes=sum(r["mixed_selection_changed"] for r in rows),
            full_selection_changes=sum(r["full_selection_changed"] for r in rows)))
    summary={"freeze_sha256":sha(OUT/"freeze.json"),"instances":len(data),"compiled_circuits":sum(x["compiler_calls"] for x in data),
       "grid_cells_per_instance_target_strategy":int(np.prod(SHAPE)),
       "search_candidate_evaluations":sum(2*r["scheduled_evaluations_per_space"] for p in data for r in p["results"]),
       "summary":summaries,"stability_summary":stable_summary,"validation":checks,
       "classification_scope":"finite candidate library; certified subset additionally excludes all full representations logically",
       "postprocessing_sha256":sha(__file__)}
    dump(OUT/"summary.json",summary);dump(OUT/"per_instance_phase_counts.json",perstudy)
    dump(OUT/"stability.json",stability);dump(OUT/"certified_witnesses.json",witnesses)
    np.savez_compressed(OUT/"phase_counts.npz",**{"__".join(k):v for k,v in phase_counts.items()})
    np.savez_compressed(OUT/"certified_phase_counts.npz",**{"__".join(k):v for k,v in cert_counts.items()})
    plot(firstmap,cert_counts,summary)
    print(json.dumps(summary,indent=2))

def plot(firstmap,certcounts,summary):
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.spines.top":False,"axes.spines.right":False,"pdf.fonttype":42})
    fig,axs=plt.subplots(2,3,figsize=(11.5,6.4),sharex=True,sharey=True)
    di=list(D).index(96);mi=list(M).index(4.4)
    for row,strategy in enumerate(CONFIG["strategies"]):
        for col,topo in enumerate(CONFIG["topologies"]):
            ax=axs[row,col];z=firstmap[(topo,strategy)][:,:,di,mi]
            ax.pcolormesh(np.arange(-2,243,4),np.arange(5.5,13.5),z,cmap=ListedColormap(COLORS),norm=BoundaryNorm(np.arange(-.5,5),5),rasterized=True)
            # Numeric phase labels make category identity recoverable without colour.
            for category in range(5):
                cells=np.argwhere(z==category)
                if len(cells):
                    centroid=cells.mean(axis=0)
                    chosen=cells[np.argmin(np.sum((cells-centroid)**2,axis=1))]
                    ax.text(G[chosen[1]],Q[chosen[0]],str(category+1),ha="center",va="center",fontsize=8,
                        bbox={"boxstyle":"circle,pad=0.12","facecolor":"white","edgecolor":"#333333","linewidth":.5,"alpha":.95})
            ax.set_title(f"{topo.replace('12','-12')} / {strategy}");ax.set_yticks(Q);ax.set_xlim(0,240)
            if row==1:ax.set_xlabel("CX gate budget Gmax")
            if col==0:ax.set_ylabel("Physical width budget Qmax")
    fig.legend(handles=[Patch(facecolor=c,label=f"{i+1}. {l}") for i,(c,l) in enumerate(zip(COLORS,LABELS))],loc="lower center",ncol=3,frameon=False,bbox_to_anchor=(.5,.005))
    fig.suptitle("Joint-budget feasibility: first indexed pair-star + isolated instance",fontsize=13)
    fig.text(.5,.915,"Fixed slice: CX depth <= 96, penalty <= 4.4. Library feasibility; endpoint-only labels may include mixed designs.",ha="center",fontsize=9)
    fig.subplots_adjust(top=.83,bottom=.19,hspace=.3,wspace=.18)
    fig.savefig(OUT/"joint_budget_phase_map.pdf",bbox_inches="tight");fig.savefig(OUT/"joint_budget_phase_map.png",dpi=180,bbox_inches="tight");plt.close(fig)
    fig,axs=plt.subplots(2,3,figsize=(11.5,6.2),sharex=True,sharey=True)
    for row,strategy in enumerate(CONFIG["strategies"]):
        for col,topo in enumerate(CONFIG["topologies"]):
            ax=axs[row,col];z=certcounts[("pair_star_isolated",topo,strategy)][:,:,di,mi]
            im=ax.pcolormesh(np.arange(-2,243,4),np.arange(5.5,13.5),100*z.astype(float)/30,cmap="Blues",vmin=0,vmax=100,rasterized=True)
            ax.set_title(f"{topo.replace('12','-12')} / {strategy}");ax.set_yticks(Q);ax.set_xlim(0,240)
            if row==1:ax.set_xlabel("CX gate budget Gmax")
            if col==0:ax.set_ylabel("Physical width budget Qmax")
    fig.suptitle("Certified strict-mixed-only feasibility across 30 constructed instances",fontsize=13)
    fig.text(.5,.918,"Fixed slice: CX depth <= 96, penalty <= 4.4; full endpoint excluded by exhaustive logical enumeration.",ha="center",fontsize=9)
    fig.subplots_adjust(top=.83,bottom=.12,hspace=.3,wspace=.18,right=.89)
    cax=fig.add_axes([.915,.18,.018,.56]);fig.colorbar(im,cax=cax,label="Instances (%)")
    fig.savefig(OUT/"joint_budget_certified_frequency.pdf",bbox_inches="tight");fig.savefig(OUT/"joint_budget_certified_frequency.png",dpi=180,bbox_inches="tight");plt.close(fig)

if __name__=="__main__":main()
