---
description: Rename local files from what the documents say — {date}_{vendor}_{ref}{ext} and other templates — with the carrel CLI (dry-run first, then apply)
argument-hint: <files or folder> [--template '{date}_{vendor}_{ref}{ext}'] [--apply]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: rename
---

Rename the files the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel rename --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel rename [OPTIONS] PATHS...

  Plan (default) or perform (--apply) renaming PATH... from the documents' own fields.

  Placeholders: {date} (or {date:%Y-%m}), {yyyy}, {mm}, {vendor}, {ref}, {total}, {fields.NAME},
  {meta.KEY}, {type}, {stem}, {name}, {ext}, {sha8}. Dates come from the document (then the desk,
  then mtime); {ref} is the invoice number or the first reference found. Values are slugified; a
  file with an unresolved placeholder is skipped unless --fallback is given. Renames happen next to
  the source (a literal / in the template files into subfolders), never overwrite (-1, -2, …
  suffixes), and carry the desk row under --root along. JSON: [{src, dest, action:
  rename|renamed|skip, reason, sources}].

  --apply refuses (exit 2) when a PATH *directory* is inside a git work tree, where renaming tracked
  files breaks imports, tests and history. Explicitly named files are never guarded; --force
  overrides.

Options:
  --template TEXT          Name template; see the placeholders in the command description.
                           [default: {date}_{vendor}_{ref}{ext}]
  --apply / --dry-run      Execute the renames. Default is a dry-run that only prints the plan.
  --date-order [mdy|dmy]   How to read an ambiguous slashed date in the document.  [default: mdy]
  --fallback TEXT          Use TEXT for a placeholder that has no value instead of skipping the
                           file.
  --lower                  Lower-case the rendered name.
  --max-len INTEGER RANGE  Cap the stem length.  [default: 120; x>=8]
  --ocr                    OCR images and scanned PDFs to read their fields (needs tesseract /
                           ocrmypdf).
  --force                  Rename even when a PATH directory is inside a git work tree (see the
                           description).
  --json                   Machine-readable JSON output.
  --help                   Show this message and exit.
```
<!-- usage:end -->

- **Always dry-run first** (`carrel --json rename PATH...`) and show the plan: `src → dest`, plus every `skip` with its reason (usually an unresolved `{ref}` or `{vendor}`). Only pass `--apply` after the user has seen the plan and agreed; offer `--fallback TEXT` for files that lack a value.
- Placeholders: `{date}` / `{date:%Y-%m}` / `{yyyy}` / `{mm}` (document date, then desk field, then mtime), `{vendor}`, `{ref}` (invoice number or first reference), `{total}`, `{fields.NAME}`, `{meta.KEY}`, `{type}`, `{stem}`, `{name}`, `{ext}`, `{sha8}`. Values are slugified; `--lower` lower-cases.
- Renames stay in the file's own directory, never overwrite (`-1`, `-2`, … suffixes), and carry the desk row (tags, notes, fields) along under the global `--root`.
- European dates need `--date-order dmy`; scans need `--ocr`.

Report the plan (or the applied renames) conversationally, listing skipped files and why. For filing into `YYYY/MM` folders as well, point at `/carrel-watch:intake`.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
