# E1/E4 post-processing correction commands

```powershell
python ".\run_pipeline_tests.py"
python ".\repair_fibre_e1_e4_postprocess_v2.py" `
  --output ".\fibre_e1_e6_v2" `
  --config ".\configs\experiment_config_v2.yaml" `
  --config-hash ".\configs\experiment_config_v2.sha256"
python ".\run_fibre_e1_e6_v2.py" --step final
```

The second command reads the existing E4 raw-run CSV and rewrites only derived
summaries, validation provenance, and sidecars. The final command only rebuilds
the completion audit, package manifest, ZIP, and ZIP sidecar. No E1--E6
experiment command is part of this correction.
