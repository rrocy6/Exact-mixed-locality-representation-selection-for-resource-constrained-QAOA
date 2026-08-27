# URSS assumptions and decisions

## Status

- Config revision: `experiment_config_v1_draft_2`, version `1.0-draft.2`.
- Status: `draft_pending_pilot_and_approval`.
- Freeze gate: blocked, with 23 declared blockers.
- Smoke validation: passed; these outputs are not formal results.
- Formal manifests and formal train/validation/test assignments do not yet exist.
- No E1-E6 result may be reported from the smoke evidence.

## Authoritative inputs

| Source | SHA-256 |
|---|---|
| `benchmark_spec_v1.md` | `7ce13bdf2135fed2e34eddffeb2cde75ec25ee9c284adfd9177b63e487af78cb` |
| `instance_schema/instance_schema_v1.json` | `21c06ecf36855e12d1b86a31ded625cfceba8ae0004a83ecd74bb653172b675b` |
| `paper/main.tex` | `33c48ab1ec316710c25f19d13b92134b9cd2e8c67a815061b148a2d1d579d351` |
| `URSS_experiment_execution_guide_for_partner.pdf` | `9f75d6db53b84e59e9bffd7e0b24ba64ef8ea7f1ab543d15693853feb32f1539` |

## Decisions already made

### D1 - Seed namespaces

- Formal generation master seed: `2026082701`.
- Independent validation seed: `2026082702`.
- Split seed: `2026082703`.
- Matched-random seeds: `2026082711` through `2026082715`.
- Transpiler seeds: `2026082721` through `2026082725`.
- Optimizer seeds: `2026082731` through `2026082733`.
- Circuit seeds: `2026082741` through `2026082743`.
- Measurement seeds: `2026082751` through `2026082753`.

Reason: separate namespaces prevent accidental seed reuse across logically
different random processes while preserving simple deterministic provenance.

### D2 - Fully quadratized reference

The full reference uses a minimum-cardinality pair cover. Multiple optimal pair
sets and term assignments are resolved lexicographically.

Reason: this gives a strong full-quadratization endpoint, avoids an arbitrary
weak pair assignment, and is deterministic. Solver status and any failure to
certify minimum cardinality must be recorded rather than silently accepted.

### D3 - Matched-random baseline

Matched-random selective designs match the selected design's auxiliary count
and are averaged over five fixed seeds.

Reason: matching width directly controls the primary qubit-cost difference.
Five seeds keep the pilot affordable while exposing random-baseline variance.

### D4 - Penalty tightness offsets

Use `delta=1` below threshold and `epsilon=1` above threshold.

Reason: both benchmark families produce exact integer canonical coefficients,
and the paper's worked example uses unit positive margins. E1 must still verify
failure/tie/unique-consistency behaviour at `T-1`, `T`, and `T+1`.

### D5 - Selector structure

Use the paper's deterministic Pareto-beam search followed, when requested, by
anytime branch-and-bound certification. Beam allocation is 50% smallest
resource score and 50% nondominated rank/crowding. Final ties use the
lexicographic action vector. Always-valid compiler lower bounds are zero.

Reason: these rules are stated in the paper and therefore are not replaced by
an alternative heuristic. Beam width and deterministic evaluation budget remain
pilot decisions.

### D6 - Reference compiler

- Aggregate coefficients before compilation and remove exact zeros only.
- Order originals first and active auxiliary pairs lexicographically.
- Order Pauli strings by increasing weight, then lexicographically.
- Use the ancilla-free CX-Rz-CX parity gadget targeting the largest index.
- Disable cross-gadget cancellation, commutation reordering, and approximate
  angle simplification.

Reason: these rules reproduce the deterministic reference compiler defined in
the paper. Device-level routing remains a separate protocol.

### D7 - Compiler randomness

Every representation uses the same five transpiler seeds. The selector uses the
median compiled metric across the complete bundle.

Reason: the median is deterministic and reduces sensitivity to an unusually
lucky routing seed. Every raw per-seed row is still retained.

### D8 - QAOA initial parameters

