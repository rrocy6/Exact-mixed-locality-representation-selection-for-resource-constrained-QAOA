# Apply Step 1 draft revision 2

This package updates only the configuration and reproducibility documentation.
It does not overwrite pipeline source code or smoke evidence.

## Files to copy into the repository root

```text
RUN_COMMANDS.md
assumptions_and_decisions.md
requirements-pilot.in
configs/experiment_config_v1.draft.yaml
configs/experiment_config_v1.draft.sha256
```

Keep the existing `RUN_COMMANDS_SMOKE.md` and
`assumptions_and_decisions_smoke.md`; they remain the historical smoke-scope
records.

## Required validation

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.draft.yaml

python .\run_pipeline_tests.py

Push-Location .\golden_example
python .\run_tests.py
$goldenExitCode = $LASTEXITCODE
Pop-Location

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; do not commit"
}

git diff --check
git status --short
```

Expected config result: valid draft, `freeze_blocked=true`, 23 blockers after the quantum-stack version freeze.
Expected regressions: 14 pipeline tests and 10 golden tests pass.

## Suggested checkpoint commit

Review the diff before staging. Then:

```powershell
git add -- `
  .\configs\experiment_config_v1.draft.yaml `
  .\configs\experiment_config_v1.draft.sha256 `
  .\RUN_COMMANDS.md `
  .\assumptions_and_decisions.md `
  .\requirements-pilot.in `
  .\APPLY_STEP1_DRAFT2.md

git diff --cached --check
git --no-pager diff --cached --stat
git commit -m "Record Step 1 experimental decisions and pilot prerequisites"
```

Do not change the status to frozen in this commit.
