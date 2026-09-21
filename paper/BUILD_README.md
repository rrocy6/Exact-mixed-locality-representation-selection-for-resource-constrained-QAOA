# Integrated manuscript build

This directory contains the complete uploaded manuscript baseline with the R12 review changes, its 13 referenced graphics, `quantumarticle.cls`, and the newly built `main.pdf`.

The available local compiler was Tectonic 0.17.0 (XeTeX); pdfLaTeX was not installed. The actual build ran from this directory with shell escape disabled:

```text
tectonic -X compile --untrusted --keep-logs --keep-intermediates -o <delivery>/paper_build main.tex
```

The final PDF has 80 pages and SHA-256 `b0f59b9b7d4dfb087fc7515039ef8036c7fad2b3deeb7fd2d32cf6433e81e62e`. The final TeX log has no undefined references, TeX errors, or overfull boxes. All 80 pages were rendered for a contact-sheet scan; the changed main-text and SI pages were inspected at higher resolution. The compiler emitted nonfatal environment/package warnings (Fontconfig default config and an upstream `algorithm.sty` UTF-8 byte). Build logs, PDF inspection details, and the baseline-to-integrated diff are in the independent closeout delivery.

This is a candidate for author review. Final manuscript adoption remains pending author confirmation.
