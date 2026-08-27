# Formal Step 3 / E1 command

Run from the clean repository root with the frozen pilot environment active:

```powershell
python .\run_e1_exactness.py `
  --config .\configs\experiment_config_v1.yaml `
  --config-hash .\configs\experiment_config_v1.sha256 `
  --data .\data `
  --results .\results `
  --tables .\tables `
  --assumptions .\assumptions_and_decisions.md `
  --run-commands .\RUN_COMMANDS.md
```

The command refuses a dirty Git tree, changed frozen hashes, a failed Step 2
audit, non-exact oracle ground truth, existing E1 output, or any mandatory
strict-exactness failure.
