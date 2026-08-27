# Apply and run formal Step 4 / E2

Run every command from the repository root in Windows PowerShell 5.1. Formal
E2 uses two commits: first the clean implementation and reporting dependency,
then the immutable result artifacts.

## A. Verify the completed Step 3 checkpoint

```powershell
git --no-pager log -5 --format="%h %s"
git status

$e1 = Get-Content ".\results\e1_validation_summary.json" -Raw |
  ConvertFrom-Json

if ($e1.status -ne "pass") { throw "Formal E1 did not pass" }
if (-not $e1.e2_e6_may_continue) { throw "Formal E1 blocks E2" }
if ($e1.strict_mismatch_count -ne 0) { throw "E1 strict mismatch" }
if ($e1.strict_inconsistent_minimiser_count -ne 0) {
  throw "E1 inconsistent minimiser"
}

if (git status --porcelain) {
  throw "Step 3 checkpoint is not clean"
}
```

Required latest result checkpoint:

```text
Complete formal Step 3 E1 exactness
nothing to commit, working tree clean
```

## B. Extract the update and install the reporting dependency

Verify the delivery SHA-256 supplied with the ZIP, then extract into the
repository root. Run:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python -m pip install -r ".\requirements-pilot.in"
python -m pip check

$reportlabVersion = python -c `
  "import reportlab; print(reportlab.Version)"

"REPORTLAB VERSION: $reportlabVersion"

if ($reportlabVersion.Trim() -ne "4.4.9") {
  throw "Expected ReportLab 4.4.9"
}
```

Refresh the environment records because ReportLab, Pillow, and
charset-normalizer are now formal reporting dependencies:

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false)
$freeze = [string[]](& python -m pip freeze)
if ($LASTEXITCODE -ne 0) { throw "pip freeze failed" }

[System.IO.File]::WriteAllLines(
  ".\requirements-pilot-lock.txt",
  $freeze,
  $utf8
)

$cpu = Get-CimInstance Win32_Processor
$computer = Get-CimInstance Win32_ComputerSystem
$versions = [string[]](
  & python -c "import numpy, qiskit, qiskit_aer, reportlab, scipy; print('numpy=' + numpy.__version__); print('qiskit=' + qiskit.__version__); print('qiskit_aer=' + qiskit_aer.__version__); print('scipy=' + scipy.__version__); print('reportlab=' + reportlab.Version)"
)

$snapshot = @(
  "snapshot_utc=$([DateTime]::UtcNow.ToString('o'))"
  "python_version=$(& python -c 'import platform; print(platform.python_version())')"
  "python_implementation=$(& python -c 'import platform; print(platform.python_implementation())')"
  "python_executable_relative=.venv/Scripts/python.exe"
  "pip_version=$(& python -c 'import pip; print(pip.__version__)')"
  "git=$(& git --version)"
  "cpu=$($cpu.Name.Trim())"
  "physical_cores=$($cpu.NumberOfCores)"
  "logical_processors=$($cpu.NumberOfLogicalProcessors)"
  "ram_gb=$([math]::Round($computer.TotalPhysicalMemory / 1GB, 1))"
  ""
  "formal_stack:"
) + $versions + @(
  ""
  "pip_freeze:"
) + $freeze

[System.IO.File]::WriteAllLines(
  ".\configs\environment_snapshot_v1.txt",
  [string[]]$snapshot,
  $utf8
)
```

## C. Run 54 regressions and Golden tests

```powershell
New-Item -ItemType Directory -Force ".\evidence" | Out-Null

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP4_E2_WINDOWS.txt"
)
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) { throw "Regression tests failed" }
if (($testOutput -join "`n") -notmatch "Ran 54 tests") {
  throw "Did not run the required 54 tests"
}

Push-Location ".\golden_example"
python ".\run_tests.py"
$goldenExitCode = $LASTEXITCODE
Pop-Location
"GOLDEN EXIT CODE: $goldenExitCode"
if ($goldenExitCode -ne 0) { throw "Golden regression failed" }
```

Required: `Ran 54 tests`, `OK`, test exit `0`, and Golden `10 passed`.

## D. Commit the E2 implementation before the formal run

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP4_E2.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP4_E2.md" `
  ".\RUN_COMMANDS_FORMAL_STEP4_E2.md" `
  ".\configs\environment_snapshot_v1.txt" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP4_E2_WINDOWS.txt" `
  ".\requirements-pilot.in" `
  ".\requirements-pilot-lock.txt" `
  ".\run_e2_resources.py" `
  ".\tests\test_e2_resources.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\e2_resources.py"

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Add formal Step 4 E2 resource pipeline"
git status
```

Do not run E2 until Git reports `nothing to commit, working tree clean`.

## E. Run formal E2

The following targets must not already exist:

```powershell
$targets = @(
  ".\results\e2_logical_resources.csv"
  ".\results\e2_compiled_resources_by_seed.csv"
  ".\results\e2_compiled_resources_summary.csv"
  ".\results\selector_validation.csv"
  ".\results\e2_designs.json"
  ".\results\e2_validation_summary.json"
  ".\tables\table_e2_resources.tex"
  ".\figures\figure_e2_resources.pdf"
  ".\e2_step4_building"
)

foreach ($target in $targets) {
  if (Test-Path -LiteralPath $target) {
    throw "Existing E2 target; refusing overwrite: $target"
  }
}
```

