IEEE TQE revision -- project layout (created 17 September 2026)

main.tex            Main manuscript. ieeeaccess.cls (official TQE template, March 2020).
                    Front matter complete (title placeholder, authors, affiliations, funding,
                    corresponding author). Section skeleton follows the agreed structure:
                    I Introduction, II Related Work, III Exact Selective Locality Reduction,
                    IV Resource-Aware Representation Selection, V Experimental Evaluation,
                    VI Discussion, VII Conclusion, Acknowledgment, Data and Code Availability.
bibliography.tex    Reference list (\input by main.tex and supplementary.tex). 63 entries carried
                    over from the original draft plus 10 added in revision. Must be reordered by
                    first citation and reformatted to IEEE style once the text is final.
biography.tex       Six IEEEbiography blocks in author order, with photos/placeholder.png.
supplementary.tex   Standalone Supplementary Information (IEEEtran, one column). Sections S1-S7.
ieeeaccess.cls, IEEEtran.cls, logo.png, notaglinelogo.png, bullet.png
                    Class and graphics files required by the TQE template.
photos/             Author photographs (1 in x 1.25 in, >= 300 dpi). Replace placeholder.png.
template_original/  Untouched copy of the IEEE template (tqe.tex, TQE.pdf, fig1.png).

Figures are read from ../figures/ via \graphicspath.

Compile (pdfLaTeX, run twice; no BibTeX step):
    pdflatex main.tex && pdflatex main.tex
    pdflatex supplementary.tex && pdflatex supplementary.tex
Overleaf: set main.tex as the main document, compiler pdfLaTeX.

Known template behaviour: ieeeaccess.cls loads hyperref only under a class option, so \href is
not available; links were removed from bibliography entries. amsthm conflicts with the class,
so theorem environments use the class-native \newtheorem.
