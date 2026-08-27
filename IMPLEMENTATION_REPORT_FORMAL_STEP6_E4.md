# Formal Step 6 / E4 implementation report

## Scope

This update implements the frozen warm-start and relaxation ablation only. It does not change the Step 2 data freeze, E2 compiler protocol, E3 depth/budget plan, optimizer budget, restart/seed bundles, or primary original-objective scoring.

## Implemented protocol

- Rechecks the complete formal E3 artifact and hash gate before any E4 work.
- Solves one deterministic `scipy.optimize.linprog(method="highs")` SA/RLT level-2 lift per frozen test instance.
- Returns every first moment `mu_i` and pair moment `q_ij` under Boolean McCormick/RLT constraints; cubic lifted variables obey all pair-to-single envelopes.
- Implements the paper's clipped product warm state and matched local mixer.
- Runs only cold, original-variable-only, and original-plus-auxiliary warm starts.
- Uses lifted pair moments as the primary auxiliary initialization and `q_ij=mu_i*mu_j` as the only relaxation ablation.
- Deduplicates original-plus-auxiliary variants whenever a design has no auxiliary qubit.
- Regenerates the cold rows and requires numerical agreement with every formal E3 cold row.
- Retains all restarts and reports original objective, optimum hit rate, encoded energy, and auxiliary inconsistency.

## Verified formal-scale shape

| Check | Result |
|---|---:|
| Frozen test instances | 14 |
| Frozen designs | 112 |
| Designs with active auxiliaries | 20 |
| Optimal SA/RLT solves | 14 |
| Marginal diagnostic rows | 388 |
| Original marginal rows | 96 |
| Pair marginal rows | 292 |
| E4 raw run rows | 3168 |
| Cold rows | 1344 |
| Original-only rows | 1344 |
| Pair-moment rows | 240 |
| Independence-ablation rows | 240 |
| Summary rows | 96 |
| Cold-vs-E3 mismatches | 0 |
| Failed runs | 0 |
| Budget/seed/evaluation/scoring mismatches | 0 |

Eleven instances meet the declared descriptive weak-signal rule: median raw `|mu_i-0.5|` no greater than the frozen clipping delta. They remain in every analysis.

## Outputs

- `results/e4_warmstart_runs.csv`
- `results/e4_marginal_diagnostics.csv`
- `results/e4_warmstart_summary.csv`
- `results/e4_validation_summary.json`
- `tables/table_e4_warmstart.tex`
- `figures/figure_e4_marginals.pdf`
- SHA-256 sidecars for every formal artifact

The formal outputs must be generated on the partner's frozen Windows environment from a clean implementation commit. Local validation used placeholder provenance only and is not shipped as a formal result.
