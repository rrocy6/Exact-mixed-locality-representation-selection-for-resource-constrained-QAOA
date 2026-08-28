# Fibre-aware selector v2 command record

## Frozen environment

Use the repository `.venv` already recorded by the pilot lock:

```text
Python 3.12.10
NumPy 2.5.2
SciPy 1.18.1
Qiskit 2.4.2
Qiskit Aer 0.17.2
jsonschema 4.25.1
psutil 7.2.2
```

## Config validation

```powershell
python ".\validate_experiment_config.py" `
  --config ".\configs\experiment_config_v2.yaml"
```

Expected config SHA256:

```text
41c4e875b5994c12270ebae98faa4df6664e6d03cc19a60ef9b74152e31822a0
```

## Regression tests

```powershell
python ".\run_pipeline_tests.py"

Push-Location ".\golden_example"
python ".\run_tests.py"
Pop-Location
```

Expected:

```text
Ran 123 tests
OK
10 passed, 0 failed
```

## Formal selector-v2 run

```powershell
$arguments = @(
  ".\run_fibre_selector_v2.py"
  "--config"
  ".\configs\experiment_config_v2.yaml"
  "--config-hash"
  ".\configs\experiment_config_v2.sha256"
  "--data"
  ".\data"
  "--output"
  ".\fibre_selector_v2"
)

python @arguments
```

Expected final line:

```text
FIBRE SELECTOR V2 GATE: pass
```
