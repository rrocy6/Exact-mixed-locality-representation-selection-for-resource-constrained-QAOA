# Apply the fibre-v2 E1/E4 post-processing correction

This update performs no E1--E6 experiment rerun. It uses the existing
`fibre_e1_e6_v2/results/e4_warmstart_runs.csv` as the only numerical source for
the corrected E4 summary and table.

## A. Apply and commit the implementation

Run from the repository root in the already activated pilot environment.

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if (git status --porcelain) {
  throw "Working tree is not clean; do not apply the correction update"
}

$requiredInputs = @(
  ".\fibre_e1_e6_v2\results\e4_warmstart_runs.csv"
  ".\fibre_e1_e6_v2\results\e4_warmstart_runs.sha256"
  ".\fibre_e1_e6_v2\results\e1_validation_summary.json"
  ".\fibre_e1_e6_v2\results\e4_validation_summary.json"
  ".\fibre_e1_e6_v2\results\e5_validation_summary.json"
  ".\fibre_e1_e6_v2\results\e6_validation_summary.json"
  ".\configs\experiment_config_v2.yaml"
  ".\configs\experiment_config_v2.sha256"
)

$missingInputs = @($requiredInputs | Where-Object { -not (Test-Path $_) })
if ($missingInputs.Count -ne 0) {
  $missingInputs
  throw "Required frozen v2 inputs are missing"
}
```

After extracting the update ZIP into the repository root, run:

```powershell
$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FIBRE_E1_E4_POSTPROCESS_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not continue"
}

if (($testOutput -join "`n") -notmatch "Ran 138 tests") {
  throw "Did not run the required 138 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location
"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; do not continue"
}
```

Required:

```text
Ran 138 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

Stage and commit only the implementation update:

```powershell
git add -- `
  ".\APPLY_FIBRE_E1_E4_POSTPROCESS_FIX.md" `
  ".\IMPLEMENTATION_REPORT_FIBRE_E1_E4_POSTPROCESS_FIX.md" `
  ".\RUN_COMMANDS_FIBRE_E1_E4_POSTPROCESS_FIX.md" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E1_E4_POSTPROCESS_FIX.csv" `
  ".\UPDATE_FILE_MANIFEST_FIBRE_E1_E4_POSTPROCESS_FIX.sha256" `
  ".\evidence\TEST_OUTPUT_FIBRE_E1_E4_POSTPROCESS_WINDOWS.txt" `
  ".\repair_fibre_e1_e4_postprocess_v2.py" `
  ".\run_fibre_e1_e6_v2.py" `
  ".\tests\test_fibre_postprocess_v2.py" `
  ".\urss_pipeline\e4_warmstart.py" `
  ".\urss_pipeline\fibre_postprocess_v2.py"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Implementation update has formatting errors"
}

git commit -m "Add E1 E4 postprocessing correction"
if ($LASTEXITCODE -ne 0) {
  throw "Implementation commit failed"
}

if (git status --porcelain) {
  throw "Implementation commit did not leave a clean worktree"
}
```

## B. Rebuild only E4 summary/table and the validation hash chain

This command does not call any E1--E6 experiment runner.

```powershell
$rawPath = ".\fibre_e1_e6_v2\results\e4_warmstart_runs.csv"
$rawHashBefore = (
  Get-FileHash -LiteralPath $rawPath -Algorithm SHA256
).Hash.ToLower()

