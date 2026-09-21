# Compiled-resource revision: results and boundaries

The complete experiment has 90 instances, 540 instance/target/synthesis settings, 31,577 compiler calls after memoization (including controls), and 32,760 scheduled search evaluations before reusing repeated candidate results. Each setting has 20,923 frozen budget cells. The underlying independent sample sizes are 30 per family, not the circuit or cell counts.

## Main findings

Certified strict-mixed-only cells exclude every direct-pair full reduction by a joint logical width/penalty certificate, require native to fit physical width but fail compiled gate/depth, and exhibit a feasible compiled mixed design. At least one certified cell occurs in 23/30 Max3SAT, 2/30 cubic-spin, and 30/30 constructed instances across any setting. It occurs in all six settings for 3/30, 0/30 and 21/30 respectively. The spin family has **no** mixed-only cells under reuse synthesis. Therefore the result does not establish universal compiler-robust necessity.

The best proper mixed candidate has lower scalar J than the resource-optimized full candidate in every setting, under equal candidate counts. However the unrestricted mixed selector chooses native in every random-family setting and 173/180 constructed settings. The existence of a hard-budget feasible mixed representation must not be confused with preference for a mixed representation under unconstrained J, much less improved QAOA quality.

The strongest concrete example is in `audit.json`: the first indexed constructed instance, ring-12, canonical synthesis, budget (Q,G,D,M)=(12,92,48,2.2). Native=(12,96,55,0), a full candidate=(12,80,40,3.85), and a mixed candidate=(12,92,43,2.2). Every full assignment with logical width <=12 has M>=2.475; the other full assignments exceed width. This example is explicitly a post-hoc explanatory selection from the unchanged frozen grid. All three stored circuits were independently recompiled, reproducing the resource records.

Minimum-auxiliary, maximum-reuse, resource-optimized full, and bespoke graph-distance-aware baselines are saved for each setting. The last is labelled inspired, not a faithful reproduction of a named literature implementation. Random controls match auxiliary count and reduced cubic count; 495/540 also have a distinct exact penalty match, while 15 have no distinct required-count match and are recorded as degenerate. Controls sometimes beat the selected strict mixed candidate.

## Compilation and stability limits

Q is physical active footprint: all initially occupied sites plus every site touched during routing. `logical_Q` is n+aux. G and D are compiled CX count and CX-only scheduled depth for the cost layer, excluding state preparation and mixers. They are not pulse duration or a full QAOA execution budget. Symbolic gamma prevents special-angle shortcuts. All three topologies have capacity12 and use a fixed identity initial placement. Two gadget orderings and cross-gadget optimization are tested within Qiskit2.5.2, with one seed; this is not independent-compiler or seed-distribution evidence.

Within a topology, canonical/reuse strategies have identical candidate banks, and Spearman rho compares common candidate identities. Pareto sets use (Q,G,D,M), and their Jaccard overlap compares all archived candidates. Across topologies, the distance-aware seed can change the bank: Spearman still uses the common subset, while Pareto Jaccard describes **sampled-library stability** and is not a pure connectivity effect. Only within-topology synthesis results are quoted in the manuscript insert. The provided raw stability file preserves both analyses.

The five-class map is library-relative except where explicit certificates apply. The constructed family exhaustively covers all capacity-feasible full assignments, but its mixed library is finite. “None found” never proves no feasible mixed representation exists. In endpoint-only classes, mixed designs may also be feasible; the label describes the endpoints.

## Provenance and amendment

`compiled_results/freeze.json` is the original pre-generation freeze. Its source hash matches `compiled_study_frozen_v1.py`, and its protocol hash matches `COMPILED_PROTOCOL_frozen_v1.md`. All 60 random-family results used that original code. Before any constructed-family results were produced, its 32-candidate assertion failed because only27 full assignments fit capacity12. `amendment_01.json` records the repair: both search spaces use min(32, eligible full assignments), giving27 each in that family. The generator, data, objective, compiler settings and budgets were unchanged. The current source hash matches the amendment. The constructed cohort is an amended mechanism study; only the original60 are described as following the original prospective protocol.

## Files

- `compiled_study.py`: generation, representation, real symbolic compilation, equal-budget selection, semantic checks and resumable execution.
- `compiled_study_frozen_v1.py`: immutable original frozen source.
- `analyse_compiled_study.py`: all budget classifications, summary metrics, rank/frontier comparisons and figures.
- `audit_compiled_results.py`: stronger explanatory witnesses, cross-setting counts, independent witness recompilation.
- `compiled_results/instances_frozen.json`: all90 independent inputs, generated after the original freeze.
- `compiled_results/instances/*.json`: every action, compiled resource vector, selected baseline and exhaustive full logical assignment.
- `compiled_results/summary.json`, `per_instance_phase_counts.json`, `stability.json`: fully traceable aggregate results.
- `compiled_results/phase_counts.npz`, `certified_phase_counts.npz`: all five-class and certified population counts, axes in the frozen config.
- `compiled_results/joint_budget_phase_map.pdf`: first-indexed constructed instance, fixed D=96/M=4.4 slice.
- `compiled_results/joint_budget_certified_frequency.pdf`: all30 constructed instances in the same slice.
- `compiled_results/semantic_checks.json`: exhaustive development-instance value checks,32 logical unitaries,12 routed-statevector checks; maximum error7.11e-16.
- `compiled_manuscript_insert.tex`: suggested prose for integration into main.tex only.

## Reproduction

Use Python3.12, Qiskit2.5.2, NumPy2.5.3, SciPy1.18.1 and Matplotlib3.11.2 (full recorded versions are in the freeze). Activate the dedicated environment installed using the archive-root `requirements-revision.txt`. From this directory:

```text
python compiled_study.py verify
python compiled_study.py run --workers 4
python analyse_compiled_study.py
python audit_compiled_results.py
```

The run resumes already completed records. To recompile all circuits, make a complete copy of the delivered archive, retain the supplied freeze, amendment, frozen source/protocol and `instances_frozen.json`, move that copy's `compiled_results/instances` directory to a backup location, then run the commands above. This reuses the same frozen inputs and is a replication, not a new confirmatory cohort. The current source already includes the capacity-based equal-budget rule. The analysis script intentionally validates the delivered original freeze and amendment; replacing them with a newly generated freeze is not a supported replay path. Do not overwrite the supplied original freeze or its amendment.

