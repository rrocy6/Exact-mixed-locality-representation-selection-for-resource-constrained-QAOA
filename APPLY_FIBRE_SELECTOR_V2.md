# Apply and run the frozen fibre-aware selector v2

This update is additive. It preserves `experiment_config_v1`, every v1 data
manifest, raw/canonical instances, ground truth, and the completed E1/E2
resource-only correction at commit `fca0d24`.

Do not continue to the affected E1--E6 reruns until the final gate in section E
passes.

## A. Verify the checkpoint and extract the update

Run from the repository root in the activated `.venv`:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Record E1 E2 review corrections") {
  throw "Expected the independent E1/E2 correction checkpoint"
}

if (git status --porcelain) {
  throw "Working tree is not clean; do not apply selector v2"
}

$zipPath = Join-Path `
  $env:USERPROFILE `
  "Downloads\URSS_FIBRE_AWARE_SELECTOR_V2_UPDATE_2026-08-28.zip"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Selector-v2 update ZIP not found"
}

$zipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()
$zipHashPath = $zipPath + ".sha256"

if (-not (Test-Path -LiteralPath $zipHashPath)) {
  throw "Selector-v2 ZIP sidecar not found"
}

$expectedZipHash = (
  Get-Content -Raw -LiteralPath $zipHashPath
).Trim().ToLower()

"ZIP SHA256: $zipHash"

if ($zipHash -ne $expectedZipHash) {
  throw "Selector-v2 ZIP hash mismatch"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

git status --short
```

Expected source files include:

```text
configs/experiment_config_v2.yaml
configs/experiment_config_v2.sha256
run_fibre_selector_v2.py
tests/test_fibre_selector.py
urss_pipeline/fibre_selector.py
urss_pipeline/fibre_validation.py
```

## B. Validate config v2 and run all regressions

```powershell
$configReport = @(
  python ".\validate_experiment_config.py" `
    --config ".\configs\experiment_config_v2.yaml" 2>&1
) | Out-String

$configReport

if ($LASTEXITCODE -ne 0) {
  throw "experiment_config_v2 validation failed"
}

if ($configReport -notmatch '"remaining_blocker_count": 0') {
  throw "experiment_config_v2 still has blockers"
}

if (
  $configReport -notmatch `
    '9d124ad72c0fe2b841fbfc927ec45c35cb413a6a0e01baada17f1025709d315c'
) {
  throw "Unexpected experiment_config_v2 hash"
}

New-Item -ItemType Directory -Force ".\evidence" | Out-Null

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE

"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 124 tests") {
  throw "Did not run the required 124 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location

"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed"
}
```

Required:

```text
Ran 124 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## C. Commit the implementation before reading held-out test instances

```powershell
git add -- `
  ".\APPLY_FIBRE_SELECTOR_V2.md" `
  ".\IMPLEMENTATION_REPORT_FIBRE_SELECTOR_V2.md" `
  ".\RUN_COMMANDS_FIBRE_SELECTOR_V2.md" `
  ".\configs\experiment_config_v2.yaml" `
  ".\configs\experiment_config_v2.sha256" `
  ".\run_fibre_selector_v2.py" `
  ".\tests\test_fibre_selector.py" `
  ".\urss_pipeline\fibre_selector.py" `
  ".\urss_pipeline\fibre_validation.py"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Selector-v2 implementation has formatting errors"
}

git commit -m "Add frozen fibre-aware selector v2"

if ($LASTEXITCODE -ne 0) {
  throw "Selector-v2 implementation commit failed"
}

if (git status --porcelain) {
  throw "Implementation commit did not leave a clean worktree"
}
```

## D. Run the frozen selector-v2 pipeline

The full run took about 27 minutes on the reference Linux environment. Keep the
PowerShell window open. Progress is printed for all 48 calibration, 12 held-out
oracle, 72 QAOA-tier, and 180 compilation-tier instances.

```powershell
$outputPath = ".\fibre_selector_v2"
$stagingPath = ".\fibre_selector_v2_building"

if (Test-Path -LiteralPath $outputPath) {
  throw "Formal selector-v2 output already exists; do not overwrite it"
}

if (Test-Path -LiteralPath $stagingPath) {
  throw "Incomplete selector-v2 staging exists; move it aside before rerun"
}

$selectorArguments = @(
  ".\run_fibre_selector_v2.py"
  "--config"
  ".\configs\experiment_config_v2.yaml"
  "--config-hash"
  ".\configs\experiment_config_v2.sha256"
  "--data"
  ".\data"
  "--output"
  $outputPath
)

python @selectorArguments 2>&1 |
  Tee-Object ".\evidence\FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt"

$selectorExitCode = $LASTEXITCODE
"SELECTOR V2 EXIT CODE: $selectorExitCode"

