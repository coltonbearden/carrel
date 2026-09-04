---
description: Organize a messy folder into subfolders by file type or date using the carrel CLI (dry-run first, then apply)
argument-hint: <folder> [by type|date|exif-date]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: organize
---

Organize the folder the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel organize --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel organize [OPTIONS] DIRECTORY

  Plan (default) or perform (--apply) sorting DIRECTORY's files.

  Only files directly inside DIRECTORY are considered; subdirectories and hidden files stay put.
  Existing files are never overwritten — colliding names get a -1, -2, … suffix. JSON output is a
  list of {src, dest, action} ('move' planned, 'moved' executed, 'skip').

Options:
  --by [type|date|exif-date]  Grouping: 'type' -> pdf/, images/ (jpg, png, ico), data/ (json, xml,
                              csv), docs/ (md, txt, html); 'date' -> YYYY/MM from mtime; 'exif-date'
                              -> YYYY/MM from EXIF DateTimeOriginal, mtime fallback (images only;
                              other files are skipped).  [default: type]
  --into CATEGORY=DIR         Override a type category's destination subdir, e.g. --into images=pics
                              (only with --by type; repeatable).
  --apply / --dry-run         Execute the moves. Default is a dry-run that only prints the plan.
  --json                      Machine-readable JSON output.
  --help                      Show this message and exit.
```
<!-- usage:end -->

Note: `--json` is a **global** flag and may come before the subcommand.

- `--by type` (default): subdirs like pdf/, images/, data/, docs/; `date`: YYYY/MM from mtime; `exif-date`: EXIF DateTimeOriginal with mtime fallback (images only).
- `--into CATEGORY=DIR`: override a category's subdirectory name (type mode only; categories: pdf, images, data, docs — e.g. `--into images=pics`). Repeatable.
- **Dry-run is the default.** ALWAYS run the dry-run first, show the user the planned moves `{src, dest, action}`, and only re-run with `--apply` after they confirm (or when they already asked to "actually move" things). Collisions get `-1`, `-2` suffixes; nothing is ever overwritten.

If the installed carrel predates `organize` (its `--help` reports no such command), say so and offer manual organization (list files with `carrel inspect`/Glob, propose moves) instead of guessing flags.

Report afterwards: how many files moved where, and any collisions renamed.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
