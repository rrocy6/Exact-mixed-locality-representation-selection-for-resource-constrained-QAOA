# Apply formal Step 7 / E5

Run every section in order from the repository root in the active frozen Python 3.12 environment.

## A. Prove formal Step 6 / E4 is complete before extraction

```powershell
$requiredE4 = @(
  ".\results\e4_warmstart_runs.csv"
  ".\results\e4_marginal_diagnostics.csv"
  ".\results\e4_warmstart_summary.csv"
  ".\results\e4_validation_summary.json"
  ".\tables\table_e4_warmstart.tex"
  ".\figures\figure_e4_marginals.pdf"
  ".\evidence\FORMAL_STEP6_E4_AUDIT_WINDOWS.txt"
)

$missingE4 = @(
  $requiredE4 |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingE4.Count -ne 0) {
  "MISSING STEP 6 FILES:"
  $missingE4
  throw "Formal Step 6 outputs are incomplete"
}

foreach ($artifact in $requiredE4[0..5]) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing Step 6 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLowerInvariant()

  if ($actual -ne $declared) {
    throw "Step 6 hash mismatch: $artifact"
  }
}

$e4 = Get-Content `
  ".\results\e4_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e4Checks = @(
  ($e4.status -eq "pass")
  ($e4.e5_e6_may_continue -eq $true)
  ($e4.frozen_test_instance_count -eq 14)
  ($e4.scheduled_design_count -eq 112)
  ($e4.relaxation_optimal_instance_count -eq 14)
  ($e4.missing_marginal_count -eq 0)
  ($e4.cold_e3_reproduction_mismatch_count -eq 0)
  ($e4.failed_run_count -eq 0)
  ($e4.evaluation_budget_mismatch_count -eq 0)
  ($e4.seed_policy_mismatch_count -eq 0)
  ($e4.compiled_budget_exceed_count -eq 0)
  ($e4.primary_score -eq "original_family_objective")
  ($e4.primary_relaxation -eq "SA_RLT_level_2_pair_moments")
  ($e4.only_relaxation_ablation -eq "independence_mu_product")
)

if ($e4Checks -contains $false) {
  $e4 | ConvertTo-Json -Depth 10
  throw "Formal Step 6 E4 gate does not permit Step 7"
}

$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Complete formal Step 6 E4 warm-start ablation") {
  throw "Step 6 result commit is missing or is not the current checkpoint"
}

$preApplyState = @(
  git status --porcelain=v1 --untracked-files=all
)

if ($preApplyState.Count -ne 0) {
  $preApplyState
  throw "Working tree is not clean; do not apply Step 7"
}

"STEP 6 COMPLETION GATE: PASS"
```

Required:

```text
STEP 6 COMPLETION GATE: PASS
```

## B. Verify and extract the Step 7 package

```powershell
$zipPath = Join-Path `
  "$env:USERPROFILE\Downloads" `
  "URSS_FORMAL_STEP7_E5_UPDATE_2026-08-27.zip"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Step 7 ZIP not found in Downloads"
}

$zipHash = (
  Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
).Hash.ToLowerInvariant()

"ZIP SHA256: $zipHash"

$expectedZipHash = (
  Read-Host "Paste the ZIP SHA256 from the Codex delivery message"
).Trim().ToLowerInvariant()

