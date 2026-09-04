---
description: Extract the images embedded in a PDF, packed in an ICO, or referenced by a local HTML file using the carrel CLI
argument-hint: <pdf|ico|html file> [output dir] [minimum size]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: extract-images
---

Extract the images from: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel extract-images --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel extract-images [OPTIONS] SRC

  Extract images embedded in / referenced by SRC (pdf, ico, html).

  pdf uses pdfimages, ico uses icotool (or a Pillow fallback), html copies local <img src> files
  that exist next to the document — remote URLs are never fetched. With --json, prints one JSON
  object {"src", "out_dir", "count", "extracted"}.

Options:
  --out-dir DIRECTORY       Output directory [default: <SRC>-images next to the source].
  --min-size INTEGER RANGE  pdf mode: discard images smaller than this on either edge.  [default:
                            32; x>=1]
  --json                    Machine-readable JSON output.
  --help                    Show this message and exit.
```
<!-- usage:end -->

- `SRC`: a pdf (via pdfimages), an ico (via icotool, Pillow fallback), or an html file — for html only local `<img src>` files that exist next to the document are copied; remote URLs are never fetched.
- `--out-dir DIR` (default `<SRC>-images` next to the source): where the images land.
- `--min-size N` (pdf only, default 32): drop images smaller than N px on either edge — raise it when the user wants "the real figures, not icons".

Use `--json` and interpret `{src, out_dir, count, extracted}`: report how many images were written and where; offer `carrel thumb` on the output directory if the user wants a quick look. Exit code 3 means pdfimages (poppler-utils) or icotool is missing — relay the install hint from stderr. Exit code 4 means the input type has no extractable images.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
