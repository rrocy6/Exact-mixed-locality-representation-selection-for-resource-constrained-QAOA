# Apply formal Step 5 / E3

This update implements the frozen four-representation fair-QAOA comparison. Run every section in order from the repository root in the active Python 3.12 pilot environment.

## A. Prove formal Step 4 is complete before extraction

```powershell
$requiredE2 = @(
  ".\results\e2_logical_resources.csv"
  ".\results\e2_compiled_resources_by_seed.csv"
  ".\results\e2_compiled_resources_summary.csv"
  ".\results\selector_validation.csv"
  ".\results\e2_designs.json"
  ".\results\e2_validation_summary.json"
  ".\tables\table_e2_resources.tex"
  ".\figures\figure_e2_resources.pdf"
)

$missingE2 = @(
  $requiredE2 |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingE2.Count -ne 0) {
  "MISSING STEP 4 FILES:"
  $missingE2
  throw "Formal Step 4 outputs are incomplete"
}

foreach ($artifact in $requiredE2) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing Step 4 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLower()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLower()

  if ($actual -ne $declared) {
    throw "Step 4 hash mismatch: $artifact"
  }
}

$e2 = Get-Content `
  ".\results\e2_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e2Checks = @(
  ($e2.status -eq "pass")
  ($e2.e3_e6_may_continue -eq $true)
  ($e2.compilation_instance_count -eq 180)
  ($e2.logical_row_count -eq 1440)
  ($e2.compiled_raw_row_count -eq 14400)
  ($e2.compiled_summary_row_count -eq 1440)
  ($e2.selector_validation_row_count -eq 180)
  ($e2.unexpected_compiler_failure_count -eq 0)
  ($e2.instance_alignment_failure_count -eq 0)
  ($e2.topology_bundle_failure_count -eq 0)
  ($e2.seed_bundle_failure_count -eq 0)
  ($e2.compiler_protocol_failure_count -eq 0)
  ($e2.selector_test_retuning_count -eq 0)
)

if ($e2Checks -contains $false) {
  $e2 | ConvertTo-Json -Depth 10
  throw "Formal Step 4 E2 gate does not permit Step 5"
}

$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Complete formal Step 4 E2 resources") {
  throw "Step 4 result commit is missing or is not the current checkpoint"
}

$preApplyState = @(
  git status --porcelain=v1 --untracked-files=all
)

if ($preApplyState.Count -ne 0) {
  $preApplyState
  throw "Working tree is not clean; do not apply Step 5"
}

"STEP 4 COMPLETION GATE: PASS"
```

Required:

```text
STEP 4 COMPLETION GATE: PASS
```

## B. Verify and extract the Step 5 package

```powershell
$zipPath = Join-Path `
  "$env:USERPROFILE\Downloads" `
  "URSS_FORMAL_STEP5_E3_UPDATE_2026-08-27.zip"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Step 5 ZIP not found in Downloads"
}

$zipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLower()

"ZIP SHA256: $zipHash"

$expectedZipHash = (
  Read-Host "Paste the ZIP SHA256 from the Codex delivery message"
).Trim().ToLower()

if ($zipHash -ne $expectedZipHash) {
  throw "Step 5 ZIP hash mismatch; do not extract"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

$requiredImplementation = @(
  ".\APPLY_FORMAL_STEP5_E3.md"
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP5_E3.md"
  ".\RUN_COMMANDS_FORMAL_STEP5_E3.md"
  ".\run_e3_qaoa.py"
  ".\tests\test_e3_qaoa.py"
  ".\urss_pipeline\e3_qaoa.py"
)

$missingImplementation = @(
  $requiredImplementation |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingImplementation.Count -ne 0) {
  $missingImplementation
  throw "Step 5 package was not fully extracted"
}

git status --short --untracked-files=all
```

## C. Run the implementation regression gates

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python -m pip check

python -c "import numpy, scipy, qiskit, qiskit_aer, reportlab; print('numpy=' + numpy.__version__); print('scipy=' + scipy.__version__); print('qiskit=' + qiskit.__version__); print('qiskit_aer=' + qiskit_aer.__version__); print('reportlab=' + reportlab.Version)"

New-Item `
  -ItemType Directory `
  -Force `
  ".\evidence" |
  Out-Null

$testOutput = @(
  python ".\run_pipeline_tests.py" 2>&1 |
    Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP5_E3_WINDOWS.txt"
)

$testExitCode = $LASTEXITCODE
$testOutput
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 66 tests") {
  throw "Did not run the required 66 tests"
}

