---
description: Full-text search the carrel desk index (FTS5, bm25-ranked) for local files matching a query, with type and tag filters
argument-hint: <query> [type/tag filters]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: search
---

Search the desk index for: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel search --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel search [OPTIONS] QUERY

  Full-text search the desk index for QUERY (FTS5 syntax, bm25-ranked).

  Matched terms are bracketed in the snippet. Filters combine with AND. JSON output is a list of
  {"path", "score", "snippet"} (lower bm25 score = better match). Run the `index` command first to
  build the index under --root.

Options:
  --limit INTEGER  Maximum number of hits.  [default: 20]
  --type T1,T2     Only these file types, comma-separated (e.g. pdf,md).
  --tag TAG        Only files carrying TAG (repeatable — every TAG must match).
  --fail-empty     Exit 5 when there are no hits.
  --json           Machine-readable JSON output.
  --help           Show this message and exit.
```
<!-- usage:end -->

Note: `--json` and `--root` are **global** flags and go before `search` (`carrel --json --root DIR search "QUERY"`).

- `QUERY` uses FTS5 syntax: quoted phrases (`"exact phrase"`), `AND`/`OR`/`NOT`, prefix matching (`term*`). Translate natural-language requests into a sensible FTS5 query.
- `--type T1,T2`: restrict to file types (e.g. `pdf,md`) — use it when the user says "which PDFs..." or "in my notes".
- `--tag TAG` (repeatable, ANDed): only files carrying every given tag — pairs with `/carrel-organize:tag`.
- `--limit N` (default 20). `--fail-empty`: exit 5 instead of an empty list when nothing matches (handy in scripts).
- `--root DIR`: use it when the user's desk lives somewhere other than the cwd.

The index must exist first: if the search errors because there is no index under `--root`, run `carrel index` there (add `--ocr` only if the user wants image/scan text searchable) and retry, telling the user what you did.

Always use `--json` and interpret the `{path, score, snippet}` hits (lower bm25 score = better): present the top hits with their snippets, matched terms are bracketed. No hits → suggest a broader query, a different `--type`, or re-indexing. To turn the hits into context for a longer answer, hand the same query to `/carrel-inspect:pack --query`.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
