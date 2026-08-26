# URSS Instance Schema v1.0 draft

This package is the code-side data contract derived from
`benchmark_spec_v1.0` for the two raw benchmark families:

- weighted Max-3SAT;
- pure cubic spin glass.

Files:

- `instance_schema_v1.md`: human-readable field contract, identity rules,
  semantic validation, and decisions that still need approval;
- `instance_schema_v1.json`: JSON Schema Draft 2020-12 structural validator;
- `examples/max3sat_golden.json`: the five-variable golden Max-3SAT instance;
- `examples/cubic_spin_glass_manual.json`: a small valid spin-glass instance.

The formal JSON Schema validates structure and primitive constraints. Conditions
that depend on another field, mathematical equivalence, sorting, coverage, or a
recomputed hash are listed as semantic validator requirements in the Markdown
contract.

Source specification SHA-256:

```text
7ce13bdf2135fed2e34eddffeb2cde75ec25ee9c284adfd9177b63e487af78cb
```

Status: draft for joint Benchmark/Code review. It is not a frozen dataset
contract until the decisions in Section 9 of the Markdown file are approved.

