"""Rebuild main.tex from the untouched uploaded baseline; never edit other TeX files."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
text = (ROOT / 'main.original.tex').read_text(encoding='utf-8')

def replace(old, new):
    global text
    if old not in text:
        raise ValueError('Missing anchor: ' + old[:100])
    text = text.replace(old, new, 1)

replace(r'\pdfoutput=1', r'\ifdefined\pdfoutput\pdfoutput=1\fi')
replace(r'\usepackage{graphicx}', r'\usepackage{graphicx}'+'\n'+r'\graphicspath{{A_IEEE_TQE/}{output/pdf/}}')
replace(r'\usepackage{booktabs}',r'\usepackage{booktabs}'+'\n'+r'\usepackage{array}')
replace(r'\title{Exact selective locality reduction for resource constrained quantum approximate optimisation}',
        r'\title{Exact representation selection and resource trade-offs for quantum optimisation}')
abstract = r'''Native higher-order encodings and complete quadratization are two endpoints of an exact representation family with competing resource requirements. We study the selection of executable mixed-locality representations, without assuming an improvement in QAOA solution quality. Direct semantic pair substitutions give a reduction capacity $K_Q$ under auxiliary, penalty and degree budgets. We prove an exact feasibility criterion, derive a closed form for unit-weight pair-star forests, and construct infinitely many instances for which every feasible representation is strictly mixed. An additional corollary establishes simultaneous gate, depth and width separation under an explicitly fixed phase-gadget synthesis. Aggregate-residual penalties and sequential composition provide the underlying pointwise-exactness guarantees. A new 90-instance compilation study finds certified mixed-only budget regions on equal-capacity sparse topologies, while showing that their prevalence and representation rankings depend on synthesis. A separate 60-instance noiseless QAOA study separates classical preparation from incremental evolution; native encoding retains the best mean objective under both equal-effort and scan-refined comparisons. Our contribution is a resource-constrained representation problem, provable phase boundaries within a declared grammar, and reproducible evidence of the limits of compiled and variational advantages.'''
text = re.sub(r'\\begin\{abstract\}.*?\\end\{abstract\}', lambda _: '\\begin{abstract}\n'+abstract+'\n\\end{abstract}', text, count=1, flags=re.S)

start = text.index('They nevertheless retain a common endpoint view:')
end = text.index('Making this intermediate space rigorous', start)
text = text[:start] + r'''The cited methods address different representation classes and objectives; none should be treated as unable to perform a partial substitution merely because its stated output is quadratic. Table~\ref{tab:related-work-scope} compares their published scope with the narrower question studied here.

\begin{table}[tbp]
\centering\footnotesize
\setlength{\tabcolsep}{3pt}
\renewcommand{\arraystretch}{1.18}
\caption{Scope of representative methods. ``Not studied'' concerns the cited formulation, not impossibility or a claim about every method in that category. The final column refers specifically to a theorem separating native, full and mixed feasibility under joint budgets. Exactness means the pointwise minimum identity, not equality of quantum dynamics.}
\label{tab:related-work-scope}
\begin{tabular}{@{}>{\raggedright\arraybackslash}p{.19\linewidth}>{\raggedright\arraybackslash}p{.10\linewidth}>{\raggedright\arraybackslash}p{.14\linewidth}>{\raggedright\arraybackslash}p{.16\linewidth}>{\raggedright\arraybackslash}p{.15\linewidth}>{\raggedright\arraybackslash}p{.12\linewidth}@{}}
\toprule
Method & Pointwise exact & Mixed output & Joint reduced-set / pair choice & Resource objective & Endpoint phase theorem\\
\midrule
Rosenberg substitution~\cite{Rosenberg1975,BorosGruber2014} & Yes & Partial use possible & Local construction & Not a compiler objective & Not studied\\
Compact quadratization~\cite{BorosCramaRodriguezHeck2020} & Yes & Quadratic output & Construction dependent & Auxiliary bounds & Not studied\\
Automatic full reduction~\cite{Schmidbauer2024,Schmidbauer2026} & Yes & Full-Q target & Substitution choice & Transformation and circuit costs & Not studied\\
Hardware-aware selection~\cite{Rovara2026} & Yes & Full-Q target & Auxiliary selection & Graph structure and mapped depth & Not studied\\
Approximate reduction~\cite{Dragoi2026} & Not in general & Ansatz dependent & Different ansatz space & Qubit and circuit cost & Not studied\\
This work & Yes & Explicit output & Both $\mathcal D$ and $\rho$ & Fixed-compiler joint budgets & Within direct pair grammar\\
\bottomrule
\end{tabular}
\end{table}

A digital processor can execute a mixed-locality Hamiltonian: a limited number of auxiliaries may replace expensive interactions while other terms remain native. Partial use of an exact substitution is a natural option, and the Rosenberg gadget itself is not our novelty claim. The question is when the freedom to select both reduced terms and their shared pairs is necessary for resource feasibility. We answer it within a declared direct-pair grammar, rather than asserting that mixed representations are universally superior or unavailable to other frameworks.

''' + text[end:]

start = text.index('Here we introduce \\emph{exact selective locality reduction}')
end = text.index('\\section{Results}', start)
text = text[:start] + r'''Our principal theoretical contribution is a resource-feasibility result. A capacity $K_Q$ characterises how many cubic terms can be reduced under simultaneous auxiliary, penalty and auxiliary-degree limits. For pair-star forests we compute this capacity in closed form and obtain explicit phase boundaries, including an infinite family in which both endpoints fail but a mixed representation is feasible. A separate corollary counts emitted gates and scheduled two-qubit depth under a fixed phase-gadget synthesis. The static theorem does not depend on a compiler; the compiled corollary does.

The exactness machinery supports this representation problem. We state the sharp aggregate-residual Rosenberg threshold and its compositional extension to arbitrary degree. These are guarantees for a specified construction, not universal minimum penalties over all reformulations. At higher degree the sharp residual norm may itself require difficult Boolean optimisation; a coefficient-sum bound remains an efficiently computable sufficient alternative. Practical selection and small exact certificates are distinguished from a claim of scalable global search.

Experimentally, the main comparison is between minimising the same resource score over full reductions and over the larger selective family. Compiled joint-budget maps assess executable representations; warm-state controls and larger optimisation budgets assess a separate question about solution quality. The original 14-instance QAOA comparison, 20-instance signal-enriched study and 18-instance noise study are development evidence throughout. In particular, the native mean values in Table~\ref{tab:e3-qaoa-summary} are an important boundary result. Neither pointwise exactness nor smaller circuits establishes a QAOA performance advantage, and a distinct advantage from auxiliary pair moments remains unresolved.

''' + text[end:]

replace('The experiments use cubic objectives', 'The main empirical studies use cubic objectives')
replace('The one-step inequalities telescope; the full gap bound and proof are in',
'''The threshold is sharp only within the chosen Rosenberg substitution.
For arbitrary degree, computing $\\|A_p\\|_\\infty$ can require exponential
Boolean optimisation. The bound $M_p\\geq\\sum_{S\\in\\mathcal S_p}|d_S|$
is sufficient and easy to compute, but need not be sharp.
The one-step inequalities telescope; the full gap bound and proof are in''')

# Fresh sections are embedded into main.tex so the teacher's TeX files remain intact.
theory = ROOT / 'theory' / 'static_compiled_section.tex'
if theory.exists():
    replace('We test Max-3SAT and cubic spin-glass objectives on 60 oracle instances,',
            theory.read_text(encoding='utf-8')+'\n\n'+r'\section{Resource and QAOA evaluation}'+'\n'+r'\label{sec:new-evaluation}'+'\n'+r'\subsection{Historical development studies}'+'\n'+
            'We tested Max-3SAT and cubic spin-glass objectives on 60 oracle instances,')
else:
    replace('We test Max-3SAT and cubic spin-glass objectives on 60 oracle instances,',
            r'\subsection{Historical development studies}'+'\n'+
            'We tested Max-3SAT and cubic spin-glass objectives on 60 oracle instances,')

for old, new in [
('\\subsection{Exactness and selector validation}', '\\subsection{Development evidence: exactness and selector validation}'),
('\\subsection{Resource savings and structural dependence}', '\\subsection{Development evidence: resource trade-offs}'),
('\\subsection{QAOA performance under matched budgets}', '\\subsection{Boundary result: native quality under the historical budget}'),
('\\subsection{Warm-start benefits and their limits}', '\\subsection{Exploratory warm-start mechanisms and their limits}'),
('On the 14 test-labelled instances, native achieves', 'On the 14 development instances (historically labelled test), native achieves'),
]:
    replace(old,new)

replace('These are finite-space validation results for the numerical feasible set specified below.',
'''These are finite-space validation results for the historical diagnostic-constrained
feasible set. They do not certify the new resource-only selector or the new target compilers.''')
replace('The repaired v2 Pareto beam satisfied the raw-moment guardrail on all 60',
        'The historical v2 Pareto beam satisfied its raw-moment guardrail on all 60')
replace('Thus substitution choices matter beyond auxiliary count.',
'''This association is conditional on auxiliary count; reduced-term count,
penalty scale and the selection procedure remain possible confounders.''')
replace('It tests whether choosing substitutions carries\ninformation beyond the number of added variables; the observed advantage\ncannot be attributed to fewer auxiliaries alone.',
'''It controls only register enlargement. Consequently, the historical advantage
does not isolate the causal value of partial reduction; the new controls match
both auxiliary count and the number of reduced cubic terms.''')

# Remove unsupported diagnostic from primary selector, retaining its historical appendix.
start=text.index('Numerical selection and certification use the exact all-to-all reference')
end=text.index('The feasible set and optimisation target are',start)
text=text[:start]+r'''The primary selector uses resource constraints only. Selection must call the compiler for the target topology being evaluated; historical all-to-all certificates are kept as validation of that historical model. New searches are finite-budget heuristics unless an exhaustive certificate is explicitly stated.

The fibre quantity $E_{\mathrm{fib}}=\mathbb E[F_\sigma(X,Y)-f(X)]$ is retained solely as an optional heuristic diagnostic in Appendix~\ref{app:fibre-risk}. Raw pseudo-moments and the clipped probabilities actually used for preparation define different product laws. Neither diagnostic has established predictive value for final quality or consistency after controlling for width, gates and depth. Its algorithmic utility remains unresolved, and it is excluded from primary selection.
\begin{equation}
E_{\mathrm{fib}}(\sigma;\eta,\xi)=\mathbb E[F_\sigma(X,Y)-f(X)]\geq0,
\qquad \widehat E_{\mathrm{fib}}=E_{\mathrm{fib}}/s_{\mathrm{fib}}.
\label{eq:fibre-excess-short}
\end{equation}
Here the original and auxiliary bits are independently Bernoulli with parameters $(\eta,\xi)$ and $s_{\mathrm{fib}}>0$ is design independent. This definition does not assert a joint distribution for raw pseudo-moments.

''' + text[end:]
replace(r'M_{\max,\sigma}\leq B_M,\ \widehat E_{\mathrm{fib}}(\sigma)\leq\tau_{\mathrm{fib}}',r'M_{\max,\sigma}\leq B_M')
replace('The minimum is attained whenever $\\mathcal F_{\\mathrm{sel}}$ is nonempty.',r'''The minimum is attained whenever $\mathcal F_{\mathrm{sel}}$ is nonempty.
To isolate the freedom to retain terms, compare
\begin{equation}
\min_{\rho:(E,\rho)\in\mathcal F_{\mathrm{sel}}}J_{\mathrm{res}}(E,\rho)
\quad\hbox{with}\quad
\min_{\mathcal D,\rho:(\mathcal D,\rho)\in\mathcal F_{\mathrm{sel}}}J_{\mathrm{res}}(\mathcal D,\rho).
\label{eq:fair-full-comparison}
\end{equation}
The full family is a subset of the selective family, so exact optimisation cannot worsen the latter's best score. Under finite search budgets that ordering is not guaranteed: report incumbent costs and actual compiler calls, not an unearned optimum. Minimum-auxiliary full reduction instead isolates the effect of changing the resource objective. Maximum reuse tests a simple structural rule; a hardware-aware rule tests the value of explicit device information. Random controls matched on both $a_\sigma$ and $|\mathcal D|$ test choices within that structural stratum. They still do not hold penalty or pair-reuse distribution fixed.''')
replace('Appendix~\\ref{app:selection-implementation}.}',
        'Appendix~\\ref{app:selection-implementation}. The historical optional fibre constraint is not part of the primary selector.}')
replace('Algorithm~\\ref{alg:selector}, admissible bounds, numerical requirements and',
'''The historical Algorithm~\\ref{alg:selector} includes an optional fibre check;
it is disabled for the primary resource-only problem. Its admissible bounds, numerical requirements and''')

replace('The evaluated tiers contain 60 oracle instances, 180 compilation instances',
        'The historical development tiers contain 60 oracle instances, 180 compilation instances')
replace('Each raw instance has native, fully quadratized, selective and matched-random',
        'In those historical tiers, each raw instance has native, fully quadratized, selective and matched-random')
replace('All representations use common synthesis settings and five transpiler seeds',
        'The historical representations use common synthesis settings and five transpiler seeds')
replace('Representations are optimised independently using COBYLA',
        'Historical QAOA runs used COBYLA')
replace('The raw instance is the statistical unit. Resource aggregation first takes',
        'The raw instance is the statistical unit. In the historical studies, resource aggregation first takes')
replace('The threshold behaviour is summarised in Section~\\ref{sec:results-exactness}.\n\\Cref{tab:e1-exactness-summary} gives the representation-level counts:',
        'Section~\\ref{sec:results-exactness} summarises the threshold behaviour.\nTable~\\ref{tab:e1-exactness-summary} reports the counts:')

replace('The 60-instance oracle study validates completed searches under the fixed',
        'The historical 60-instance oracle study validates completed searches under the fixed')
replace('The resource results support this distinction. Max-3SAT showed the clearest',
r'''The new compilation study strengthens an existence claim: measured mixed circuits can satisfy joint budgets while exhaustive logical enumeration excludes the entire full endpoint and native violates compiled cost limits. It also narrows its practical scope. An unrestricted weighted score chose native in every random-instance setting, and a stronger gadget ordering removed the observed spin-glass mixed-only regions. High rank correlations coexisted with changing Pareto sets and full assignments. Thus hard budgets, target-specific selection and the declared synthesis are substantive parts of the result, not incidental implementation details.

The new QAOA study separates two different sources of improvement. Native incremental evolution is positive on all 30 instances of each family under the frozen equal-effort protocol, while preparation itself gives measurable average benefit only for Max-3SAT. Yet native also has the best mean original objective under the second optimiser and the larger scan/refinement budget. Some individual winners change as optimisation effort increases. These small, noiseless findings support a boundary between executable representation and variational quality; they neither establish a mixed quality advantage nor a scalable quantum advantage.

The historical resource results support this distinction. Max-3SAT showed the clearest''')
replace('Similarly, the relaxation-derived selection diagnostic is a\nguardrail, not a guarantee of the prepared state\'s subsequent dynamics.',
'''The relaxation-derived fibre diagnostic is now optional and excluded from
primary selection. Compliance with its threshold does not establish
predictive or algorithmic utility.''')
replace('The numerical scope remains limited: the general QAOA comparison uses',
        'The historical numerical scope is limited: that QAOA comparison uses')
replace('Its representative simulator\nparameters do not establish robustness on a calibrated device.',
        'Its representative simulator\nparameters do not establish robustness on a calibrated device.')
replace('Full quadratization uses a minimum-cardinality pair cover of all',
        'The historical full-quadratization baseline uses a minimum-cardinality pair cover of all')
replace('This appendix specifies the quantities and routines used in Section~\\ref{sec:selection}.',
'''This appendix preserves the historical reference compiler and search routines
underlying the development evidence. The new primary resource-only formulation
is in Section~\\ref{sec:selection}; historical fibre checks below are optional,
and new target-specific compiler settings are reported with their study.''')
replace('Incorporating such transformations would define a different compilation\noracle, for which the designs and resource bounds would need re-evaluation.',
'''Such transformations define a different compilation oracle. The new compiler
study evaluates two optimised gadget strategies directly on each target;
the analytical reference counts remain statements about the synthesis above.''')

# Agent-produced sections are integrated as literal text, never as extra body TeX files.
for name in ['resource_results.tex', 'qaoa_results.tex']:
    p=ROOT/'manuscript_sections'/name
    if p.exists():
        replace('\\subsection{Historical development studies}',p.read_text(encoding='utf-8')+'\n\\subsection{Historical development studies}')

scaling = ROOT/'theory'/'higher_degree_scaling_section.tex'
if scaling.exists():
    replace('\\section{Additional Experimental Protocol Details}', scaling.read_text(encoding='utf-8')+'\n\\section{Additional Experimental Protocol Details}')
resource_supplement=ROOT/'manuscript_sections/resource_supplement.tex'
if resource_supplement.exists():
    replace('\\section{Additional Experimental Protocol Details}', resource_supplement.read_text(encoding='utf-8')+'\n\\section{Additional Experimental Protocol Details}')

replace('The framework therefore supplies a controlled way to compare exact',
r'''The new phase theorem identifies a stronger utility than occupying an intermediate point: within its declared grammar and budgets, every feasible representation can be mixed. This does not exclude nonsemantic auxiliaries or other quadratization grammars. The compiled corollary depends on its fixed synthesis, and the compiler study tests rather than assumes robustness to ordering and connectivity. Joint-budget feasibility without a solution-quality constraint means executable exact representation, not a demonstrated useful approximation ratio or quantum advantage. No quality-threshold feasibility claim is made without sufficient new quality data.

The framework therefore supplies a controlled way to compare exact''')

replace('The processed data and source manifests supporting the findings of this study',
'''The new evaluation data, frozen protocols, execution records and analysis scripts
are supplied in the accompanying revision code-and-evidence archive. They have
not been represented as uploaded to the public repository. The historical
processed data and source manifests''')
replace('The code used to generate and analyse the reported results, together with the',
'''The new resource and QAOA evaluation code and its reproduction instructions
are included with this revision. Historical code, together with the''')
replace('All authors reviewed and approved the manuscript.',
        'All authors contributed to the manuscript; this revision remains subject to their review and approval.')

# Typesetting and terminology edits to integrated sections only.
replace(r'''The frozen grid is $Q_{\max}\in\{6,\ldots,12\}$,
$G_{\max}\in\{0,4,\ldots,240\}$,
$D_{\max}\in\{24,48,72,96,120,160,240\}$ and
$M_{\max}\in\{0,1.1,2.2,3.3,4.4,6.6,8.8\}$.''',r'''The frozen grid is
\[
\begin{aligned}
Q_{\max}&\in\{6,\ldots,12\}, & G_{\max}&\in\{0,4,\ldots,240\},\\
D_{\max}&\in\{24,48,72,96,120,160,240\},\\
M_{\max}&\in\{0,1.1,2.2,3.3,4.4,6.6,8.8\}.
\end{aligned}
\]''')
replace('constructed family. Corresponding median Pareto-set Jaccard overlaps\nin $(Q,G,D,M)$ are',
        'constructed family.\n\nMedian Pareto-set overlaps in $(Q,G,D,M)$, measured by Jaccard similarity, are')
replace('of 31,577 distinct circuit compilations, with 32,760 scheduled candidate',
        'of 31,577 compiler calls, with 32,760 scheduled candidate')
replace(r'budgets $(Q_{\max},G_{\max},D_{\max},M_{\max})=(28,512,512,128)$.',
        r'budgets $Q_{\max}=28$, $G_{\max}=512$, $D_{\max}=512$ and $M_{\max}=128$.')
text=text.replace(r'$n=30$ &',r'$N=30$ &')

(ROOT/'overleaf/main.tex').write_text(text,encoding='utf-8')
print('Rebuilt main.tex:', len(text.splitlines()), 'lines')
