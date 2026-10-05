from pathlib import Path
import json, statistics, random
ROOT=Path(__file__).resolve().parent
data=[json.loads(p.read_text()) for p in sorted((ROOT/'experiments/compiled_results/instances').glob('*.json'))]
families=[('max3sat','Max-3SAT'),('spin_glass','Cubic spin'),('pair_star_isolated','Constructed')]
names=['native','min_aux_full','max_reuse','hardware_distance','resource_full','best_strict_mixed','matched_random']
lines=[r'\subsection{Additional new-study resource controls}',r'\label{app:new-resource-controls}',
 r'Table~\ref{tab:new-resource-baselines} reports the same score for every retained comparator on grid-12. These are medians of 30 instance values per row, not independent compiler-run observations. The score is Eq.~\eqref{eq:new-compiled-score}; smaller is better. The distance heuristic is explicitly not a reproduction of a named external implementation. Unconstrained native preference does not determine feasibility under hard budgets.',
 r'\begin{table}[htbp]\centering\footnotesize',
 r'\caption{Median compiled resource scores on grid-12. MinA: minimum-auxiliary full; reuse: maximum-frequency pair full; distance: distance-aware full; resFull: resource-optimised full within its candidate budget; strict: best proper mixed; random: control matched on auxiliary and reduced-term counts, with penalty matching when possible.}',
 r'\label{tab:new-resource-baselines}',r'\begin{tabular}{llrrrrrrr}\toprule',
 r'Family & Synthesis & Native & MinA & Reuse & Distance & resFull & Strict & Random\\\midrule']
contrasts=[]
for family,label in families:
 for strategy in ['canonical','reuse']:
  rows=[next(r for r in p['results'] if r['topology']=='grid12' and r['strategy']==strategy)['baselines'] for p in data if p['instance']['family']==family]
  vals=[statistics.median(r[n]['J'] for r in rows) for n in names]
  lines.append(label+' & '+strategy+' & '+' & '.join(f'{x:.3f}' for x in vals)+r'\\')
  difference=[r['best_strict_mixed']['J']-r['resource_full']['J'] for r in rows]
  rng=random.Random(71711)
  boot=sorted(statistics.mean(rng.choices(difference,k=30)) for _ in range(10000))
  contrasts.append(dict(family=family,strategy=strategy,topology='grid12',contrast='strict minus resource-full',mean=statistics.mean(difference),low=boot[250],high=boot[9749],n=30))
lines.extend([r'\bottomrule\end{tabular}\end{table}',r'The grid-12 mean paired strict-minus-resource-full score differences, with descriptive 95\% percentile bootstrap intervals from 10,000 instance resamples, are:'])
for family,label in families:
 c=[r for r in contrasts if r['family']==family]
 lines.append(label+': '+ '; '.join(f"{r['strategy']} ${r['mean']:.3f}\\;[{r['low']:.3f},{r['high']:.3f}]$" for r in c)+'.')
lines.extend([r'These secondary intervals are unadjusted and concern finite-search incumbents. They do not certify the optimal full assignment or imply a solution-quality difference. Cross-topology rank comparisons use common candidate identities. Their Pareto-set overlaps additionally depend on the candidate libraries, which can differ through the distance-aware proposals; they are sampled-library stability measures rather than a pure causal isolation of connectivity.',
 r'\begin{figure}[htbp]\centering\includegraphics[width=\textwidth]{figures/joint_budget_certified_frequency.pdf}',
 r'\caption{Certified mixed-only incidence across the 30 constructed mechanism instances in the fixed $(D_{\max},M_{\max})=(96,4.4)$ slice. Each plotted cell counts independent instances, with the native and full endpoints excluded as specified in Section~\ref{sec:fresh-compiled}. Budget cells and compiler settings are not independent samples.}\label{fig:certified-population}\end{figure}'])
(ROOT/'manuscript_sections/resource_supplement.tex').write_text('\n\n'.join(lines),encoding='utf-8')
(ROOT/'experiments/compiled_results/supplementary_score_contrasts.json').write_text(json.dumps(contrasts,indent=2),encoding='utf-8')
