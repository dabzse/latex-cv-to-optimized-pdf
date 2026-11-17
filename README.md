# LaTeX CV builder & PDF optimizer

Two small Python utilities for building CVs from LaTeX sources and shrinking the resulting PDFs with Ghostscript.

## Files

| File               | Description                                                                                          |
| :----------------- | :--------------------------------------------------------------------------------------------------- |
| `build_cv.py`      | Compiles `.tex` CVs to PDF (via `pdflatex`/`lualatex`/`xelatex`) and optimizes them with Ghostscript |
| `optimize_pdfs.py` | Standalone batch optimizer: runs Ghostscript `pdfwrite` over any set of PDFs                         |

## Requirements

- Python 3.10+
- A LaTeX engine (`pdflatex`, `lualatex` or `xelatex`) for `build_cv.py`
- Ghostscript (`gs`) for PDF optimization — optional, see "Ghostscript fallback" below
- `pdfinfo` (poppler-utils) — optional, only used to print the page count

## build_cv.py

Compiles one or more `.tex` files and optimizes each resulting PDF.

```bash
# No arguments: builds every file listed in DEFAULT_TEX
python3 build_cv.py

# Explicit inputs (.tex and/or .pdf, any number)
python3 build_cv.py cv_hu.tex cv_en.pdf

# Useful flags
python3 build_cv.py --engine xelatex --passes 3
python3 build_cv.py --preset ebook --compat 1.7
python3 build_cv.py --keep-raw --keep-aux
python3 build_cv.py -o out/cv.pdf cv_hu.tex   # single input only
```

### DEFAULT_TEX

`DEFAULT_TEX` at the top of the script is a tuple of `.tex` filenames that live next to the script. When no input argument is given, every entry is built in order. All entries must end in `.tex` (validated at startup).

### Where do the auxiliary files go?

All LaTeX byproducts (`.aux`, `.log`, `.out`, …) are written into a temporary directory via `-output-directory` and deleted automatically after each file — the source folder stays clean. `--keep-aux` keeps them in a persistent `build/` subdirectory instead. `--keep-raw` additionally saves the unoptimized PDF as `<name>_raw.pdf`.

### Ghostscript fallback

Optimization is the last step, so it never aborts the build:

- If `gs` is not installed → a warning is printed and the **unoptimized** PDF
  is kept at the output path.
- If `gs` runs but fails → its output is shown, a warning is printed, and the
  unoptimized PDF is kept.

## optimize_pdfs.py

Batch-optimizes PDFs with Ghostscript. Defaults to the script's own directory.

```bash
python3 optimize_pdfs.py                    # all PDFs in this folder
python3 optimize_pdfs.py path/to/dir        # or a single PDF file
python3 optimize_pdfs.py -r -o out/ dir     # recursive, separate output dir
python3 optimize_pdfs.py --in-place *.pdf   # overwrite originals
python3 optimize_pdfs.py --only-smaller     # keep result only if smaller
python3 optimize_pdfs.py --dry-run          # list targets, change nothing
```

Useful flags: `--preset {prepress,printer,ebook,screen,default}`, `--compat 1.5`, `--no-fast-web-view`, `-r/--recursive`, `--in-place`.

Already-optimized files (`*_optimized.pdf`) and files inside the output directory are skipped automatically.

If Ghostscript is not installed, the script prints a warning and exits cleanly (exit code 0) instead of failing.
