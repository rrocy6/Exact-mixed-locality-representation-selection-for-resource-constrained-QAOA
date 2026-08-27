# Formal Step 2 implementation report

## Outcome

The formal data-freeze pipeline is implemented and has passed both reduced deterministic regressions and a full-scale local pressure run.

The full-scale run produced:

| Tier | Max-3SAT | Cubic spin glass | Total |
|---|---:|---:|---:|
| Oracle | 30 | 30 | 60 |
| QAOA | 36 | 36 | 72 |
| Compilation | 90 | 90 | 180 |
| Noise subset | 9 | 9 | 18 subset rows |

There are 312 unique formal raw instances. The noise manifest is a pre-result subset of the QAOA instances, not an additional raw pool.

## Internal gates

The one formal command performs, in order:

1. frozen-config and SHA-256 validation;
2. automatic smoke-batch validation;
3. deterministic candidate generation for both families;
4. schema and fixed-seed rerun checks;
5. direct-objective versus canonical-PUBO checks;
6. Boolean versus collected-Ising checks;
7. canonical metadata and coefficient diagnostics;
8. exact full-width checks for QAOA eligibility;
9. fixed 60/20/20 split assignment before any result;
10. pre-result structural noise-subset selection;
11. exact original-objective ground truth through `n=10` and explicit non-exact statuses above it;
12. four manifests, individual hashes, bundle hash, JSON audit, and HTML audit.

Outputs are built in `data_step2_building/` and renamed to `data/` only after the audit passes. Existing formal data is never overwritten.

## Full-scale verification result

The local pressure run reported:

```text
formal_instance_count: 312
duplicate_raw_instance_count: 0
split_leakage_count: 0
validation_failure_count: 0
qmax_feasibility_failure_count: 0
formal_manifests_created: true
formal_split_created: true
test_split_frozen_before_results: true
formal_results_created: false
status: pass
```

Ground truth statuses were `201 optimal` and `111 not_run_width_above_declared_exact_limit`. The latter are explicitly not represented as best-known or exact truth.

## Coverage

Both QAOA families retained all declared `n={6,8,10}`, all low/intermediate/high regimes, and both uniform/anchor-pair modes while satisfying `Qmax=12`. Both compilation families retained all `n={8,12,16,20}`, all three regimes, and both modes. Oracle spin-glass eligibility concentrated on the low regime because of the frozen `m3<=8` rule; this is recorded as structural filtering rather than hidden result selection.

QAOA candidates above Qmax remain in the candidate-exclusion audit and are promoted into the compilation tier only when their width belongs to the declared compilation n-values and capacity remains.

## Scope boundary

No E1-E6 experiment has been run. The pipeline explicitly records `formal_results_created=false`. The next stage may consume only these frozen hashes and manifests.
