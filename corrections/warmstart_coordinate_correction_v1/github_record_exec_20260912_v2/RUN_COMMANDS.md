# RUN_COMMANDS — actual executed sequence

These commands describe this completed Linux run. They are not instructions to overwrite its output directory. The source ZIP is an exact as-executed snapshot. A future run requires a new execution ID and a truthful new binding, including that the present corrected outcomes have already been viewed.

Working root: /workspace/scratch/870f211b1fbc
Working engine: correction_engine/
Environment for every executor/postprocessing command:

```bash
export PYTHONPATH=/workspace/scratch/870f211b1fbc/test_dependencies
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
```

1. Materialize exact frozen inputs, reconstruct archived moments and designs, validate every old saved-parameter row:

```bash
python warmstart_correction.py prepare --repo ../urss_work --plan ../correction_plan/URSS_warmstart_correction_plan_v1 --output ../corrections/warmstart_coordinate_correction_v1/exec_20260912_v1
```

2. The initial source snapshot 74c8e8e83387ebef9fde8213e22395858038247d was bound and passed its regression tests. Its run entry rejected array-form TASK_INPUTS.json before workers started. The binding, exact source archive and blocker remain in exec_20260912_v1. No formal optimization outcomes were produced. Copy the preparation assets byte-for-byte to v2; see EXECUTION_LINEAGE.json. Fix the array reader and commit 1301a48c88d27ddc47c4fe10c547745d6fe28d9b.

3. Bind corrected source; 26 synthetic/null/executor tests pass:

```bash
python warmstart_correction.py bind --output ../corrections/warmstart_coordinate_correction_v1/exec_20260912_v2 --workers 4
```

4. Run A, then compute CHECKPOINT_CONTRASTS.csv and CHECKPOINT_DECISION.json using the bound aggregate() and actual A rows. A technical completion gates B, not effect significance:

```bash
python warmstart_correction.py run --output ../corrections/warmstart_coordinate_correction_v1/exec_20260912_v2 --study targeted
python warmstart_correction.py run --output ../corrections/warmstart_coordinate_correction_v1/exec_20260912_v2 --study original_e4
python postprocess_correction.py --output ../corrections/warmstart_coordinate_correction_v1/exec_20260912_v2
```

5. From the working root, run FINALIZE_SOURCE.py (distributed copy of finalize_correction.py). This is separate post-execution audit/presentation code; it does not modify experimental inputs or bound optimizer implementation. It verifies all 4,800 identities, source commits, attempts and parameter traces, and generates manuscript materials. Its absolute ROOT assumes this recorded workspace layout; adapt output paths for independent reanalysis and record the adaptation.

6. From manuscript_snapshot/:

```bash
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../latex_preview correction_preview.tex
latexmk -pdf -interaction=nonstopmode -halt-on-error -outdir=../latex_snapshot main.tex
```

The preview succeeds; full snapshot compilation reports missing quantumarticle.cls. Actual build logs are retained. Manuscript rendering did not rerun experiments.

7. Package via PACKAGE_SOURCE.py; `verify_delivery.py` verifies the delivered file manifest and 4,800 task identities using only Python's standard library. ENVIRONMENT.json and EXECUTION_DEPENDENCIES.txt record the actual environment; the historical snapshots are separately retained under source_inputs/.
