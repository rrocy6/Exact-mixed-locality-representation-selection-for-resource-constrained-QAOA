# Apply the fibre-v2 E4 active-auxiliary gate fix

This patch removes the frozen-v1 constant `20` from the v2 E4 gate. The normal
v1 entry point retains `20` as its default; the v2 orchestrator derives the
expected value from the immutable QAOA-tier design bundle and passes it into
E4. The count follows E4's actual schedule: Full, Selected, and Matched-random
designs with auxiliaries are included; Native is not. No numerical count is
assumed by the guide or implementation.

## A. Inspect and retain the failed evidence

Run from the repository root in the activated `.venv`:

```powershell
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$failedSummaryPath = `
  ".\fibre_e1_e6_v2\e4_step6_building\results\e4_validation_summary.json"

if (-not (Test-Path -LiteralPath $failedSummaryPath)) {
  throw "Failed E4 validation summary is missing"
}

$failedE4 = Get-Content -LiteralPath $failedSummaryPath -Raw |
  ConvertFrom-Json

$failedE4 |
  Select-Object `
    status,
    scheduled_design_count,
    active_auxiliary_design_count,
    run_row_count_mismatch,
    failed_run_count,
    missing_restart_group_count,
    evaluation_budget_mismatch_count,
    seed_policy_mismatch_count,
    compiled_budget_exceed_count,
    non_original_primary_score_count,
    illegal_warmstart_variant_count,
    zero_auxiliary_duplicate_count,
    cold_e3_reproduction_mismatch_count,
    missing_marginal_count |
  Format-List

$designBundle = Get-Content `
  ".\fibre_selector_v2\qaoa_representation_designs_v2.json" `
  -Raw |
  ConvertFrom-Json

$testDesigns = @(
  $designBundle.records |
    Where-Object { $_.split -eq "test" }
)

$fullActive = @(
  $testDesigns |
    Where-Object { @($_.cubic_supports).Count -gt 0 }
).Count

$selectedActive = @(
  $testDesigns |
    Where-Object { [int]$_.selected.n_auxiliary -gt 0 }
).Count

$matchedActive = @(
  $testDesigns |
    ForEach-Object { $_.matched_random } |
    Where-Object { [int]$_.n_auxiliary -gt 0 }
).Count

$expectedActive = $fullActive + $selectedActive + $matchedActive

"FULL ACTIVE:     $fullActive"
"SELECTED ACTIVE: $selectedActive"
"MATCHED ACTIVE:  $matchedActive"
"EXPECTED ACTIVE: $expectedActive"
"OBSERVED ACTIVE: $($failedE4.active_auxiliary_design_count)"

if ($failedE4.active_auxiliary_design_count -ne $expectedActive) {
  throw "Observed E4 active-auxiliary count differs from the frozen v2 bundle"
}
```

Do not delete or move the staging directory yet.

## B. Verify and extract the patch

```powershell
$zip = Get-ChildItem `
  -LiteralPath "$env:USERPROFILE\Downloads" `
  -File |
  Where-Object {
    $_.Name -like "URSS_FIBRE_E4_V2_FULL_ACTIVE_AUX_FIX_2026-08-28*.zip"
  } |
  Select-Object -First 1

if ($null -eq $zip) {
  throw "Downloads 中未找到哈希正确的 E4 修复包"
}

$sidecar = Get-ChildItem `
  -LiteralPath "$env:USERPROFILE\Downloads" `
  -File |
  Where-Object {
    $_.Name -like "URSS_FIBRE_E4_V2_FULL_ACTIVE_AUX_FIX_2026-08-28*.zip.sha256"
  } |
  Select-Object -First 1

if ($null -eq $sidecar) {
  throw "Downloads 中缺少 E4 修复包 SHA256 文件"
}

$expectedHash = (Get-Content -LiteralPath $sidecar.FullName -Raw).Trim().ToLower()
$actualHash = (
  Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256
).Hash.ToLower()

"PATCH ZIP HASH MATCH: $($actualHash -eq $expectedHash)"
if ($actualHash -ne $expectedHash) {
  throw "E4 compatibility patch ZIP hash mismatch"
}

Expand-Archive `
  -LiteralPath $zip.FullName `
  -DestinationPath . `
  -Force

