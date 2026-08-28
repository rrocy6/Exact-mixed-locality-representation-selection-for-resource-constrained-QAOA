# Apply and run the fibre-aware Selected/Matched-random E1--E6 update

This update is additive. It never overwrites the frozen v1 `results/`,
`tables/`, or `figures/`. All new formal artifacts are written under
`fibre_e1_e6_v2/`.

## A. Preconditions and extraction

Run from the repository root in the activated frozen `.venv`.

```powershell
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (git status --porcelain) {
  throw "Working tree is not clean; do not apply the v2 rerun update"
}

git merge-base --is-ancestor 7ce70fb HEAD
if ($LASTEXITCODE -ne 0) {
  throw "Required selector-v2 checkpoint 7ce70fb is not present"
}

$selectorAudit = Get-Content `
  ".\fibre_selector_v2\fibre_selector_v2_audit.json" `
  -Raw |
  ConvertFrom-Json

if (
  $selectorAudit.status -ne "pass" -or
  $selectorAudit.calibration_status -ne "pass" -or
  $selectorAudit.e1_e6_rerun_completed -ne $false
) {
  throw "Frozen selector-v2 audit does not permit E1-E6 rerun"
}
```

After independently verifying the downloaded ZIP hash against its accompanying
`.sha256` file, extract it into the repository root:

```powershell
$zipPath = Join-Path `
  $env:USERPROFILE `
  "Downloads\URSS_FIBRE_E1_E6_V2_RERUN_UPDATE_2026-08-28.zip"

$declaredZipHash = (
  Get-Content ($zipPath + ".sha256") -Raw
).Trim().ToLower()

$actualZipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()

"ZIP HASH MATCH: $($actualZipHash -eq $declaredZipHash)"
if ($actualZipHash -ne $declaredZipHash) {
  throw "Update ZIP hash mismatch"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force
```

## B. Regression gate and implementation checkpoint

```powershell
New-Item -ItemType Directory -Force ".\evidence" | Out-Null

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_E1_E6_V2_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE

"TEST EXIT CODE: $testExitCode"
if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not commit"
}
if (($testOutput -join "`n") -notmatch "Ran 133 tests") {
  throw "Did not run the required 133 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location

"GOLDEN EXIT CODE: $goldenExitCode"
if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; do not commit"
}

git add -- `
  ".\APPLY_FIBRE_E1_E6_V2.md" `
  ".\IMPLEMENTATION_REPORT_FIBRE_E1_E6_V2.md" `
  ".\RUN_COMMANDS_FIBRE_E1_E6_V2.md" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E1_E6_V2.csv" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E1_E6_V2.sha256" `
  ".\run_fibre_e1_e6_v2.py" `
  ".\tests\test_fibre_rerun.py" `
  ".\urss_pipeline\fibre_rerun.py" `
  ".\urss_pipeline\e5_regime.py" `
  ".\evidence\TEST_OUTPUT_FIBRE_E1_E6_V2_WINDOWS.txt"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "v2 rerun implementation has formatting errors"
}

git commit -m "Add fibre-aware E1 E6 rerun orchestrator"
if ($LASTEXITCODE -ne 0) {
  throw "Implementation commit failed"
}

if (git status --porcelain) {
  throw "Implementation commit did not leave a clean worktree"
}
```

Required regression result:

```text
Ran 133 tests
OK
10 passed, 0 failed
```

## C. Run E1 through E6 strictly in order

The following block writes every console log inside the additive output root,
so later steps still satisfy the clean-implementation gate. It stops at the
first failing step.

```powershell
New-Item `
  -ItemType Directory `
  -Force `
  ".\fibre_e1_e6_v2\evidence" |
  Out-Null

function Invoke-FibreV2Step {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("e1", "e2", "e3", "e4", "e5", "e6")]
    [string]$Step
  )

  $upper = $Step.ToUpper()
  $logPath = `
    ".\fibre_e1_e6_v2\evidence\FIBRE_V2_${upper}_CONSOLE_WINDOWS.txt"

  python ".\run_fibre_e1_e6_v2.py" `
    --step $Step 2>&1 |
    Tee-Object $logPath

  $exitCode = $LASTEXITCODE
  "$upper EXIT CODE: $exitCode"
  if ($exitCode -ne 0) {
    throw "$upper failed; do not continue"
  }
}

foreach ($step in @("e1", "e2", "e3", "e4", "e5", "e6")) {
  Invoke-FibreV2Step -Step $step
}
```

Required terminal gates:

```text
FIBRE V2 E1 GATE: PASS
FIBRE V2 E2 GATE: PASS
FIBRE V2 E3 GATE: PASS
FIBRE V2 E4 GATE: PASS
FIBRE V2 E5 GATE: PASS
FIBRE V2 E6 GATE: PASS
```

If a step fails and reports an incomplete staging directory, do not delete it.
After diagnosing the original failure, move the exact reported staging
directory to a timestamped recovery directory outside the repository, confirm
that the reported staging path no longer exists, and rerun only that step.

## D. Visual gate and final v2 result pack

Open these PDFs and confirm that every panel, label, legend, and error bar is
visible:

```powershell
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e2_resources.pdf"
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e3_equal_layer.pdf"
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e3_equal_2q_budget.pdf"
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e4_marginals.pdf"
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e5_regime_map.pdf"
Invoke-Item ".\fibre_e1_e6_v2\figures\figure_e6_noise.pdf"

$visualGate = Read-Host `
  "Type PASS only after checking every v2 PDF panel"

if ($visualGate.Trim().ToUpperInvariant() -ne "PASS") {
  throw "v2 PDF visual gate not confirmed"
}

python ".\run_fibre_e1_e6_v2.py" --step final
$finalExitCode = $LASTEXITCODE

"FINAL PACK EXIT CODE: $finalExitCode"
if ($finalExitCode -ne 0) {
  throw "Final v2 result pack failed"
}

$completion = Get-Content `
  ".\fibre_e1_e6_v2\FIBRE_E1_E6_V2_COMPLETION_AUDIT.json" `
  -Raw |
  ConvertFrom-Json

if (
  $completion.status -ne "pass" -or
  $completion.e1_e6_rerun_completed -ne $true -or
  $completion.final_result_pack_may_be_built -ne $true -or
  $completion.v1_results_overwritten -ne $false
) {
  throw "Final v2 completion audit failed"
}

"FIBRE V2 COMPLETION GATE: PASS"
```

## E. Result checkpoint

```powershell
git add -- `
  ".\fibre_e1_e6_v2" `
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip" `
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip.sha256"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Generated v2 artifacts have formatting errors"
}

git commit -m "Complete fibre-aware Selected Matched E1 E6 rerun"
if ($LASTEXITCODE -ne 0) {
  throw "v2 result commit failed"
}

git --no-pager log -5 --oneline
git status
```

Required final state:

```text
Complete fibre-aware Selected Matched E1 E6 rerun
Add fibre-aware E1 E6 rerun orchestrator
Freeze fibre-aware selector v2 designs
nothing to commit, working tree clean
```
