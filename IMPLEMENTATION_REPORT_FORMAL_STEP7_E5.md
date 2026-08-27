# Formal Step 7 / E5 implementation report

## Scope

This update implements only the frozen sparsity-reuse-connectivity regime analysis. It does not regenerate data, replace test instances, inspect noise results, change E2/E3/E4 settings, or promote sign balance or original width into primary axes.

## Predeclared analysis

`configs/e5_analysis_v1.json` and its SHA-256 sidecar are part of the implementation commit, before formal E5 runs. They freeze:

- `selective` as treatment and `matched_random_selective` as the auxiliary-count-matched control;
- canonical cubic sparsity, pair reuse, and connectivity/routing as the only primary axes;
- sign balance and original width as supplementary diagnostics only;
- fixed structural coverage bins;
- 1% normalized original-objective and 5% normalized resource tolerances;
- a 95% paired normal interval rule;
- `help` only when the complete interval is above tolerance, `hurt` only when it is below negative tolerance, and `little_effect` otherwise, including uncertain results.

## Pairing and retained results

- E3 original-objective values are paired by raw instance, budget, and restart. Matched-random representation seeds are averaged within the same restart before comparison.
- E2 two-qubit gates, depth, and routing overhead are paired by raw instance, topology, and transpiler seed. Matched-random representation seeds are averaged within the same transpiler seed.
- Every row is from a frozen test split.
- Expected sparse-topology width infeasibility is retained as `not_estimable`, never imputed or silently deleted.
- Negative, null, and uncertainty-crossing results remain in the instance and summary files.
- Family views are reported separately; the combined view averages family means so one family cannot dominate it.

## Required outputs

- `results/e5_regime_instance_level.csv`
- `results/e5_regime_summary.csv`
- `results/e5_validation_summary.json`
- `tables/table_e5_help_tie_hurt.tex`
- `figures/figure_e5_regime_map.pdf`
- SHA-256 sidecars for every formal artifact

The vector PDF contains six panels: two family-specific sparsity views, a combined pair-reuse view, two family-specific connectivity views, and a help/little-effect/hurt count view.

## Verification

The complete frozen dependency environment runs 91 tests, including 13 new E5 tests. A local formal-shape validation exercised all 14 frozen QAOA test IDs, all 36 frozen compilation test IDs, 56 QAOA paired rows, 216 compiled-resource rows, and the required 272-row instance-level schema. Local effect values are fixtures and are not shipped or represented as formal results.
