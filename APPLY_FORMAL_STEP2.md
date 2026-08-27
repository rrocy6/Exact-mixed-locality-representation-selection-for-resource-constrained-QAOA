# Apply and run formal Step 2

Run from the repository root in Windows PowerShell 5.1. Step 2 uses two commits so every generated row records the exact committed implementation that created it.

## A. Verify the completed Step 1 checkpoint

```powershell
git --no-pager log -1 --format="%h %s"
git status

python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.yaml

$actualConfigHash = (
  Get-FileHash .\configs\experiment_config_v1.yaml -Algorithm SHA256
).Hash.ToLower()

$storedConfigHash = (
  Get-Content .\configs\experiment_config_v1.sha256 -Raw
).Trim()

"CONFIG HASH MATCH: $($actualConfigHash -eq $storedConfigHash)"
```

Required:

```text
Freeze formal Step 1 experiment configuration
nothing to commit, working tree clean
declared_status: frozen
freeze_blocked: false
remaining_blocker_count: 0
CONFIG HASH MATCH: True
```

## B. Extract the update and run regression tests

Verify the delivery SHA-256, then extract the ZIP into the repository root.

```powershell
Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python .\run_pipeline_tests.py |
  Tee-Object .\evidence\TEST_OUTPUT_FORMAL_STEP2_WINDOWS.txt

$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not commit or generate formal data"
}

Push-Location .\golden_example
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
Ran 36 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## C. Commit the Step 2 implementation before generating data

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP2.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP2.md" `
  ".\RUN_COMMANDS_FORMAL_STEP2.md" `
  ".\configs\formal_data_generation_v1.json" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP2_WINDOWS.txt" `
  ".\run_formal_data_pipeline.py" `
  ".\tests\test_formal_data.py" `
  ".\tests\test_reference_pilot.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\formal_data.py" `
  ".\urss_pipeline\representations.py"

git diff --cached --check
git --no-pager diff --cached --stat

git commit -m "Add formal Step 2 data freeze pipeline"

git status
```

Do not run the formal pipeline until `nothing to commit, working tree clean` appears. The clean commit hash is embedded in every formal row.

## D. Run the formal data-freeze pipeline

Before running, the following paths must not exist:

```powershell
if (Test-Path .\data) {
  throw "data already exists; refusing overwrite"
}

if (Test-Path .\data_step2_building) {
  throw "An incomplete Step 2 staging directory exists; stop and inspect it"
}
```

Run without `Tee-Object` because the program verifies that the Git tree is clean before producing its first output:

```powershell
python .\run_formal_data_pipeline.py `
  --config .\configs\experiment_config_v1.yaml `
  --config-hash .\configs\experiment_config_v1.sha256 `
  --plan .\configs\formal_data_generation_v1.json `
  --smoke-config .\configs\smoke_config_v1.json `
  --schema .\instance_schema\instance_schema_v1.json `
  --output .\data `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md

$formalDataExitCode = $LASTEXITCODE
"FORMAL DATA EXIT CODE: $formalDataExitCode"

if ($formalDataExitCode -ne 0) {
  throw "Formal Step 2 failed; do not commit data"
}
```

Expected progress:

```text
SMOKE GATE: pass
GENERATED oracle/max3sat: 30/30 accepted
GENERATED oracle/cubic_spin_glass: 30/30 accepted
GENERATED qaoa/max3sat: 36/36 accepted
GENERATED qaoa/cubic_spin_glass: 36/36 accepted
GENERATED compilation/max3sat: 90/90 accepted
GENERATED compilation/cubic_spin_glass: 90/90 accepted
SPLITS AND NOISE SUBSET: frozen
GROUND TRUTH: complete for declared affordable widths
DATA FREEZE GATE: pass
FORMAL DATA EXIT CODE: 0
```

## E. Verify the audit and counts

```powershell
$auditPath = ".\data\benchmark_audit_v1.json"
$audit = Get-Content $auditPath -Raw | ConvertFrom-Json

