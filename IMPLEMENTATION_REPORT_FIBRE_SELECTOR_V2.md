# Fibre-aware selector v2 implementation report

## Scope

This additive update closes the method gap identified by the E1/E2 correction
review. The v1 resource-only results remain reproducible and unchanged. V2
freezes and validates the fibre-aware representation selector claimed by the
paper.

## Frozen definitions

- Primary relaxation: SA/RLT level 2 using the pinned SciPy HiGHS stack.
- Moment source: all first moments `mu_i` and pair moments `q_ij` from one
  common relaxation per raw instance.
- Optimum-face rule: primary objective followed by a deterministic
  SHA256-derived positive secondary objective within tolerance `1e-9`.
- Fibre excess:
  `sum_p((q_p-mu_i*mu_j)*A_p(mu)+M_p*ell_p)`.
- Rosenberg expectation:
  `ell_p=mu_i*mu_j+q_p*(3-2*mu_i-2*mu_j)`.
- Design-independent normalisation:
  `4*sum_candidate_pairs(sum_incident_abs_cubic_coefficients+margin)`.
- Guardrail: normalised fibre excess at most `tau_fib=0.02`.
- Resource weights: auxiliary `0.05`, 2Q gates `0.45`, 2Q depth `0.45`,
  maximum penalty `0.05`.
- Search: deterministic 64-wide beam, 50/50 score and five-coordinate
  nondominated-rank/crowding allocation, lexicographic final action tie-break,
  and complete oracle certification up to 65,536 leaves.
- Matched-random: five SHA256-derived seeds, exact auxiliary-count matching,
  bounded pair-set sampling, polynomial bipartite matching, and a declared
  fallback.

## Calibration boundary

Only the 36 train and 12 validation oracle instances were used to choose the
weight vector and `tau_fib`. No QAOA outcomes and no test instance files were
read during calibration. The frozen calibration reproduces:

| Split | Native | Mixed | Full | Guardrail changed | Max score degradation |
|---|---:|---:|---:|---:|---:|
| Train | 18 | 13 | 5 | 10 | 0.0380208333 |
| Validation | 6 | 4 | 2 | 2 | 0.0486979167 |

The validation non-native fraction is `0.5` and the mixed fraction is `1/3`.
The config hash is frozen before the twelve held-out oracle files are opened.

## Local full-scale validation

- `123/123` repository tests passed after installing the frozen dependency set.
- `60/60` closed-form fibre-excess values agreed with direct enumeration; the
  maximum absolute error was `7.55e-15`.
- Oracle validation produced `180` rows and no negative regret.
- Pareto beam hit the certified design on `58/60` oracle instances.
- Native-completion greedy hit the certified design on `30/60` instances.
- Design manifests were generated for `60` oracle, `72` QAOA, and `180`
  compilation instances.
- Every instance has five deterministic Matched-random rows with exact
  auxiliary-count matching.
- All ten primary generated artifacts and their sidecars passed the package
  hash manifest.

## Reuse and mandatory reruns

Raw data, canonical data, ground truth, instance splits, Native representation,
and deterministic Full representation are unchanged. Native/Full result rows
may be reused only when their config-independent protocol fields, depth, budget,
and seeds remain identical and the new report records that reuse explicitly.

Selected and Matched-random designs have changed. Their affected E1--E6 rows,
summaries, tables, figures, hashes, E5 regime map, and final result pack must be
rebuilt in a following checkpoint. This update intentionally reports
`e1_e6_rerun_completed=false` until that work is done.
