# R12 full-manuscript change matrix

Input: uploaded complete `paper_base/main.tex`, SHA-256 `d116642591137bc223a82257ff702dca02d38fa4a75b6b555d54ddfff651a031`. Status refers to that uploaded baseline before this PR's edits.

| Topic | Baseline status | Location | Evidence and action |
|---|---|---|---|
| Five fixed seeds, frozen candidate library, 60 reused instances, two syntheses, three topologies, 101,460 saved tasks | already_present | `sec:multiseed-robustness`, `sec:multiseed-methods` | `final_analysis/EXPERIMENT_REPORT.md`, `AUDIT.json`; retained once. |
| Seed-1729 TRUE 149,439; all-five common 79,069; 52.910552131639% pooled retention | needs_update | `sec:multiseed-robustness`, `tab:multiseed-retention` | Counts already present and match `final_analysis/seed_summary.csv`; main text now gives 52.91% with explicit ratio. |
| Same budget tuple across seeds, possibly different feasible mixed witnesses | already_present | `sec:multiseed-robustness`, `supp:multiseed-results` | `MULTISEED_PAPER_FRAGMENT.tex`, corrected analysis; retained. |
| Stability categories stable 49, partial 171, disappeared 35, empty baseline 105 | needs_update | `sec:multiseed-robustness`, `tab:multiseed-region-changes` discussion | `final_analysis/classification_flips.csv` and independent R12 report; added. Baseline retention is distinguished from exact equality of full sets. |
| Family/topology pooled counts and row order | already_present | `tab:multiseed-retention` | Six row values match `MULTISEED_PAPER_FRAGMENT.tex`; existing line/ring/grid ordering retained. |
| Seed-wise setting denominator 360 and region-presence table | already_present | `tab:multiseed-seeds` | `final_analysis/seed_region_presence.csv`; retained. |
| Selector score, fixed baseline winner, changes in feasible grid | already_present | `sec:multiseed-methods`, `supp:multiseed-results` | `final_analysis/selector_stability.csv`; retained. |
| Resource feasibility versus QAOA quality and finite-library limits | already_present | abstract, `sec:discussion-search-scope`, `sec:multiseed-methods` | R12 report and saved protocol; retained. |
| Historical versus current source artifact identity | already_present | `app:multiseed-audit` and R12 map | `PAPER_ARTIFACT_MAP_v2.json`; historical map retained. |
| Current repository URL and public-availability wording | needs_update | Data availability, Code availability, `app:reproducibility` | Current GitHub repository and draft PR; historical commit `efaa1ce...` verified locally. |
| Complete authors, theory, QAOA, Appendices A–H and SI | already_present | full manuscript | Uploaded `paper_base/main.tex`; preserved without substituting the shorter historical repair sketch. |

No unresolved numerical conflict was found in the inspected five-seed text. PDF build and visual layout are tracked separately in the closeout report.
