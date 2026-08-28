# E1/E2 correction command

```powershell
$correctionArguments = @(
  ".\run_e1_e2_corrections.py"
  "--config"
  ".\configs\experiment_config_v1.yaml"
  "--config-hash"
  ".\configs\experiment_config_v1.sha256"
  "--data"
  ".\data"
  "--results"
  ".\results"
  "--output"
  ".\corrections\e1_e2_v1"
  "--e3-source"
  ".\urss_pipeline\e3_qaoa.py"
)

python @correctionArguments
```

Required result: `E1/E2 CORRECTION GATE: pass`.

The command reads existing frozen E1/E2 artifacts, performs no E2
recompilation, and never overwrites the original results.