if (($testOutput -join "`n") -notmatch "(?m)^OK\s*$") {
  throw "The 66-test suite did not finish with OK"
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
Ran 66 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## D. Commit the Step 5 implementation checkpoint

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP5_E3.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP5_E3.md" `
  ".\RUN_COMMANDS_FORMAL_STEP5_E3.md" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP5_E3_WINDOWS.txt" `
  ".\run_e3_qaoa.py" `
  ".\tests\test_e3_qaoa.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\e3_qaoa.py"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Step 5 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Add formal Step 5 E3 fair QAOA pipeline"

git --no-pager log -1 --format="%h %s"
git status
```

Required:

```text
Add formal Step 5 E3 fair QAOA pipeline
nothing to commit, working tree clean
```

## E. Run formal E3 from the clean implementation commit

Do not use `Tee-Object` on this command. Creating an evidence file before the program checks Git would make the working tree dirty. Do not interrupt merely because one dense instance takes longer.

```powershell
$formalTargets = @(
  ".\results\e3_qaoa_runs.csv"
  ".\results\e3_qaoa_summary.csv"
  ".\results\e3_budget_plan.csv"
  ".\results\e3_validation_summary.json"
  ".\tables\table_e3_qaoa.tex"
  ".\figures\figure_e3_equal_layer.pdf"
  ".\figures\figure_e3_equal_2q_budget.pdf"
  ".\e3_step5_building"
)

$existingTargets = @(
  $formalTargets |
    Where-Object { Test-Path -LiteralPath $_ }
)

if ($existingTargets.Count -ne 0) {
  $existingTargets
  throw "Formal E3 target or staging path already exists; inspect it and do not overwrite"
}

if (git status --porcelain) {
  throw "Formal E3 requires a clean implementation commit"
}

python ".\run_e3_qaoa.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"

$e3ExitCode = $LASTEXITCODE
"E3 EXIT CODE: $e3ExitCode"

if ($e3ExitCode -ne 0) {
  throw "Formal E3 failed; do not continue to E4-E6"
}
```

The program prints progress after each of the 14 frozen test instances. A `p=0` row under the 128-gate budget is a declared maximum-feasible-depth result when one compiled layer costs more than 128 gates; it is not an omitted run and must not be changed to `p=1`.

## F. Validate every E3 artifact and fairness gate

```powershell
$e3Summary = Get-Content `
  ".\results\e3_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e3Summary | ConvertTo-Json -Depth 10

$e3Checks = @(
  ($e3Summary.status -eq "pass")
  ($e3Summary.e4_e6_may_continue -eq $true)
  ($e3Summary.frozen_test_instance_count -eq 14)
  ($e3Summary.representation_family_count -eq 4)
  ($e3Summary.matched_random_seed_count -eq 5)
  ($e3Summary.scheduled_design_count -eq 112)
  ($e3Summary.budget_plan_row_count -eq 112)
  ($e3Summary.run_row_count -eq 1344)
  ($e3Summary.summary_row_count -eq 32)
  ($e3Summary.failed_run_count -eq 0)
  ($e3Summary.objective_evaluations_per_restart -eq 60)
  ($e3Summary.restarts_per_design_budget -eq 3)
  ($e3Summary.primary_score -eq "original_family_objective")
  ($e3Summary.missing_restart_group_count -eq 0)
  ($e3Summary.evaluation_budget_mismatch_count -eq 0)
  ($e3Summary.seed_policy_mismatch_count -eq 0)
  ($e3Summary.initial_parameter_reuse_group_count -eq 0)
  ($e3Summary.compiled_budget_exceed_count -eq 0)
  ($e3Summary.non_original_primary_score_count -eq 0)
  ($e3Summary.best_only_or_missing_budget_group_count -eq 0)
)

if ($e3Checks -contains $false) {
  throw "Formal E3 fairness gate failed"
}

$runs = @(
  Import-Csv ".\results\e3_qaoa_runs.csv"
)

$summaryRows = @(
  Import-Csv ".\results\e3_qaoa_summary.csv"
)

$budgetRows = @(
  Import-Csv ".\results\e3_budget_plan.csv"
)

"RUN ROWS: $($runs.Count)"
"SUMMARY ROWS: $($summaryRows.Count)"
"BUDGET PLAN ROWS: $($budgetRows.Count)"

$evaluationMismatch = @(
  $runs |
    Where-Object {
      [int]$_.evaluations -ne 60 -or
      [int]$_.evaluation_budget -ne 60
    }
)

$budgetExceeds = @(
  $runs |
    Where-Object {
      $_.budget_mode -eq "equal_compiled_two_qubit_gates" -and
      [int]$_.actual_2q_gates -gt [int]$_.compiled_2q_budget
    }
)

$wrongPrimaryScore = @(
  $runs |
    Where-Object {
      $_.objective_scoring -ne
        "original_family_objective_projected_from_statevector"
    }
)

if (
  $runs.Count -ne 1344 -or
  $summaryRows.Count -ne 32 -or
  $budgetRows.Count -ne 112 -or
  $evaluationMismatch.Count -ne 0 -or
  $budgetExceeds.Count -ne 0 -or
  $wrongPrimaryScore.Count -ne 0
) {
  throw "Formal E3 raw-row validation failed"
}

$e3Artifacts = @(
  ".\results\e3_qaoa_runs.csv"
  ".\results\e3_qaoa_summary.csv"
  ".\results\e3_budget_plan.csv"
  ".\results\e3_validation_summary.json"
  ".\tables\table_e3_qaoa.tex"
  ".\figures\figure_e3_equal_layer.pdf"
  ".\figures\figure_e3_equal_2q_budget.pdf"
)

foreach ($artifact in $e3Artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing E3 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLower()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLower()

  if ($actual -ne $declared) {
    throw "E3 hash mismatch: $artifact"
  }
}

"E3 HASH GATE: PASS"
```

Open both PDFs:

```powershell
Start-Process (
  Resolve-Path ".\figures\figure_e3_equal_layer.pdf"
).Path

Start-Process (
  Resolve-Path ".\figures\figure_e3_equal_2q_budget.pdf"
).Path
```

Confirm that each PDF has two visible panels, readable titles/labels, no clipping, no overlap, no black squares, and no missing fonts.

```powershell
$visual = Read-Host "Both E3 PDFs render correctly? Enter YES"

if ($visual -cne "YES") {
  throw "E3 PDF visual validation failed"
}

"E3 PDF VISUAL GATE: PASS"
```

Create the Windows audit evidence only after all gates pass:

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false)

$auditLines = @(
  "formal_step=5"
  "experiment=E3_fair_QAOA"
  "status=$($e3Summary.status)"
  "e4_e6_may_continue=$($e3Summary.e4_e6_may_continue)"
  "test_instances=$($e3Summary.frozen_test_instance_count)"
  "scheduled_designs=$($e3Summary.scheduled_design_count)"
  "run_rows=$($e3Summary.run_row_count)"
  "summary_rows=$($e3Summary.summary_row_count)"
  "failed_runs=$($e3Summary.failed_run_count)"
  "zero_layer_budget_runs=$($e3Summary.zero_layer_budget_run_count)"
  "compiled_budget_exceeds=$($e3Summary.compiled_budget_exceed_count)"
  "evaluation_mismatches=$($e3Summary.evaluation_budget_mismatch_count)"
  "primary_score=$($e3Summary.primary_score)"
  "pdf_visual_gate=pass"
)

[System.IO.File]::WriteAllLines(
  ".\evidence\FORMAL_STEP5_E3_AUDIT_WINDOWS.txt",
  [string[]]$auditLines,
  $utf8
)

git diff --check

if ($LASTEXITCODE -ne 0) {
  throw "Generated E3 files have formatting errors"
}
```

## G. Commit the formal Step 5 results

```powershell
git add -- `
  ".\results\e3_qaoa_runs.csv" `
  ".\results\e3_qaoa_runs.sha256" `
  ".\results\e3_qaoa_summary.csv" `
  ".\results\e3_qaoa_summary.sha256" `
  ".\results\e3_budget_plan.csv" `
  ".\results\e3_budget_plan.sha256" `
  ".\results\e3_validation_summary.json" `
  ".\results\e3_validation_summary.sha256" `
  ".\tables\table_e3_qaoa.tex" `
  ".\tables\table_e3_qaoa.sha256" `
  ".\figures\figure_e3_equal_layer.pdf" `
  ".\figures\figure_e3_equal_layer.sha256" `
  ".\figures\figure_e3_equal_2q_budget.pdf" `
  ".\figures\figure_e3_equal_2q_budget.sha256" `
  ".\evidence\FORMAL_STEP5_E3_AUDIT_WINDOWS.txt" `
  ".\assumptions_and_decisions.md" `
  ".\RUN_COMMANDS.md"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "E3 result files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Complete formal Step 5 E3 fair QAOA"

git --no-pager log -4 --format="%h %s"
git status
```

Final required Git state:

```text
Complete formal Step 5 E3 fair QAOA
Add formal Step 5 E3 fair QAOA pipeline
Complete formal Step 4 E2 resources
nothing to commit, working tree clean
```

Formal Step 5 is complete only when the JSON gate, raw-row checks, hash checks, both visual PDF checks, result commit, and clean worktree all pass. Only then may Step 6 / E4 begin.