Each restart receives independently seeded uniform parameters, with gamma in
`[0, 2*pi)` and beta in `[0, pi)`. Representations are optimized independently
using the same seed policy and budget.

Reason: the rule is reproducible, representation-neutral, and does not reuse a
winner's optimized parameters for another representation.

### D9 - Primary relaxation implementation

Implement SA/RLT level 2 with `scipy.optimize.linprog(method="highs")` and
presolve enabled. Pair moments from this relaxation are primary;
`q_ij=mu_i*mu_j` is only the declared ablation.

Reason: HiGHS provides a reproducible local LP implementation suitable for the
small pilot. The exact SciPy version is frozen only after successful install and
tests.

## Decisions that require pilot evidence

- Common `Qmax`.
- Selector weights, normalisation scales, hard limits, beam width, and complete
  candidate-evaluation budget.
- Sparse directed coupling map and basis gates.
- Device translation, layout, routing, optimisation, and scheduling settings.
- QAOA depths, compiled two-qubit budgets, optimizer, evaluations, restarts,
  tolerance, shots, and warm-start clipping delta.
- Fixed noise model and the parameters of exactly two nonzero noise levels.

The pilot may use only generation/training/validation information. It may not
inspect test-set representation winners.

## Automatic decision rule

Within the scope already authorised by the benchmark specification and paper,
choose the simplest reproducible setting that:

1. preserves pointwise exactness;
2. applies identical budgets and compiler protocols to all representations;
3. fits the declared memory/runtime limit;
4. does not cause avoidable sparsity/reuse coverage collapse; and
5. does not use test outcomes.

Record every chosen value, pilot evidence, and deviation here. Intermediate
confirmation is not required. Stop instead of continuing only for strict
exactness failure, train/test leakage, or an unfair comparison budget.

## Current deviations and limitations

- The formal config is intentionally not named `experiment_config_v1.yaml`.
- The smoke manifest uses `split=smoke_not_formal`; it is not a frozen split.
- Qiskit/Aer were absent from the original smoke environment; the pilot environment now pins Qiskit 2.4.2 and Qiskit Aer 0.17.2.
- The device topology, formal selector, QAOA, and noise pipeline are not yet
  implemented.
- Paper Results and Reproducibility sections still contain TODO placeholders.
- Source approval by benchmark owner and project lead is not yet recorded.

## Formal Step 1 freeze (v1)

- Status: `frozen`; remaining blocker count: `0`.
- Formal config: `configs/experiment_config_v1.yaml`.
- Formal config SHA-256: `c1fe6ddb0aa5e0bd75dbc46707e2824bbe199bac82b2d766160294ce56353d99`.
- Evidence-backed common width cap: `Qmax=12`.
- Selector: equal weights `0.25/0.25/0.25/0.25`, beam width `64`, complete oracle budget `65536`.
- Sparse compiler target: bidirectional 3-by-4 grid, `rz/sx/x/cx`, optimisation level `1`, SABRE layout/routing, deterministic seed bundle already declared.
- QAOA: depths `[1, 2]`, compiled 2Q budgets `[128, 256]`, COBYLA with `60` evaluations and `3` restarts, `4096` sampled/noisy shots.
- Warm-start clipping delta: `0.05`.
- Noise model: `aer_local_depolarizing_and_symmetric_readout_grid_v1` with exactly two frozen nonzero levels.
- Pilot config SHA-256: `52f025c8cbe8de594661b24f9129696b9bf0ca8727e416026417952e77ee818d`.
- Pilot audit SHA-256: `8f1a985cbdb9a14f30c7c26258f872fde3b1dfb59f65f9d0bb7353e5950a0fff`.
- Formal manifests/splits have not yet been created; their generation belongs to Step 2.

This section supersedes the earlier draft-status and pending-pilot statements. The complete values and rationales are authoritative in the formal config, its `freeze_provenance`, and `configs/step1_freeze_decisions_v1.json`.

## Formal Step 2 data freeze (v1)

