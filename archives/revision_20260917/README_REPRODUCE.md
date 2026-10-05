# URSS revision: code and evidence

The Overleaf manuscript is in `revision/overleaf/main.tex`. Only that file changed among original project files. The new scientific work is in `revision/experiments`, `revision/qaoa_new` and `revision/theory`; reused original Python helpers and the raw-instance archive needed for overlap checks are in `revision/code/source`.

Read `revision/修改说明与审核结论.md` for the point-by-point Chinese explanation. Each experiment directory has its own protocol and results README. The new studies were actually executed; raw instance-level data, all QAOA optimisation traces, scanned surfaces, compiler resource records, frozen hashes and a disclosed technical amendment are included.

## Environment and verification

Tested with Python 3.12 on Windows. Install `requirements-revision.txt` in a dedicated environment. The scientific dependency versions match the actual runs. `pypdf` is needed only for document QA, not the experiments.

From the archive root:

```powershell
python -m venv .venv
& .venv/Scripts/Activate.ps1
python -m pip install -r requirements-revision.txt
python revision/qaoa_new/run.py test
python revision/qaoa_new/run.py verify
python revision/experiments/compiled_study.py verify
python revision/theory/verify_theory.py
python revision/theory/review_qaoa_results.py
python revision/validate_delivery.py
```

`verify_theory.py` and `validate_delivery.py` use the Python standard library. `review_qaoa_results.py` independently checks all QAOA records and reconstructs a state with a dense matrix. The original freeze uses Windows-relative path strings; Windows is the supported exact replay platform of this delivery.

To regenerate reports from saved results:

```powershell
python revision/qaoa_new/report.py
python revision/experiments/analyse_compiled_study.py
python revision/experiments/audit_compiled_results.py
python revision/build_resource_supplement.py
```

The experiment runners resume existing results. Follow their directory READMEs to rerun simulations or compilation in a separate copy while preserving the delivered provenance. Do not overwrite the original freeze to present a rerun as a new confirmatory cohort. The constructed compiler family has a documented 32-to-27 candidate-cap correction; both full and mixed search receive the same count.

`revision/revise_manuscript.py` rebuilds the root manuscript from `main.original.tex` and checked-in insertion text. It does not modify any other original TeX file. `revision/validate_delivery.py` checks original-file integrity, references, figures, experiment counts and original/amended source hashes.

The standalone Overleaf ZIP needs no Python or experimental software. Its bibliography and all figures are bundled. The preview PDF was compiled with Tectonic 0.17.0; Overleaf should use the root `main.tex` and current pdfLaTeX. The complete historical code/result ZIP supplied by the user remains the authority for old experiments; this focused archive carries the helpers and raw objectives needed by the newly executed studies, not every historical output archive.

## Interpretation

This is evidence for exact resource-constrained representation selection. It is not evidence of a general mixed-representation QAOA-quality advantage. A finite candidate library's failure to find a representation is not global infeasibility. Certified mixed-only cells have a separate exhaustive full-endpoint exclusion. Circuit resources concern cost-layer CX count and depth plus actual physical routing footprint, not pulse duration. Both compiler strategies use the same Qiskit version and seed.
