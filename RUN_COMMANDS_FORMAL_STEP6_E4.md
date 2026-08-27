# Formal Step 6 / E4 command

Run from the repository root in the active frozen Python 3.12 environment, after committing the Step 6 implementation files:

```powershell
python ".\run_e4_warmstart.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"
```

Do not pipe this command through `Tee-Object`: E4 requires a clean Git worktree before it creates outputs. The program prints progress after each of the 14 frozen instances.
