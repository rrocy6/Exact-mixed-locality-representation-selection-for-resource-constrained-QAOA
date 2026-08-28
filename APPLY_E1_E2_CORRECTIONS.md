# Apply the formal E1/E2 review corrections

This update is additive. It preserves the original E1 native/full results and
the original E2 all-to-all rows. It adds a nontrivial-selective E1 supplement,
repairs the 23 below-threshold witness exports, restores selector-validation in
the correction package, and rebuilds the sparse main comparison on the same 21
common-feasible instances.

The package deliberately records the current E1/E2/E3 selector as
`resource-only`. It does not invent an unfrozen fibre-risk rule.

## A. Preflight before extraction

Run from the repository root in the activated `.venv`:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$repository = (Get-Location).Path
"REPOSITORY: $repository"

$statusBefore = @(git status --porcelain)
if ($statusBefore.Count -ne 0) {
  $statusBefore
  throw "Working tree is not clean. Move untracked handoff/final-pack files outside the repository, then retry."
}

git --no-pager log -1 --format="LATEST COMMIT: %h %s"
```

Do not delete an untracked `handoff/` directory. Move it to a dated recovery
directory outside the repository if necessary.

## B. Verify and extract the ZIP

Adjust only `$zipPath` if the browser added a numeric suffix:

```powershell
$zipPath = Join-Path $env:USERPROFILE "Downloads\URSS_E1_E2_REVIEW_CORRECTIONS_2026-08-28.zip"
$sidecarPath = $zipPath + ".sha256"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Correction ZIP not found: $zipPath"
}

if (-not (Test-Path -LiteralPath $sidecarPath)) {
  throw "Correction ZIP SHA256 sidecar not found: $sidecarPath"
}

$expectedZipHash = (
  (Get-Content -LiteralPath $sidecarPath -Raw).Trim() -split "\s+"
)[0].ToLower()

$actualZipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()

"ZIP SHA256: $actualZipHash"
"ZIP HASH MATCH: $($actualZipHash -eq $expectedZipHash)"

if ($actualZipHash -ne $expectedZipHash) {
  throw "Correction ZIP hash mismatch"
}

Expand-Archive -LiteralPath $zipPath -DestinationPath . -Force

python -c "import csv,hashlib,pathlib,sys; root=pathlib.Path('.'); rows=list(csv.DictReader((root/'UPDATE_FILE_MANIFEST.csv').open(encoding='utf-8'))); bad=[r['path'] for r in rows if not (root/r['path']).is_file() or hashlib.sha256((root/r['path']).read_bytes()).hexdigest()!=r['sha256'] or (root/r['path']).stat().st_size!=int(r['size_bytes'])]; print('UPDATE FILE COUNT:',len(rows)); print('UPDATE HASH FAILURES:',len(bad)); sys.exit(1 if bad else 0)"

if ($LASTEXITCODE -ne 0) {
  throw "Extracted update-file manifest validation failed"
}

git status --short
```

Expected new files include:

```text
APPLY_E1_E2_CORRECTIONS.md
IMPACT_ON_E3_E6.md
IMPLEMENTATION_REPORT_E1_E2_CORRECTIONS.md
RUN_COMMANDS_E1_E2_CORRECTIONS.md
UPDATE_FILE_MANIFEST.csv
UPDATE_FILE_MANIFEST.sha256
patch_e1_witness_priority.py
run_e1_e2_corrections.py
tests/test_e1_e2_corrections.py
urss_pipeline/e1_e2_corrections.py
```

## C. Patch the witness-selection bug and test the implementation

```powershell
python ".\patch_e1_witness_priority.py" `
  --file ".\urss_pipeline\e1_exactness.py"

if ($LASTEXITCODE -ne 0) {
  throw "E1 witness-priority patch failed"
}

python -m unittest ".\tests\test_e1_e2_corrections.py" -v
$correctionTestExitCode = $LASTEXITCODE
"CORRECTION TEST EXIT CODE: $correctionTestExitCode"

if ($correctionTestExitCode -ne 0) {
  throw "Correction unit tests failed"
}

New-Item -ItemType Directory -Force ".\evidence" | Out-Null

$allTestOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_E1_E2_CORRECTIONS_WINDOWS.txt"
)
$allTestExitCode = $LASTEXITCODE
"ALL TEST EXIT CODE: $allTestExitCode"

if ($allTestExitCode -ne 0) {
  throw "Full regression failed"
}

if (($allTestOutput -join "`n") -notmatch "Ran 116 tests") {
  throw "Expected 116 tests after adding the 8 correction tests"
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
Ran 8 tests ... OK
Ran 116 tests ... OK
10 passed, 0 failed
```

## D. Commit the correction implementation before producing results

```powershell
git add -- `
  ".\APPLY_E1_E2_CORRECTIONS.md" `
  ".\IMPACT_ON_E3_E6.md" `
  ".\IMPLEMENTATION_REPORT_E1_E2_CORRECTIONS.md" `
  ".\RUN_COMMANDS_E1_E2_CORRECTIONS.md" `
  ".\UPDATE_FILE_MANIFEST.csv" `
  ".\UPDATE_FILE_MANIFEST.sha256" `
  ".\patch_e1_witness_priority.py" `
  ".\run_e1_e2_corrections.py" `
  ".\tests\test_e1_e2_corrections.py" `
  ".\urss_pipeline\e1_e2_corrections.py" `
  ".\urss_pipeline\e1_exactness.py"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Correction implementation has formatting errors"
}

git commit -m "Add E1 E2 review correction pipeline"

if ($LASTEXITCODE -ne 0) {
  throw "Correction implementation commit failed"
}

if (git status --porcelain) {
  throw "Implementation commit did not leave a clean worktree"
}
```

