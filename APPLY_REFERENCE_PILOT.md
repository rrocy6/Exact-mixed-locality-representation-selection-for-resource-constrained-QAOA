# Apply the reference compiler pilot update

This update belongs on a new commit after the Step 1 configuration and
environment checkpoint. It implements a non-formal reference compiler pilot;
it does not freeze Qmax or create E1--E6 results.

## 1. Finish and commit the current Step 1 checkpoint

Run these commands before extracting this update:

~~~powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$utf8 = [System.Text.UTF8Encoding]::new($false)

python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.draft.yaml
~~~

The draft must be valid. After recording the installed SciPy, Qiskit, and Aer
versions, the expected remaining blocker count is 23. Do not mark it frozen.

Recompute and verify its hash:

~~~powershell
$configPath = (Resolve-Path `
  ".\configs\experiment_config_v1.draft.yaml").Path

$configHash = (Get-FileHash `
  -LiteralPath $configPath `
  -Algorithm SHA256).Hash.ToLower()

$hashPath = Join-Path `
  (Split-Path $configPath) `
  "experiment_config_v1.draft.sha256"

[System.IO.File]::WriteAllText(
  $hashPath,
  $configHash + "`n",
  $utf8
)

$storedHash = (Get-Content -Raw $hashPath).Trim()
if ($storedHash -ne $configHash) {
  throw "Config hash file does not match the YAML"
}
~~~

Run the existing regressions, stage only the Step 1 files, and commit them:

~~~powershell
python .\run_pipeline_tests.py
if ($LASTEXITCODE -ne 0) {
  throw "Pipeline tests failed; do not commit"
}

Push-Location .\golden_example
python .\run_tests.py
$goldenExitCode = $LASTEXITCODE
Pop-Location

if ($goldenExitCode -ne 0) {
  throw "Golden tests failed; do not commit"
}

git add -- `
  .\configs\environment_snapshot_v1.txt `
  .\configs\experiment_config_v1.draft.sha256 `
  .\configs\experiment_config_v1.draft.yaml `
  .\APPLY_STEP1_DRAFT2.md `
  .\RUN_COMMANDS.md `
  .\assumptions_and_decisions.md `
  .\requirements-pilot.in `
  .\requirements-pilot-lock.txt

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Record Step 1 decisions and frozen pilot environment"

if (git status --porcelain) {
  throw "Working tree is not clean after the Step 1 commit"
}
~~~

## 2. Extract this update from a clean working tree

~~~powershell
$zipPath = Join-Path `
  "$env:USERPROFILE\Downloads" `
  "URSS_REFERENCE_COMPILER_PILOT_UPDATE_2026-08-27.zip"

if (-not (Test-Path $zipPath)) {
  throw "Reference pilot ZIP not found"
}

if (git status --porcelain) {
  throw "Working tree is not clean; stop before applying the update"
}

Expand-Archive `
  -LiteralPath $zipPath `
  -DestinationPath . `
  -Force
~~~

## 3. Verify dependencies and run 25 tests

~~~powershell
python -m pip install -r .\requirements-pilot.in
python -m pip check

New-Item -ItemType Directory -Force .\evidence | Out-Null

python .\run_pipeline_tests.py |
  Tee-Object .\evidence\TEST_OUTPUT_REFERENCE_PILOT_WINDOWS.txt

$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not run or commit the pilot"
}
~~~

Expected: 25 tests, `OK`, exit code 0.

## 4. Run the Windows pilot

~~~powershell
$pilotOutput = ".\evidence\reference_pilot_v1_windows"

if (
  (Test-Path $pilotOutput) -and
  (Get-ChildItem $pilotOutput -Force | Select-Object -First 1)
) {
  throw "Pilot output exists and is non-empty; preserve it and use a new path"
}

python .\run_reference_pilot.py `
  --config .\configs\reference_pilot_v1.json `
  --output $pilotOutput |
  Tee-Object .\evidence\REFERENCE_PILOT_CONSOLE_WINDOWS.txt

$pilotExitCode = $LASTEXITCODE
"PILOT EXIT CODE: $pilotExitCode"

if ($pilotExitCode -ne 0) {
  throw "Reference pilot failed; do not commit"
}

Get-Content `
  .\evidence\reference_pilot_v1_windows\reference_pilot_audit.json
~~~

The audit must report `status: pass`, 2 instances, 4 resource rows, 8
statevector probes, exactness pass, statevector pass, and `qmax_frozen: false`.

## 5. Review and create the reference-pilot commit

~~~powershell
git diff --check
git status --short --untracked-files=all
git --no-pager diff --stat

git add -- `
  .\APPLY_REFERENCE_PILOT.md `
  .\IMPLEMENTATION_REPORT_REFERENCE_PILOT.md `
  .\RUN_COMMANDS_REFERENCE_PILOT.md `
  .\configs\reference_pilot_v1.json `
  .\evidence\REFERENCE_PILOT_CONSOLE_WINDOWS.txt `
  .\evidence\TEST_OUTPUT_REFERENCE_PILOT_WINDOWS.txt `
  .\evidence\reference_pilot_v1_windows `
  .\requirements-pilot.in `
  .\run_reference_pilot.py `
  .\tests\test_reference_pilot.py `
  .\urss_pipeline\__init__.py `
  .\urss_pipeline\qaoa_pilot.py `
  .\urss_pipeline\reference_compiler.py `
  .\urss_pipeline\reference_pilot.py `
  .\urss_pipeline\representations.py

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Add deterministic reference compiler pilot"

git --no-pager log -2 --format="%h %an <%ae> %s"
git status
~~~

The final working tree must be clean. Keep the formal experiment config in
draft status; the Windows measurements are evidence for the later Qmax and
search-budget pilot, not grounds to freeze Qmax by themselves.
