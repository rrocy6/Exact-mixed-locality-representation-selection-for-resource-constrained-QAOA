# URSS multi-seed compilation robustness experiment

Run ID: `multiseed_20260918T163717Z`  
Status: formal compilation, classification, and audit complete  
Controlled seed set: `[1729, 2718, 31415, 57721, 65537]`; seed `1729` is the comparison seed.  
Environment: Qiskit `2.5.2` frozen input, explicit `SabreSwap(trials=8)`, identity placement, line-12/ring-12/grid-12, canonical/reuse synthesis.  
The historical archive used Qiskit 2.5.2 with implicit routing trials; `baseline_comparison.csv` therefore treats this run as a controlled re-baseline rather than claiming that only the seed changed.

## Scope and completion

- Complete sample: 30 Max-3SAT and 30 constructed (`pair_star_isolated`) instances.
- Restricted sample: the first 10 of each family under the declared selection hash, nested in the complete sample.
- Candidate rows: 20292; formal task rows: see `task_manifest.csv` (the complete task count is audited in `AUDIT.json`).
- Candidate categories are full `11330`, strict mixed `8602`, and native `360`; the frozen library contains no degenerate selective rows, and the non-mixed treatment is covered by the classification tests.
- Every result is classified against a complete `(Q,G,D,M)` budget tuple. Missing resource values remain `UNKNOWN`.
- `classification_arrays.npz` is the complete cell-level archive; `budget_classification.csv` is represented by the seed summary and robust-region tables because a fully expanded 37-million-row CSV would obscure rather than improve auditability.

## Results

Across instance/topology/synthesis layers, seed-1729 baseline TRUE cells total `149439`. The five-seed common TRUE cells total `79069`; baseline retention is `0.5291` when the baseline denominator is nonzero. The per-layer result, UNKNOWN coverage, and classification flips are in `seed_summary.csv`, `robust_regions.csv`, and `classification_flips.csv`.

Seed TRUE-cell totals: 1729=149439, 2718=156824, 31415=155289, 57721=165626, 65537=155638.  
Seed UNKNOWN-cell totals: 1729=0, 2718=0, 31415=0, 57721=0, 65537=0.

Pareto stability is reported in `pareto_stability.csv`; pooled five-seed feasibility is reported separately in `pooled_seed_summary.csv` and uses a union of complete actual circuit vectors, never componentwise minima. Selector re-selection under the existing resource score is in `selector_stability.csv`.

## Engineering audit

`RUN_STATE.json` records execution completeness; `compilation_rows.csv` records every candidate/instance/topology/synthesis/seed task and its terminal status. Each raw batch is atomically written under `raw/`; compact QPY digests and pass-manager provenance are under `circuit_digests/`. `baseline_comparison.csv` records the controlled seed-1729 comparison to the historical archive.
The `implementation_hash` in `experiment_config.json` is the frozen compile snapshot used for all formal rows; the later source edit only corrected final audit-manifest ordering and did not change compilation or classification logic.

P1 also passed 16 exact-representation checks, 32 logical-circuit unitary checks, and 12 routed-statevector checks; the largest phase error was `7.11e-16` (`P1_SEMANTIC_CHECKS.json`). The repository's paper source was updated at `paper/main.tex` with the actual seed protocol, stratified retention values, and scope limitation. A local LaTeX build was not run because no `pdflatex`, `xelatex`, `lualatex`, `latexmk`, or `tectonic` executable is installed in the current environment.

The new multi-seed classification tests passed (`6/6`), and the existing mixer-null-control tests passed (`16/16`); their logs are in `logs/test_multiseed_experiment.txt` and `logs/test_mixer_null_control.txt`. The full repository suite ran 172 tests but ended with 31 environment errors. The stack traces are dominated by the current Windows temporary-directory access policy; this environment also lacks optional matplotlib/PDF support used by some repository checks. The UTF-8 log is `logs/test_pipeline_suite_utf8.txt`. These errors did not affect the completed formal compilation or its audit.

## Scientific limits

These are five fixed descriptive compilation seeds, a finite frozen candidate library, three fixed 12-qubit topologies, and two synthesis strategies. They do not establish compiler-seed independence for all seeds or global infeasibility outside the tested library. UNKNOWN cells and compile failures remain visible in the audit.

## Reproduction

```powershell
& .\revisions\URSS_20260917_verified_v1\.venv_revision\Scripts\python.exe -X utf8 -B scripts\multiseed_experiment.py --stage all --run-dir C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/results/multiseed_20260918T163717Z
```
Resume formal batches with `--stage run --run-dir C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/results/multiseed_20260918T163717Z`; re-run analysis only with `--stage analyze`.
