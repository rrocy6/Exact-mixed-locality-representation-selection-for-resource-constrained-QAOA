# Fibre-v2 E1/E4 post-processing correction report

## Scope

- No E1--E6 experiment is rerun.
- `e4_warmstart_runs.csv` remains byte-for-byte unchanged.
- E4 restart rows are averaged within design.
- Matched-random designs are averaged within instance.
- Confidence intervals use instance-level observations.
- E4 groups retain family, representation, budget mode, concrete budget value,
  warm-start policy, and pair closure.
- The LaTeX table prints `p=...` or `2Q=...` and 95% confidence intervals.
- E1 guardrail provenance is read from frozen `experiment_config_v2`.
- E4 -> E5 -> E6 validation-summary hashes and step audit hashes are cascaded.
- The existing final-pack builder regenerates the completion audit, package
  manifest, final ZIP, and ZIP sidecar.

## Safety gates

- Input sidecars are verified before any derived artifact is replaced.
- Any non-passing E4 raw row stops the correction instead of being discarded.
- A staging directory is used for all derived writes.
- The raw E4 hash is checked before and after replacement.
- A machine-readable post-processing audit records the unchanged raw hash,
  grouping fields, CI unit/method, old hashes, and new summary hashes.
- A previous final ZIP is moved to a recoverable sibling directory before the
  final ZIP is rebuilt.

## Verification performed for this update

- Python compilation passed for all modified/new modules.
- Existing E4 tests plus four new correction tests passed: 16/16.
- The complete suite discovered 138 tests in the build environment. Tests that
  do not require the absent Qiskit/Aer/jsonschema/psutil stack passed; the apply
  guide requires all 138 tests in the repository's frozen Windows environment.
- Golden regression remains required before applying the correction.
