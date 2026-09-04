---
description: Show rich metadata for a local file (pdf, image, json, csv, xml, html, md, txt) using the carrel CLI
argument-hint: <file> [deep]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Inspect the file the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel inspect` (verify with `carrel inspect --help` if unsure — never invent flags):

```
carrel inspect PATH [--deep] --json
```

- Always reported: name, size, mtime, detected type, sha256, mime guess.
- Per-type detail: pdf (pages, title/author/producer, encryption, form fields, annotations), images (dimensions, mode, EXIF summary), json (shape, key count, depth), csv (dialect, columns, rows), xml (root tag, element count, depth), html (title, headings, link/img counts), md (headings outline, word count), txt (lines/words/chars).
- `--deep`: adds exiftool's full tag table when exiftool is installed (harmless without it) — pass it when the user asks for "everything", EXIF detail, or deep metadata.

Always pass `--json`, then present the interesting fields conversationally — lead with what the user actually asked about (e.g. "is this PDF encrypted?" → the encryption field), not a raw JSON dump. Exit code 4 means the file is missing/unreadable/unsupported — say so plainly.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
