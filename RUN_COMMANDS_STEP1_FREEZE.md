# Formal Step 1 command summary

The complete guarded workflow is in `APPLY_STEP1_FREEZE.md`. The one command that converts the audited 23-blocker draft into the formal zero-blocker config is:

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

It must report `status=pass`, `remaining_blocker_count=0`, `qmax=12`, `formal_step1_complete=true`, and `formal_step2_started=false`.

The formal config hash must then match:

```powershell
$actual = (Get-FileHash ".\configs\experiment_config_v1.yaml" -Algorithm SHA256).Hash.ToLower()
$stored = (Get-Content ".\configs\experiment_config_v1.sha256" -Raw).Trim()
"HASH MATCH: $($actual -eq $stored)"
```
