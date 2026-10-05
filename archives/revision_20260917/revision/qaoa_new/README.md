# Fresh QAOA evaluation

This directory contains an actually executed, locally frozen evaluation of 60 new independent instances: 30 weighted Max-3SAT and 30 cubic spin-glass, each with six original variables and six raw clauses/interactions. It is a small noiseless p=1 study, not evidence of scalable or hardware quantum advantage.

## What was changed

- `protocol.json` fixes hypotheses, seeds, budgets, objective, selection domains and reporting conventions. `freeze.json` was created before generating evaluation instances and hashes both protocol/runner and reused original pipeline sources. It records the actual package versions.
- Both proper-mixed and full-Q arms are chosen with the same resource score and up to 128 distinct candidate evaluations; domains smaller than the cap are exhausted. Full-Q is resource-optimised within its evaluated domain, not chosen only by auxiliary count. Proper mixed is explicitly conditional on reducing at least one and fewer than all cubics. On this small set the unrestricted resource winner among evaluated candidates is native on all 60 instances.
- Fibre guardrails have no role in this primary selection. This QAOA comparison uses the fixed reference compiler, separate from the topology-specific compiled study. No hardware-and-quality joint threshold is inferred from separate sets.
- Every representation/policy uses the same three parameter starts for an instance and exactly 360 objective evaluations, scored by original objective after marginalising auxiliaries. All statevectors are exact floating-point simulations, with no shot noise in the optimisation objective.
- COBYLA stops may occur before their 120-call restart quota. The frozen protocol completes the remaining quota with uniform parameter samples from a common seeded stream. The main equal-effort study therefore uses **COBYLA plus quota completion**, not 360 COBYLA iterations. Of 172,800 total equal-effort calls, 17,959 were such completion samples. Raw traces preserve every call and early-stop message.
- Warm p=0 states, rounding and 2,048 independent draws per instance from the same clipped relaxation provide classical controls. Pair and independence auxiliary warming use the same clipping interval. Warm p=0 original expectations are equal in construction across representations, checked to tolerance 1e-10. The equal-effort incumbent does not include a p=0 candidate, so positive evolution gain is not automatic.
- A full-domain 65x65 parameter grid plus four 240-call refinement quotas (5,185 calls per arm) and a second equal-effort Nelder–Mead run probe optimisation sensitivity. There were 4,681 quota-completion samples among 172,800 refinement calls, and none among the second optimiser's 64,800 calls. Grid evaluation contributes an additional 760,500 circuit expectations. These runs are sensitivity checks, not a global convergence proof.

## Main findings

Positive gains below mean lower original objective. Intervals are paired instance-level 95% percentile bootstrap intervals, 10,000 resamples.

| Family | Classical preparation gain | Native incremental evolution gain |
|---|---:|---:|
| Weighted Max-3SAT | 0.484 [0.279, 0.703] | 1.152 [0.959, 1.344] |
| Cubic spin glass | 0.000 [0.000, 0.000] | 2.133 [2.004, 2.238] |

Native incremental gain is positive on all 30 instances of each family under the prespecified equal-effort protocol. These gains demonstrate change after evolution in this simulator protocol, not computational advantage against strong classical optimisation.

Native has the lowest scanned/refined mean objective and wins 28/30 Max-3SAT and 30/30 spin-glass instances. The winning representation changes between equal effort and scan/refinement on 7/30 and 1/30 respectively; mean representation-rank Spearman correlations are 0.717 and 0.917. This reinforces the boundary between resource feasibility and QAOA quality.

Pair-moment auxiliary warming has no consistent advantage across both representations and families. The secondary Max-3SAT full-Q contrast is positive (0.119 [0.040, 0.202]), while proper-mixed and spin-glass intervals cross zero. It must not be elevated into a general contribution. The raw rounding control is sometimes better and sometimes worse than expectation-based controls; it has no comparable optimisation budget and is not a strong classical optimisation baseline.

## Files

- `instances/`: all 60 generated source instances.
- `results/`: all 480 representation/warming arm results, parameters, initial probabilities, full optimisation traces, consistency metrics, classical controls and lineage.
- `grids/`: all 180 65x65 objective surfaces.
- `analysis/summary.json`: audit and family-level summaries.
- `analysis/instance_arm_results.csv`: flat per-instance arm metrics.
- `analysis/paired_contrasts.csv`: paired means, confidence intervals and sign counts.
- `analysis/optimization_curves.csv`: per-family/representation mean incumbent versus objective calls for both optimisers.
- `analysis/warm_gain_decomposition.pdf`, `analysis/optimizer_curves.pdf`: publication-ready figures, visually inspected in PNG form.
- `analysis/manuscript_insert.tex`: prose and tables for integration into `main.tex`; not an independently edited Overleaf body file.

## Reproduce on Windows

Keep this directory at `revision/qaoa_new` alongside the original pipeline at `revision/code/source/urss_pipeline`. Use Python 3.12 with the versions in `requirements.txt`, or activate the virtual environment created from the archive-root `requirements-revision.txt`. Existing results are retained on rerun, allowing interruption recovery.

```powershell
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
python revision/qaoa_new/run.py test
python revision/qaoa_new/run.py verify
python revision/qaoa_new/report.py
```

To rerun simulations, use a copy of this deliverable, relocate its `instances`, `results` and `grids` directories, retain the original frozen source and manifest, and execute `python revision/qaoa_new/run.py run --workers 2`. The freeze manifest uses the Windows-relative paths from the actual run.

Validation includes exhaustive pointwise exactness of every selected representation on every instance; independent direct-vs-expanded original objective checks; a full Kronecker matrix comparison for the mixer; p=0 invariance; scalar/batched scan equivalence; periodicity; norm checks; identical objective-call counts; and warm-p0 marginal equality. There are 60 distinct seeds, instance IDs and objective polynomials, zero overlap with the 27 historical n=6 objectives in the original raw-data directory, and zero performance-based exclusions or generation rejections.

The old 14/20/18-instance sets remain exploratory/development evidence. This new locally frozen study is not externally preregistered. All secondary intervals are descriptive and unadjusted for multiplicity.
