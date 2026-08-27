# Formal Step 8 / E6 command

```powershell
python ".\run_e6_noise.py" `
  --config ".\configs\experiment_config_v1.yaml" `
  --config-hash ".\configs\experiment_config_v1.sha256" `
  --protocol-config ".\configs\e6_noise_v1.json" `
  --protocol-config-hash ".\configs\e6_noise_v1.sha256" `
  --data ".\data" `
  --results ".\results" `
  --tables ".\tables" `
  --figures ".\figures" `
  --assumptions ".\assumptions_and_decisions.md" `
  --run-commands ".\RUN_COMMANDS.md"
```

Required result: `E6 LIMITED-NOISE GATE: pass`,
`final_result_pack_may_be_built=true`, 1296 raw rows, 24 summary rows, and zero
fairness/scope failures.
