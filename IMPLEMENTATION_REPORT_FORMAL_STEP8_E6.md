# Formal Step 8 / E6 implementation report

## Scope

This update implements only the limited-noise study required by the frozen
execution guide. It does not use real hardware, add further noise levels, change
the frozen structural subset, or select instances after observing noisy
outcomes.

## Frozen inputs and continuation gates

The pipeline re-verifies the formal config and sidecar, the complete Step 2 data
freeze, `noise_subset_v1.csv` and its sidecar, formal E3 artifacts, and the
formal E5 continuation gate. The frozen subset contains exactly 18 unique
instances, nine per family, and all four representation families satisfy Qmax.

## Limited-noise protocol

- Sampled noiseless, `realistic_low`, and `realistic_high` are the only levels.
- Each run uses 4096 shots on `device_sparse_v1`.
- Physical `sx` and `x` gates receive the frozen one-qubit depolarizing error;
  `cx` receives the frozen two-qubit depolarizing error; each measured physical
  qubit receives independent symmetric readout error.
- The 256 compiled-two-qubit budget is the only E6 budget.
- Each design is optimized under the frozen noiseless E3 COBYLA protocol with
  three independent restarts and 60 evaluations, then the exact parameters are
  held fixed across all three paired noise levels.
- The representative transpiler seed is chosen before noise simulation as the
  smallest frozen seed attaining the median one-layer compiled cost.
- The full measured circuit is compiled before execution. If the E3 per-layer
  estimate would exceed 256 gates, depth is reduced until the actual full
  compiled circuit obeys the budget.

## Scoring and outputs

Auxiliary bits are always discarded before the original Max-3SAT or spin-glass
objective is evaluated. Encoded energy and auxiliary inconsistency are retained
as diagnostics. The pipeline emits 1296 run rows, 24 summary rows, provenance,
a LaTeX table, a four-panel vector PDF, validation JSON, and SHA-256 sidecars.

## Mandatory stop conditions

The pipeline stops on any frozen hash mismatch, Step 5/7 continuation failure,
noise-subset replacement, missing paired level, cross-level parameter or seed
change, different shots/topology across representations, actual compiled budget
exceedance, non-original primary scoring, simulation failure, or unexpected
row count.