- Status: `pass`; formal manifests and the fixed split are frozen.
- Formal instance count: `312`.
- Oracle: `30` instances per family; QAOA: `36` per family; compilation: `90` per family; noise subset: `9` per family.
- QAOA common width cap: `Qmax=12`; accepted-manifest feasibility failures: `0`.
- Split counts: oracle `{'test': 12, 'train': 36, 'validation': 12}`, QAOA `{'test': 14, 'train': 44, 'validation': 14}`, compilation `{'test': 36, 'train': 108, 'validation': 36}`.
- Manifest bundle SHA-256: `79f5fdcba689459dcf7f80bc5c0fa9c08f12dfc4111da298f283911fbb239fe3`.
- Config SHA-256: `c1fe6ddb0aa5e0bd75dbc46707e2824bbe199bac82b2d766160294ce56353d99`.
- Generation-plan SHA-256: `ce881ad150a72354b843adb6c936e4afe1527655ac750bc3d89c0ae476cfc355`.
- Code commit: `bee9c67f3f61ba16ad7ba5dbb0f1b3b151c68c16`.
- Direct-vs-canonical, Boolean-vs-Ising, schema, fixed-seed rerun, duplicate, and split-leakage gates all passed.
- Ground truth is exact only where `status=optimal`; larger unaffordable instances remain explicitly `not_run_width_above_declared_exact_limit` and are not presented as exact.
- No selector, representation-winner, QAOA, or noise-winner result was used for data selection.
- E1-E6 formal result files have not yet been created.

The machine-readable authority is `data/benchmark_audit_v1.json` together with `data/manifests/manifest_bundle_v1.json` and their SHA-256 sidecars.

## Formal Step 2 audit-sidecar repair

- The frozen JSON and HTML audit contents were not changed.
- Root cause: both artifacts previously mapped to benchmark_audit_v1.sha256;
  the later HTML write overwrote the JSON hash.
- JSON SHA-256: 80b0717b3cbfe483c137d9838378b6673b817ab7eba623e8d1c241779f68c1c7.
- HTML SHA-256: 6185116ef4d6098fe84267634c0815a831117ee1233a6b0cf4d58edcbd422970.
- Separate JSON and HTML sidecars now verify independently.

## Formal Step 3 / E1 exactness (v1)

- Data-freeze gate revalidated before E1; config and oracle manifest hashes were locked.
- Oracle selection used complete deterministic enumeration under the frozen 65,536-candidate budget and frozen resource objective.
- The frozen v1 selector config does not declare a fibre-risk threshold; E1 records this transparently and does not invent one.
- Below/at threshold trials perturb one active pair at a time while all other penalties remain strict.
- E2-E6 may continue only because every strict trial was pointwise exact with a unique consistent auxiliary fibre.
## Formal Step 4 / E2 resources (v1)

- Status: `pass`; E3-E6 continuation is allowed.
- Frozen compilation instances: `180`; logical rows: `1440`; raw compiler rows: `14400`.
- Every design uses both frozen topology IDs and the complete five-seed transpiler bundle.
- Expected sparse width failures retained: `3705`; unexpected compiler failures: `0`.
- The compilation tier includes widths above Qmax and above the frozen 12-qubit sparse device. Its selector uses the frozen weights without QAOA hard limits, while oracle selector validation retains the QAOA feasibility limits and complete-space certification.
- Sparse rows wider than 12 qubits are retained as `infeasible_width_exceeds_topology`; they are not excluded or imputed.
- Selector weights were not tuned on test. Certified, beam-incumbent, and heuristic rows are distinguished in `results/selector_validation.csv`.
- Compiler protocol ID: `compiler_d2b3b8844e9b97c1d3d3fd40`.
- Config hash: `c1fe6ddb0aa5e0bd75dbc46707e2824bbe199bac82b2d766160294ce56353d99`; compilation manifest hash: `9626c07cf4ccf3251a3585a4b367551c7a78f57218970c0d71f73f221adea5d3`.
- Matched-random designs degenerating to the selected design: `715`; this is reported rather than resampled when no distinct matched design was found.
