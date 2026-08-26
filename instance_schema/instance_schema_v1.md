# URSS Raw Instance Schema v1.0 - Draft

**Derived from:** `benchmark_spec_v1.0`  
**Source SHA-256:** `7ce13bdf2135fed2e34eddffeb2cde75ec25ee9c284adfd9177b63e487af78cb`  
**Owner:** Code / Numerical Pipeline负责人  
**Reviewers:** Benchmark / Applications负责人 and project lead  
**Status:** Draft; not frozen

## 1. Purpose and boundary

This schema is the machine-facing contract for a **raw mathematical benchmark
instance**. It supports:

1. weighted Max-3SAT;
2. pure cubic spin glass.

It intentionally excludes the following downstream data:

- canonical PUBO coefficients and derived structural features;
- native/selective/full/random representation choices;
- auxiliary variables, pair assignments, thresholds, or penalties;
- train/validation/test split and tier membership;
- topology, compiler, QAOA, optimizer, shots, or noise configuration;
- ground truth and experimental results.

Those data belong in canonical/metadata, design, manifest, compiler/run,
ground-truth, or result schemas. Keeping them out ensures that all
representations of the same raw mathematical problem share one `instance_id`.

## 2. Top-level model

The draft uses a common envelope plus a family-specific payload:

```text
RawInstance
  schema_version
  spec_version
  family
  normalisation_convention
  conventions
  problem
  generation
  instance_id
```

`family` is the discriminator:

```text
family = "max3sat"           -> Max3SAT payload
family = "cubic_spin_glass" -> CubicSpinGlass payload
```

## 3. Common fields

| Field | Type | Required | Meaning | In identity material? |
|---|---|---:|---|---:|
| `schema_version` | string | yes | File-contract version | no |
| `spec_version` | string | yes | Benchmark mathematical-definition version | yes |
| `family` | enum | yes | `max3sat` or `cubic_spin_glass` | yes |
| `normalisation_convention` | string | yes | V1 is `none` | yes |
| `conventions` | object | yes | Variable/index/objective conventions | yes |
| `problem` | object | yes | Raw mathematical data | partly; see Section 7 |
| `generation` | object | yes | Reproduction provenance | only `generator_version` |
| `instance_id` | string | yes | Content-derived stable identity | computed output |

### 3.1 Generation provenance

| Field | Type | Required | Rule |
|---|---|---:|---|
| `generator_mode` | enum | yes | `uniform`, `anchor_pair`, or `manual_golden` |
| `generator_parameters` | object | yes | Mode-specific configuration |
| `master_seed` | integer/null | yes | Nonnegative integer except proposed manual exception |
| `instance_seed` | integer/null | yes | Nonnegative integer except proposed manual exception |
| `generator_version` | string | yes | Version of generation logic |
| `rejection_count` | integer | no | Number of rejected proposals before acceptance |

For generated benchmark data, both seeds must be nonnegative integers. The
draft permits `null` only for `manual_golden`; this exception requires approval.

## 4. Weighted Max-3SAT payload

### 4.1 Conventions

```text
domain           = binary_0_1
indexing         = one_based
literal_encoding = signed_integer_positive_is_x_negative_is_not_x
objective_sense  = minimize
```

### 4.2 Problem fields

| Field | Type | Required | Rule |
|---|---|---:|---|
| `n` | integer | yes | `n >= 3` |
| `m_clause` | integer | yes | Must equal `len(clauses)` |
| `clauses` | array of clause records | yes | At least one clause |
| `clause_density` | number | yes | Must equal `m_clause / n` |

Each clause record is:

```json
{
  "literals": [-1, -2, -3],
  "weight": 5
}
```

Optional `signed_clause_hash` may be stored for audit after its hash input is
approved. It is not part of the mathematical identity material.

### 4.3 Required semantic validation

For each clause:

