# Golden regression output

Command:

```text
python run_tests.py
```

Output:

```text
PASS test_all_32_direct_vs_canonical
PASS test_clause_expansion_and_canonical_pubo
PASS test_cubic_shadow_reuse_and_pair_cover
PASS test_direct_easy_assignments
PASS test_full_pointwise_exactness_and_unique_consistency
PASS test_isolated_14_sharp_boundary
PASS test_metrics_optimum_and_minimiser_count
PASS test_rosenberg_truth_table_and_thresholds
PASS test_selective_pointwise_exactness_and_unique_consistency
PASS test_selective_sharp_boundary_witness

10 passed, 0 failed
```

Command:

```text
python -m src.exactness
```

Output:

```text
canonical coefficients: {(): 4, (2,): -4, (3,): -4, (4,): -4, (2, 3): 4, (2, 4): 4, (3, 4): 4, (1, 2, 3): 5, (1, 4, 5): 2, (2, 3, 4): -4}
canonical coefficients match: PASS
assignments checked: 32
direct-vs-canonical mismatches: 0
selective pointwise mismatches: 0
selective non-unique/inconsistent minima at M23=6: 0
full pointwise mismatches: 0
full non-unique/inconsistent minima at strict M: 0
M23 boundary values (y23=0, y23=1): {4: (4, 5), 5: (5, 5), 6: (6, 5)}
M14 boundary values (y14=0, y14=1): {1: (1, 2), 2: (2, 2), 3: (3, 2)}
original optimum: 0
number of original minimisers: 21
```

No definition choices beyond the supplied hand-calculation checklist were made.
The local environment did not include pytest, so `run_tests.py` provides a
dependency-free runner for the same pytest-compatible test functions.
