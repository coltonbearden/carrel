---
description: Build or refresh the carrel desk index (.carrel/carrel.db) so search, pack --query and the MCP tools can find files by content
argument-hint: [folder or files] [ocr?] [prune?] [status?]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: index
---

Index for the desk: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel index --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel index [OPTIONS] [PATHS]...

  Index PATH... (default: the desk root) into .carrel/carrel.db.

  Walks directories for the supported file types, skipping hidden entries (.carrel, .git, dotfiles).
  Files unchanged since the last run (same size + mtime) are skipped. Text comes from
  core.textextract; images are registered but only get searchable text with --ocr. Progress goes to
  stderr; the JSON summary is {"indexed", "skipped", "pruned", "errors"}. `--status` prints the
  `carrel catalog status` report instead.

Options:
  --ocr         OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --prune       Remove index rows whose files no longer exist on disk.
  --update      Treat PATH... as individual files to (re)index — no directory walking; unsupported
                or missing files are silently skipped.
  --if-indexed  Exit 0 silently when no desk db exists yet under --root (for hooks: only refresh an
                index someone already created).
  --status      Report index health instead of indexing (alias of `carrel catalog status`); other
                options are ignored. Exit 4 when no desk db exists under --root.
  --json        Machine-readable JSON output.
  --help        Show this message and exit.
```
<!-- usage:end -->

Note: `--json` and `--root` are **global** flags and go before `index` (`carrel --json --root DIR index`). The desk root is where `.carrel/carrel.db` lives — default cwd; use `--root` when the user's collection is elsewhere.

- No PATHS: index the whole desk root. Directories are walked for supported types; hidden entries (`.carrel`, `.git`, dotfiles) are skipped. Unchanged files (same size + mtime) are skipped, so re-running is always cheap and safe.
- `--ocr`: also make images/scanned PDFs searchable (needs tesseract/ocrmypdf) — only when the user wants scan text found.
- `--prune`: drop index rows for files that no longer exist. `--update FILE...`: (re)index just those files, no walking.
- `--if-indexed`: hook mode — silently exit 0 when no desk exists yet (never creates one).
- `--status`: report index health (`schema_version`, row counts, `stale.changed/missing/unindexed`) instead of indexing — the same report as `carrel catalog status`.

Interpret `{indexed, skipped, pruned, errors}` for the user; if `--status` shows stale entries, offer a plain `carrel index` (and `--prune` for missing files). Exit code 3 means an OCR binary is missing — relay the install hint from stderr. Exit code 4 with `--status` means there is no desk db yet.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
