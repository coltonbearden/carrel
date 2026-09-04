---
description: Show rich metadata for a local file (pdf, image, json, csv, xml, html, md, txt, docx, odt, epub, rtf, xlsx) using the carrel CLI
argument-hint: <file> [deep]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: inspect
---

Inspect the file the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel inspect --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel inspect [OPTIONS] PATH

  Show metadata for one file.

  Always: name, size, mtime, detected type, sha256 (files under 512 MB) and a mime guess. Plus per-
  type detail: pdf (pages, title/author/producer, encryption, form fields, annotations), images
  (dimensions, mode, EXIF summary), json (shape, key count, depth), csv (dialect, columns, rows),
  xml (root tag, element count, depth), html (title, headings outline, link/img counts), md
  (headings outline, word count), txt (lines/words/chars), docx (paragraphs, words,
  title/author/created), epub (title, creator, language, spine items, words), odt/rtf (words), xlsx
  (sheets with row/column counts; needs the `office` extra). Word counts for office/ebook files use
  pandoc and are null without it.

Options:
  --json  Machine-readable JSON output.
  --deep  Add exiftool's full tag table when exiftool is installed; without it the output notes 'not
          installed' (never an error).
  --help  Show this message and exit.
```
<!-- usage:end -->

- Always reported: name, size, mtime, detected type, sha256, mime guess.
- Per-type detail: pdf (pages, title/author/producer, encryption, form fields, annotations), images (dimensions, mode, EXIF summary), json (shape, key count, depth), csv (dialect, columns, rows), xml (root tag, element count, depth), html (title, headings, link/img counts), md (headings outline, word count), txt (lines/words/chars), docx/epub/odt/rtf (words, title/author where the format carries them), xlsx (sheets with row/column counts).
- `--deep`: adds exiftool's full tag table when exiftool is installed (harmless without it) — pass it when the user asks for "everything", EXIF detail, or deep metadata.

Always pass `--json`, then present the interesting fields conversationally — lead with what the user actually asked about (e.g. "is this PDF encrypted?" → the encryption field), not a raw JSON dump. Exit code 4 means the file is missing/unreadable/unsupported — say so plainly.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