python -m py_compile `
  ".\urss_pipeline\e4_warmstart.py" `
  ".\urss_pipeline\fibre_rerun.py" `
  ".\run_fibre_e1_e6_v2.py" `
  ".\tests\test_fibre_rerun.py"

if ($LASTEXITCODE -ne 0) {
  throw "E4 compatibility patch syntax check failed"
}
```

## C. Test and commit the compatibility patch

```powershell
$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_E4_V2_FIX_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE

"TEST EXIT CODE: $testExitCode"
if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}
if (($testOutput -join "`n") -notmatch "Ran 134 tests") {
  throw "Did not run the required 134 tests"
}

git add -- `
  ".\APPLY_FIBRE_E4_V2_ACTIVE_AUX_FIX.md" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E4_V2_FIX.csv" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E4_V2_FIX.sha256" `
  ".\run_fibre_e1_e6_v2.py" `
  ".\tests\test_fibre_rerun.py" `
  ".\urss_pipeline\e4_warmstart.py" `
  ".\urss_pipeline\fibre_rerun.py" `
  ".\evidence\TEST_OUTPUT_FIBRE_E4_V2_FIX_WINDOWS.txt"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "E4 compatibility patch has formatting errors"
}

git commit -m "Use selector v2 active auxiliary count in E4"
if ($LASTEXITCODE -ne 0) {
  throw "E4 compatibility patch commit failed"
}
```

The worktree will still contain the additive `fibre_e1_e6_v2/` results. That is
expected; do not commit them until E6 and the final pack pass.

## D. Recover the failed staging directory and rerun only E4

```powershell
$repository = (Get-Location).Path
$staging = Join-Path `
  $repository `
  "fibre_e1_e6_v2\e4_step6_building"

if (-not (Test-Path -LiteralPath $staging)) {
  throw "E4 failed staging directory is missing"
}

$recovery = Join-Path `
  (Split-Path $repository -Parent) `
  ("FIBRE_V2_E4_FAILED_GATE_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

Move-Item `
  -LiteralPath $staging `
  -Destination $recovery

"RECOVERY DIRECTORY: $recovery"
"STAGING EXISTS AFTER MOVE: $(Test-Path -LiteralPath $staging)"

if (Test-Path -LiteralPath $staging) {
  throw "E4 failed staging directory was not recovered"
}

python ".\run_fibre_e1_e6_v2.py" `
  --step e4 2>&1 |
  Tee-Object `
    ".\fibre_e1_e6_v2\evidence\FIBRE_V2_E4_CONSOLE_WINDOWS.txt"

$e4ExitCode = $LASTEXITCODE
"E4 EXIT CODE: $e4ExitCode"
if ($e4ExitCode -ne 0) {
  throw "Corrected E4 failed; do not continue"
}

$e4 = Get-Content `
  ".\fibre_e1_e6_v2\results\e4_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e4 |
  Select-Object `
    status,
    e5_e6_may_continue,
    active_auxiliary_design_count,
    expected_active_auxiliary_design_count,
    cold_e3_reproduction_mismatch_count |
  Format-List

if (
  $e4.status -ne "pass" -or
  $e4.e5_e6_may_continue -ne $true -or
  $e4.active_auxiliary_design_count -ne $expectedActive -or
  $e4.expected_active_auxiliary_design_count -ne $expectedActive -or
  $e4.cold_e3_reproduction_mismatch_count -ne 0
) {
  throw "Corrected E4 audit gate failed"
}

"FIBRE V2 E4 ACTIVE-AUXILIARY GATE: PASS"
```

After this passes, continue without rerunning E1--E3:

```powershell
python ".\run_fibre_e1_e6_v2.py" --step e5
python ".\run_fibre_e1_e6_v2.py" --step e6
python ".\run_fibre_e1_e6_v2.py" --step final
```
