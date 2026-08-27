# Formal Step 4 / E2 command

Run from a clean committed Step 4 implementation checkpoint in Windows
PowerShell 5.1:

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

Do not pipe the formal command through `Tee-Object`: creating the evidence
file first would make Git dirty and trigger the implementation-commit guard.
The run keeps all five transpiler-seed rows and all compiler failures. Widths
that exceed the frozen 12-qubit sparse topology are retained as
`infeasible_width_exceeds_topology` rather than removed.

Required final lines:

```text
E2 RESOURCE GATE: pass
E2 EXIT CODE: 0
```