$audit |
  Format-List `
    status,
    formal_instance_count,
    formal_manifests_created,
    formal_split_created,
    split_leakage_count,
    qmax,
    qmax_feasibility_failure_count,
    representation_split_consistent,
    validation_failure_count,
    test_split_frozen_before_results,
    formal_results_created,
    manifest_bundle_sha256

if ($audit.status -ne "pass") { throw "Audit failed" }
if ($audit.formal_instance_count -ne 312) { throw "Wrong instance count" }
if (-not $audit.formal_manifests_created) { throw "Manifests not frozen" }
if (-not $audit.formal_split_created) { throw "Split not frozen" }
if ($audit.split_leakage_count -ne 0) { throw "Split leakage detected" }
if ($audit.qmax -ne 12) { throw "Wrong Qmax" }
if ($audit.qmax_feasibility_failure_count -ne 0) { throw "Qmax failure" }
if ($audit.validation_failure_count -ne 0) { throw "Validation failure" }
if (-not $audit.test_split_frozen_before_results) { throw "Test not frozen" }
if ($audit.formal_results_created) { throw "Unexpected formal E1-E6 results" }

"ORACLE MAX3SAT: $($audit.manifest_counts.oracle.max3sat)"
"ORACLE SPIN:    $($audit.manifest_counts.oracle.cubic_spin_glass)"
"QAOA MAX3SAT:   $($audit.manifest_counts.qaoa.max3sat)"
"QAOA SPIN:      $($audit.manifest_counts.qaoa.cubic_spin_glass)"
"COMP MAX3SAT:   $($audit.manifest_counts.compilation.max3sat)"
"COMP SPIN:      $($audit.manifest_counts.compilation.cubic_spin_glass)"
"NOISE MAX3SAT:  $($audit.manifest_counts.noise_subset.max3sat)"
"NOISE SPIN:     $($audit.manifest_counts.noise_subset.cubic_spin_glass)"
```

Required counts per family are `30 / 36 / 90 / 9`.

## F. Verify every manifest hash

```powershell
$manifestFiles = Get-ChildItem `
  ".\data\manifests\*_v1.csv"

foreach ($manifest in $manifestFiles) {
  $sidecar = $manifest.FullName -replace '\.csv$', '.sha256'
  $actual = (
    Get-FileHash -LiteralPath $manifest.FullName -Algorithm SHA256
  ).Hash.ToLower()
  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim()
  "$($manifest.Name) HASH MATCH: $($actual -eq $declared)"
  if ($actual -ne $declared) {
    throw "Manifest hash mismatch: $($manifest.Name)"
  }
}

$bundlePath = ".\data\manifests\manifest_bundle_v1.json"
$bundleActual = (
  Get-FileHash $bundlePath -Algorithm SHA256
).Hash.ToLower()
$bundleDeclared = (
  Get-Content ".\data\manifests\manifest_bundle_v1.sha256" -Raw
).Trim()

"BUNDLE HASH MATCH: $($bundleActual -eq $bundleDeclared)"

if ($bundleActual -ne $bundleDeclared) {
  throw "Manifest bundle hash mismatch"
}
```

Every line and the bundle check must display `True`.

## G. Save the audit output and commit the frozen data

```powershell
Get-Content .\data\benchmark_audit_v1.json |
  Tee-Object .\evidence\FORMAL_STEP2_AUDIT_WINDOWS.txt

git diff --check
git status --short

git add -- `
  ".\RUN_COMMANDS.md" `
  ".\assumptions_and_decisions.md" `
  ".\data" `
  ".\evidence\FORMAL_STEP2_AUDIT_WINDOWS.txt"

git diff --cached --check
git --no-pager diff --cached --stat

git commit -m "Freeze formal Step 2 manifests"

git --no-pager log -5 --format="%h %s"
git status
```

Formal Step 2 is complete only when the data-freeze commit exists and the worktree is clean.
