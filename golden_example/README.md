# Section 7.1.1 Max-3SAT golden regression

This repository reproduces the supplied five-variable weighted Max-3SAT hand calculation.

Run the automated assertions with no third-party dependency:

```bash
python run_tests.py
```

If pytest is installed, the same assertions can also be run with:

```bash
python -m pytest -q
```

Print the numerical summary:

```bash
python -m src.exactness
```

Scope is deliberately limited to clause evaluation, canonical PUBO expansion,
Rosenberg penalties, selective/full encodings, and exhaustive exactness checks.
It does not run QAOA or generate random instances.
