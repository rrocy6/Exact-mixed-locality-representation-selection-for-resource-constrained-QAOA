# Apply the formal Step 1 freeze update

Run every command from the repository root in Windows PowerShell 5.1. This update is intended for the clean commit immediately after `Add deterministic reference compiler pilot`.

## 1. Preconditions

```powershell
git status

python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.draft.yaml
```

Required state:

```text
nothing to commit, working tree clean
freeze_blocked: true
remaining_blocker_count: 23
status: valid
```

The existing Windows reference pilot must remain at:

```text
evidence/reference_pilot_v1_windows/
```

Its audit must still report `status=pass`, eight statevector probes, four resource rows, and no formal manifest/split.

## 2. Apply this update ZIP

Verify the ZIP hash printed in the delivery message, then extract it into the repository root:

```powershell
Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force

git status --short
```

Expected source changes:

```text
M  urss_pipeline/__init__.py
?? APPLY_STEP1_FREEZE.md
?? IMPLEMENTATION_REPORT_STEP1_FREEZE.md
?? RUN_COMMANDS_STEP1_FREEZE.md
?? configs/step1_freeze_decisions_v1.json
?? run_finalize_step1.py
?? tests/test_step1_freeze.py
?? urss_pipeline/step1_freeze.py
```

Do not create the formal config by hand.

## 3. Run all regressions

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

New-Item -ItemType Directory -Force ".\evidence" | Out-Null

python .\run_pipeline_tests.py |
  Tee-Object ".\evidence\TEST_OUTPUT_STEP1_FREEZE_WINDOWS.txt"

$pipelineExitCode = $LASTEXITCODE
"PIPELINE EXIT CODE: $pipelineExitCode"

if ($pipelineExitCode -ne 0) {
  throw "Pipeline regression failed; do not freeze Step 1"
}

Push-Location ".\golden_example"
python .\run_tests.py
$goldenExitCode = $LASTEXITCODE
Pop-Location

"GOLDEN EXIT CODE: $goldenExitCode"

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; do not freeze Step 1"
}
```

Required results:

```text
Ran 29 tests
OK
PIPELINE EXIT CODE: 0
10 passed, 0 failed
GOLDEN EXIT CODE: 0
```

## 4. Freeze the formal config

The command below validates the existing pilot evidence before writing anything formal. It refuses changed blocker lists, failed width-12 evidence, mismatched hashes, inconsistent versions, nonempty evidence output, and an existing formal config.

```powershell
python .\run_finalize_step1.py `
  --draft-config .\configs\experiment_config_v1.draft.yaml `
  --decisions .\configs\step1_freeze_decisions_v1.json `
  --reference-pilot-config .\configs\reference_pilot_v1.json `
  --pilot-output .\evidence\reference_pilot_v1_windows `
  --formal-config .\configs\experiment_config_v1.yaml `
  --output .\evidence\step1_freeze_v1 `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md |
  Tee-Object ".\evidence\STEP1_FREEZE_CONSOLE_WINDOWS.txt"

$freezeExitCode = $LASTEXITCODE
"FREEZE EXIT CODE: $freezeExitCode"

if ($freezeExitCode -ne 0) {
  throw "Formal Step 1 freeze failed; do not commit"
}
```

Required audit fields:

```text
status: pass
formal_step1_complete: true
formal_step2_started: false
remaining_blocker_count: 0
resolved_blocker_count: 23
qmax: 12
formal_manifest_created: false
formal_split_created: false
FREEZE EXIT CODE: 0
```

## 5. Validate the formal config and hash

```powershell
$formalConfig = ".\configs\experiment_config_v1.yaml"
$formalHashFile = ".\configs\experiment_config_v1.sha256"

python .\validate_experiment_config.py --config $formalConfig

if ($LASTEXITCODE -ne 0) {
  throw "Formal config validation failed"
}

$actualHash = (
  Get-FileHash -LiteralPath $formalConfig -Algorithm SHA256
).Hash.ToLower()

$declaredHash = (
  Get-Content -LiteralPath $formalHashFile -Raw
).Trim()

"ACTUAL HASH:   $actualHash"
"DECLARED HASH: $declaredHash"
"HASH MATCH:    $($actualHash -eq $declaredHash)"

if ($actualHash -ne $declaredHash) {
  throw "Formal config hash mismatch"
}

Get-Content ".\evidence\step1_freeze_v1\step1_freeze_audit.json"
```

Required validator state:

```text
config_id: experiment_config_v1
config_version: 1.0
declared_status: frozen
freeze_blocked: false
remaining_blocker_count: 0
status: valid
HASH MATCH: True
```

## 6. Commit the completed Step 1 checkpoint

```powershell
git diff --check
git status --short

git add -- `
  ".\APPLY_STEP1_FREEZE.md" `
  ".\IMPLEMENTATION_REPORT_STEP1_FREEZE.md" `
  ".\RUN_COMMANDS_STEP1_FREEZE.md" `
  ".\RUN_COMMANDS.md" `
  ".\assumptions_and_decisions.md" `
  ".\configs\experiment_config_v1.yaml" `
  ".\configs\experiment_config_v1.sha256" `
  ".\configs\step1_freeze_decisions_v1.json" `
  ".\evidence\STEP1_FREEZE_CONSOLE_WINDOWS.txt" `
  ".\evidence\TEST_OUTPUT_STEP1_FREEZE_WINDOWS.txt" `
  ".\evidence\step1_freeze_v1" `
  ".\run_finalize_step1.py" `
  ".\tests\test_step1_freeze.py" `
  ".\urss_pipeline\__init__.py" `
  ".\urss_pipeline\step1_freeze.py"

git diff --cached --check
git --no-pager diff --cached --stat

git commit -m "Freeze formal Step 1 experiment configuration"

git --no-pager log -4 --format="%h %s"
git status
```

Completion means the new commit exists and the working tree is clean. Only then may the formal Step 2 manifest pipeline be executed.