if ($zipHash -ne $expectedZipHash) {
  throw "Step 7 ZIP hash mismatch; do not extract"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

$requiredImplementation = @(
  ".\APPLY_FORMAL_STEP7_E5.md"
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP7_E5.md"
  ".\RUN_COMMANDS_FORMAL_STEP7_E5.md"
  ".\configs\e5_analysis_v1.json"
  ".\configs\e5_analysis_v1.sha256"
  ".\run_e5_regime.py"
  ".\tests\test_e5_regime.py"
  ".\urss_pipeline\e5_regime.py"
)

$missingImplementation = @(
  $requiredImplementation |
    Where-Object { -not (Test-Path -LiteralPath $_) }
)

if ($missingImplementation.Count -ne 0) {
  $missingImplementation
  throw "Step 7 package was not fully extracted"
}

$analysisActual = (
  Get-FileHash `
    -LiteralPath ".\configs\e5_analysis_v1.json" `
    -Algorithm SHA256
).Hash.ToLowerInvariant()

$analysisDeclared = (
  Get-Content `
    -LiteralPath ".\configs\e5_analysis_v1.sha256" `
    -Raw
).Trim().ToLowerInvariant()

"ANALYSIS CONFIG HASH MATCH: $($analysisActual -eq $analysisDeclared)"

if ($analysisActual -ne $analysisDeclared) {
  throw "Frozen E5 analysis config hash mismatch"
}

git status --short --untracked-files=all
```

## C. Run all 91 implementation regression tests

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
  python ".\run_pipeline_tests.py" 2>&1
)

$testExitCode = $LASTEXITCODE

$testOutput |
  Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP7_E5_WINDOWS.txt"

"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 91 tests") {
  throw "Did not run the required 91 tests"
}

if (($testOutput -join "`n") -notmatch "(?m)^OK\s*$") {
  throw "The 91-test suite did not finish with OK"
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
Ran 91 tests
OK
TEST EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## D. Commit the Step 7 implementation checkpoint

```powershell
git add -- `
  ".\APPLY_FORMAL_STEP7_E5.md" `
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP7_E5.md" `
  ".\RUN_COMMANDS_FORMAL_STEP7_E5.md" `
  ".\configs\e5_analysis_v1.json" `
  ".\configs\e5_analysis_v1.sha256" `
  ".\evidence\TEST_OUTPUT_FORMAL_STEP7_E5_WINDOWS.txt" `
  ".\run_e5_regime.py" `
  ".\tests\test_e5_regime.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\e5_regime.py"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Step 7 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Add formal Step 7 E5 regime-map pipeline"

git --no-pager log -1 --format="%h %s"
git status
```

The worktree must be clean before E5 runs.

## E. Run formal E5

```powershell
if (git status --porcelain=v1 --untracked-files=all) {
  throw "Working tree must be clean before formal E5"
}

python ".\run_e5_regime.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --analysis-config ".\configs\e5_analysis_v1.json" `
  --analysis-config-hash ".\configs\e5_analysis_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"

$e5ExitCode = $LASTEXITCODE
"E5 EXIT CODE: $e5ExitCode"

if ($e5ExitCode -ne 0) {
  throw "Formal E5 failed; do not continue to E6"
}
```

## F. Validate every E5 artifact and protocol gate

```powershell
$e5 = Get-Content `
  ".\results\e5_validation_summary.json" `
  -Raw |
  ConvertFrom-Json

$e5 | ConvertTo-Json -Depth 20

$classifiedCount = (
  $e5.help_count +
  $e5.little_effect_count +
  $e5.hurt_count
)

$e5Checks = @(
  ($e5.status -eq "pass")
  ($e5.e6_may_continue -eq $true)
  ($e5.frozen_qaoa_test_instance_count -eq 14)
  ($e5.frozen_compilation_test_instance_count -eq 36)
  ($e5.qaoa_instance_level_row_count -eq 56)
  ($e5.compiled_instance_level_row_count -eq 216)
  ($e5.instance_level_row_count -eq 272)
  ($e5.summary_row_count -gt 0)
  ($e5.expected_infeasible_row_count -gt 0)
  ($e5.unexpected_failure_count -eq 0)
  ($e5.non_test_input_count -eq 0)
  ($e5.winner_based_instance_selection_count -eq 0)
  ($classifiedCount -eq (272 - $e5.expected_infeasible_row_count))
  (($e5.primary_axes -join ",") -eq "canonical_cubic_sparsity,pair_reuse,connectivity_routing")
  (($e5.diagnostic_only_axes -join ",") -eq "sign_balance,n_original")
  ($e5.treatment -eq "selective")
  ($e5.control -eq "matched_random_selective")
  ($e5.uncertainty_method -eq "paired_normal_interval")
)

if ($e5Checks -contains $false) {
  throw "Formal E5 protocol gate failed"
}

$instanceRows = @(
  Import-Csv ".\results\e5_regime_instance_level.csv"
)

$summaryRows = @(
  Import-Csv ".\results\e5_regime_summary.csv"
)

if ($instanceRows.Count -ne 272) {
  throw "Wrong E5 instance-level row count"
}

if ($summaryRows.Count -ne $e5.summary_row_count) {
  throw "Wrong E5 summary row count"
}

if (@($instanceRows | Where-Object { $_.split -ne "test" }).Count -ne 0) {
  throw "E5 consumed a non-test row"
}

if (
  @(
    $instanceRows |
      Where-Object {
        $_.comparison -ne "selective_vs_matched_random_selective"
      }
  ).Count -ne 0
) {
  throw "E5 comparison changed"
}

$artifacts = @(
  ".\results\e5_regime_instance_level.csv"
  ".\results\e5_regime_summary.csv"
  ".\results\e5_validation_summary.json"
  ".\tables\table_e5_help_tie_hurt.tex"
  ".\figures\figure_e5_regime_map.pdf"
)

foreach ($artifact in $artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension(
    $artifact,
    ".sha256"
  )

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing E5 hash sidecar: $sidecar"
  }

  $actual = (
    Get-FileHash -LiteralPath $artifact -Algorithm SHA256
  ).Hash.ToLowerInvariant()

  $declared = (
    Get-Content -LiteralPath $sidecar -Raw
  ).Trim().ToLowerInvariant()

  "$artifact HASH MATCH: $($actual -eq $declared)"

  if ($actual -ne $declared) {
    throw "E5 hash mismatch: $artifact"
  }
}

