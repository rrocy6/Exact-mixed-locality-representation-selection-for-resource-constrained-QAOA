# Formal Step 4 / E2 implementation report

## Implemented scope

- Revalidates the frozen config, Step 2 manifests and hashes, canonical-file
  hashes, and the formal E1 continuation gate before doing any work.
- Constructs all-native, deterministic full, frozen-weight selective, and
  five-seed auxiliary-count-matched random representations for all 180 frozen
  compilation instances.
- Records logical width, auxiliaries, retained cubics, quadratic couplings,
  strict maximum penalty, and collected-Pauli coefficient dynamic range.
- Emits the paper Appendix D all-to-all reference CNOT count and deterministic
  earliest-layer depth for every frozen transpiler seed.
- Uses Qiskit 2.4.2 with the same frozen sparse coupling map, basis, layout,
  routing, optimisation level, translation method, and five-seed bundle for
  every representation. The routing-pass callback retains inserted SWAPs.
- Retains every scheduled seed row. Expected device-capacity failures and
  unexpected compiler failures have different statuses and are never silently
  deleted.
- Produces mean, median, standard deviation, and 95% normal-approximation
  uncertainty intervals while retaining scheduled/success/failure counts.
- Runs certified full-space, Pareto-beam, and greedy oracle selector validation
  with regret, hit, runtime, and compiler-call reporting. Test retuning is a
  hard failure.
- Saves exact E2 design assignments for reuse by E3.
- Generates the required LaTeX table and an embedded-font vector PDF figure.

## Frozen-scope interpretation

The compilation manifest deliberately includes original widths 16 and 20,
while the QAOA limit and frozen sparse device both have capacity 12. E2 does
not change Qmax or the topology:

- the compilation-tier selector uses the already-frozen weights without the
  QAOA-only hard feasibility limits;
- the reference all-to-all compiler reports logical synthesis/scheduling at
  the representation width;
- sparse designs wider than 12 remain scheduled failure rows.

This preserves the frozen data and provides transparent capacity coverage.

## Verification performed before delivery

- 54 regression tests passed with the exact pinned NumPy, SciPy, Qiskit,
  Qiskit Aer, and ReportLab stack.
- The fast integer-scaled selector evaluator matched the full exact-reference
  evaluator for every design of the signed multi-cubic regression instance.
- A real Qiskit sparse integration test passed and captured SWAPs for the
  frozen seeds.
- One real compilation-manifest instance produced all 80 scheduled design /
  topology / seed rows; expected sparse-width failures were retained.
- One oracle instance produced certified, beam, and heuristic validation rows
  with non-negative regret.
- The PDF was rendered through Poppler and visually checked for font
  substitution, clipping, overlap, and unreadable labels. The final generator
  embeds an available DejaVu Sans or Windows Arial TrueType font.

No formal E2 results are included in the update package. The user's clean
implementation commit must be embedded in every formal result row.
