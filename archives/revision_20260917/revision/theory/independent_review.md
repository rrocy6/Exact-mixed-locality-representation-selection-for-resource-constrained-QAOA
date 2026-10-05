# Independent review of the fresh QAOA study

Reviewed `qaoa_new/run.py`, `protocol.json`, `freeze.json`, `report.py`, the generated manuscript insertion, all 60 raw result files, and selected compiled-study code and witnesses. No frozen implementation or result was changed. The read-only audit is reproducible with `theory/review_qaoa_results.py`; its results are in `independent_qaoa_checks.json`.

## Conclusion

No material numerical or scientific error was found in the new QAOA insertion. The manuscript correctly distinguishes conditional proper-mixed comparisons, finite search budgets, equal-effort optimization, approximate-convergence checks, and original-objective quality. The negative conclusion about mixed representations' solution quality is supported, rather than concealed.

## Executed checks

- All 29 currently frozen source/protocol hashes match. All 60 result files refer to the same freeze; there are 60 distinct instance identifiers and seeds and 480 representation/warming arms.
- Checked every trace's call count, contiguous evaluation numbering, incumbent monotonicity, final best objective, state norm, and equality between recorded optimized objective and final original-objective expectation.
- Confirmed 172,800 equal-effort calls, 64,800 second-optimizer calls, 172,800 scan-refinement calls, and 760,500 grid values. Total: 1,170,900 objective values. Uniform completion counts are exactly 17,959 / 0 / 4,681 for the three optimizer stages, agreeing with the manuscript.
- Loaded all 180 grids: every grid is 65 by 65; recorded minima match the files; every refined result is at least as good as its grid minimum; every zero-phase row equals the prepared-state expectation. The scan adds 4,225 grid values to 960 local-search values per warm arm, giving the stated 5,185.
- Independently reconstructed `max3sat_00`'s proper-mixed, pair-warmed state using an explicit 128-by-128 Kronecker mixer, instead of the simulator or scan mixer. Recomputed original expectation `0.7530905143283937`, prepared expectation `2.499999999999999`, and incremental evolution gain `1.7469094856716054`. Six grid points, including zero phase and both near-period boundaries, agree to at most `1.78e-15`.
- Regenerated that instance's representation selections and matched the complete stored selection metadata. For all 60 instances, each full/proper-mixed arm uses exactly `min(128, domain_size)` distinct scored candidates.
- Independently recalculated both primary native-evolution means and 10,000-resample percentile intervals: Max3SAT `1.151858 [0.958813, 1.343777]`; spin glass `2.133169 [2.004469, 2.237500]`. Both match the manuscript rounding and stored report exactly.

## Scope that must remain explicit

1. “Resource-optimised full” means the best of the same bounded candidate-call protocol, not an exact global minimum. The fresh QAOA selector is seeded candidate sampling, not beam search. A smaller full domain is exhausted rather than padded with duplicate calls; the manuscript already states this correctly.
2. Proper mixed is a restricted comparison arm. It is not the outcome of minimizing over native plus all mixed plus full representations. The sentence acknowledging that an unrestricted selector may choose native must remain.
3. The optimized observable is the original objective while the phase evolution uses the penalized representation. This is an explicitly chosen comparison policy; it does not make auxiliaries consistent or reproduce encoded-energy minimization. Both encoded energy and inconsistency are retained as diagnostics.
4. The scan covers the full periodic parameter rectangle, but its four refinements start from the four lowest grid points, which may belong to one basin. Calling it a sensitivity check is accurate; calling it approximately globally converged or certified would overstate the evidence. Integer encoded energies justify the phase period in this QAOA experiment. That period should not be transferred to the separate fractional-penalty compiler study without rechecking.
5. The full-Q Max3SAT pair-warming secondary interval is positive in this dataset, while the other pair-information comparisons are not consistently positive. The text correctly reports the former without promoting it to a general pair-information contribution.
6. These are local prospective results on 30 small noiseless instances per family, with stated generator conditions. They do not establish a quality threshold on the routed devices or an advantage against a fully optimized classical algorithm. Existing exploratory cohorts remain separate.

## Limited compiler-study review

The technical amendment is explicit: both constructed-family domains are capped at 27 capacity-feasible full candidates, while the 60 random-family runs retain their original 32-candidate protocol. This is correctly labelled an amended mechanism study. The original source and hashes are retained.

The certified phase classification is logically sound: it requires a compiled feasible strict-mixed witness, native width feasibility plus a gate/depth failure, and exhaustive exclusion of every full assignment by logical width/penalty. Using logical width to exclude physical-width feasibility is valid because occupied physical width cannot be smaller. Other phase cells remain finite-library findings, so “none found” must not become “globally infeasible”.

The selected clean ring-12 constructed example has budgets `(Q,G,D,M)=(12,92,48,2.2)`, native `(12,96,55,0)`, mixed `(12,92,43,2.2)`, and a gate/depth-feasible full example `(12,80,40,3.85)`. Its full obstruction is the joint width/penalty condition, not a claim that every full candidate alone exceeds width. This aligns with the saved witness.

One minor interpretation caveat: synthesis-strategy comparisons use identical candidate libraries, but topology-specific libraries can differ through the distance-based seed. Therefore topology Pareto-set Jaccard values can reflect both changed compilation and changed finite libraries. Rank correlations are restricted to common candidate identifiers. If reporting topology Jaccard values, identify them as sampled-library stability; do not interpret them as a controlled exact global-frontier comparison. This does not affect the same-topology/two-synthesis comparison or the certified feasibility witnesses.