1. exactly three literals;
2. every literal is a nonzero integer;
3. `1 <= abs(literal) <= n`;
4. three distinct absolute variable indices;
5. canonical literal order is increasing absolute variable index;
6. weight is an integer in `{1,2,3,4,5}`;
7. no duplicate canonical signed-literal triple, regardless of weight.

For the whole instance:

1. `m_clause == len(clauses)`;
2. each variable `1,...,n` occurs in at least one clause;
3. `clause_density == m_clause/n` in the semantic rational model;
4. the stored `instance_id` equals the recomputed ID.

Different sign patterns over the same unsigned variable triple are allowed.

## 5. Cubic spin-glass payload

### 5.1 Conventions

```text
raw_domain        = spin_minus1_plus1
canonical_domain  = binary_0_1
indexing          = one_based
boolean_conversion = s=1-2x
objective_sense   = minimize
```

### 5.2 Problem fields

| Field | Type | Required | Rule |
|---|---|---:|---|
| `n` | integer | yes | `n >= 3` |
| `m_edge` | integer | yes | Must equal `len(hyperedges)` |
| `hyperedges` | array | yes | Unique cubic hyperedges |
| `c` | integer | yes | Exactly `0` in V1 main benchmark |
| `h` | array | yes | Empty sparse nonzero-term list in V1 |
| `J` | array | yes | Empty sparse nonzero-term list in V1 |
| `hyperedge_density` | number | yes | `m_edge / choose(n,3)` |

Each hyperedge record is:

```json
{
  "variables": [1, 2, 3],
  "coefficient": -1
}
```

### 5.3 Required semantic validation

1. every hyperedge has exactly three variables;
2. `1 <= i < j < k <= n`;
3. no duplicate unordered hyperedge;
4. coefficient is exactly `-1` or `+1`;
5. `m_edge == len(hyperedges)`;
6. each variable `1,...,n` occurs in at least one hyperedge;
7. `hyperedge_density == m_edge/choose(n,3)`;
8. `c == 0`, `h == []`, and `J == []`;
9. the stored `instance_id` equals the recomputed ID.

## 6. Raw versus derived data

The following are **not raw identity fields** and must be computed after
canonical coefficient aggregation:

```text
canonical_term_count
canonical_degree
m3
cubic_density
cubics_per_variable
pair_shadow_size
pair_reuse_score
Delta2
pair-degree statistics
tau2 and its status/bounds
coefficient masses
canonical cancellation statistics
```

`clause_density` and `hyperedge_density` are retained in the raw record because
the Benchmark Spec explicitly lists them as required raw fields. They are
redundant checks and are excluded from identity material.

`split` and `tier` belong in metadata/manifests. They must not affect instance
identity.

## 7. Canonical identity procedure

The Benchmark Spec requires a content-derived deterministic ID but does not
freeze the hash algorithm or byte serialization. This draft proposes the
following procedure.

### 7.1 Normalize family payload

Max-3SAT:

1. sort literals within each clause by increasing absolute variable index;
2. sort clause records lexicographically by `literals`, then `weight`;
3. identity payload contains only `n` and the normalized clause records.

Cubic spin glass:

1. sort variables in every hyperedge so `i<j<k`;
2. sort hyperedge records lexicographically by `variables`, then coefficient;
3. identity payload contains `n`, hyperedges, `c`, `h`, and `J`.

### 7.2 Construct identity material

```json
{
  "family": "...",
  "generator_version": "...",
  "normalisation_convention": "none",
  "raw_mathematical_instance": {},
  "spec_version": "benchmark_spec_v1.0",
  "variable_convention": {}
}
```

Explicitly excluded:

- `schema_version`;
- `instance_id` itself;
- generator mode, parameters, seeds, and rejection count;
- redundant density/count fields when determined by the payload;
- signed-clause audit hashes;
- timestamp, raw filename, and storage path;
- split and tier;
- canonical/derived metadata;
- representation, topology, compiler, QAOA, optimizer, noise, and results.

