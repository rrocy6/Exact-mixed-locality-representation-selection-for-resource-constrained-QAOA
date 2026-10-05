"""Postprocessing only: never generates instances or changes frozen evaluation."""
from pathlib import Path
import csv
import json
import hashlib
import sys
import numpy as np
from scipy.stats import spearmanr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from run import read, write, sha, verify_freeze, truth_values
from run import max3sat_to_pubo, spin_glass_to_pubo

def interval(values, seed=3619):
    values=np.asarray(values,dtype=float)
    rng=np.random.default_rng(seed)
    boot=values[rng.integers(0,len(values),size=(10000,len(values)))].mean(axis=1)
    lo,hi=np.quantile(boot,[.025,.975])
    return dict(n=len(values),mean=float(values.mean()),low=float(lo),high=float(hi),
                positive_count=int((values>1e-9).sum()),negative_count=int((values< -1e-9).sum()))

def csvout(path,rows):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def lookup(instance,rep,policy="pair"):
    return next(x for x in instance["rows"] if x["representation"]==rep and x["warming"]==policy)

def signature(instance):
    poly=(max3sat_to_pubo if instance["family"]=="max3sat" else spin_glass_to_pubo)(instance)
    return hashlib.sha256(json.dumps([[list(k),float(v)] for k,v in sorted(poly.items())]).encode()).hexdigest()

