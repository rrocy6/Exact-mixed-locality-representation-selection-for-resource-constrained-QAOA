OVERLEAF PROJECT — URSS revision, 13 September 2026

Upload URSS_Overleaf_updated.zip using New Project > Upload Project.
Main document: main.tex. Compiler: pdfLaTeX. A current TeX Live installation is recommended.
The bibliography is embedded in main.tex; no separate .bib file or BibTeX step is required.
The ten external vector PDF figures are included. Figure 2 is generated directly by TikZ.
quantumarticle.cls and the algorithm style files are included for portability.

Contents
main.tex: revised manuscript.
figures/: tightly cropped vector PDF figures.
data/: frozen summary inputs for the regenerated figures.
rebuild_figures.py: rebuilds Figures 1, 6, 7, 8, 9 and 11; no experiments are rerun.
code_updates/make_selected_qaoa_paper_updates.py: repaired original figure/text generator.
code_updates/generator.patch: difference from the supplied source snapshot.

To rebuild the six revised plots locally, install numpy, scipy and matplotlib, then run
python rebuild_figures.py
This is optional; Overleaf compiles the supplied PDFs directly and does not run Python.
To use the repaired original generator, copy it into the experiment source directory and run
python make_selected_qaoa_paper_updates.py --output /path/to/verified/QAOA/result_directory
The complete original result archives remain authoritative; this project includes only
summary data required for plotting and current original-E4 auxiliary eligibility.

Changes
- Rebuilt current resource and QAOA plots from verified merged summaries.
- Figure 9 uses one spin-glass and seven Max-3SAT instances, with no interval for n=1.
- Figure 8 retains frozen LP values and updates current design-status markers.
  Two instances (not one) have stronger single-variable signal and active selected auxiliaries.
- Corrected the active instance–representation/draw group count from 68 to 62.
- Corrected cross-references and grammar; residual classifications now mean inconclusive.
- Specified the 1e-9 tolerance and the numerical feasible set for certification.
- Removed stale hard-coded p=2 numbers from the supplementary generator.
- Cropped all ten external figures without rasterising vector graphics.
- Adjusted float-only page spacing and condensed repetitive noise discussion.

Validation
Compiled with pdfLaTeX/latexmk to 58 pages; no undefined citations/references or overfull boxes.
Abstract: 148 whitespace-delimited words. Existing figure/table numbering is preserved.
Figures were inspected after rendering; no experiment was rerun for this revision.

Class source: https://github.com/quantum-journal/quantum-journal (quantumarticle v6.1).
The class and style files retain their upstream licence notices.