## E. Run the additive correction pipeline

The complete E1 supplement normally takes several minutes. No E2 recompilation
is performed.

```powershell
$correctionOutput = ".\corrections\e1_e2_v1"
$stagingOutput = ".\corrections\e1_e2_v1_building"

if (Test-Path -LiteralPath $correctionOutput) {
  throw "Correction output already exists; do not overwrite it"
}

if (Test-Path -LiteralPath $stagingOutput) {
  throw "Incomplete correction staging exists; move it to recovery before retrying"
}

$correctionArguments = @(
  ".\run_e1_e2_corrections.py"
  "--config"
  ".\configs\experiment_config_v1.yaml"
  "--config-hash"
  ".\configs\experiment_config_v1.sha256"
  "--data"
  ".\data"
  "--results"
  ".\results"
  "--output"
  $correctionOutput
  "--e3-source"
  ".\urss_pipeline\e3_qaoa.py"
)

python @correctionArguments 2>&1 |
  Tee-Object ".\evidence\E1_E2_CORRECTION_CONSOLE_WINDOWS.txt"

$correctionExitCode = $LASTEXITCODE
"CORRECTION EXIT CODE: $correctionExitCode"

if ($correctionExitCode -ne 0) {
  throw "E1/E2 correction failed; do not build a final pack"
}
```

Required console ending:

```text
"status": "pass"
E1/E2 CORRECTION GATE: pass
CORRECTION EXIT CODE: 0
```

## F. Verify the generated audit and hashes

