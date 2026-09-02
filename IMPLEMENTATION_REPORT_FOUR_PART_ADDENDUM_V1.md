# Four-part addendum v1 implementation report

## Scope and immutability

The implementation is additive to parent checkpoint `1a4f866`. All newly
computed experimental artifacts are confined to `four_part_addendum_v1`.
Frozen E1--E6 raw data, exactness outputs, SA/RLT bundle, benchmark outputs,
old E3/E4/E6 runs, tables, figures, and manifests are read-only inputs.

Each experimental phase writes `RUN_STATE.json`. A completed phase is rejected
on every later run, including `--resume`. An interrupted phase can be resumed
only when its config hash is unchanged. The final builder requires four
passing phase audits before constructing a SHA-256 manifest and ZIP.

## Certification

The previous oracle certificate used complete leaf enumeration. The addendum
performs a real priority-queue branch-and-bound search. A partial node lower
bound contains the monotone, nonnegative auxiliary-count and maximum-penalty
coordinates. Gate and depth lower bounds are conservatively zero because
native completion can change those values non-monotonically. Capacity and
penalty hard limits prune partial nodes. A node is objective-pruned only when
its lower bound is strictly greater than the incumbent, preserving the frozen
risk and lexicographic tie-breaks.

The frontier is exhausted. At that point the global lower bound is set to the
incumbent upper bound, giving a zero final gap. The phase additionally requires
the certified objective to match the frozen complete-enumeration objective on
all 60 oracle instances.

## Hardware topologies

The new coupling maps are a bidirectional 12-node line, bidirectional 12-node
ring, and Qiskit distance-3 19-node heavy-hex graph. Compilation uses the
unchanged basis gates, layout, routing, translation, optimization level, and
five transpiler seeds. Post-compilation two-qubit edges are checked against the
declared map. Logical-width failures remain explicit scheduled rows. The phase
reports qubit capacity, two-qubit gate count/depth, SWAP estimate, routing
overhead, runtime, and status. It executes zero QAOA runs.

## Selector ablation

The main setting remains `(0.05,0.45,0.45,0.05)`, beam width 64, fibre
threshold 0.02, and positive penalty margin 1.0. All other settings differ
from main in exactly one factor. The weight variants include equal,
auxiliary-heavy, penalty-heavy, gate-only, depth-only, and gate-depth joint
objectives. Beam widths are 16/32/64/128, thresholds are
0/0.01/0.02/0.05/0.1, and margins are 0.5/1/2. Baselines are the existing
deterministic fibre-aware greedy selector and a deterministic maximum-reuse
rule with lexicographic ties. No old QAOA or noise experiment is called.

The existing resource evaluators now obtain the strictly positive penalty
margin from `selector.fibre_risk.positive_penalty_margin`; the parent value is
1, so frozen main behavior is unchanged while the margin ablation is genuine.

## Strong-bias warm-start

The candidate pool is generated deterministically for both benchmark
families. Every candidate receives the same two-stage deterministic SA/RLT
level-2 solve and the frozen fibre-aware selector. Only feasible selective
designs with at least one active auxiliary and at most 12 encoded qubits enter
screening.

Screening ranks, within family, by median `|mu_i-0.5|`, then mean active-pair
`|clip(q_ij)-clip(mu_i)clip(mu_j)|`, then instance ID. The screening function
rejects any column containing `qaoa` or an outcome field. Ten instances per
family are selected before QAOA is run.

The new experiment uses only the selective representation, noiseless
statevectors, `p=1,2`, the four declared cold/original/pair-moment/independence
policies, three restarts, and 60 COBYLA evaluations. The unchanged sparse
compiler and five seeds establish the per-layer two-qubit cost. Exact small-n
enumeration supplies the original-objective optimum only for scoring the new
instances. Confidence intervals use instances as uncertainty units via the
corrected E4 summarizer.

## Compatibility repair and tests

The supplied source archive contains a Windows CRLF transformation of signed
selector-bundle text files while the sidecars describe LF bytes. Bundle
verification now accepts this transport only if LF normalization reproduces
both the exact declared digest and declared size. Arbitrary content changes
still fail.

Twelve addendum-specific unit tests cover the certificate, topology definitions,
one-factor-at-a-time design, penalty-margin behavior, deterministic baseline,
screening isolation, and non-overwrite state machine. The full frozen suite is
run in the pinned environment before packaging.