if ($selectorExitCode -ne 0) {
  throw "Fibre-aware selector v2 failed; do not continue"
}
```

If a prior interrupted run left the staging directory, preserve it instead of
deleting it:

```powershell
$recovery = Join-Path `
  (Split-Path -Parent (Resolve-Path ".").Path) `
  ("FIBRE_V2_FAILED_RUN_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

Move-Item -LiteralPath ".\fibre_selector_v2_building" -Destination $recovery
"RECOVERY DIRECTORY: $recovery"
```

Then rerun section D.

## E. Verify audit and every generated hash

```powershell
$auditPath = ".\fibre_selector_v2\fibre_selector_v2_audit.json"
$audit = Get-Content -Raw -LiteralPath $auditPath | ConvertFrom-Json

"STATUS: $($audit.status)"
"FORMULA CHECKS: $($audit.closed_form_enumeration_check_count)"
"FORMULA FAILURES: $($audit.closed_form_enumeration_failure_count)"
"ORACLE VALIDATION ROWS: $($audit.oracle_validation_row_count)"
"NEGATIVE REGRETS: $($audit.oracle_negative_regret_count)"
"BEAM HITS: $($audit.oracle_beam_hit_count)"
"GREEDY HITS: $($audit.oracle_greedy_hit_count)"
"ORACLE DESIGNS: $($audit.representation_design_counts.oracle)"
"QAOA DESIGNS: $($audit.representation_design_counts.qaoa)"
"COMPILATION DESIGNS: $($audit.representation_design_counts.compilation)"
"TEST FILES READ DURING CALIBRATION: $($audit.test_instance_files_read_during_calibration)"

$auditGate = (
  $audit.status -eq "pass" -and
  $audit.closed_form_enumeration_check_count -eq 60 -and
  $audit.closed_form_enumeration_failure_count -eq 0 -and
  $audit.oracle_validation_row_count -eq 180 -and
  $audit.oracle_negative_regret_count -eq 0 -and
  $audit.representation_design_counts.oracle -eq 60 -and
  $audit.representation_design_counts.qaoa -eq 72 -and
  $audit.representation_design_counts.compilation -eq 180 -and
  $audit.test_instance_files_read_during_calibration -eq 0 -and
  $audit.raw_canonical_ground_truth_rebuilt -eq $false -and
  $audit.native_full_protocols_changed -eq $false -and
  $audit.selected_matched_random_require_e1_e6_rerun -eq $true -and
  $audit.e1_e6_rerun_completed -eq $false
)

if (-not $auditGate) {
  throw "Selector-v2 audit gate failed"
}

$packageRoot = Resolve-Path ".\fibre_selector_v2"
$manifestPath = Join-Path $packageRoot "PACKAGE_SHA256_MANIFEST.csv"
$manifestRows = Import-Csv -LiteralPath $manifestPath
$hashFailures = [System.Collections.Generic.List[string]]::new()

foreach ($row in $manifestRows) {
  $artifactPath = Join-Path $packageRoot $row.path
  $sidecarPath = [System.IO.Path]::ChangeExtension($artifactPath, ".sha256")

  if (-not (Test-Path -LiteralPath $artifactPath)) {
    $hashFailures.Add("missing artifact: $($row.path)")
    continue
  }

  if (-not (Test-Path -LiteralPath $sidecarPath)) {
    $hashFailures.Add("missing sidecar: $($row.path)")
    continue
  }

  $actual = (
    Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256
  ).Hash.ToLower()
  $declared = (Get-Content -Raw -LiteralPath $sidecarPath).Trim()

  if ($actual -ne $row.sha256 -or $actual -ne $declared) {
    $hashFailures.Add("hash mismatch: $($row.path)")
  }
}

$manifestActual = (
  Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256
).Hash.ToLower()
$manifestDeclared = (
  Get-Content -Raw `
    ".\fibre_selector_v2\PACKAGE_SHA256_MANIFEST.sha256"
).Trim()

if ($manifestActual -ne $manifestDeclared) {
  $hashFailures.Add("package manifest hash mismatch")
}

"HASH FAILURE COUNT: $($hashFailures.Count)"
$hashFailures

if ($hashFailures.Count -ne 0) {
  throw "Selector-v2 generated hashes failed"
}

"FIBRE SELECTOR V2 FREEZE GATE: PASS"
```

Required headline values:

```text
STATUS: pass
FORMULA CHECKS: 60
FORMULA FAILURES: 0
ORACLE VALIDATION ROWS: 180
NEGATIVE REGRETS: 0
ORACLE DESIGNS: 60
QAOA DESIGNS: 72
COMPILATION DESIGNS: 180
TEST FILES READ DURING CALIBRATION: 0
HASH FAILURE COUNT: 0
FIBRE SELECTOR V2 FREEZE GATE: PASS
```

## F. Commit the frozen selector-v2 evidence

```powershell
git add -- `
  ".\evidence\FIBRE_SELECTOR_V2_CONSOLE_WINDOWS.txt" `
  ".\evidence\TEST_OUTPUT_FIBRE_SELECTOR_V2_WINDOWS.txt" `
  ".\fibre_selector_v2"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Generated selector-v2 evidence has formatting errors"
}

git commit -m "Freeze fibre-aware selector v2 designs"

if ($LASTEXITCODE -ne 0) {
  throw "Selector-v2 evidence commit failed"
}

git --no-pager log -4 --format="%h %s"
git status
```

The audit deliberately keeps `e1_e6_rerun_completed=false`. Passing this guide
finishes the selector-v2 freeze and design regeneration checkpoint; it does not
claim that affected E1--E6 results or the final result pack have already been
rebuilt.
