# Formal Step 5 / E3 commands

The complete guarded Windows procedure is in `APPLY_FORMAL_STEP5_E3.md`.

Implementation regression:

```powershell
python ".\run_pipeline_tests.py"

Push-Location ".\golden_example"
python ".\run_tests.py"
Pop-Location
```

Required regression result: 66 tests `OK` and Golden 10/10.

Formal E3 command, run only from the clean Step 5 implementation commit:

```powershell
python ".\run_e3_qaoa.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"
```

Required formal result: `E3 FAIRNESS GATE: pass`, 1,344 raw rows, zero failed runs, zero fairness mismatches, every hash matching, both PDFs visually valid, and `e4_e6_may_continue=true`.
