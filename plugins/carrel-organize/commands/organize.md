---
description: Organize a messy folder into subfolders by file type or date using the carrel CLI (dry-run first, then apply)
argument-hint: <folder> [by type|date|exif-date]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Organize the folder the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. **First run `carrel organize --help`** to confirm the exact flags available in the installed version, then map the user's request onto them — never invent flags. The expected interface is:

```
carrel --json organize DIR [--by type|date|exif-date] [--into CATEGORY=DIR]... [--apply]
```

Note: `--json` is a **global** flag and must come before the subcommand.

- `--by type` (default): subdirs like pdf/, images/, data/, docs/; `date`: YYYY/MM from mtime; `exif-date`: EXIF DateTimeOriginal with mtime fallback (images only).
- `--into CATEGORY=DIR`: override a category's subdirectory name (type mode only; categories: pdf, images, data, docs — e.g. `--into images=pics`). Repeatable.
- **Dry-run is the default.** ALWAYS run the dry-run first, show the user the planned moves `{src, dest, action}`, and only re-run with `--apply` after they confirm (or when they already asked to "actually move" things). Collisions get `-1`, `-2` suffixes.

If `carrel organize --help` reports that the command does not exist, the installed carrel predates it — say so and offer manual organization (list files with `carrel inspect`/Glob, propose moves) instead of guessing flags.

Report afterwards: how many files moved where, and any collisions renamed.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
