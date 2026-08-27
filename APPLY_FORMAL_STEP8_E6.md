# Apply formal Step 8 / E6

Run A-G in order from the repository root. Paste each PowerShell block
separately.

## A. Verify the completed Step 7 checkpoint

```powershell
$requiredE5 = @(
  ".\results\e5_regime_instance_level.csv"
  ".\results\e5_regime_summary.csv"
  ".\results\e5_validation_summary.json"
  ".\tables\table_e5_help_tie_hurt.tex"
  ".\figures\figure_e5_regime_map.pdf"
  ".\evidence\FORMAL_STEP7_E5_AUDIT_WINDOWS.txt"
)

$missingE5 = @($requiredE5 | Where-Object { -not (Test-Path -LiteralPath $_) })

if ($missingE5.Count -ne 0) {
  "MISSING STEP 7 FILES:"
  $missingE5
  throw "Formal Step 7 outputs are incomplete"
}

foreach ($artifact in $requiredE5[0..4]) {
  $sidecar = [System.IO.Path]::ChangeExtension($artifact, ".sha256")

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing Step 7 hash sidecar: $sidecar"
  }

  $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
  $declared = (Get-Content -LiteralPath $sidecar -Raw).Trim().ToLowerInvariant()

  if ($actual -ne $declared) {
    throw "Step 7 hash mismatch: $artifact"
  }
}

$e5 = Get-Content ".\results\e5_validation_summary.json" -Raw | ConvertFrom-Json

$e5Checks = @(
  ($e5.status -eq "pass")
  ($e5.e6_may_continue -eq $true)
  ($e5.instance_level_row_count -eq 272)
  ($e5.winner_based_instance_selection_count -eq 0)
  ($e5.unexpected_failure_count -eq 0)
)

if ($e5Checks -contains $false) {
  throw "Formal Step 7 gate does not permit Step 8"
}

$latestSubject = git log -1 --format="%s"
"LATEST COMMIT: $latestSubject"

if ($latestSubject -ne "Complete formal Step 7 E5 regime map") {
  throw "Step 7 result commit is not the current checkpoint"
}

$preApplyState = @(git status --porcelain=v1 --untracked-files=all)

if ($preApplyState.Count -ne 0) {
  $preApplyState
  throw "Working tree is not clean; move handoff files outside the repository"
}

"STEP 7 COMPLETION GATE: PASS"
```

Required: `STEP 7 COMPLETION GATE: PASS`.

## B. Verify and extract the Step 8 package

```powershell
$zipPath = Join-Path "$env:USERPROFILE\Downloads" "URSS_FORMAL_STEP8_E6_UPDATE_2026-08-27.zip"

if (-not (Test-Path -LiteralPath $zipPath)) {
  throw "Step 8 ZIP not found in Downloads"
}

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"ZIP SHA256: $zipHash"

$expectedZipHash = (Read-Host "Paste the ZIP SHA256 from the Codex delivery message").Trim().ToLowerInvariant()

if ($zipHash -ne $expectedZipHash) {
  throw "Step 8 ZIP hash mismatch; do not extract"
}

Expand-Archive -LiteralPath $zipPath -DestinationPath . -Force

$requiredImplementation = @(
  ".\APPLY_FORMAL_STEP8_E6.md"
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP8_E6.md"
  ".\RUN_COMMANDS_FORMAL_STEP8_E6.md"
  ".\configs\e6_noise_v1.json"
  ".\configs\e6_noise_v1.sha256"
  ".\run_e6_noise.py"
  ".\tests\test_e6_noise.py"
  ".\urss_pipeline\e6_noise.py"
)

$missingImplementation = @($requiredImplementation | Where-Object { -not (Test-Path -LiteralPath $_) })

if ($missingImplementation.Count -ne 0) {
  $missingImplementation
  throw "Step 8 package was not fully extracted"
}

$protocolActual = (Get-FileHash -LiteralPath ".\configs\e6_noise_v1.json" -Algorithm SHA256).Hash.ToLowerInvariant()
$protocolDeclared = (Get-Content -LiteralPath ".\configs\e6_noise_v1.sha256" -Raw).Trim().ToLowerInvariant()

"E6 PROTOCOL HASH MATCH: $($protocolActual -eq $protocolDeclared)"

if ($protocolActual -ne $protocolDeclared) {
  throw "Frozen E6 protocol config hash mismatch"
}

git status --short --untracked-files=all
```

