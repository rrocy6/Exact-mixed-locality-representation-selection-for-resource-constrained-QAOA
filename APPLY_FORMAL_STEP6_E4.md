# Apply formal Step 6 / E4

Run every section in order from the repository root in the active frozen Python 3.12 environment.

## A. Prove formal Step 5 is complete before extraction

```powershell
$requiredE3 = @(
  ".\results\e3_qaoa_runs.csv"
  ".\results\e3_qaoa_summary.csv"
  ".\results\e3_budget_plan.csv"
  ".\results\e3_validation_summary.json"
  ".\tables\table_e3_qaoa.tex"
  ".\figures\figure_e3_equal_layer.pdf"
  ".\figures\figure_e3_equal_2q_budget.pdf"
)

$missingE3 = @(
  $requiredE3 |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingE3.Count -ne 0) {
  "MISSING STEP 5 FILES:"
  $missingE3
  throw "Formal Step 5 outputs are incomplete"
}

foreach ($artifact in $requiredE3) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing Step 5 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLowerInvariant()

  if ($actual -ne $declared) {
    throw "Step 5 hash mismatch: $artifact"
  }
}

$e3 = Get-Content `
  ".\results\e3_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e3Checks = @(
  ($e3.status -eq "pass")
  ($e3.e4_e6_may_continue -eq $true)
  ($e3.frozen_test_instance_count -eq 14)
  ($e3.representation_family_count -eq 4)
  ($e3.matched_random_seed_count -eq 5)
  ($e3.scheduled_design_count -eq 112)
  ($e3.budget_plan_row_count -eq 112)
  ($e3.run_row_count -eq 1344)
  ($e3.summary_row_count -eq 32)
  ($e3.failed_run_count -eq 0)
  ($e3.objective_evaluations_per_restart -eq 60)
  ($e3.restarts_per_design_budget -eq 3)
  ($e3.primary_score -eq "original_family_objective")
  ($e3.missing_restart_group_count -eq 0)
  ($e3.evaluation_budget_mismatch_count -eq 0)
  ($e3.seed_policy_mismatch_count -eq 0)
  ($e3.initial_parameter_reuse_group_count -eq 0)
  ($e3.compiled_budget_exceed_count -eq 0)
  ($e3.non_original_primary_score_count -eq 0)
  ($e3.best_only_or_missing_budget_group_count -eq 0)
)

if ($e3Checks -contains $false) {
  $e3 | ConvertTo-Json -Depth 10
  throw "Formal Step 5 E3 gate does not permit Step 6"
}

$runs = @(Import-Csv ".\results\e3_qaoa_runs.csv")
$budgets = @(Import-Csv ".\results\e3_budget_plan.csv")
$summaries = @(Import-Csv ".\results\e3_qaoa_summary.csv")

if (
  $runs.Count -ne 1344 -or
  $budgets.Count -ne 112 -or
  $summaries.Count -ne 32
) {
  throw "Step 5 raw-row counts disagree with its audit"
}

$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Complete formal Step 5 E3 fair QAOA") {
  throw "Step 5 result commit is missing or is not the current checkpoint"
}

$preApplyState = @(
  git status --porcelain=v1 --untracked-files=all
)

if ($preApplyState.Count -ne 0) {
  $preApplyState
  throw "Working tree is not clean; do not apply Step 6"
}

"STEP 5 COMPLETION GATE: PASS"
```

Required:

```text
STEP 5 COMPLETION GATE: PASS
```

## B. Verify and extract the Step 6 package

```powershell
$zipPath = Join-Path `
  "$env:USERPROFILE\Downloads" `
  "URSS_FORMAL_STEP6_E4_UPDATE_2026-08-27.zip"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Step 6 ZIP not found in Downloads"
}

$zipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLowerInvariant()

"ZIP SHA256: $zipHash"

$expectedZipHash = (
  Read-Host "Paste the ZIP SHA256 from the Codex delivery message"
).Trim().ToLowerInvariant()

