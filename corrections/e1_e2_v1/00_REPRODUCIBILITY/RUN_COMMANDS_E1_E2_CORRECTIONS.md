# Exact correction command

```powershell
python .\run_e1_e2_corrections.py `
  --config .\configs\experiment_config_v1.yaml `
  --config-hash .\configs\experiment_config_v1.sha256 `
  --data .\data `
  --results .\results `
  --output .\corrections\e1_e2_v1 `
  --e3-source .\urss_pipeline\e3_qaoa.py
```
