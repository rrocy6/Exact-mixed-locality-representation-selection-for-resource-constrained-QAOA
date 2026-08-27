# Reference compiler pilot commands

This pilot validates the deterministic all-to-all reference compiler, the
minimum-pair-cover full representation, pointwise exactness, and small
statevector execution. It does not freeze Qmax and is not an E1-E6 result.

Run from the repository root in the Python 3.12 virtual environment.

## Preconditions

~~~powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

python -m pip check
python -c "import numpy, scipy, qiskit, qiskit_aer; print(numpy.__version__, scipy.__version__, qiskit.__version__, qiskit_aer.__version__)"
~~~

Expected versions:

~~~text
2.5.2 1.18.1 2.4.2 0.17.2
~~~

## Run all regression tests

~~~powershell
python .\run_pipeline_tests.py
$testExitCode = $LASTEXITCODE
"TEST EXIT CODE: $testExitCode"

if ($testExitCode -ne 0) {
  throw "Regression tests failed; do not run the pilot"
}
~~~

Expected result after this update: 25 tests, "OK", exit code 0.

## Run the reference pilot

Use a new output directory. The runner refuses to overwrite non-empty
evidence.

~~~powershell
$pilotOutput = ".\evidence\reference_pilot_v1"

if (
  (Test-Path $pilotOutput) -and
  (Get-ChildItem $pilotOutput -Force | Select-Object -First 1)
) {
  throw "Pilot output already exists and is non-empty"
}

python .\run_reference_pilot.py --config .\configs\reference_pilot_v1.json --output $pilotOutput

$pilotExitCode = $LASTEXITCODE
"PILOT EXIT CODE: $pilotExitCode"

if ($pilotExitCode -ne 0) {
  throw "Reference pilot failed; do not commit evidence"
}
~~~

Required audit:

~~~text
status: pass
instance_count: 2
representation_resource_row_count: 4
statevector_probe_count: 8
all_full_quadratization_exactness_checks_pass: true
all_statevector_probes_pass: true
formal_manifest_created: false
qmax_frozen: false
~~~

## Inspect timing and resources

~~~powershell
Import-Csv ".\evidence\reference_pilot_v1\reference_resources.csv" | Format-Table family,representation,n_qubits,two_qubit_gate_count,two_qubit_depth

Import-Csv ".\evidence\reference_pilot_v1\qaoa_statevector_timing.csv" | Format-Table probe_type,instance_id,representation,n_qubits,simulation_runtime_sec,statevector_raw_mib
~~~

The width probes stop at 12 qubits. They verify the runner and establish the
first timing curve; they do not justify selecting Qmax.

## Git review

~~~powershell
git diff --check
git status --short --untracked-files=all
git --no-pager diff --stat
~~~
