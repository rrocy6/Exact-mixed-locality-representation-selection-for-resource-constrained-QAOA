# E1/E2 review correction implementation report

Implemented corrections:

- Additive nontrivial-selective E1 supplement using a deterministic single
  reduction that guarantees `n_aux > 0` and `retained_cubic > 0` whenever
  constructible.
- Five-seed auxiliary-count-matched random supplement that also remains
  nontrivial.
- Strict, at-threshold, and below-threshold pointwise enumeration with separate
  witnesses.
- Future E1 witness selection prioritizes a positive pointwise error over a
  tie-only inconsistency.
- Re-export of the 23 existing below-threshold witnesses from their original
  parent trials.
- Selector-validation recovery with hash agreement against the original E2
  validation summary.
- E2 sparse main comparison based on the intersection of Native, Full, and
  Selected successful instance IDs, aggregated first across the five
  transpiler seeds and then paired by raw instance.
- Separate capacity/feasibility accounting.
- Six-panel revised PDF and LaTeX correction tables.
- Explicit auditable method status: current E1/E2/E3 selector is resource-only.

Local validation completed before release:

- 8/8 new unit tests passed.
- All 60 frozen oracle instances were constructible: 30 cubic spin glass and 30
  Max-3SAT.
- 1,080 supplement trial rows passed.
- 720 threshold witnesses were generated.
- Strict mismatch and inconsistent-minimizer counts were zero.
- All 23 existing tie-only below witnesses were re-exported with positive
  pointwise error.
- A synthetic 14,400-row E2 integration fixture reproduced 7,200 sparse rows,
  3,705 capacity failures, 108/21/95 representation-specific successful
  instances, and the 21-instance common-feasible cohort.
