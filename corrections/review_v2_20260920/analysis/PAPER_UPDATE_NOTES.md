# Paper update notes for `analysis`

The current manuscript source is `paper/main.tex`. Add the following paragraph to the experimental-results discussion after the compiled-resource comparison, replacing placeholders only with values from the audited CSV files:

> We additionally evaluated the frozen candidate library under five fixed transpiler seeds (1729, 2718, 31415, 57721, and 65537), with explicit SABRE trials set to 8 and identity placement on line-12, ring-12, and grid-12 topologies. The complete sample contained 30 Max-3SAT and 30 constructed instances, with a nested 10-instance restricted subset per family. We report seed-wise strict mixed-only regions, their five-seed intersection, classification flips, UNKNOWN coverage, and Pareto-frontier stability. Because the historical archive used a different effective routing configuration, the new seed-1729 run is treated as a controlled re-baseline; it is not described as a seed-only change. The evidence is limited to the frozen candidate library, software stack, topologies, and five tested seeds.

Exact run artifacts: `C:/Users/rocyz/Desktop/量子算法组合优化tsp/协作/URSS_REPAIR_20260920_154042_4937f93c/URSS_REPAIR_WORKSPACE_20260920/project/corrections/review_v2_20260920/analysis`. The audited numerical values are in `seed_summary.csv`, `classification_flips.csv`, `pareto_stability.csv`, and `pooled_seed_summary.csv`.
