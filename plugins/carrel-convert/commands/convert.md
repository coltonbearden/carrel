---
description: Convert local files between supported types (pdf, md, txt, html, json, xml, csv, png, jpg, ico, docx, odt, epub, rtf, xlsx) using the carrel CLI
argument-hint: <files...> to <target-type> [options in plain words]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: convert
---

Convert the file(s) the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel convert --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel convert [OPTIONS] SRC...

  Convert SRC... to another supported type.

  By default the output lands next to each SRC with the new extension. Existing outputs are never
  overwritten without --force. With --json, prints one JSON array of {"src", "dest", "via", "ok"}
  records.

  Office and ebook sources (docx, odt, epub, rtf) are read by pandoc and can go to md/html/txt/pdf
  (pdf also needs weasyprint); md/html/txt can be written as docx or odt, and docx <-> epub round-
  trips. xlsx reads need the `office` extra (openpyxl) and go to csv or json only.

Options:
  --to EXT             Target type: pdf, md, txt, html, json, xml, csv, png, jpg, ico, docx, odt,
                       epub.  [required]
  -o, --output FILE    Explicit output path (single SRC only).
  --out-dir DIRECTORY  Write outputs into this directory (required for multiple SRC).
  --force              Overwrite existing outputs.
  --pages [first|all]  pdf → png/jpg only: rasterize the first page, or every page as DEST-1..N.
                       [default: first]
  --sheet NAME|N|all   xlsx → csv/json only: pick a sheet by name or 1-based number (default: first;
                       json defaults to every sheet). 'all' with csv writes DEST-<sheet>.csv per
                       sheet.
  --json               Machine-readable JSON output.
  --help               Show this message and exit.

  Supported conversions (SRC type → --to targets):
    csv   → html, json, md
    docx  → epub, html, md, pdf, txt
    epub  → docx, html, md, pdf, txt
    html  → docx, md, odt, pdf, txt
    ico   → jpg, pdf, png
    jpg   → ico, pdf, png
    json  → csv, html, xml
    md    → docx, html, odt, pdf, txt
    odt   → html, md, pdf, txt
    pdf   → html, jpg, md, png, txt
    png   → ico, jpg, pdf
    rtf   → html, md, pdf, txt
    txt   → docx, html, md, odt, pdf
    xlsx  → csv, json
    xml   → json
```
<!-- usage:end -->

Note: `--json` is a **global** flag and may come before `convert` (`carrel --json convert ...`); the per-command `--json` after it works too.

- `--to EXT` (required): pick the target from the conversion matrix at the bottom of the help — it lists exactly which SRC types reach which targets.
- `-o/--output FILE`: explicit output path — single SRC only.
- `--out-dir DIR`: output directory — required when converting multiple SRC files.
- `--force`: only pass when the user explicitly wants existing outputs overwritten.
- `--pages first|all`: pdf → png/jpg only; `all` rasterizes every page as DEST-1..N.
- `--sheet NAME|N|all`: xlsx → csv/json only; `all` with csv writes one file per sheet.
- Office/ebook sources (docx, odt, epub, rtf) go through pandoc; xlsx needs the `office` extra.

Always use `--json` and interpret the result for the user: report each `{src, dest, via, ok}` record, say what worked, and explain any failures. Exit code 3 means an optional binary (pandoc, pdftotext, pdftoppm, weasyprint...) is missing — relay the install hint from stderr. Exit code 4 means an unsupported input/conversion pair — suggest a supported target from the matrix.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