def main():
    verify_freeze()
    data=[read(p) for p in sorted((HERE/"results").glob("*.json"))]
    assert len(data)==60
    assert len({r["seed"] for r in data})==60
    assert len({r["instance_id"] for r in data})==60
    out=HERE/"analysis";out.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.spines.top":False,
        "axes.spines.right":False,"savefig.bbox":"tight","pdf.fonttype":42})
    families=["max3sat","spin_glass"]
    names={"max3sat":"Weighted Max-3SAT","spin_glass":"Cubic spin glass"}
    reps=["native","proper_mixed","full"]
    labels={"native":"Native","proper_mixed":"Proper mixed","full":"Full-Q"}
    colors={"native":"#2266aa","proper_mixed":"#cc8833","full":"#557755"}
    results={};flat=[];contrasts=[];curves=[]
    for family in families:
        group=[r for r in data if r["family"]==family]
        stat={}
        def calc(name,fn):
            values=[fn(r) for r in group]
            result=interval(values)
            stat[name]=result
            contrasts.append(dict(family=family,contrast=name,**result))
        calc("classical_preparation_gain",lambda r:r["cold_p0"]-lookup(r,"native")["p0"])
        calc("classical_preparation_gain_normalized",lambda r:(r["cold_p0"]-lookup(r,"native")["p0"])/(r["maximum"]-r["optimum"]))
        calc("warm_p0",lambda r:lookup(r,"native")["p0"])
        calc("classical_rounding",lambda r:r["classical_rounding"])
        calc("independent_sampling_mean",lambda r:r["independent_sampling_mean"])
        calc("cold_p0",lambda r:r["cold_p0"])
        for rep in reps:
            for policy in ["cold","pair"]+(["independence"] if rep!="native" else []):
                calc(rep+"_"+policy+"_equal_mean",lambda r:lookup(r,rep,policy)["equal_effort"]["objective"])
                for r in group:
                    row=lookup(r,rep,policy)
                    flat.append(dict(family=family,number=r["number"],instance_id=r["instance_id"],
                        representation=rep,warming=policy,p0=row["p0"],equal_effort=row["equal_effort"]["objective"],
                        scan_refined=row.get("scan_refined",{}).get("objective",""),
                        second_optimizer=row.get("second_optimizer",{}).get("objective",""),
                        calls=row["equal_effort"]["calls"],consistency_failure=row["equal_effort"]["auxiliary_inconsistency"],
                        optimum=r["optimum"],maximum=r["maximum"],
                        width=r["selections"][rep]["width"],resource_score=r["selections"][rep]["score"]))
            calc(rep+"_incremental_gain",lambda r:lookup(r,rep)["p0"]-lookup(r,rep)["equal_effort"]["objective"])
            calc(rep+"_incremental_gain_normalized",lambda r:(lookup(r,rep)["p0"]-lookup(r,rep)["equal_effort"]["objective"])/(r["maximum"]-r["optimum"]))
            calc(rep+"_scan_extra_gain",lambda r:lookup(r,rep)["equal_effort"]["objective"]-lookup(r,rep)["scan_refined"]["objective"])
            calc(rep+"_scan_extra_gain_normalized",lambda r:(lookup(r,rep)["equal_effort"]["objective"]-lookup(r,rep)["scan_refined"]["objective"])/(r["maximum"]-r["optimum"]))
            calc(rep+"_scan_mean",lambda r:lookup(r,rep)["scan_refined"]["objective"])
            calc(rep+"_second_mean",lambda r:lookup(r,rep)["second_optimizer"]["objective"])
            if rep!="native":
                calc(rep+"_pair_information_gain",lambda r:lookup(r,rep,"independence")["equal_effort"]["objective"]-lookup(r,rep,"pair")["equal_effort"]["objective"])
            for call in range(360):
                vals=[(lookup(r,rep)["equal_effort"]["trace"][call]["incumbent"]-r["optimum"])/(r["maximum"]-r["optimum"]) for r in group]
                vals2=[(lookup(r,rep)["second_optimizer"]["trace"][call]["incumbent"]-r["optimum"])/(r["maximum"]-r["optimum"]) for r in group]
                curves.append(dict(family=family,representation=rep,call=call+1,mean_normalized_gap=float(np.mean(vals)),
                    second_mean_normalized_gap=float(np.mean(vals2))))
        equal_winners={r:0 for r in reps};scan_winners={r:0 for r in reps};second_winners={r:0 for r in reps}
        changed=0;changed_second=0;correlations=[];correlations_second=[];rank_changes=0
        for r in group:
            equal=[lookup(r,rep)["equal_effort"]["objective"] for rep in reps]
            scanned=[lookup(r,rep)["scan_refined"]["objective"] for rep in reps]
            second=[lookup(r,rep)["second_optimizer"]["objective"] for rep in reps]
            ei,si,oi=int(np.argmin(equal)),int(np.argmin(scanned)),int(np.argmin(second))
            equal_winners[reps[ei]]+=1;scan_winners[reps[si]]+=1;second_winners[reps[oi]]+=1
            changed+=ei!=si;changed_second+=ei!=oi
            rank_changes+=not np.array_equal(np.argsort(equal),np.argsort(scanned))
            correlations.append(float(spearmanr(equal,scanned).statistic))
            correlations_second.append(float(spearmanr(equal,second).statistic))
        stat["rank_robustness"]=dict(equal_winners=equal_winners,scan_winners=scan_winners,second_winners=second_winners,
            scan_winner_changed=int(changed),second_winner_changed=int(changed_second),scan_complete_order_changed=int(rank_changes),
            mean_spearman_equal_scan=float(np.mean(correlations)),mean_spearman_equal_second=float(np.mean(correlations_second)))
        stat["unrestricted_resource_winners"]={rep:sum(r["selections"]["unrestricted_among_evaluated"]==rep for r in group) for rep in reps}
        stat["native_pair_equal_to_cold_p0_count"]=sum(abs(lookup(r,"native")["p0"]-r["cold_p0"])<1e-10 for r in group)
        stat["selection_calls_range"]={rep:[min(r["selections"][rep]["calls"] for r in group),max(r["selections"][rep]["calls"] for r in group)] for rep in reps}
        stat["width_range"]={rep:[min(r["selections"][rep]["width"] for r in group),max(r["selections"][rep]["width"] for r in group)] for rep in reps}
        results[family]=stat
    new_instances=[read(p) for p in sorted((HERE/"instances").glob("*.json"))]
    new_signatures={signature(x) for x in new_instances}
    historical=[]
    for p in (HERE.parent/"code"/"source"/"data"/"raw").glob("*/*.json"):
        old=read(p)
        if old.get("family") in families and old.get("problem",{}).get("n")==6:
            historical.append(signature(old))
    audit=dict(instance_count=60,unique_seed_count=60,unique_id_count=60,
        unique_objective_count=len(new_signatures),historical_n6_objective_count=len(historical),
        objective_overlap_with_historical_raw=len(new_signatures.intersection(historical)),
        generation_rejections=sum(len(r["rejected_generation_attempts"]) for r in data),
        uniform_completion_calls=sum(t.get("uniform_completion_calls",0) for r in data for row in r["rows"] for t in row["equal_effort"]["trace"]),
        uniform_completion_by_method={method:sum(t.get("uniform_completion_calls",0) for r in data for row in r["rows"] if method in row for t in row[method]["trace"]) for method in ["equal_effort","second_optimizer","scan_refined"]},
        total_calls_by_method={method:sum(row[method]["calls"] for r in data for row in r["rows"] if method in row) for method in ["equal_effort","second_optimizer","scan_refined"]},
        maximum_monte_carlo_error=float(max(abs(r["independent_sampling_mean"]-r["independent_sampling_expected_mean"]) for r in data)),
        freeze_sha256=sha(HERE/"freeze.json"))
    write(out/"summary.json",dict(audit=audit,families=results))
    csvout(out/"instance_arm_results.csv",flat)
    csvout(out/"paired_contrasts.csv",contrasts)
    csvout(out/"optimization_curves.csv",curves)
    fig,axes=plt.subplots(1,2,figsize=(9.3,3.35),sharex=True,sharey=True)
    for ax,fam in zip(axes,families):
        keys=["classical_preparation_gain_normalized"]+[rep+"_incremental_gain_normalized" for rep in reps]
        ylabel=["Classical preparation","Evolution: native","Evolution: mixed","Evolution: full-Q"]
        for i,key in enumerate(keys):
            s=results[fam][key];color="#777777" if i==0 else colors[reps[i-1]]
            ax.errorbar(s["mean"],3-i,xerr=[[s["mean"]-s["low"]],[s["high"]-s["mean"]]],fmt="o",color=color,capsize=3)
        ax.axvline(0,color="#999999",lw=.7)
        ax.set_yticks(range(4),ylabel[::-1]);ax.set_title(names[fam]+" (30 independent instances)")
        ax.set_xlabel("Gain / original objective range")
        ax.grid(axis="x",color="#eeeeee");ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out/"warm_gain_decomposition.pdf")
    fig.savefig(out/"warm_gain_decomposition.png",dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(9.3,6.0),sharex="col")
    for j,fam in enumerate(families):
        for rep in reps:
            rr=[r for r in curves if r["family"]==fam and r["representation"]==rep]
            axes[0,j].plot([r["call"] for r in rr],[r["mean_normalized_gap"] for r in rr],color=colors[rep],label=labels[rep])
            axes[1,j].plot([r["call"] for r in rr],[r["second_mean_normalized_gap"] for r in rr],color=colors[rep],label=labels[rep])
        axes[0,j].set_title(names[fam]);axes[1,j].set_xlabel("Objective evaluations (3 restarts combined)")
        for ax in axes[:,j]:
            ax.grid(color="#eeeeee");ax.set_axisbelow(True);ax.set_ylim(bottom=0)
    axes[0,0].set_ylabel("Mean normalized gap\nCOBYLA + quota completion")
    axes[1,0].set_ylabel("Mean normalized gap\nNelder–Mead")
    axes[0,1].legend(frameon=False,loc="lower right")
    fig.tight_layout();fig.savefig(out/"optimizer_curves.pdf");fig.savefig(out/"optimizer_curves.png",dpi=180);plt.close(fig)
    text=[]
    def clean(x):return 0.0 if abs(x)<.0005 else x
    def ci(s):return f"{clean(s['mean']):.3f} [{clean(s['low']):.3f}, {clean(s['high']):.3f}]"
    text.extend([r"\subsection{Fresh evaluation: preparation and incremental evolution}",
        r"\label{sec:fresh-qaoa}",
        r"To separate preparation from subsequent evolution, we froze the implementation, seeds, hypotheses and budgets locally before generating 30 new independent instances of each family. These are uniform, $n=6$ instances with six clauses or spin interactions, subject only to coverage and at least two nonzero cubic monomials. This scope is deliberately small and noiseless. The earlier 14-instance QAOA set and 20-/18-instance follow-up sets are exploratory; signal-enriched samples are mechanism studies. The new protocol is locally prospective, not an externally registered study.",
        r"We compare native, proper mixed ($0<|D|<|E|$), and fully reduced representations. Both reduction domains receive up to 128 distinct seeded candidate evaluations under the same reference-compiler score $J_{\rm res}=(a/4+G/160+D_2/120+M/8)/4$, with exhaustive evaluation if a domain is smaller. These proper-mixed arms are conditional representation comparisons: native has the lowest resource score among all evaluated candidates on all 60 instances. Penalties are the exact cubic threshold plus one. No fibre diagnostic affects selection. This all-to-all reference selection is separate from the topology-specific compiler study and does not establish a joint quality-and-hardware threshold.",
        r"All $p=1$ equal-effort arms use three identical parameter starts per instance and exactly $120$ objective evaluations per restart. COBYLA runs first; whenever it terminates before its quota, the remaining calls use a prespecified, commonly seeded stream of uniform parameter samples. Consequently this is a COBYLA-plus-uniform-completion protocol, not 120 COBYLA steps. The objective is the exact original $\mathbb E[f(x)]$, marginalising auxiliary variables; encoded energy is only a diagnostic. Starts are uniform on $[0,2\pi)\times[0,\pi)$, and the $p=0$ state is not inserted into the optimiser incumbent. Thus a positive incremental gain is not guaranteed by including a no-evolution candidate. Original probabilities come from one common pair/triple McCormick--RLT relaxation and are clipped to $[0.05,0.95]$. Auxiliary pair probabilities and products of the clipped original probabilities are each clipped to the same interval. The matched mixer and product preparation are identical across representation arms apart from their added auxiliaries.",
        r"The decomposition is $f_{\rm cold,0}-f_{\rm warm,1}=(f_{\rm cold,0}-f_{\rm warm,0})+(f_{\rm warm,0}-f_{\rm warm,1})$. All warm $p=0$ original expectations agree exactly across representations. Independent sampling from those clipped original marginals has that same expectation; we also report 2,048 actual draws per instance and deterministic rounding of the raw relaxation marginals (ties to zero). These controls isolate preparation without implying an advantage over a fully optimised classical algorithm.",
        r"\begin{table}[t]\centering\small",
        r"\caption{Fresh $n=6$ evaluation, 30 independent instances per family. Original-objective gains (lower objective is better) and paired 95\% percentile-bootstrap intervals, with 10,000 instance resamples. Evolution uses pair auxiliary warming and $3\times120$ calls under the equal-effort protocol. Only native incremental evolution is the prespecified QAOA contrast; other intervals are descriptive.}",
        r"\label{tab:fresh-warm-gain}",r"\begin{tabular}{llcc}\toprule",r"Family & Gain & Mean [95\% interval] & Positive / 30\\\midrule"])
    for fam in families:
        for label,key in [("Preparation","classical_preparation_gain"),("Native evolution","native_incremental_gain"),("Mixed evolution","proper_mixed_incremental_gain"),("Full-Q evolution","full_incremental_gain")]:
            s=results[fam][key];text.append(f"{names[fam]} & {label} & {ci(s)} & {s['positive_count']} \\\\")
    text.extend([r"\bottomrule\end{tabular}\end{table}",r"\begin{figure}[t]\centering\includegraphics[width=\linewidth]{figures/revision_warm_gain_decomposition.pdf}",
        r"\caption{Classical preparation and subsequent $p=1$ evolution on fresh instances. Each gain is divided by its instance's exact original-objective range before averaging. Bars are paired instance-bootstrap 95\% intervals; positive values reduce the original objective. The incremental bars use the same warm $p=0$ comparator.}\label{fig:fresh-warm-decomposition}\end{figure}"])
    for fam in families:
        st=results[fam];rank=st["rank_robustness"]
        text.append(f"For {names[fam]}, classical preparation changes the mean objective by {ci(st['classical_preparation_gain'])}, while native incremental evolution contributes {ci(st['native_incremental_gain'])}. The raw rounding, independent-sampling and prepared-state means are {clean(st['classical_rounding']['mean']):.3f}, {clean(st['independent_sampling_mean']['mean']):.3f} and {clean(st['warm_p0']['mean']):.3f}, respectively.")
        text.append(f"Pair-moment warming relative to independence gives mean original-objective gains of {ci(st['proper_mixed_pair_information_gain'])} for proper mixed and {ci(st['full_pair_information_gain'])} for full-Q. These are secondary finite-budget contrasts, not a general pair-information advantage.")
    text.extend([r"\paragraph{Optimisation-budget sensitivity.} A separate $65\times65$ scan covers the full $(\gamma,\beta)$ domain, followed by four Nelder--Mead refinements with quotas of 240 evaluations each (5,185 objective evaluations in total per warm pair arm). Early termination in refinement uses the same prespecified uniform quota-completion rule. Integer encoded energies make the stated $2\pi$ phase period valid. A second equal-effort Nelder--Mead run uses the same three starts and $3\times120$ evaluations. The scan and refinements are an approximate-convergence sensitivity check, not a global-optimality certificate; the scan's zero-phase row includes the $p=0$ expectation.",
        r"\begin{table}[t]\centering\small\caption{Original-objective means for warm pair arms. EE: equal-effort COBYLA with quota completion; NM: equal-effort Nelder--Mead; scan: $65^2$ grid plus local refinement. Lower is better.}\label{tab:fresh-optimizer}",
        r"\begin{tabular}{llrrr}\toprule Family & Representation & EE & NM & Scan\\\midrule"])
    for fam in families:
        for rep in reps:
            st=results[fam];text.append(f"{names[fam]} & {labels[rep]} & {st[rep+'_pair_equal_mean']['mean']:.3f} & {st[rep+'_second_mean']['mean']:.3f} & {st[rep+'_scan_mean']['mean']:.3f} \\\\")
    text.extend([r"\bottomrule\end{tabular}\end{table}"])
    text.append(f"The equal-effort COBYLA arms use {audit['uniform_completion_by_method']['equal_effort']:,} uniform-completion calls out of {audit['total_calls_by_method']['equal_effort']:,} objective evaluations. The second-optimiser and scan-refinement stages use {audit['uniform_completion_by_method']['second_optimizer']:,} and {audit['uniform_completion_by_method']['scan_refined']:,} completion calls, respectively. All evaluation traces, early-stop messages and exact call counts are retained.")
    for fam in families:
        st=results[fam]["rank_robustness"]
        text.append(f"For {names[fam]}, the winning representation changes on {st['scan_winner_changed']}/30 instances between equal-effort COBYLA and scanned refinement; the mean within-instance Spearman correlation across the three representations is {st['mean_spearman_equal_scan']:.3f}. Switching to equal-effort Nelder--Mead changes the winner on {st['second_winner_changed']}/30. These changes limit conclusions drawn from one optimiser budget.")
    text.extend([r"\begin{figure}[t]\centering\includegraphics[width=.92\linewidth]{figures/revision_optimizer_curves.pdf}",
        r"\caption{Incumbent original-objective gap, divided by each instance's exact objective range, versus cumulative evaluations over three restarts. Each line averages 30 independent instances. All curves use pair warming. They distinguish equal-effort behaviour from the separately reported larger scan-and-refinement budget.}\label{fig:fresh-optimizer-curves}\end{figure}",
        r"The new evidence addresses independent-instance count and explicitly separates preparation from evolution, but only for small noiseless $p=1$ problems under the stated protocol. It establishes neither scalable quantum advantage nor a solution-quality advantage of mixed representations. Fibre guardrails remain optional appendix diagnostics whose predictive algorithmic utility is unresolved."])
    (out/"manuscript_insert.tex").write_text("\n\n".join(text),encoding="utf-8")
    print(json.dumps(dict(audit=audit,families={f:{k:v for k,v in results[f].items() if k in ["classical_preparation_gain","native_incremental_gain","proper_mixed_incremental_gain","full_incremental_gain","proper_mixed_pair_information_gain","full_pair_information_gain","rank_robustness","unrestricted_resource_winners"]} for f in families}),indent=2))

if __name__=="__main__":main()
