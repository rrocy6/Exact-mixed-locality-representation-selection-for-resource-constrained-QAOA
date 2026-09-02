# Four-part addendum v1 run commands

Run these commands from the repository root after committing the update. The
phases are independent of the old E1--E6 outputs and write only under
`four_part_addendum_v1`.

## 1. Branch-and-bound certification

```powershell
python ".\run_four_part_addendum_v1.py" --phase certification
```

This runs actual best-bound branch-and-bound on the existing 60 oracle
instances. It records node/time traces, final lower and upper bounds, gaps,
explored nodes, runtimes, a LaTeX table, and a gap-versus-time PDF.

## 2. Additional hardware topologies

```powershell
python ".\run_four_part_addendum_v1.py" --phase topologies
```

This compiles the frozen Selected and Matched-random representations under
`line_12`, `ring_12`, and `heavy_hex_d3_19`, using the unchanged five
transpiler seeds and compiler settings. Existing all-to-all and 3x4-grid rows
are read into the combined E2 summary. No QAOA is run.

## 3. Selector ablation

```powershell
python ".\run_four_part_addendum_v1.py" --phase selector-ablation
```

This runs one-factor-at-a-time resource-weight, beam-width, fibre-threshold,
and penalty-margin sensitivity analyses on the 60 oracle instances, plus
deterministic greedy and maximum-reuse baselines. It does not change the main
setting and does not rerun QAOA or noise.

## 4. Strong-bias warm-start

```powershell
python ".\run_four_part_addendum_v1.py" --phase strong-bias
```

This deterministically generates a fixed candidate pool, screens exclusively
with SA/RLT relaxation signals, retains 10 usable active-auxiliary instances
per family, and runs only the new noiseless selective-representation
warm-start experiment at `p=1,2`. It compares exactly four policies with three
restarts and 60 evaluations. It does not rerun old E3, E4, or E6 rows.

If a phase is interrupted, rerun that same command with `--resume`. Do not use
`--resume` on a completed phase; completed results are intentionally
non-overwritable.

## 5. Final audit and result pack

```powershell
python ".\run_four_part_addendum_v1.py" --phase build
```

The final command requires all four phase audits to pass, creates the package
manifest, and writes these files in the repository root:

```text
URSS_FOUR_PART_ADDENDUM_V1_RESULT_PACK.zip
URSS_FOUR_PART_ADDENDUM_V1_RESULT_PACK.zip.sha256
```

Send both files. Confirm the sidecar before sending:

```powershell
$zip = Resolve-Path ".\URSS_FOUR_PART_ADDENDUM_V1_RESULT_PACK.zip"
$declared = (
  Get-Content ".\URSS_FOUR_PART_ADDENDUM_V1_RESULT_PACK.zip.sha256" -Raw
).Trim().ToLower()
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()

"HASH MATCH: $($actual -eq $declared)"
if ($actual -ne $declared) {
  throw "Final result pack hash mismatch; do not send"
}
```
