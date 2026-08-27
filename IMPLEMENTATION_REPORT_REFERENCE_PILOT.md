# Reference compiler pilot implementation report

## Outcome

This update implements the deterministic all-to-all reference compiler defined
in the paper appendix and a non-formal statevector timing pilot.

## Implemented

- Exact Boolean-to-Pauli conversion under x=(I-Z)/2 using rational coefficient
  aggregation.
- Pauli-string ordering by increasing weight and then lexicographically.
- Ancilla-free CX-Rz-CX parity gadgets targeting the largest-index qubit.
- No cross-gadget cancellation, commutation reordering, or approximate angle
  simplification.
- Deterministic earliest-layer two-qubit depth.
- Reference SWAP count fixed to zero.
- Lexicographically first minimum-cardinality pair cover for small pilot
  instances.
- Canonical mixed-sign Rosenberg thresholds with unit positive margin.
- Exhaustive pointwise exactness and unique-consistent-fibre validation.
- Cold-start, fixed-angle, depth-one QAOA statevector timing probes.
- Projected scoring on original variables for augmented representations.
- Separate collected-PUBO and collected-Pauli coefficient dynamic ranges.
- Hashes of both the collected Pauli terms and emitted CNOT stream.
- Native/full resource rows and synthetic width probes at 6, 8, 10, and 12
  qubits.
- Refusal to overwrite non-empty pilot evidence.

## Evidence contract

The runner writes:

~~~text
reference_resources.csv
reference_exactness.csv
qaoa_statevector_timing.csv
config_snapshot.json
reference_pilot_audit.json
~~~

Timing rows are empirical machine measurements and are not expected to be
byte-for-byte identical. Algebraic resource records, exactness results, config
snapshots, and compiler stream hashes are deterministic.

## Scope limits

- This is not a formal train/validation/test batch.
- It does not create a manifest.
- It compares only all-native and deterministic fully quadratized
  representations.
- It does not implement the selective Pareto-beam selector.
- It does not freeze selector weights, device topology, QAOA budgets, noise, or
  Qmax.
- The exact exhaustive pair-cover routine intentionally rejects candidate
  shadows larger than the configured pilot limit instead of silently changing
  algorithms.

## Next gate

After this pilot passes on Windows, extend the width list and candidate-pool
coverage pilot. Use those measurements to choose Qmax and search budgets before
implementing the formal selector comparison.
