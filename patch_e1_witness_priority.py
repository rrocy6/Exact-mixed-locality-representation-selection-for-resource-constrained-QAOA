"""Make E1 export a positive-error witness before an inconsistent tie witness."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


MARKER = "# E1/E2 correction: prefer a pointwise-error witness over a tie-only witness."
OLD = "        if first_witness is None and (error or inconsistent):\n"
NEW = (
    f"        {MARKER}\n"
    "        if (\n"
    "            first_witness is None and (error or inconsistent)\n"
    "        ) or (\n"
    "            error\n"
    "            and first_witness is not None\n"
    "            and float(first_witness[\"pointwise_error\"]) == 0.0\n"
    "        ):\n"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch(path: Path) -> tuple[str, str, str]:
    before = sha256(path)
    source = path.read_text(encoding="utf-8")
    if MARKER in source:
        return "already_patched", before, before
    if source.count(OLD) != 1:
        raise RuntimeError(
            "Expected evaluate_pointwise witness-selection line was not found exactly once; STOP"
        )
    updated = source.replace(OLD, NEW)
    compile(updated, str(path), "exec")
    path.write_text(updated, encoding="utf-8", newline="\n")
    return "patched", before, sha256(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file",
        default="urss_pipeline/e1_exactness.py",
        help="Existing formal E1 implementation to patch in place",
    )
    args = parser.parse_args()
    status, before, after = patch(Path(args.file))
    print(f"PATCH STATUS: {status}")
    print(f"E1 SOURCE SHA256 BEFORE: {before}")
    print(f"E1 SOURCE SHA256 AFTER:  {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
