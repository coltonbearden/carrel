---
description: Generate thumbnails for PDFs, images, HTML, and ICO files using the carrel CLI
argument-hint: <files...> [size] [output dir]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Generate thumbnail(s) for: $ARGUMENTS

Run the carrel CLI via Bash. **First run `carrel thumb --help`** to confirm the exact flags available in the installed version, then map the user's request onto them — never invent flags. The expected interface is:

```
carrel --json thumb SRC... [--size 256] [--out-dir DIR] [--format png]
```

Note: `--json` is a **global** flag and must come before the subcommand.

- `SRC...`: pdf (first page), images, html, or ico files.
- `--size N` (default 256): thumbnail bounding box in pixels, aspect preserved.
- `--out-dir DIR` (default ./thumbs): where thumbnails land.
- `--format png`: output image format.

If `carrel thumb --help` reports that the command does not exist, the installed carrel predates it — fall back to `carrel convert SRC --to png` for pdf/image sources and say so.

Interpret the JSON result: report each `{src, thumb, w, h}` record and where the files landed. Exit code 3 means an optional binary (e.g. pdftoppm) is missing — relay the install hint from stderr.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
