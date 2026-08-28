# Fibre-aware selector v2 rerun commands

After the implementation checkpoint is clean, run the affected formal chain in
this exact order:

```powershell
python ".\run_fibre_e1_e6_v2.py" --step e1
python ".\run_fibre_e1_e6_v2.py" --step e2
python ".\run_fibre_e1_e6_v2.py" --step e3
python ".\run_fibre_e1_e6_v2.py" --step e4
python ".\run_fibre_e1_e6_v2.py" --step e5
python ".\run_fibre_e1_e6_v2.py" --step e6
python ".\run_fibre_e1_e6_v2.py" --step final
```

Every command validates the v2 config, selector package, source manifest hashes,
parent v1 data freeze, and all prior continuation gates before doing work.
`--step all` is also supported, but the explicit sequence above makes failure
recovery and evidence capture easier on Windows.