The Spec explicitly includes `generator_version` in identity material; this
draft follows that requirement even when two generator versions produce the
same raw clauses/hyperedges.

### 7.3 Serialize and hash

Draft proposal:

1. UTF-8 JSON;
2. keys sorted lexicographically;
3. no insignificant whitespace (`separators=(",", ":")` semantics);
4. ASCII escaping enabled;
5. exact integers for identity-bearing coefficients;
6. SHA-256 of the serialized bytes;
7. `instance_id = "inst_" + lowercase_hex_digest`.

Stored array order may differ, but validation must normalize before hashing.

## 8. Structural and semantic validation split

`instance_schema_v1.json` validates:

- required fields and allowed family;
- primitive types and fixed conventions;
- three-entry clause/hyperedge arrays;
- Max-3SAT weight range;
- spin coefficient range and zero lower-order terms;
- generated-instance seed presence/types;
- top-level and nested unexpected fields.

A code validator is additionally required for:

- bounds involving `n`;
- distinct absolute Max-3SAT variables;
- canonical ordering and duplicate detection;
- full variable coverage;
- count/list and density formula agreement;
- canonical serialization and `instance_id` recomputation;
- fixed-seed regeneration equality;
- direct-versus-canonical mathematical evaluation.

Passing JSON Schema alone does not make an instance benchmark-valid.

## 9. Decisions needed before freeze

| ID | Decision | Current draft proposal | Owner/approval |
|---|---|---|---|
| `D1` | Clause and weight storage | Atomic `{literals, weight}` records, not parallel arrays | Benchmark + Code |
| `D2` | Exact ID algorithm | Canonical JSON + SHA-256 + `inst_` prefix | Benchmark + Code |
| `D3` | Clause literal ordering | Increasing absolute variable index | Benchmark + Code |
| `D4` | Manual golden seeds | Permit `null` only when mode is `manual_golden` | Benchmark + Code |
| `D5` | Density storage | Store for spec compliance; exclude from ID | Benchmark + Code |
| `D6` | Mode-specific generator parameters | Define separate uniform and anchor-pair sub-schemas | Benchmark supplies fields; Code implements |
| `D7` | Signed-clause hash | Decide canonical input and whether stored per clause | Benchmark + Code |
| `D8` | Spin zero lower-order representation | Sparse empty arrays `h=[]`, `J=[]` and `c=0` | Benchmark + Code |
| `D9` | Exact version strings | Approve `benchmark_spec_v1.0` and `instance_schema_v1.0` naming | Joint sign-off |
| `D10` | Distribution of JSON Schema `$id` | Replace draft URN with final repository URI if available | Code/project lead |

## 10. Additional material needed

No additional paper material is required to review this raw-instance draft.
Before the schema can be frozen, the following inputs/decisions are needed:

1. approved field lists for `generator_parameters` in uniform and anchor-pair
   modes for both families;
2. approval of decisions `D1`-`D10` above;
3. the repository/package namespace, if the final JSON Schema `$id` must use a
   project URI;
4. confirmation whether manual golden examples are governed by the same
   fixed-seed requirement or are an explicit unit-test exception.

`feature_dictionary_v1.md` is not required to freeze the raw instance schema,
but it will be required for the separate derived-metadata schema.

## 11. Acceptance checks

Before changing status to frozen:

- both example files pass JSON Schema validation;
- invalid family and unexpected-field examples are rejected;
- out-of-range/duplicate literals and hyperedges are rejected semantically;
- count and density inconsistencies are rejected;
- schema read/write/read round trip is lossless;
- reordering raw clauses/hyperedges does not change `instance_id`;
- changing a mathematical coefficient does change `instance_id`;
- changing timestamp, split, or storage path does not change `instance_id`;
- generated instances require fixed seeds;
- fixed seed and config regenerate identical raw data and identity;
- Benchmark and Code owners approve all `decision_needed` items.

