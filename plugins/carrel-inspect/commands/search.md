---
description: Full-text search the carrel desk index (FTS5, bm25-ranked) for local files matching a query
argument-hint: <query> [type/tag filters]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Search the desk index for: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel search` (verify with `carrel search --help` if unsure — never invent flags):

```
carrel --json [--root DIR] search "QUERY" [--limit 20] [--type pdf,md] [--tag TAG] [--fail-empty]
```

Note: `--json` and `--root` are **global** flags and must come before `search`.

- `QUERY` uses FTS5 syntax: quoted phrases (`"exact phrase"`), `AND`/`OR`/`NOT`, prefix matching (`term*`). Translate natural-language requests into a sensible FTS5 query.
- `--type T1,T2`: restrict to file types (e.g. `pdf,md`).
- `--tag TAG` (repeatable): only files carrying every given tag.
- `--limit N` (default 20).
- `--root DIR`: use it when the user's desk lives somewhere other than the cwd.

The index must exist first: if the search errors because there is no index under `--root`, run `carrel index` there (add `--ocr` only if the user wants image/scan text searchable) and retry, telling the user what you did.

Always use the global `--json` and interpret the `{path, score, snippet}` hits (lower bm25 score = better): present the top hits with their snippets, matched terms are bracketed. No hits → suggest a broader query, a different `--type`, or re-indexing.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
