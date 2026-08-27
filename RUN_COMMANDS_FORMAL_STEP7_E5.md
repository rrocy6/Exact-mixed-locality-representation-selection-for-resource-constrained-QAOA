# Formal Step 7 / E5 command

Run from the repository root in the active frozen Python 3.12 environment, after committing the Step 7 implementation files:

```powershell
python ".\run_e5_regime.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --analysis-config ".\configs\e5_analysis_v1.json" `
  --analysis-config-hash ".\configs\e5_analysis_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"
```

Do not pipe this command through `Tee-Object`: E5 requires a clean Git worktree before it creates outputs.