"E5 PROTOCOL GATE: PASS"
```

Open the PDF:

```powershell
Start-Process ".\figures\figure_e5_regime_map.pdf"
```

Confirm that all six panels render, text is readable, and no panel is blank or clipped. Then run this as a separate block:

```powershell
$visualGate = (
  Read-Host "Type PASS only after visually checking all six E5 PDF panels"
).Trim().ToUpperInvariant()

if ($visualGate -ne "PASS") {
  throw "E5 PDF visual gate not confirmed"
}

$utf8 = [System.Text.UTF8Encoding]::new($false)

$auditLines = @(
  "formal_step=7"
  "experiment=E5_sparsity_reuse_connectivity_regime_map"
  "status=$($e5.status)"
  "e6_may_continue=$($e5.e6_may_continue)"
  "qaoa_test_instances=$($e5.frozen_qaoa_test_instance_count)"
  "compilation_test_instances=$($e5.frozen_compilation_test_instance_count)"
  "instance_rows=$($e5.instance_level_row_count)"
  "summary_rows=$($e5.summary_row_count)"
  "help=$($e5.help_count)"
  "little_effect=$($e5.little_effect_count)"
  "hurt=$($e5.hurt_count)"
  "expected_infeasible=$($e5.expected_infeasible_row_count)"
  "unexpected_failures=$($e5.unexpected_failure_count)"
  "non_test_inputs=$($e5.non_test_input_count)"
  "winner_based_selection=$($e5.winner_based_instance_selection_count)"
  "primary_axes=$($e5.primary_axes -join ',')"
  "diagnostic_axes=$($e5.diagnostic_only_axes -join ',')"
  "analysis_config_hash=$($e5.analysis_config_hash)"
  "pdf_visual_gate=pass"
)

[System.IO.File]::WriteAllLines(
  ".\evidence\FORMAL_STEP7_E5_AUDIT_WINDOWS.txt",
  [string[]]$auditLines,
  $utf8
)

Get-Content ".\evidence\FORMAL_STEP7_E5_AUDIT_WINDOWS.txt"
```

## G. Commit formal E5 results

```powershell
git add -- `
  ".\RUN_COMMANDS.md" `
  ".\assumptions_and_decisions.md" `
  ".\evidence\FORMAL_STEP7_E5_AUDIT_WINDOWS.txt" `
  ".\results\e5_regime_instance_level.csv" `
  ".\results\e5_regime_instance_level.sha256" `
  ".\results\e5_regime_summary.csv" `
  ".\results\e5_regime_summary.sha256" `
  ".\results\e5_validation_summary.json" `
  ".\results\e5_validation_summary.sha256" `
  ".\tables\table_e5_help_tie_hurt.tex" `
  ".\tables\table_e5_help_tie_hurt.sha256" `
  ".\figures\figure_e5_regime_map.pdf" `
  ".\figures\figure_e5_regime_map.sha256"

git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "E5 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git status --short

git commit -m "Complete formal Step 7 E5 regime map"

git --no-pager log -4 --format="%h %s"
git status
```

Formal Step 7 / E5 is complete only when the JSON gate, 272 instance rows, all hashes, six-panel visual gate, result commit, and clean worktree all pass. Only then may Step 8 / E6 begin.