## C. Run all 108 implementation tests

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python -m pip check
python -c "import numpy, scipy, qiskit, qiskit_aer, reportlab; print('numpy=' + numpy.__version__); print('scipy=' + scipy.__version__); print('qiskit=' + qiskit.__version__); print('qiskit_aer=' + qiskit_aer.__version__); print('reportlab=' + reportlab.Version)"

New-Item -ItemType Directory -Force ".\evidence" | Out-Null

$testOutput = @(python ".\run_pipeline_tests.py" 2>&1)
$testExitCode = $LASTEXITCODE
$testOutput | Tee-Object ".\evidence\TEST_OUTPUT_FORMAL_STEP8_E6_WINDOWS.txt"

"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed"
}

if (($testOutput -join "`n") -notmatch "Ran 108 tests") {
  throw "Did not run the required 108 tests"
}

if (($testOutput -join "`n") -notmatch "(?m)^OK\s*$") {
  throw "The 108-test suite did not finish with OK"
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

Required: `Ran 108 tests`, `OK`, `TEST EXIT CODE: 0`, and
`10 passed, 0 failed`.

## D. Commit the implementation checkpoint

```powershell
$implementationFiles = @(
  ".\APPLY_FORMAL_STEP8_E6.md"
  ".\IMPLEMENTATION_REPORT_FORMAL_STEP8_E6.md"
  ".\RUN_COMMANDS_FORMAL_STEP8_E6.md"
  ".\configs\e6_noise_v1.json"
  ".\configs\e6_noise_v1.sha256"
  ".\evidence\TEST_OUTPUT_FORMAL_STEP8_E6_WINDOWS.txt"
  ".\run_e6_noise.py"
  ".\tests\test_e6_noise.py"
  ".\urss_pipeline\__init__.py"
  ".\urss_pipeline\e6_noise.py"
)

git add -- $implementationFiles
git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "Step 8 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git commit -m "Add formal Step 8 E6 limited-noise pipeline"

if ($LASTEXITCODE -ne 0) {
  throw "Step 8 implementation commit failed"
}

git --no-pager log -1 --format="%h %s"
git status
```

The worktree must be clean before E6 runs.

## E. Run formal E6

This performs 432 noiseless parameter optimizations and 1296 sampled circuit
evaluations. Keep the computer connected to power.

```powershell
if (git status --porcelain=v1 --untracked-files=all) {
  throw "Working tree must be clean before formal E6"
}

$e6Arguments = @(
  ".\run_e6_noise.py"
  "--config"
  ".\configs\experiment_config_v1.yaml"
  "--config-hash"
  ".\configs\experiment_config_v1.sha256"
  "--protocol-config"
  ".\configs\e6_noise_v1.json"
  "--protocol-config-hash"
  ".\configs\e6_noise_v1.sha256"
  "--data"
  ".\data"
  "--results"
  ".\results"
  "--tables"
  ".\tables"
  "--figures"
  ".\figures"
  "--assumptions"
  ".\assumptions_and_decisions.md"
  "--run-commands"
  ".\RUN_COMMANDS.md"
)

python @e6Arguments 2>&1 | Tee-Object ".\evidence\FORMAL_STEP8_E6_CONSOLE_WINDOWS.txt"
$e6ExitCode = $LASTEXITCODE

"E6 EXIT CODE: $e6ExitCode"

if ($e6ExitCode -ne 0) {
  throw "Formal E6 failed; do not build the final result pack"
}
```

## F. Validate the E6 protocol and artifacts

```powershell
$e6 = Get-Content ".\results\e6_validation_summary.json" -Raw | ConvertFrom-Json
$e6 | ConvertTo-Json -Depth 20

$e6Checks = @(
  ($e6.status -eq "pass")
  ($e6.final_result_pack_may_be_built -eq $true)
  ($e6.frozen_noise_subset_instance_count -eq 18)
  ($e6.instances_per_family -eq 9)
  ($e6.representation_family_count -eq 4)
  ($e6.matched_random_seed_count -eq 5)
  ($e6.scheduled_design_count -eq 144)
  ($e6.parameter_optimization_run_count -eq 432)
  ($e6.run_row_count -eq 1296)
  ($e6.summary_row_count -eq 24)
  ($e6.noise_level_count -eq 3)
  ($e6.nonzero_noise_level_count -eq 2)
  ($e6.shots_per_run -eq 4096)
  ($e6.topology_id -eq "device_sparse_v1")
  ($e6.primary_score -eq "original_family_objective_after_discarding_auxiliaries")
  ($e6.auxiliary_inconsistency_reported -eq $true)
  ($e6.real_device_used -eq $false)
  ($e6.failed_run_count -eq 0)
  ($e6.full_circuit_depth_reduction_count -eq 46)
  ($e6.paired_group_count_mismatch -eq 0)
  ($e6.missing_noise_level_group_count -eq 0)
  ($e6.cross_level_protocol_mismatch_count -eq 0)
  ($e6.cross_level_parameter_mismatch_count -eq 0)
  ($e6.compiled_budget_exceed_count -eq 0)
  ($e6.non_original_primary_score_count -eq 0)
)

if ($e6Checks -contains $false) {
  throw "Formal E6 protocol gate failed"
}

$runRows = @(Import-Csv ".\results\e6_noise_runs.csv")
$summaryRows = @(Import-Csv ".\results\e6_noise_summary.csv")

if ($runRows.Count -ne 1296) {
  throw "Wrong E6 raw row count"
}

if ($summaryRows.Count -ne 24) {
  throw "Wrong E6 summary row count"
}

foreach ($level in @("noiseless", "realistic_low", "realistic_high")) {
  $count = @($runRows | Where-Object { $_.noise_level -eq $level }).Count
  "$level ROWS: $count"

  if ($count -ne 432) {
    throw "Wrong E6 noise-level row count: $level"
  }
}

if (@($runRows | Where-Object { [int]$_.shots -ne 4096 }).Count -ne 0) {
  throw "E6 shots differ across rows"
}

if (@($runRows | Where-Object { $_.topology_id -ne "device_sparse_v1" }).Count -ne 0) {
  throw "E6 topology differs across rows"
}

if (@($runRows | Where-Object { [int]$_.actual_2q_gates -gt 256 }).Count -ne 0) {
  throw "E6 actual compiled budget was exceeded"
}

$pairedGroups = @(
  $runRows |
    Group-Object instance_id,representation,random_rep_seed,design_id,restart_id
)

if ($pairedGroups.Count -ne 432) {
  throw "Wrong E6 paired group count"
}

foreach ($group in $pairedGroups) {
  if ($group.Count -ne 3) {
    throw "E6 paired group does not contain three noise levels"
  }

  if (@($group.Group.noise_level | Sort-Object -Unique).Count -ne 3) {
    throw "E6 paired group has duplicate or missing levels"
  }

  if (@($group.Group.optimized_parameters_sha256 | Sort-Object -Unique).Count -ne 1) {
    throw "E6 parameters changed between paired levels"
  }

  if (@($group.Group.shots | Sort-Object -Unique).Count -ne 1) {
    throw "E6 shots changed within a paired group"
  }

  if (@($group.Group.transpiler_seed | Sort-Object -Unique).Count -ne 1) {
    throw "E6 transpiler seed changed within a paired group"
  }

  if (@($group.Group.measurement_seed | Sort-Object -Unique).Count -ne 1) {
    throw "E6 measurement seed changed within a paired group"
  }
}

$artifacts = @(
  ".\results\e6_noise_runs.csv"
  ".\results\e6_noise_summary.csv"
  ".\results\e6_noise_provenance.json"
  ".\results\e6_validation_summary.json"
  ".\tables\table_e6_noise.tex"
  ".\figures\figure_e6_noise.pdf"
)

foreach ($artifact in $artifacts) {
  $sidecar = [System.IO.Path]::ChangeExtension($artifact, ".sha256")

  if (-not (Test-Path -LiteralPath $sidecar)) {
    throw "Missing E6 hash sidecar: $sidecar"
  }

  $actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
  $declared = (Get-Content -LiteralPath $sidecar -Raw).Trim().ToLowerInvariant()
  "$artifact HASH MATCH: $($actual -eq $declared)"

  if ($actual -ne $declared) {
    throw "E6 hash mismatch: $artifact"
  }
}

"E6 PROTOCOL GATE: PASS"
```

Open `figures/figure_e6_noise.pdf`:

```powershell
Start-Process ".\figures\figure_e6_noise.pdf"
```

Confirm all four panels, labels, and legend render without clipping. A
zero-height noiseless bar is valid. Then run this as a separate block:

```powershell
$visualGate = (Read-Host "Type PASS after checking all four E6 PDF panels").Trim().ToUpperInvariant()

if ($visualGate -ne "PASS") {
  throw "E6 PDF visual gate not confirmed"
}

$utf8 = [System.Text.UTF8Encoding]::new($false)

$auditLines = @(
  "formal_step=8"
  "experiment=E6_limited_noise_study"
  "status=$($e6.status)"
  "final_result_pack_may_be_built=$($e6.final_result_pack_may_be_built)"
  "noise_subset_instances=$($e6.frozen_noise_subset_instance_count)"
  "instances_per_family=$($e6.instances_per_family)"
  "scheduled_designs=$($e6.scheduled_design_count)"
  "parameter_optimizations=$($e6.parameter_optimization_run_count)"
  "run_rows=$($e6.run_row_count)"
  "summary_rows=$($e6.summary_row_count)"
  "noise_levels=$($e6.noise_level_count)"
  "nonzero_noise_levels=$($e6.nonzero_noise_level_count)"
  "shots_per_run=$($e6.shots_per_run)"
  "topology=$($e6.topology_id)"
  "full_circuit_depth_reductions=$($e6.full_circuit_depth_reduction_count)"
  "failed_runs=$($e6.failed_run_count)"
  "paired_group_mismatches=$($e6.paired_group_count_mismatch)"
  "missing_noise_level_groups=$($e6.missing_noise_level_group_count)"
  "protocol_mismatches=$($e6.cross_level_protocol_mismatch_count)"
  "parameter_mismatches=$($e6.cross_level_parameter_mismatch_count)"
  "budget_exceeds=$($e6.compiled_budget_exceed_count)"
  "non_original_scores=$($e6.non_original_primary_score_count)"
  "config_hash=$($e6.config_hash)"
  "noise_manifest_hash=$($e6.noise_manifest_hash)"
  "protocol_config_hash=$($e6.protocol_config_hash)"
  "pdf_visual_gate=pass"
)

[System.IO.File]::WriteAllLines(
  ".\evidence\FORMAL_STEP8_E6_AUDIT_WINDOWS.txt",
  [string[]]$auditLines,
  $utf8
)

Get-Content ".\evidence\FORMAL_STEP8_E6_AUDIT_WINDOWS.txt"
```

## G. Commit formal E6 results

```powershell
$resultFiles = @(
  ".\RUN_COMMANDS.md"
  ".\assumptions_and_decisions.md"
  ".\evidence\FORMAL_STEP8_E6_AUDIT_WINDOWS.txt"
  ".\evidence\FORMAL_STEP8_E6_CONSOLE_WINDOWS.txt"
  ".\results\e6_noise_runs.csv"
  ".\results\e6_noise_runs.sha256"
  ".\results\e6_noise_summary.csv"
  ".\results\e6_noise_summary.sha256"
  ".\results\e6_noise_provenance.json"
  ".\results\e6_noise_provenance.sha256"
  ".\results\e6_validation_summary.json"
  ".\results\e6_validation_summary.sha256"
  ".\tables\table_e6_noise.tex"
  ".\tables\table_e6_noise.sha256"
  ".\figures\figure_e6_noise.pdf"
  ".\figures\figure_e6_noise.sha256"
)

git add -- $resultFiles
git diff --cached --check

if ($LASTEXITCODE -ne 0) {
  throw "E6 staged files have formatting errors"
}

git --no-pager diff --cached --stat
git commit -m "Complete formal Step 8 E6 limited-noise study"

if ($LASTEXITCODE -ne 0) {
  throw "Step 8 result commit failed"
}

git --no-pager log -4 --format="%h %s"
git status
```

Step 8 is complete only after the JSON gate, 1296 raw rows, 24 summary rows,
hashes, visual gate, result commit, and clean worktree all pass. E1-E6 are then
complete; build the single Final Result Pack instead of starting another
experiment.
