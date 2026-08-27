# Formal Step 1 freeze implementation report

## Outcome

This update turns the existing audited `1.0-draft.2` configuration into `experiment_config_v1`, version `1.0`, only after validating the Windows reference-pilot evidence. It resolves exactly the remaining 23 blockers and creates no formal data manifest or split.

Local verification completed with:

- 29/29 pipeline tests passing;
- the existing reference pilot reproduced as evidence input;
- final config validator reporting `frozen`, `freeze_blocked=false`, and `remaining_blocker_count=0`;
- formal config SHA-256 matching its sidecar file;
- guarded updates to `assumptions_and_decisions.md` and `RUN_COMMANDS.md`.

## Frozen decisions

| Area | Frozen value |
|---|---|
| Common QAOA width | `Qmax=12` |
| Qmax basis | Largest predeclared synthetic width passed by the Windows pilot |
| Selector weights | Equal `0.25` weights for auxiliaries, 2Q gates, 2Q depth, and maximum penalty |
| Selector search | Beam width `64`; complete oracle budget `65,536` candidates |
| Sparse topology | Bidirectional 3-by-4 rectangular grid on 12 qubits |
| Basis / compiler | `rz`, `sx`, `x`, `cx`; optimisation level 1; SABRE layout/routing; translator; scheduling disabled |
| Equal-layer QAOA | `p = 1, 2` |
| Equal-2Q budgets | `128, 256` two-qubit gates |
| Optimizer | COBYLA; 60 evaluations; 3 restarts; tolerance `1e-3` |
| Sampled/noisy shots | `4096` |
| Warm-start clipping | `0.05` |
| Noise | Aer local depolarizing plus symmetric readout; exactly two nonzero levels |

The detailed topology, limits, noise probabilities, rationale, and exact blocker list are machine-readable in `configs/step1_freeze_decisions_v1.json` and copied into the final config provenance.

## Guardrails

The finalizer stops without freezing when any of the following occurs:

- the draft does not contain the exact audited 23 blockers;
- SciPy/Qiskit/Aer versions differ from the frozen pilot stack;
- the pilot config or audit hash does not match;
- exactness or any statevector probe failed;
- width 12 is not the largest predeclared passing synthetic probe;
- the sparse topology does not cover exactly 12 qubits bidirectionally;
- the evidence output is nonempty or a formal config already exists.

## Scope boundary

The final audit deliberately records:

```text
formal_step1_complete: true
formal_step2_started: false
formal_manifest_created: false
formal_split_created: false
```

The next commit may implement and run formal Step 2 against this immutable config hash.
