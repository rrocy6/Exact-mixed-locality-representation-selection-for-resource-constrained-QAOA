# R12 Windows log supplement

These six `entry_*.log` files are byte-identical copies of the original logs
from `delivery/repair_acceptance_20260921T131947Z_final_validation/
extracted_validation/` in the accepted local delivery. They correspond by
index to the six commands in `PACKAGE_VALIDATION.json`.

`entry_0.log` records 193 tests passing. The remaining entries record the
golden tests, P1 coverage, numerical verification, artifact map verification,
and saved-run gate check. `SHA256_MANIFEST.json` records each copied file's
size and SHA-256. The ZIP at the repository root packages this directory for
download. These are preserved historical logs; this supplement did not rerun
the validation commands.