if ($zipHash -ne $expectedZipHash) {
  throw "Step 6 ZIP hash mismatch; do not extract"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

$requiredImplementation = @(
  ".\APPLY_FORMAL_STEP6_E4.md"
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP6_E4.md"
  ".\RUN_COMMANDS_FORMAL_STEP6_E4.md"
  ".\run_e4_warmstart.py"
  ".\tests\test_e4_warmstart.py"
  ".\urss_pipeline\e4_warmstart.py"
)

$missingImplementation = @(
  $requiredImplementation |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingImplementation.Count -ne 0) {
  $missingImplementation
  throw "Step 6 package was not fully extracted"
}

git status --short --untracked-files=all
```

## C. Run all implementation regression gates

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
    Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP6_E4_WINDOWS.txt"
)

$testExitCode = $LASTEXITCODE
$testOutput
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 78 tests") {
  throw "Did not run the required 78 tests"
}

if (($testOutput -join "`n") -notmatch "(?m)^OK\s*$") {
  throw "The 78-test suite did not finish with OK"
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
Ran 78 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## D. Commit the Step 6 implementation checkpoint

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP6_E4.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP6_E4.md" `
  ".\RUN_COMMANDS_FORMAL_STEP6_E4.md" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP6_E4_WINDOWS.txt" `
  ".\run_e4_warmstart.py" `
  ".\tests\test_e4_warmstart.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\e4_warmstart.py"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Step 6 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Add formal Step 6 E4 warm-start pipeline"

git --no-pager log -1 --format="%h %s"
git status
```

Required:

```text
Add formal Step 6 E4 warm-start pipeline
nothing to commit, working tree clean
```

## E. Run formal E4 from the clean implementation commit

Do not use `Tee-Object` on this command. Do not interrupt a dense instance.

```powershell
$formalTargets = @(
  ".\results\e4_warmstart_runs.csv"
  ".\results\e4_marginal_diagnostics.csv"
  ".\results\e4_warmstart_summary.csv"
  ".\results\e4_validation_summary.json"
  ".\tables\table_e4_warmstart.tex"
  ".\figures\figure_e4_marginals.pdf"
  ".\e4_step6_building"
)

$existingTargets = @(
  $formalTargets |
    Where-Object { Test-Path -LiteralPath $_ }
)

if ($existingTargets.Count -ne 0) {
  $existingTargets
  throw "Formal E4 target or staging path already exists; do not overwrite"
}

if (git status --porcelain) {
  throw "Formal E4 requires a clean implementation commit"
}

python ".\run_e4_warmstart.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"

$e4ExitCode = $LASTEXITCODE
"E4 EXIT CODE: $e4ExitCode"

if ($e4ExitCode -ne 0) {
  throw "Formal E4 failed; do not continue to E5-E6"
}
```

## F. Validate every E4 artifact and protocol gate

```powershell
$e4 = Get-Content `
  ".\results\e4_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e4 | ConvertTo-Json -Depth 10

$e4Checks = @(
  ($e4.status -eq "pass")
  ($e4.e5_e6_may_continue -eq $true)
  ($e4.frozen_test_instance_count -eq 14)
  ($e4.scheduled_design_count -eq 112)
  ($e4.active_auxiliary_design_count -eq 20)
  ($e4.relaxation_optimal_instance_count -eq 14)
  ($e4.marginal_diagnostic_row_count -eq 388)
  ($e4.expected_marginal_diagnostic_row_count -eq 388)
  ($e4.missing_marginal_count -eq 0)
  ($e4.original_marginal_row_count -eq 96)
  ($e4.pair_marginal_row_count -eq 292)
  ($e4.warmstart_run_row_count -eq 3168)
  ($e4.expected_run_row_count -eq 3168)
  ($e4.cold_run_row_count -eq 1344)
  ($e4.original_only_run_row_count -eq 1344)
  ($e4.pair_moment_run_row_count -eq 240)
  ($e4.independence_ablation_run_row_count -eq 240)
  ($e4.summary_row_count -eq 96)
  ($e4.failed_run_count -eq 0)
  ($e4.run_row_count_mismatch -eq 0)
  ($e4.missing_restart_group_count -eq 0)
  ($e4.evaluation_budget_mismatch_count -eq 0)
  ($e4.seed_policy_mismatch_count -eq 0)
  ($e4.compiled_budget_exceed_count -eq 0)
  ($e4.non_original_primary_score_count -eq 0)
  ($e4.illegal_warmstart_variant_count -eq 0)
  ($e4.zero_auxiliary_duplicate_count -eq 0)
  ($e4.cold_e3_reproduction_mismatch_count -eq 0)
  ($e4.primary_score -eq "original_family_objective")
  ($e4.primary_relaxation -eq "SA_RLT_level_2_pair_moments")
  ($e4.only_relaxation_ablation -eq "independence_mu_product")
  ($e4.zero_auxiliary_variants_deduplicated -eq $true)
)

if ($e4Checks -contains $false) {
  throw "Formal E4 validation gate failed"
}

$e4Runs = @(Import-Csv ".\results\e4_warmstart_runs.csv")
$marginals = @(Import-Csv ".\results\e4_marginal_diagnostics.csv")
$e4SummaryRows = @(Import-Csv ".\results\e4_warmstart_summary.csv")

$evaluationMismatches = @(
  $e4Runs |
    Where-Object {
      [int]$_.evaluations -ne 60 -or
      [int]$_.evaluation_budget -ne 60
    }
)

$budgetExceeds = @(
  $e4Runs |
    Where-Object {
      $_.budget_mode -eq "equal_compiled_two_qubit_gates" -and
      [int]$_.actual_2q_gates -gt [int]$_.compiled_2q_budget
    }
)

$wrongScore = @(
  $e4Runs |
    Where-Object {
      $_.objective_scoring -ne
        "original_family_objective_projected_from_statevector"
    }
)

$zeroAuxDuplicates = @(
  $e4Runs |
    Where-Object {
      [int]$_.n_aux -eq 0 -and
      $_.warm_start_policy -eq "original_and_auxiliary_variables"
    }
)

if (
  $e4Runs.Count -ne 3168 -or
  $marginals.Count -ne 388 -or
  $e4SummaryRows.Count -ne 96 -or
  $evaluationMismatches.Count -ne 0 -or
  $budgetExceeds.Count -ne 0 -or
  $wrongScore.Count -ne 0 -or
  $zeroAuxDuplicates.Count -ne 0
) {
  throw "Formal E4 raw-row validation failed"
}

$e4Artifacts = @(
  ".\results\e4_warmstart_runs.csv"
  ".\results\e4_marginal_diagnostics.csv"
  ".\results\e4_warmstart_summary.csv"
  ".\results\e4_validation_summary.json"
  ".\tables\table_e4_warmstart.tex"
  ".\figures\figure_e4_marginals.pdf"
)

foreach ($artifact in $e4Artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing E4 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLowerInvariant()

  if ($actual -ne $declared) {
    throw "E4 hash mismatch: $artifact"
  }
}

"E4 HASH GATE: PASS"
```

Open the PDF:

```powershell
Start-Process (
  Resolve-Path ".\figures\figure_e4_marginals.pdf"
).Path
```

Confirm that the page has two visible panels, readable titles/axes/legends, no clipping, no overlap, no black squares, and no missing fonts.

```powershell
$visual = Read-Host "E4 marginal PDF renders correctly? Enter YES"

if ($visual -cne "YES") {
  throw "E4 PDF visual validation failed"
}

"E4 PDF VISUAL GATE: PASS"
```

Create the Windows audit evidence only after every gate passes:

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false)

$auditLines = @(
  "formal_step=6"
  "experiment=E4_warmstart_and_relaxation_ablation"
  "status=$($e4.status)"
  "e5_e6_may_continue=$($e4.e5_e6_may_continue)"
  "test_instances=$($e4.frozen_test_instance_count)"
  "scheduled_designs=$($e4.scheduled_design_count)"
  "active_auxiliary_designs=$($e4.active_auxiliary_design_count)"
  "optimal_relaxations=$($e4.relaxation_optimal_instance_count)"
  "run_rows=$($e4.warmstart_run_row_count)"
  "marginal_rows=$($e4.marginal_diagnostic_row_count)"
  "summary_rows=$($e4.summary_row_count)"
  "weak_signal_instances=$($e4.weak_signal_instance_count)"
  "cold_e3_mismatches=$($e4.cold_e3_reproduction_mismatch_count)"
  "failed_runs=$($e4.failed_run_count)"
  "evaluation_mismatches=$($e4.evaluation_budget_mismatch_count)"
  "seed_mismatches=$($e4.seed_policy_mismatch_count)"
  "budget_exceeds=$($e4.compiled_budget_exceed_count)"
  "zero_auxiliary_duplicates=$($e4.zero_auxiliary_duplicate_count)"
  "primary_score=$($e4.primary_score)"
  "primary_relaxation=$($e4.primary_relaxation)"
  "only_ablation=$($e4.only_relaxation_ablation)"
  "pdf_visual_gate=pass"
)

[System.IO.File]::WriteAllLines(
  ".\evidence\FORMAL_STEP6_E4_AUDIT_WINDOWS.txt",
  [string[]]$auditLines,
  $utf8
)

git diff --check

if ($LASTEXITCODE -ne 0) {
  throw "Generated E4 files have formatting errors"
}
```

## G. Commit the formal Step 6 results

```powershell
git add -- `
  ".\results\e4_warmstart_runs.csv" `
  ".\results\e4_warmstart_runs.sha256" `
  ".\results\e4_marginal_diagnostics.csv" `
  ".\results\e4_marginal_diagnostics.sha256" `
  ".\results\e4_warmstart_summary.csv" `
  ".\results\e4_warmstart_summary.sha256" `
  ".\results\e4_validation_summary.json" `
  ".\results\e4_validation_summary.sha256" `
  ".\tables\table_e4_warmstart.tex" `
  ".\tables\table_e4_warmstart.sha256" `
  ".\figures\figure_e4_marginals.pdf" `
  ".\figures\figure_e4_marginals.sha256" `
  ".\evidence\FORMAL_STEP6_E4_AUDIT_WINDOWS.txt" `
  ".\assumptions_and_decisions.md" `
  ".\RUN_COMMANDS.md"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "E4 result files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Complete formal Step 6 E4 warm-start ablation"

git --no-pager log -4 --format="%h %s"
git status
```

Final required Git state:

```text
Complete formal Step 6 E4 warm-start ablation
Add formal Step 6 E4 warm-start pipeline
Complete formal Step 5 E3 fair QAOA
Add formal Step 5 E3 fair QAOA pipeline
nothing to commit, working tree clean
```

Only after the JSON gate, raw-row checks, hash checks, PDF visual check, result commit, and clean worktree pass may Step 7 / E5 begin.