```powershell
$auditPath = ".\corrections\e1_e2_v1\04_AUDIT\E1_E2_CORRECTION_AUDIT.json"
$audit = Get-Content -LiteralPath $auditPath -Raw | ConvertFrom-Json

if ($audit.status -ne "pass") {
  throw "Overall correction audit did not pass"
}

if (-not $audit.e1_correction_pass) {
  throw "E1 correction audit did not pass"
}

if (-not $audit.e2_correction_pass) {
  throw "E2 correction audit did not pass"
}

if ($audit.method_status -ne "resource_only_selector") {
  throw "Unexpected selector method status"
}

$e1 = Get-Content `
  ".\corrections\e1_e2_v1\01_E1_CORRECTION\e1_correction_validation_summary.json" `
  -Raw | ConvertFrom-Json

$e2 = Get-Content `
  ".\corrections\e1_e2_v1\02_E2_CORRECTION\e2_correction_validation_summary.json" `
  -Raw | ConvertFrom-Json

"E1 STATUS: $($e1.status)"
"E1 CONSTRUCTIBLE SPIN: $($e1.constructible_instance_count_by_family.cubic_spin_glass)"
"E1 CONSTRUCTIBLE MAX3SAT: $($e1.constructible_instance_count_by_family.max3sat)"
"E1 STRICT MISMATCH: $($e1.strict_mismatch_count)"
"E1 STRICT INCONSISTENT: $($e1.strict_inconsistent_minimiser_count)"
"E1 REPAIRED WITNESSES: $($e1.existing_below_witnesses_reexported_count)"
"E2 STATUS: $($e2.status)"
"E2 COMMON INSTANCES: $($e2.common_feasible_instance_count)"
"E2 SPARSE SCHEDULED: $($e2.sparse_scheduled_row_count)"
"E2 SPARSE INFEASIBLE: $($e2.sparse_infeasible_width_row_count)"
"SELECTOR ROWS: $($e2.selector_validation_row_count)"

if ($e1.strict_mismatch_count -ne 0) { throw "E1 strict mismatch" }
if ($e1.strict_inconsistent_minimiser_count -ne 0) { throw "E1 strict inconsistency" }
if ($e1.existing_below_witnesses_reexported_count -ne 23) { throw "Wrong repaired witness count" }
if ($e2.common_feasible_instance_count -ne 21) { throw "Wrong common-feasible count" }
if ($e2.sparse_scheduled_row_count -ne 7200) { throw "Wrong sparse scheduled count" }
if ($e2.sparse_infeasible_width_row_count -ne 3705) { throw "Wrong sparse capacity-failure count" }
if ($e2.selector_validation_row_count -ne 180) { throw "Wrong selector-validation count" }

python -c "import csv,hashlib,pathlib,sys; root=pathlib.Path(r'.\corrections\e1_e2_v1'); rows=list(csv.DictReader((root/'PACKAGE_SHA256_MANIFEST.csv').open(encoding='utf-8'))); bad=[r['path'] for r in rows if hashlib.sha256((root/r['path']).read_bytes()).hexdigest()!=r['sha256'] or (root/r['path']).stat().st_size!=int(r['size_bytes'])]; print('PACKAGE FILE COUNT:',len(rows)); print('PACKAGE HASH FAILURES:',len(bad)); sys.exit(1 if bad else 0)"

if ($LASTEXITCODE -ne 0) {
  throw "Correction package manifest validation failed"
}
```

## G. Visual gate for the revised E2 sparse figure

```powershell
$figurePath = (
  Resolve-Path `
    ".\corrections\e1_e2_v1\02_E2_CORRECTION\figure_e2_sparse_common_feasible.pdf"
).Path

Start-Process -FilePath $figurePath

$visualGate = Read-Host "Type PASS after checking all six panels"

if ($visualGate -cne "PASS") {
  throw "E2 correction PDF visual gate not confirmed"
}

$utf8 = [System.Text.UTF8Encoding]::new($false)
$evidenceLines = @(
  "correction_status=pass"
  "e1_strict_mismatch_count=0"
  "e1_strict_inconsistent_minimiser_count=0"
  "existing_below_witnesses_reexported_count=23"
  "e2_common_feasible_instance_count=21"
  "e2_sparse_scheduled_row_count=7200"
  "e2_sparse_infeasible_width_row_count=3705"
  "selector_validation_row_count=180"
  "method_status=resource_only_selector"
  "e2_pdf_visual_gate=pass"
)

[System.IO.File]::WriteAllLines(
  ".\evidence\E1_E2_CORRECTION_AUDIT_WINDOWS.txt",
  [string[]]$evidenceLines,
  $utf8
)
```

Confirm that both family rows appear in each metric column, bars and error bars
render, labels are readable, and no panel is blank. All main bars must use the
same common-feasible cohort; capacity failures belong only in the separate CSV.

## H. Commit the correction evidence

```powershell
git add -- `
  ".\corrections\e1_e2_v1" `
  ".\evidence\E1_E2_CORRECTION_AUDIT_WINDOWS.txt" `
  ".\evidence\E1_E2_CORRECTION_CONSOLE_WINDOWS.txt" `
  ".\evidence\TEST_OUTPUT_E1_E2_CORRECTIONS_WINDOWS.txt"

git diff --cached --check
if ($LASTEXITCODE -ne 0) {
  throw "Generated correction evidence has formatting errors"
}

git commit -m "Record E1 E2 review corrections"

if ($LASTEXITCODE -ne 0) {
  throw "Correction result commit failed"
}

git --no-pager log -3 --format="%h %s"
git status
```

Required final state:

```text
Record E1 E2 review corrections
Add E1 E2 review correction pipeline
nothing to commit, working tree clean
```

Do not build the final manuscript pack until `METHOD_STATUS_E3_E6.md` has been
used to label the existing selective results as resource-only, or a separately
specified fibre-aware selector has been frozen and its dependent branches
rerun.
