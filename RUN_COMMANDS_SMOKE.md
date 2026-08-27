# URSS smoke pipeline commands

This smoke batch validates the raw benchmark data layer. It does not create a
formal train/validation/test split and must not be reported as E1-E6 results.

Run the commands below from the repository root in the active Python 3.12
virtual environment.

## Install the two smoke dependencies

```powershell
python -m pip install -r .\requirements-smoke.txt
```

## Run all regression tests

```powershell
python .\run_pipeline_tests.py
```

## Validate the existing experiment-config draft

```powershell
python .\validate_experiment_config.py `
  --config .\configs\experiment_config_v1.draft.yaml
```

The report must say `"status": "valid"`. A positive remaining-blocker count is
expected while the configuration remains a draft.

## Generate the first smoke batch

The output directory must be new or empty. Existing evidence is never
overwritten silently.

```powershell
python .\run_smoke_pipeline.py `
  --config .\configs\smoke_config_v1.json `
  --schema .\instance_schema\instance_schema_v1.json `
  --output .\data\smoke_v1
```

Success requires the printed audit to contain:

```text
"status": "pass"
"instance_count": 4
"all_schema_valid": true
"all_fixed_seed_reruns_identical": true
"all_direct_vs_canonical_checks_pass": true
"formal_manifest_created": false
```

## Demonstrate byte-for-byte reproducibility

```powershell
python .\run_smoke_pipeline.py `
  --config .\configs\smoke_config_v1.json `
  --schema .\instance_schema\instance_schema_v1.json `
  --output .\data\smoke_v1_repeat

$left = Get-ChildItem .\data\smoke_v1 -Recurse -File

foreach ($file in $left) {
  $relative = $file.FullName.Substring(
    (Resolve-Path .\data\smoke_v1).Path.Length
  )
  $other = Join-Path (Resolve-Path .\data\smoke_v1_repeat).Path $relative
  if ((Get-FileHash $file.FullName).Hash -ne (Get-FileHash $other).Hash) {
    throw "Reproducibility mismatch: $relative"
  }
}

"SMOKE OUTPUTS ARE BYTE-FOR-BYTE IDENTICAL"
```
