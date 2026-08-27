# Formal Step 5 / E3 implementation report

## Scope

This update implements the frozen four-representation QAOA comparison required by Step 5 / E3. It does not run formal results inside the delivery workspace; the formal run must occur from the user's clean implementation commit so every row records that exact commit.

## Frozen input and continuation gates

The runner revalidates the formal config and hash, all frozen data hashes, the 14-row QAOA test split, exact original-objective ground truth, Qmax feasibility, every formal E2 artifact/hash, and the E2 continuation summary. E3 refuses to start unless E2 reports the exact expected row counts, zero unexpected compiler failures, zero topology/seed/protocol alignment failures, no selector test retuning, and `e3_e6_may_continue=true`.

## Representation protocol

Each test instance constructs all-native, deterministic fully quadratized, frozen-selector selective, and matched-random selective representations. The matched-random baseline retains all five frozen seeds and matches the selected auxiliary count. Every design must satisfy the common Qmax and the frozen selector hard limits.

## Fair QAOA budgets

Equal-layer comparisons use frozen depths `p=1,2`. Equal compiled-2Q comparisons recompile every QAOA cost layer to `device_sparse_v1` under all five frozen transpiler seeds, take the median per-layer two-qubit cost, and choose the largest integer depth that does not exceed budgets `128` or `256`.

The real frozen test preflight found per-layer sparse costs from 26 to 159 gates. Consequently, 30 fixed design slots cannot fit one layer under budget 128. They are retained as maximum-feasible `p=0` comparisons with `actual_2q_gates=0`; the pipeline never changes the frozen budget, exceeds it, drops the instance, or substitutes a different representation. No 256-gate comparison required `p=0` in the preflight.

## Optimization and scoring

Every fixed design/budget retains all three independently initialized COBYLA restarts and exactly 60 objective evaluations. Frozen optimizer, circuit, and measurement seed bundles are mapped one-to-one by restart. Final parameters are not shared across representations. Early COBYLA termination is padded with deterministic final-point evaluations so the consumed evaluation budget remains equal and is explicitly audited.

The statevector implementation uses the exact diagonal encoded polynomial and the standard cold QAOA mixer. Its probability distribution is regression-tested against Qiskit's reference circuit. The optimization and primary result both use the projected original-family objective. Encoded energy and auxiliary inconsistency are stored only as diagnostics. Exact ground truth supplies optimum-sampling probability.

## Outputs

The formal run schedules 112 fixed designs and 1,344 raw restart rows, then produces 32 family/representation/budget summary rows with paired differences versus native and 95% uncertainty intervals. It emits:

- `results/e3_qaoa_runs.csv`
- `results/e3_qaoa_summary.csv`
- `results/e3_budget_plan.csv`
- `results/e3_validation_summary.json`
- `tables/table_e3_qaoa.tex`
- `figures/figure_e3_equal_layer.pdf`
- `figures/figure_e3_equal_2q_budget.pdf`
- one SHA-256 sidecar for every formal artifact

## Mandatory stop conditions

The E3 gate fails on any missing restart, evaluation-budget mismatch, seed-policy mismatch, nonzero parameter sharing, compiled budget exceedance, encoded-objective primary scoring, omitted best-only schedule, simulation failure, row-count mismatch, frozen input/hash mismatch, or failed formal E2 gate. Failed staging is retained for diagnosis and is never silently overwritten.

## Verification completed before packaging

- 12 focused E3 tests pass.
- The complete regression suite reports 66 tests and `OK`.
- A real 14-instance budget preflight compiled all 112 design slots under all five sparse transpiler seeds.
- The preflight recorded cost range 26-159, median 90.5, 30 zero-layer slots at budget 128, and zero zero-layer slots at budget 256.
- A real depth-9, 60-evaluation statevector/COBYLA probe passed with norm error below `1e-15`.
- Both generated PDF layouts are rendered and inspected before delivery.
