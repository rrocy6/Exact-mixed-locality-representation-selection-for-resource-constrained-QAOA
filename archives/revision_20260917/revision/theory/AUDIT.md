# Theory audit and integration notes

The supplied short note is mathematically sound within its explicitly restricted direct semantic pair grammar. The integration draft is `static_compiled_section.tex`; it deliberately does not change any manuscript file.

## Necessary clarifications made

- The note budgets the sharp threshold `T_p`; the manuscript implements `M_p=T_p+epsilon`. These are different resources. The integrated result budgets the actual penalty and replaces `floor(Lambda_0)` by `floor(M_0-epsilon)`. Taking `epsilon=0` recovers value exactness, not unique consistent auxiliaries.
- Auxiliary degree `q_p+2` is correct for direct cubic pair substitutions. It must not be presented as a universal degree formula for arbitrary quadratizations or sequential higher-order substitutions.
- The class labels “native only” and “full-Q only” mean only that endpoint is feasible; mixed representations can also exist in those classes. “Mixed only” does exclude both endpoints.
- `K_Q` is a capacity for static resources. A compiler with term interactions or cancellation does not generally reduce to this cardinality invariant. The new compiled theorem is a separate construction for a declared compiler.
- All full-Q exclusions quantify over every assignment in the declared pair grammar. They do not rule out unrestricted Boolean auxiliary encodings.
- No result implies improved QAOA objective values. Exactness is equality after minimisation over auxiliaries, not dynamical equivalence.

## New compiled corollary

It uses exactly the existing manuscript's reference compiler: collected exact Pauli expansion, weight/lexicographic ordering, largest-index parity target, no cross-gadget cancellation, and earliest CNOT-layer scheduling on all-to-all connectivity. Counts are one cost layer, excluding one-qubit durations.

For an `L>=2`-petal unit pair-star plus `H>=1` isolated unit triples, with `n=L+2+3H`:

| Representation | Width | CNOT count | CNOT depth | Maximum penalty |
|---|---:|---:|---:|---:|
| Native | n | 8L+2+10H | 6L+3 | 0 |
| Reduce star only | n+1 | 2L+6+10H | 2L+6 | L+epsilon |
| Full, shared core | n+H+1 | 2L+6+8H | 2L+6 | L+epsilon |

Set the four budgets equal to the mixed row. Native violates both gate and depth. Every full pair reduction needs at least `H+1` auxiliaries, so all full representations violate width. This is an infinite class, with one-qubit affine additions also permitted without affecting the two-qubit counts.

For example `L=2,H=1` gives `n=7`: native `(7,28,15,0)`, mixed `(8,20,10,2+epsilon)`, full-core `(9,18,10,2+epsilon)`. A budget `(8,20,10,2+epsilon)` therefore forces a mixed representation.

The theorem intentionally does not claim compiler robustness. Cross-gadget cancellation, joint synthesis, reordered gadgets and routed hardware must be assessed with the new experiments; their resource values may change.

## Independent verification

`verify_theory.py` contains no external dependencies and does not import the implementation being checked. It enumerates all four local decisions (native/three possible pairs) for small forests; expands the resulting Boolean polynomial into exact rational Pauli coefficients; and emits and schedules actual CNOT streams.

The run passed:

- 301 static `(forest,r_0,C)` cases; all native budgets were additionally checked for each case.
- 248 compiled family instances (`2<=L<=32`, `1<=H<=8`), three representations each, with exact agreement with the formulas.
- 17,280 original assignments in exhaustive pointwise-exactness and unique-lift checks for `2<=L<=5`, `1<=H<=2` and `epsilon=1/4`.

The detailed output is `verification_results.json`. These checks support the algebra; they are not empirical QAOA evidence or hardware/compiler robustness evidence.
