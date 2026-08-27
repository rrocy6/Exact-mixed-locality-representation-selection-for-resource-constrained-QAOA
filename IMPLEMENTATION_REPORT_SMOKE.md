# URSS data-layer smoke pipeline implementation report

**Date:** 2026-08-27  
**Scope:** Non-formal smoke validation only  
**Result:** PASS

## Delivered implementation

- Canonical Boolean-polynomial utilities with exact coefficient aggregation.
- Independent weighted Max-3SAT direct evaluator and clause-to-PUBO conversion.
- Independent cubic spin-glass evaluator and `s=1-2x` conversion.
- Deterministic uniform and anchor-pair generators for both families.
- Stable derived seeds and canonical content-derived `instance_id` values.
- JSON Schema plus semantic validation.
- Exhaustive or fixed-seed direct-vs-canonical validation.
- Canonical structural metadata, pair reuse metrics, overlap statistics, and
  exact small-instance pair-cover values.
- Exhaustive small-instance ground truth.
- Deterministic raw, canonical, ground-truth, metadata, manifest, validation,
  and audit outputs.
- Refusal to overwrite non-empty evidence directories.

## Verification result

The regression suite completed with:

```text
Ran 14 tests
OK
```

The tests cover:

1. all eight Max-3SAT literal-sign patterns;
2. three manual spin-glass conversions;
3. the two known schema-example IDs;
4. identity invariance under record reordering;
5. identity change after a mathematical weight change;
6. duplicate-clause rejection;
7. fixed-seed regeneration for both families;
8. JSON Schema and semantic validation of generated instances;
9. direct-vs-canonical exactness;
10. byte-for-byte reproducibility of the entire smoke output tree;
11. preservation of an existing non-empty evidence directory.
12. acceptance of an explicitly blocked draft config;
13. rejection of a falsely frozen config that still contains blockers.

## Executed smoke batch

The executed smoke config SHA-256 is:

```text
f33c28265796d9ba69400232396063e400132aa79c062552574e6ae588e9496d
```

It generated four `n=6` instances:

| Family | Mode | Instance ID | Assignments checked | Result |
|---|---|---|---:|---|
| Max-3SAT | uniform | `inst_954e743987a108823fd00c2d39ffad16a112f0d22f1eaa136a5f7e40901c2d50` | 64 | PASS |
| Max-3SAT | anchor pair | `inst_df24c686f81ac95139a155b527bf033a5c7443d71cc688473ac8541dba1558a8` | 64 | PASS |
| Cubic spin glass | uniform | `inst_581d0b45390a75e0d98faa9b21dac1a3078b80e6f0ca96798db6b69294311a1f` | 64 | PASS |
| Cubic spin glass | anchor pair | `inst_47a7f2e45e83a8d4789af3417f64439dc96ec634b221cd4d9d13ca65e17ca478` | 64 | PASS |

All four passed JSON Schema validation, semantic validation, fixed-seed rerun
comparison, and exhaustive direct-vs-canonical equality. The two output-tree
runs used by the regression test were byte-for-byte identical.

The current `experiment_config_v1.draft.yaml` was also parsed and checked. Its
SHA-256 matched
`fcc7450ea20a4af51e77d4fb98196b741909cb85156a668f46e17af10508b40b`;
the config was correctly classified as valid, draft, freeze-blocked, with 32
remaining declared blockers.

## Interpretation boundary

The smoke run proves implementation mechanics for the data layer. It does not
establish formal sparsity/reuse coverage, choose `Qmax`, create a frozen
train/validation/test split, evaluate representations, or produce E1-E6
performance claims. In particular, the four observed reuse scores must not be
treated as benchmark-regime evidence.

## Next executable stage

The next stage is a timing and coverage pilot that generates a larger candidate
pool without using test outcomes. That pilot should measure reachable
sparsity/reuse cells, generator rejection rates, exact-truth runtime, and full
representation widths. Its evidence is then used to propose the formal sample
counts and `Qmax` before freezing the manifest.