python ".\repair_fibre_e1_e4_postprocess_v2.py" `
  --output ".\fibre_e1_e6_v2" `
  --config ".\configs\experiment_config_v2.yaml" `
  --config-hash ".\configs\experiment_config_v2.sha256"

$postprocessExitCode = $LASTEXITCODE
"POSTPROCESS EXIT CODE: $postprocessExitCode"
if ($postprocessExitCode -ne 0) {
  throw "E1/E4 postprocess failed; do not rebuild the final ZIP"
}

$rawHashAfter = (
  Get-FileHash -LiteralPath $rawPath -Algorithm SHA256
).Hash.ToLower()
"RAW E4 HASH BEFORE: $rawHashBefore"
"RAW E4 HASH AFTER:  $rawHashAfter"
if ($rawHashBefore -ne $rawHashAfter) {
  throw "Raw E4 experiment rows changed; STOP"
}

$auditPath = ".\fibre_e1_e6_v2\evidence\FIBRE_V2_E1_E4_POSTPROCESS_CORRECTION.json"
$audit = Get-Content -LiteralPath $auditPath -Raw | ConvertFrom-Json
if (
  $audit.status -ne "pass" -or
  $audit.e1_e6_experiments_rerun -ne $false -or
  $audit.source_e4_raw_runs_unchanged -ne $true -or
  $audit.summary_ci_unit -ne "instance"
) {
  throw "Postprocess audit gate failed"
}

$e1 = Get-Content `
  ".\fibre_e1_e6_v2\results\e1_validation_summary.json" `
  -Raw | ConvertFrom-Json
if ($e1.selector_fibre_risk_guardrail -ne "enabled_in_frozen_v2") {
  throw "E1 fibre guardrail provenance was not corrected"
}

Import-Csv ".\fibre_e1_e6_v2\results\e4_warmstart_summary.csv" |
  Select-Object -First 8 family,representation,budget_mode,budget_value,budget_label,warm_start_policy,pair_closure,instance_count,ci_unit,ci_method |
  Format-Table -AutoSize

Select-String `
  -Path ".\fibre_e1_e6_v2\tables\table_e4_warmstart.tex" `
  -Pattern "p=|2Q=" |
  Select-Object -First 8

"E1/E4 POSTPROCESS GATE: PASS"
```

The summary/table must show concrete budget labels such as `p=1`, `p=2`,
`2Q=128`, or `2Q=256`; `ci_unit` must be `instance`.

## C. Rebuild the final result ZIP only

Move the previous ZIP outside the repository so the deterministic final-pack
builder can refuse accidental overwrites while preserving the old pack.

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$repo = (Resolve-Path ".").Path
$parent = Split-Path -Parent $repo
$recovery = Join-Path $parent "FIBRE_V2_PRE_POSTPROCESS_PACK_$stamp"
New-Item -ItemType Directory -Path $recovery -Force | Out-Null

$oldPackFiles = @(
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip"
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip.sha256"
)
foreach ($oldPack in $oldPackFiles) {
  if (Test-Path -LiteralPath $oldPack) {
    Move-Item -LiteralPath $oldPack -Destination $recovery
  }
}

"OLD PACK RECOVERY: $recovery"

python ".\run_fibre_e1_e6_v2.py" --step final
$finalExitCode = $LASTEXITCODE
"FINAL PACK EXIT CODE: $finalExitCode"
if ($finalExitCode -ne 0) {
  throw "Final result-pack rebuild failed"
}
```

This `--step final` command only rehashes existing artifacts and builds the ZIP;
it does not run E1--E6.

## D. Verify and commit the corrected result set

```powershell
$newPack = ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip"
$newSidecar = ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip.sha256"

$newHash = (
  Get-FileHash -LiteralPath $newPack -Algorithm SHA256
).Hash.ToLower()
$declaredHash = (Get-Content -LiteralPath $newSidecar -Raw).Trim().ToLower()

"NEW FINAL ZIP SHA256: $newHash"
"DECLARED SHA256:      $declaredHash"
if ($newHash -ne $declaredHash) {
  throw "Final ZIP hash mismatch"
}

$manifest = Import-Csv `
  ".\fibre_e1_e6_v2\PACKAGE_SHA256_MANIFEST.csv"
$manifestFailures = @()
foreach ($row in $manifest) {
  $path = Join-Path ".\fibre_e1_e6_v2" $row.path
  if (-not (Test-Path -LiteralPath $path)) {
    $manifestFailures += "MISSING: $($row.path)"
    continue
  }
  $actual = (
    Get-FileHash -LiteralPath $path -Algorithm SHA256
  ).Hash.ToLower()
  if ($actual -ne $row.sha256.ToLower()) {
    $manifestFailures += "HASH: $($row.path)"
  }
}
if ($manifestFailures.Count -ne 0) {
  $manifestFailures
  throw "Final package manifest verification failed"
}

git add -- `
  ".\fibre_e1_e6_v2" `
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip" `
  ".\URSS_FIBRE_E1_E6_V2_RESULT_PACK.zip.sha256"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Corrected result set has formatting errors"
}

git commit -m "Correct E4 summaries and E1 guardrail provenance"
if ($LASTEXITCODE -ne 0) {
  throw "Corrected result commit failed"
}

git --no-pager log -4 --oneline
git status
```

Required final state:

```text
Correct E4 summaries and E1 guardrail provenance
Add E1 E4 postprocessing correction
nothing to commit, working tree clean
```
