---
description: Export, import, or check the carrel desk catalog (tags and notes in .carrel/carrel.db) — back it up, move it between machines, or report stale index entries
argument-hint: <export|import|status> [file]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: catalog
---

Handle this desk-catalog request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel catalog` is a group with `export`, `import` and `status`; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel catalog --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel catalog [OPTIONS] COMMAND [ARGS]...

  Export, import and check the desk catalog (tags + notes in .carrel/carrel.db).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  export  Export every tagged or annotated file's tags and notes as JSON.
  import  Merge FILE (a `catalog export` document) into the desk under --root.
  status  Report the desk db: schema version, row counts, and stale index entries.
```

```text
Usage: carrel catalog export [OPTIONS]

  Export every tagged or annotated file's tags and notes as JSON.

  Document: {"schema", "product", "version", "exported", "root", "files": [{"path": <root-relative>,
  "tags": [...sorted], "notes": [{"created", "body"}]}]}, sorted by path — byte-identical across
  runs apart from "exported". Without -o the document itself is printed (always JSON); with -o a
  short summary is printed instead. Exit 4 when no desk db exists.

Options:
  -o, --out FILE  Write the catalog to FILE instead of stdout (refuses to overwrite without
                  --force).
  --force         Overwrite an existing --out file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

```text
Usage: carrel catalog import [OPTIONS] FILE

  Merge FILE (a `catalog export` document) into the desk under --root.

  Tags already present are kept (INSERT OR IGNORE); notes are deduplicated on (file, created, body),
  so importing the same document twice adds nothing. Entries whose path does not exist under the
  root are counted in skipped_missing and not created. Exit 4 for unreadable/invalid JSON or a
  "schema" newer than this build supports. JSON output: {tags_added, notes_added, files_touched,
  skipped_missing, tags_removed, notes_removed}.

Options:
  --replace  Delete ALL existing tags and notes first, then import (prints what was removed).
  --json     Machine-readable JSON output.
  --help     Show this message and exit.
```

```text
Usage: carrel catalog status [OPTIONS]

  Report the desk db: schema version, row counts, and stale index entries.

  JSON: {schema_version, db_path, counts: {files, docs, tags, notes}, stale: {changed, missing,
  unindexed}, examples: {changed, missing, unindexed} (up to 5 paths each)}. Always exit 0 (it is a
  report); exit 4 when no .carrel/carrel.db exists under --root.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```
<!-- usage:end -->

Note: `--json` and `--root` are **global** flags and go before `catalog` (`carrel --json --root DIR catalog status`).

- **export**: writes the tags and notes of every tagged/annotated file as one JSON document (`{schema, product, version, exported, root, files: [{path, tags, notes}]}`, paths root-relative, deterministic apart from `exported`). Without `-o` the document goes to stdout; with `-o FILE` a summary is printed. Never pass `--force` unless the user wants an existing file replaced.
- **import FILE**: merges a `catalog export` document into the desk under `--root`. Idempotent — existing tags are kept and notes are deduplicated, so importing twice adds nothing. Paths that don't exist under the root are counted in `skipped_missing`. `--replace` deletes ALL existing tags and notes first — treat it like `dedupe --apply`: only after explicit confirmation.
- **status**: `{schema_version, db_path, counts: {files, docs, tags, notes}, stale: {changed, missing, unindexed}, examples}`. Always exit 0 as a report; exit 4 when no desk db exists.

Choose from intent: "back up / move my tags" → `export` then `import` on the other side; "is my index stale" → `status`, then offer `carrel index` (and `--prune`) when `stale` is non-zero. Report the numbers conversationally.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
