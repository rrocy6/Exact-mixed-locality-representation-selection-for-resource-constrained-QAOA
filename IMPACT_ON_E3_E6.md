# Impact of the E1/E2 review on E3-E6

## Confirmed current method state

The frozen selector objective contains auxiliary count, reference 2Q gate
count, reference 2Q depth, and maximum penalty. The E3 implementation selects
the `selective` representation through this resource-only beam search. It does
not consume SA/RLT level-2 pair moments and has no fibre-risk score or
guardrail.

E4 does compute SA/RLT level-2 pair moments, but only for warm-start
initialization. This does not retroactively make the E3 selector fibre-aware.

## What can be retained

- Original E1 native and full exactness results.
- E2 all-to-all native/full resource rows.
- Existing E2 compiled raw rows for the sparse paired re-summary; no
  recompilation is needed for the statistical correction.
- Existing E3-E6 outputs if every selective/matched-random claim is explicitly
  labeled as a resource-only-selector result.

## What changes without rerunning E3-E6

- Add the E1 nontrivial-selective exactness supplement.
- Replace the 23 tie-only below-threshold witness exports with positive-error
  witnesses from the same trials.
- Include `selector_validation.csv` and its matching hash.
- Replace the sparse main comparison with the common-feasible 21-instance
  paired table/figure.
- Move the original representation-specific success-only sparse view to an
  appendix and label it conditional.
- State in the manuscript, captions, result pack README, and method-status page
  that the current selective results use a resource-only selector.

## When E3-E6 must be rerun

If the manuscript must claim that the complete proposed selective method uses
SA/RLT pair moments and a fibre-risk guardrail, the rule must first be specified
and frozen. At minimum it needs a mathematical score, threshold or constraint,
tie-break, moment source, infeasible/unknown policy, and hashable config fields.

After that change, rerun:

1. E1 strict/threshold checks for the newly selected and matched-random designs.
2. E2 logical and sparse compiled resources for selected and matched-random
   designs; native/full and existing all-to-all controls can be reused when
   unchanged.
3. E3 for selected and matched-random designs because representation actions,
   widths, budgets, and objective fibres may change.
4. E4 for affected designs because auxiliary variables and warm-start pair
   mappings may change.
5. E5 because its regime map consumes E2-E4 endpoints.
6. E6 for affected designs because compiled circuits and noisy endpoints may
   change.

Changing only the manuscript label to `resource-only` does not require a
numerical rerun of E3-E6. Claiming a fibre-aware proposed selector does.
