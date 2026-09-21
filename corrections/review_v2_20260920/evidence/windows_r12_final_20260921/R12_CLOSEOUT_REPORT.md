# R12 closeout report

## Result

- Frozen bundle and packaging dependency: PASS. The source ZIP includes fibre_selector_v2 with its original manifest, sidecars, and referenced frozen files. Bundle manifest SHA-256: B79F1D5E16502097BE1C1B7B38BEA69639CA1EA9B0B4A0695D48A423D5A7F448.
- Paper/source mapping: PASS. The historical PAPER_ARTIFACT_MAP.json remains intact. The new PAPER_ARTIFACT_MAP_v2.json binds 7,648 existing files by path, size, and SHA-256, with historical analysis and current delivered source identities separate. New map SHA-256: 2BEC12600B49EFD703F5ED3D72D1F5134B704FCB21228007AC760E6BDE9B7FC9.
- ZIP integrity: PASS. CRC, path safety, complete manifests, sizes, and SHA-256 all passed for 1,000 source members and 3,915 evidence members. Assembly restored 7,702 byte-identical cross-package paths without a base archive.
- Freshly extracted repository tests: 193 run, 193 passed, 0 errors, 0 failures, 0 skipped. All five named FibreRerunBundleTests passed. The 27 repair regressions were retained in the full run.
- Golden: 10 passed, 0 failed.
- P1: expected 2,052, actual 2,052; missing, duplicate, extra, and failed all zero. The saved-run production require_full_gate() passed. No quantum compilation was repeated.
- Numerical verification: 1,800 arrays and 1,800 selector rows, zero differences; common 79,069 / baseline 149,439 = 52.910552131639%.

## Environment and limits

The final ZIP extraction and tests used the existing C:\Users\rocyz\Desktop\量子算法组合优化tsp\协作\.venv\Scripts\python.exe (Python 3.12.10, Qiskit 2.4.2, reportlab 4.4.9). The historical compilation identity remains Qiskit 2.5.2 and was checked from saved records. A clean dependency install, paper PDF, and final paper adoption were not validated. No commit, push, merge, release, or 101,460-compilation rerun occurred.

Two earlier attempts remain as evidence: the sandbox run had Windows temporary-directory access errors; a non-sandbox Python 3.12 run lacked reportlab and had six test errors. Neither counts as a passing final validation. The final run used only the two ZIPs and the stated interpreter, with PYTHONPATH removed. Full argv, cwd, exit codes, and logs are in PACKAGE_VALIDATION.json and extracted_validation/entry_*.log.

## Final ZIP SHA-256

- Source: aae92033cf71230122f6bd225c7e73c0c9b8ae836b73dc6107ce72ad8e79f065
- Evidence: 5b2371c8b76fcbedd4ed764ffde4070d2019239b26ee52b9879bd3339d434457

R12 delivery correction passes. The packages are suitable for repair-branch review, subject to the separate publication and clean-install checks above.
