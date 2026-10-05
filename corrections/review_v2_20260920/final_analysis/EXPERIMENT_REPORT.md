# URSS multi-seed compilation robustness experiment

Run ID: `final_analysis`  
Status: derived analysis complete; consult AUDIT.json for separate acceptance status  
Controlled seed set: `[1729, 2718, 31415, 57721, 65537]`; seed `1729` is the comparison seed.  
Environment: Qiskit `2.5.2` frozen input, explicit `SabreSwap(trials=8)`, identity placement, line-12/ring-12/grid-12, canonical/reuse synthesis.  
The historical archive used Qiskit 2.5.2 with implicit routing trials; `baseline_comparison.csv` therefore treats this run as a controlled re-baseline rather than claiming that only the seed changed.

## Scope and completion

- Complete sample: 30 Max-3SAT and 30 constructed (`pair_star_isolated`) instances.
- Restricted sample: the first 10 of each family under the declared selection hash, nested in the complete sample.
- Candidate rows: 20292; formal task rows: see `task_manifest.csv` (the complete task count is audited in `AUDIT.json`).
- Every result is classified against a complete `(Q,G,D,M)` budget tuple. Missing resource values remain `UNKNOWN`.
- `classification_arrays.npz` is the complete cell-level archive; `budget_classification.csv` is represented by the seed summary and robust-region tables because a fully expanded 37-million-row CSV would obscure rather than improve auditability.

## Results

Across instance/topology/synthesis layers, seed-1729 baseline TRUE cells total `149439`. The five-seed common TRUE cells total `79069`; baseline retention is `0.5291` when the baseline denominator is nonzero. The per-layer result, UNKNOWN coverage, and classification flips are in `seed_summary.csv`, `robust_regions.csv`, and `classification_flips.csv`.

Seed TRUE-cell totals: 1729=149439, 2718=156824, 31415=155289, 57721=165626, 65537=155638.  
Seed UNKNOWN-cell totals: 1729=0, 2718=0, 31415=0, 57721=0, 65537=0.

Pareto stability is reported in `pareto_stability.csv`; pooled five-seed feasibility is reported separately in `pooled_seed_summary.csv` and uses a union of complete actual circuit vectors, never componentwise minima. Selector re-selection under the existing resource score is in `selector_stability.csv`.

## Engineering audit

`RUN_STATE.json` records execution completeness; `compilation_rows.csv` records every candidate/instance/topology/synthesis/seed task and its terminal status. Each raw batch is atomically written under `raw/`; compact QPY digests and pass-manager provenance are under `circuit_digests/`. `baseline_comparison.csv` records the controlled seed-1729 comparison to the historical archive.

## Scientific limits

These are five fixed descriptive compilation seeds, a finite frozen candidate library, three fixed 12-qubit topologies, and two synthesis strategies. They do not establish compiler-seed independence for all seeds or global infeasibility outside the tested library. UNKNOWN cells and compile failures remain visible in the audit.

## Reproduction

```powershell
python -X utf8 -B scripts/multiseed_experiment.py --stage analyze --run-dir results/multiseed_20260918T163717Z --output-dir corrections/NEW_ANALYSIS
python -X utf8 -B scripts/multiseed_experiment.py --stage audit --run-dir corrections/NEW_ANALYSIS
```
Use a new output directory for every published correction. See `README_REPRODUCE_REPAIRS.md` for environment and formal replay commands.
