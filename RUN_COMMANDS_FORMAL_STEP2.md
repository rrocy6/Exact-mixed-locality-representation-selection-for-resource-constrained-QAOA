# Formal Step 2 command summary

The complete two-commit workflow and verification commands are in `APPLY_FORMAL_STEP2.md`.

After committing the implementation and confirming a clean worktree, run:

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

Successful completion prints `DATA FREEZE GATE: pass` and creates the four formal manifests, ground truth, metadata, hashes, JSON audit, and HTML audit under `data/`.
