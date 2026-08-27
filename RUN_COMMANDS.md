# URSS numerical pipeline commands

This file records commands that are currently executable and the exact software
state used for the verified smoke checkpoint. Formal data generation and E1-E6
commands will be added only after the pilot resolves every freeze blocker.

Run all commands from the repository root in Windows PowerShell 5.1.

## Current verified software state

| Component | Version / status |
|---|---|
| Python | CPython 3.12.10 |
| pip | 25.0.1 |
| Git | 2.51.0.windows.2 |
| attrs | 26.1.0 |
| jsonschema | 4.25.1 |
| jsonschema-specifications | 2025.9.1 |
| PyYAML | 6.0.3 |
| referencing | 0.37.0 |
| rpds-py | 2026.6.3 |
| typing_extensions | 4.16.0 |
| NumPy | 2.5.2 |
| SciPy | 1.18.1 |
| Qiskit | 2.4.2 |
| Qiskit Aer | 0.17.2 |

The authoritative machine snapshot is `configs/environment_snapshot_v1.txt`.

## Activate the environment

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python --version
python -c "import sys; print(sys.executable)"
python -m pip --version
```

The executable must be `.venv\Scripts\python.exe` under this repository.

## Install and freeze the pilot quantum stack

The project uses the previously validated Qiskit 2.4 line and pins Aer
explicitly. Install only inside `.venv`:

```powershell
python -m pip install -r .\requirements-pilot.in

python -c "import qiskit, qiskit_aer, scipy; print('qiskit=' + qiskit.__version__); print('qiskit_aer=' + qiskit_aer.__version__); print('scipy=' + scipy.__version__)"
```

After the installation succeeds, create a full transitive lock snapshot:

```powershell
$utf8 = [System.Text.UTF8Encoding]::new($false)
$freeze = [string[]](& python -m pip freeze)
[System.IO.File]::WriteAllLines(
  (Join-Path (Get-Location) "requirements-pilot-lock.txt"),
  $freeze,
  $utf8
)
```

Do not copy package versions into the experiment config until the import command
and the pipeline tests both succeed.

## Golden regression

```powershell
Push-Location .\golden_example
python .\run_tests.py
$goldenExitCode = $LASTEXITCODE
Pop-Location

if ($goldenExitCode -ne 0) {
  throw "Golden regression failed; stop"
}
```

Required result: `10 passed, 0 failed`.

## Pipeline regression

```powershell
python .\run_pipeline_tests.py
$pipelineExitCode = $LASTEXITCODE

if ($pipelineExitCode -ne 0) {
  throw "Pipeline regression failed; stop"
}
```

Required result: `Ran 14 tests` followed by `OK` and exit code `0`.

## Validate the current config draft

```powershell
python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.draft.yaml
```

For draft revision 2, the expected report is `status: valid`,
`freeze_blocked: true`, and `remaining_blocker_count: 23`.

## Reproduce the smoke batch

The output directory must be new or empty.

```powershell
$smokeOutput = Join-Path `
  $env:TEMP `
  ("urss_smoke_" + (Get-Date -Format "yyyyMMdd_HHmmss"))

python .\run_smoke_pipeline.py `
  --config .\configs\smoke_config_v1.json `
  --schema .\instance_schema\instance_schema_v1.json `
  --output $smokeOutput

if ($LASTEXITCODE -ne 0) {
  throw "Smoke pipeline failed; stop"
}
```

Required audit fields:

```text
status: pass
instance_count: 4
all_schema_valid: true
all_fixed_seed_reruns_identical: true
all_direct_vs_canonical_checks_pass: true
formal_manifest_created: false
```

## Recompute the draft hash after an intentional config update

```powershell
$configPath = ".\configs\experiment_config_v1.draft.yaml"
$hashPath = ".\configs\experiment_config_v1.draft.sha256"
$configHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLower()
$utf8 = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
  (Join-Path (Get-Location) $hashPath),
  $configHash + "`n",
  $utf8
)
$configHash
```

Any config change invalidates the previous hash. A draft hash proves file
identity; it does not mean the configuration is frozen.

## Git checks

```powershell
git diff --check
git status --short
git --no-pager diff --stat
```

## Commands not yet authorised as formal-result commands

The following stages do not yet have complete implementations or a frozen
config and must not be represented as completed commands:

```text
formal candidate-pool generation
formal 60/20/20 manifest freeze
E1 exactness
E2 logical/compiled resources
E3 noiseless QAOA
E4 warm-start ablation
E5 regime analysis
E6 limited noise
```

They are added here only after the pilot passes and the corresponding command
has been executed successfully at least once.

## Formal Step 1 freeze command (v1)

The evidence-gated finalizer was added after the reference compiler pilot. Run it from the repository root:

```powershell
python .\run_finalize_step1.py `
  --draft-config .\configs\experiment_config_v1.draft.yaml `
  --decisions .\configs\step1_freeze_decisions_v1.json `
  --reference-pilot-config .\configs\reference_pilot_v1.json `
  --pilot-output .\evidence\reference_pilot_v1_windows `
  --formal-config .\configs\experiment_config_v1.yaml `
  --output .\evidence\step1_freeze_v1 `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md
```

Required result: `status=pass`, `formal_step1_complete=true`, `remaining_blocker_count=0`, and `formal_step2_started=false`. Validate the written config and hash before starting Step 2.

## Formal Step 2 data-freeze command (v1)

Run only from the clean committed Step 2 implementation checkpoint:

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
```

Required result: `DATA FREEZE GATE: pass`, `status=pass`, `formal_manifests_created=true`, `formal_split_created=true`, `split_leakage_count=0`, and `qmax_feasibility_failure_count=0`.

## Formal Step 3 / E1 command (v1)

See `RUN_COMMANDS_FORMAL_STEP3_E1.md`; the result rows record the exact committed implementation hash.
## Formal Step 4 / E2 command (v1)

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
```

Required result: `E2 RESOURCE GATE: pass` and `e3_e6_may_continue=true`.
