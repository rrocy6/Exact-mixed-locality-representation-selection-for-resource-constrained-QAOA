# Fibre-aware Selected/Matched-random E1--E6 rerun implementation

## Scope

This update consumes the immutable `fibre_selector_v2` bundle and reruns the
formal E1--E6 chain without changing the v1 raw instances, canonical
coefficients, metadata, splits, ground truth, compiler protocol, QAOA budgets,
warm-start protocol, or noise model.

All new artifacts are isolated under `fibre_e1_e6_v2/`; the v1 formal outputs
remain byte-for-byte untouched.

## Mandatory input gates

Before E1, the orchestrator verifies:

- the v2 config and sidecar;
- the selector-v2 package manifest and every listed byte hash;
- the selector audit is `pass` and still declares E1--E6 incomplete;
- zero closed-form/enumeration fibre-validation failures;
- exact raw hashes of the oracle, QAOA, and compilation manifests;
- complete 60/72/180 instance coverage and instance/split/family/canonical-hash alignment;
- exactly one Selected and five auxiliary-count-matched designs per instance;
- action vectors align with the frozen canonical cubic supports.

## Rerun behavior

The existing formal functions remain the computational authority. A scoped
override injects the already-frozen v2 Selected/Matched-random action vectors:

- E1 uses oracle-tier v2 actions for exactness and penalty trials;
- E2 uses compilation-tier v2 actions and the frozen fibre-aware oracle
  selector-validation rows;
- E3, E4, and E6 use QAOA-tier v2 actions;
- E5 is regenerated from the resulting E2--E4 v2 artifacts.

Native and Full designs are not reselected. They are recomputed as invariant
controls under unchanged protocols so all pre-existing fairness counts,
pairings, summaries, and plots remain structurally complete. This is more
conservative than copying their old rows and avoids mixed-provenance raw tables.

## Provenance and non-overwrite guarantees

Each step validation summary and step audit records:

- v2 config hash;
- parent v1 data-config hash;
- selector-v2 audit hash;
- Selected/Matched-random branch scope;
- Native/Full invariant-control policy;
- representation row counts;
- committed implementation hash;
- `v1_results_overwritten=false`.

The final completion audit is written outside the immutable selector bundle.
The original selector audit deliberately remains unchanged; it describes the
state at selector freeze time. The final v2 result ZIP is deterministic and
contains its own package manifest.

## Verification performed while building the update

- Nine new v2 rerun tests passed.
- Full E1 integration passed on all 60 oracle instances, producing 480 summary
  rows with zero strict mismatch.
- Compilation and QAOA design injection each produced exactly eight feasible
  designs per checked instance.
- E2 full integration correctly stopped when the build container lacked the
  frozen `qiskit==2.4.2` dependency; no compiler results were fabricated.
- The formal Windows gate therefore requires the project's frozen `.venv` and
  `Ran 133 tests ... OK` before execution.
