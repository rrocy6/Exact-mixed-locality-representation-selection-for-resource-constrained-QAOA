Warm-start comparisons previously used different optimizer beta coordinates for cold and matched warm mixers. This correction uses a common coordinate and enforces all-qubit-half null controls.

The frozen correction plan is complete: 480 targeted tasks and 4,320 original E4 tasks, comprising 4,332 fresh optimizations and 468 validated zero-layer initial-state records. There are no failed or missing tasks. The targeted Max-3SAT improvement over cold remains; all primary original E4 pair-minus-cold instance-level Student-t intervals include zero. Applying the same Student-t method to archived E4 results also gives intervals containing zero, so the change in claim strength cannot be attributed only to the mixer.

The execution environment differs from the archived Windows environment. All positive-depth cold tasks were rerun uniformly. Historical marginals, designs, seeds, and budgets were retained; no new LP or instance screening was run.

Original execution snapshot: `1301a48c88d27ddc47c4fe10c547745d6fe28d9b` (local execution snapshot, distinct from this repository integration commit). The release tag identifies the integration version. Historical binding and source archive are preserved unchanged.

Attach the complete file `URSS_WARMSTART_CORRECTION_EXECUTED_v1.zip` (40,786,450 bytes).
SHA-256: `9e539a0aa387393e482e5ac0f186ace9695af39d05017fe3bc90eefefe5dd5e5`.

The source branch includes synthetic regression coverage and a compact audit/analysis record. The ZIP additionally includes full raw rows, frozen physical inputs, and all per-task traces. It contains an independently compiled correction preview and a patch of the old manuscript snapshot. Integration into the latest Overleaf manuscript is pending; Table 13/kappa and margin sensitivity remain separate work.
