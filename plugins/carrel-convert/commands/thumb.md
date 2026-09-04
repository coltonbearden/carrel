---
description: Generate thumbnails for PDFs, images, HTML, and ICO files using the carrel CLI
argument-hint: <files...> [size] [output dir]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: thumb
---

Generate thumbnail(s) for: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel thumb --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel thumb [OPTIONS] SRC...

  Create thumbnails for SRC... (pdf, png, jpg, ico, html).

  Thumbnails land in --out-dir as <name>.<format>, aspect preserved, never larger than --size on
  either edge. With --json, prints one JSON array of {"src", "thumb", "w", "h"} records.

Options:
  --size INTEGER RANGE  Maximum edge length in pixels.  [default: 256; x>=1]
  --out-dir DIRECTORY   Directory for the thumbnails.  [default: thumbs]
  --format [png|jpg]    Thumbnail image format.  [default: png]
  --json                Machine-readable JSON output.
  --help                Show this message and exit.
```
<!-- usage:end -->

Note: `--json` is a **global** flag and may come before the subcommand.

- `SRC...`: pdf (first page), png/jpg images, html, or ico files.
- `--size N` (default 256): maximum edge length in pixels, aspect preserved.
- `--out-dir DIR` (default ./thumbs): where thumbnails land as `<name>.<format>`.
- `--format png|jpg`: thumbnail image format.

If the installed carrel predates `thumb` (its `--help` reports no such command), fall back to `carrel convert SRC --to png` for pdf/image sources and say so.

Interpret the JSON result: report each `{src, thumb, w, h}` record and where the files landed. Exit code 3 means an optional binary (e.g. pdftoppm) is missing — relay the install hint from stderr.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
