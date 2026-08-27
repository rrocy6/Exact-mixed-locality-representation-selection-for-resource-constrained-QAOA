# Formal Step 3 / E1 implementation report

## Scope

This update implements the execution guide's formal E1 pointwise-exactness
and penalty-tightness experiment. It consumes only the frozen oracle manifest
and revalidates every relevant config, manifest, audit, and canonical-file
hash before examining a representation.

## Mathematical protocol

- Cubic supports are collected before design construction.
- A design action is native or one of the cubic's three lexicographically
  ordered constituent pairs.
- Shared-pair thresholds use `T_p = max(C_p^+, C_p^-)` exactly.
- Below and at-threshold trials perturb one active pair at a time while all
  other active pairs retain the strict canonical penalty.
- Above-threshold trials use `M_p = T_p + epsilon` for every active pair.
- Every original assignment and every auxiliary fibre are exhaustively
  enumerated with exact rational arithmetic.

## Representations

- `all_native`: the unchanged canonical objective.
- `fully_quadratized`: the deterministic lexicographically tied minimum pair
  cover already frozen by Step 1.
- `selective`: the certified complete oracle design minimising the frozen
  reference-resource objective over at most 65,536 action vectors.
- `matched_random_selective`: five deterministic random designs matched to
  the selected auxiliary count, using the frozen seed bundle.

The frozen v1 selector configuration does not declare a fibre-risk threshold.
The implementation therefore does not invent one: the selected-design record,
summary, and assumptions explicitly mark the guardrail as
`not_configured_in_frozen_v1`. E1's mathematical exactness claims do not rely
on that diagnostic; later selector-performance interpretation must retain this
limitation.

Because the all-native and fully reduced designs are valid selector endpoints,
the result summary reports how many selected designs are all-native endpoints,
strictly mixed designs, or fully reduced endpoints. A matched-random design
with a selected auxiliary count of zero necessarily degenerates to the native
endpoint; this count is reported rather than hidden or resampled by outcome.

## Mandatory stop gate

The pipeline refuses to release results when any at/above-threshold trial has
a pointwise mismatch, when any above-threshold trial has an inconsistent
minimiser, or when canonical coefficients differ from the frozen data hash.
Only a passing summary sets `e2_e6_may_continue=true`.

## Outputs

- `results/e1_exactness.csv`
- `results/e1_penalty_witnesses.json`
- `results/e1_penalty_trials.json`
- `results/e1_selected_designs.json`
- `results/e1_validation_summary.json`
- `tables/table_e1_exactness.tex`
- SHA-256 sidecars for every E1 artifact
