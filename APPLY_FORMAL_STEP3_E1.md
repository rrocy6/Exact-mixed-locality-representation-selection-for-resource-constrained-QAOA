# Apply and run formal Step 3 / E1

Run every command from the repository root in Windows PowerShell 5.1. Formal
E1 uses two commits: the clean implementation commit is embedded in every
result row, then the immutable result artifacts are committed separately.

## A. Verify the completed Step 2 checkpoint

```powershell
git --no-pager log -5 --format="%h %s"
git status

$audit = Get-Content `
  ".\data\benchmark_audit_v1.json" `
  -Raw |
  ConvertFrom-Json

if ($audit.status -ne "pass") { throw "Step 2 audit failed" }
if ($audit.formal_instance_count -ne 312) { throw "Wrong instance count" }
if (-not $audit.formal_manifests_created) { throw "Manifests are not frozen" }
if (-not $audit.formal_split_created) { throw "Split is not frozen" }
if ($audit.split_leakage_count -ne 0) { throw "Split leakage detected" }
if ($audit.validation_failure_count -ne 0) { throw "Validation failure" }
if ($audit.qmax_feasibility_failure_count -ne 0) { throw "Qmax failure" }
if ($audit.formal_results_created) { throw "Unexpected pre-E1 formal results" }
```

Required Git state:

```text
Freeze formal Step 2 manifests
nothing to commit, working tree clean
```

## B. Extract this update and run regressions

Verify the delivery SHA-256, then extract the ZIP into the repository root.

```powershell
Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python .\run_pipeline_tests.py |
  Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP3_E1_WINDOWS.txt"

$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not commit or run E1"
}

Push-Location ".\golden_example"
python .\run_tests.py
$goldenExitCode = $LASTEXITCODE
Pop-Location

"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; do not continue"
}
```

Required:

```text
Ran 45 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## C. Commit the E1 implementation before running formal E1

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP3_E1.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP3_E1.md" `
  ".\RUN_COMMANDS_FORMAL_STEP3_E1.md" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP3_E1_WINDOWS.txt" `
  ".\run_e1_exactness.py" `
  ".\tests\test_e1_exactness.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\e1_exactness.py"

git diff --cached --check
git --no-pager diff --cached --stat

git commit -m "Add formal Step 3 E1 exactness pipeline"
git status
```

Do not run E1 until `nothing to commit, working tree clean` appears. The clean
commit hash is embedded in every result row.

## D. Run formal E1

The following targets must not already exist:

```powershell
$e1Targets = @(
  ".\results\e1_exactness.csv"
  ".\results\e1_penalty_witnesses.json"
  ".\results\e1_validation_summary.json"
  ".\tables\table_e1_exactness.tex"
  ".\e1_step3_building"
)

foreach ($target in $e1Targets) {
  if (Test-Path -LiteralPath $target) {
    throw "Existing E1 target; refusing overwrite: $target"
  }
}
```

Run without `Tee-Object`: creating an evidence file before Python starts would
make the Git tree dirty and correctly trigger the implementation-hash guard.

```powershell
python .\run_e1_exactness.py `
  --config .\configs\experiment_config_v1.yaml `
  --config-hash .\configs\experiment_config_v1.sha256 `
  --data .\data `
  --results .\results `
  --tables .\tables `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md

$e1ExitCode = $LASTEXITCODE
"E1 EXIT CODE: $e1ExitCode"

if ($e1ExitCode -ne 0) {
  throw "Formal E1 failed; do not continue to E2-E6"
}
```

The final progress line must be:

```text
E1 EXACTNESS GATE: pass
E1 EXIT CODE: 0
```

## E. Verify the E1 stop gate

```powershell
$summaryPath = ".\results\e1_validation_summary.json"
$summary = Get-Content $summaryPath -Raw | ConvertFrom-Json

$summary |
  Format-List `
    status, `
    oracle_instance_count, `
    summary_row_count, `
    trial_count, `
    x_assignments_checked, `
    xy_assignments_checked, `
    strict_mismatch_count, `
    strict_inconsistent_minimiser_count, `
    threshold_mismatch_count, `
    threshold_tie_count, `
    below_threshold_mismatch_count, `
    below_threshold_failure_witness_count, `
    selected_design_classification_counts, `
    matched_random_degenerate_to_native_count, `
    canonical_coefficient_hash_mismatch_count, `
    e2_e6_may_continue

if ($summary.status -ne "pass") { throw "E1 summary failed" }
if ($summary.oracle_instance_count -ne 60) { throw "Wrong oracle count" }
if ($summary.strict_mismatch_count -ne 0) { throw "Strict mismatch" }
if ($summary.strict_inconsistent_minimiser_count -ne 0) {
  throw "Strict inconsistent minimiser"
}
if ($summary.threshold_mismatch_count -ne 0) { throw "Threshold mismatch" }
if ($summary.canonical_coefficient_hash_mismatch_count -ne 0) {
  throw "Canonical hash mismatch"
}
if (-not $summary.e2_e6_may_continue) { throw "E2-E6 continuation blocked" }
```

## F. Verify every E1 artifact hash

```powershell
$e1Artifacts = @(
  ".\results\e1_exactness.csv"
  ".\results\e1_penalty_witnesses.json"
  ".\results\e1_penalty_trials.json"
  ".\results\e1_selected_designs.json"
  ".\results\e1_validation_summary.json"
  ".\tables\table_e1_exactness.tex"
)

foreach ($artifact in $e1Artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension($artifact, ".sha256")
  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLower()
  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim()
  "$artifact HASH MATCH: $($actual -eq $declared)"
  if ($actual -ne $declared) {
    throw "E1 artifact hash mismatch: $artifact"
  }
}
```

Every line must display `True`.

## G. Save the audit and commit E1 results

```powershell
Get-Content ".\results\e1_validation_summary.json" |
  Tee-Object ".\evidence\FORMAL_STEP3_E1_AUDIT_WINDOWS.txt"

git diff --check
git status --short

git add -- `
  ".\RUN_COMMANDS.md" `
  ".\assumptions_and_decisions.md" `
  ".\evidence\FORMAL_STEP3_E1_AUDIT_WINDOWS.txt" `
  ".\results" `
  ".\tables\table_e1_exactness.tex" `
  ".\tables\table_e1_exactness.sha256"

git diff --cached --check
git --no-pager diff --cached --stat

git commit -m "Complete formal Step 3 E1 exactness"

git --no-pager log -7 --format="%h %s"
git status
```

Formal Step 3 / E1 is complete only when the result commit exists, the
worktree is clean, and `e2_e6_may_continue` is `true`.
