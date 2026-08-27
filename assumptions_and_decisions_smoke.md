# Smoke pipeline assumptions and decisions

## Scope

This implementation is a non-formal validation batch. Its outputs use
`tier=smoke` and `split=smoke_not_formal`. They must not be merged into a frozen
train/validation/test manifest or used for performance claims.

## Implemented draft decisions

- Raw IDs use canonical ASCII JSON, sorted keys, compact separators, SHA-256,
  and the `inst_` prefix described in `instance_schema_v1.md`.
- Max-3SAT clauses are stored as atomic `{literals, weight}` records.
- Literals are ordered by increasing absolute variable index.
- Generated instances require nonnegative fixed seeds.
- Manual golden examples may use null seeds.
- Redundant density fields are stored but excluded from identity material.
- Spin-glass lower-order terms are represented by `c=0`, `h=[]`, and `J=[]`.

These are implementations of the current schema draft, not evidence that joint
approval D1-D10 has already occurred.

## Smoke-only parameters

- Master seed: `20260827`.
- Validation seed: `20260828`.
- Four instances: uniform and anchor-pair proposals for both families.
- Size: `n=6`.
- Max-3SAT requested density: `m/n=2`.
- Spin-glass requested load: `m/n=1`.
- Maximum validation assignments: `1024`; all four smoke instances therefore
  receive exhaustive `2^6=64` assignment checks.

These values validate mechanics only. They do not set the formal dataset seed
bundle, sample counts, reuse coverage, split seed, Qmax, or QAOA settings.

## Safety and reproducibility behaviour

- A non-empty output directory causes the runner to stop instead of silently
  overwriting evidence.
- Every generated instance is regenerated once from the same seed and compared
  before it is written.
- JSON Schema validation, semantic validation, instance-ID recomputation, and
  direct-vs-canonical validation must all pass.
- Output JSON and CSV files use deterministic ordering and LF line endings.
- Timestamps are read from the versioned smoke config instead of the wall clock.
