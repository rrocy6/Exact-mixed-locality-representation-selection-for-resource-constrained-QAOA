# Restored archives and reproducible verification (2026-10-05)

This repair integrates main efaa1ce and the R12 repair branch e6c44c1 in a local review branch. It restores original archive bytes; it does not create new historical experiments. The main.tex and quantumarticle.cls merge conflicts retain main. R12 paper PDFs are historical artifacts and must not be interpreted as a fresh build of main.tex. Latest manuscript integration is outside this repair.

## Restored evidence

- Original multiseed run: `results/multiseed_20260918T163717Z/`, including 101,460 compilation rows and missing correction analysis inputs.
- Missing original `amendment_01.json` for the P1 compiled-study input snapshot.
- `archives/revision_20260917/`: original revision package, including 90-instance compiled study and 60-instance preparation/evolution study.
- `archives/feedback_iteration_v3/`: original 72-instance joint-resource/quality study.
- 97 P1 input files restored from Git-normalized LF to original archive bytes. No scientific content changed. `.gitattributes` prevents further normalization.

`archive_repair_20261005/RESTORED_FILES.json` records 8,741 added files; `NEWLINE_RESTORATION.json` records original and restored digests for the 97 newline restorations. The original revision and v3 manifests verify 841 and 434 files respectively, with zero mismatches. The original v3 ZIP SHA-256 is `4ff15241060cf37f784e0f02d617e7f64675b23e83c7aef98bda1766c5f35fd8`, matching the historical closeout report.

## Commands from repository root

Use Python 3.12. For v3 strict replay install exactly `archives/feedback_iteration_v3/requirements.txt` into a separate environment. The root/R12 unit tests require their own Qiskit 2.4.2 environment (`corrections/review_v2_20260920/requirements-tests-lock.txt`); do not replace a study's frozen compiler version with another study's version.

Each output path must be new. The runner refuses existing paths. Frozen sources and evidence remain unchanged.

```sh
python scripts/reproduce_restored_archives.py integrity --output verification/integrity
python scripts/reproduce_restored_archives.py multiseed --output verification/multiseed
python scripts/reproduce_restored_archives.py p1 --output verification/p1
python scripts/reproduce_restored_archives.py compiled --output verification/compiled
python scripts/reproduce_restored_archives.py qaoa --output verification/qaoa
python scripts/reproduce_restored_archives.py v3 --output verification/v3
```

`compiled` copies the full frozen input tree to the new output directory because the historical analyser writes beside its inputs. `qaoa` interprets Windows backslashes as path separators before hashing; expected hashes, the SHA-256 algorithm, frozen source bytes and original verification assertions are unchanged. `v3` invokes the original strict audit, including dependency checks, with no metadata-drift exception.

## Fresh verification results

| Check | Result |
| --- | --- |
| Restored byte identities | 8,838 / 8,838 PASS |
| Multiseed direct independent classification | 1,800 arrays and 1,800 selector rows PASS; 149,439 baseline cells, 79,069 common cells |
| Strict P1 coverage and provenance | 2,052 / 2,052 PASS; no missing/duplicate/extra rows |
| 90-instance compiled-study analyser | Exit 0, amendment and freeze checks passed |
| QAOA original verification with path adapter | 60 instances, 480 arms PASS |
| v3 original strict audit (Qiskit 2.5.2) | PASS: 4,560 exact representations, 9,120 product checks, 1,086 saved-parameter replays, 1,350 grid samples, 2,172 trace samples, 9 compiled-statevector checks |
| Merged root unit tests (Qiskit 2.4.2) | 248 / 248 PASS |

Maximum v3 independent numerical error: 1.5631940186722204e-13. These checks replay saved results and sampled circuits, not all original optimization trajectories or all candidate compilations. The original Windows metadata-drift/strict-failure record remains valid for that historical environment. No remote push, default-branch change or remote main merge was performed.

The earlier missing-archive blockers are resolved. This does not by itself certify the latest manuscript: previously identified transcription issues (243 full assignments and gate/depth budget wording), figure provenance and final manuscript build still need a separate paper review.