Run without `Tee-Object`. The full 180-instance run can take roughly one to
two hours on the recorded workstation. Progress is printed every five
instances. Do not interrupt a live process merely because one dense selector
instance takes tens of seconds.

```powershell
python .\run_e2_resources.py `
  --config .\configs\experiment_config_v1.yaml `
  --config-hash .\configs\experiment_config_v1.sha256 `
  --data .\data `
  --results .\results `
  --tables .\tables `
  --figures .\figures `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md

$e2ExitCode = $LASTEXITCODE
"E2 EXIT CODE: $e2ExitCode"
if ($e2ExitCode -ne 0) {
  throw "Formal E2 failed; do not continue to E3-E6"
}
```

Required final lines:

```text
E2 RESOURCE GATE: pass
E2 EXIT CODE: 0
```

## F. Verify the E2 gate and every hash

```powershell
$summary = Get-Content ".\results\e2_validation_summary.json" -Raw |
  ConvertFrom-Json

$summary | Format-List `
  status, `
  compilation_instance_count, `
  logical_row_count, `
  compiled_raw_row_count, `
  compiled_summary_row_count, `
  selector_validation_row_count, `
  expected_sparse_width_infeasible_row_count, `
  unexpected_compiler_failure_count, `
  instance_alignment_failure_count, `
  topology_bundle_failure_count, `
  seed_bundle_failure_count, `
  compiler_protocol_failure_count, `
  selector_test_retuning_count, `
  e3_e6_may_continue

if ($summary.status -ne "pass") { throw "E2 summary failed" }
if ($summary.compilation_instance_count -ne 180) { throw "Wrong instance count" }
if ($summary.logical_row_count -ne 1440) { throw "Wrong logical row count" }
if ($summary.compiled_raw_row_count -ne 14400) { throw "Wrong raw row count" }
if ($summary.compiled_summary_row_count -ne 1440) { throw "Wrong summary row count" }
if ($summary.selector_validation_row_count -ne 180) { throw "Wrong selector row count" }
if ($summary.unexpected_compiler_failure_count -ne 0) { throw "Unexpected compiler failure" }
if ($summary.instance_alignment_failure_count -ne 0) { throw "Instance mismatch" }
if ($summary.topology_bundle_failure_count -ne 0) { throw "Topology mismatch" }
if ($summary.seed_bundle_failure_count -ne 0) { throw "Seed mismatch" }
if ($summary.compiler_protocol_failure_count -ne 0) { throw "Compiler protocol mismatch" }
if ($summary.selector_test_retuning_count -ne 0) { throw "Selector retuned on test" }
if (-not $summary.e3_e6_may_continue) { throw "E3-E6 continuation blocked" }
```

Expected sparse-width infeasible rows are allowed and must be greater than
zero; they document the frozen 12-qubit device capacity.

```powershell
if ($summary.expected_sparse_width_infeasible_row_count -le 0) {
  throw "Expected frozen sparse-capacity records are missing"
}

$artifacts = @(
  ".\results\e2_logical_resources.csv"
  ".\results\e2_compiled_resources_by_seed.csv"
  ".\results\e2_compiled_resources_summary.csv"
  ".\results\selector_validation.csv"
  ".\results\e2_designs.json"
  ".\results\e2_validation_summary.json"
  ".\tables\table_e2_resources.tex"
  ".\figures\figure_e2_resources.pdf"
)

foreach ($artifact in $artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension($artifact, ".sha256")
  $actual = (Get-FileHash $artifact -Algorithm SHA256).Hash.ToLower()
  $declared = (Get-Content $sidecar -Raw).Trim()
  "$artifact HASH MATCH: $($actual -eq $declared)"
  if ($actual -ne $declared) { throw "Hash mismatch: $artifact" }
}
```

Open `figures/figure_e2_resources.pdf` and confirm all four panels render.

## G. Save the audit and commit E2 results

```powershell
Get-Content ".\results\e2_validation_summary.json" |
  Tee-Object ".\evidence\FORMAL_STEP4_E2_AUDIT_WINDOWS.txt"

git diff --check
git status --short

git add -- `
  ".\RUN_COMMANDS.md" `
  ".\assumptions_and_decisions.md" `
  ".\evidence\FORMAL_STEP4_E2_AUDIT_WINDOWS.txt" `
  ".\results" `
  ".\tables\table_e2_resources.tex" `
  ".\tables\table_e2_resources.sha256" `
  ".\figures\figure_e2_resources.pdf" `
  ".\figures\figure_e2_resources.sha256"

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Complete formal Step 4 E2 resources"

git --no-pager log -7 --format="%h %s"
git status
```

Formal Step 4 / E2 is complete only when the result commit exists, the
worktree is clean, and `e3_e6_may_continue` is `true`.
