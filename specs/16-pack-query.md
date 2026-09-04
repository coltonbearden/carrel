# spec: pack v2 — query-driven, git-aware context engineering

**Owns:** `src/carrel/commands/pack.py`, `tests/test_pack.py`.
**Depends on:** spec 19 (adds the `git` adapter and the `tokens` extra). **Wave:** 2.

## Why
`pack` is the product's clearest differentiator and today it is a concatenator with filters. Agents want "the files relevant to X" and "the files this PR touched" under a budget, with honest token counts. The `.gitignore` matcher also lacks negation, a documented gap in the module docstring.

## CLI (additions only — every existing flag keeps its meaning)
```
carrel pack PATH... [existing flags]
            [--query TEXT [--top N]] [--since REF | --changed]
            [--dedupe-content] [--tokenizer heuristic|exact] [--outline]
```

## Behavior
- **`--query TEXT`** — requires a desk index under `--root` (else exit 4 with `run carrel index --root …` hint). Rank with `DeskDB.fts_search(query, limit=top)` (default `--top 20`), keep only hits that also survive the normal PATH/include/exclude/gitignore filters, and emit them **in relevance order** (not tree order). Header adds `query`, `top`, and per-file `score` (also in `--stats`/`--json`). Zero hits: header says so; with `--fail-empty` exit 5. `--query` and `--since` may be combined (intersection).
- **`--since REF`** / **`--changed`** — file list from `git diff --name-only REF` (resp. `git diff --name-only HEAD` plus untracked via `git ls-files --others --exclude-standard`) run through `adapters.run("git", …)` with cwd = the PATH's git root. `git` missing → exit 3 with hint; not a repo or bad ref → exit 4 with git's first stderr line. Result is intersected with the walk (deleted files are listed in the header as `removed`, not packed). Mutually exclusive with each other (exit 2).
- **Negation in `.gitignore`** — `_IgnoreFile` (`pack.py:90`) honors `!pattern`; rules apply in file order, last match wins, directory-only rules (`dir/`) and anchored rules (`/x`) keep current semantics. Remove the "negation NOT supported" note from the module docstring and docs.
- **`--dedupe-content`** — compute `db.file_hash` per packed text file; second and later identical files are not inlined; the tree marks them `[same as <first path>]`; header counts `deduped`.
- **`--tokenizer`** — `heuristic` (default) keeps `ceil(chars/3.6)` labeled `tokens_est`. `exact` imports `tiktoken` (encoding `o200k_base`) from the `tokens` extra; missing → exit 3 with `uv tool install 'carrel[tokens]'` (or `uv sync --extra tokens` from a checkout). With `exact`, all outputs label the field `tokens` and the header says which tokenizer produced the numbers. `--chunk` budgets use whichever tokenizer is active.
- **`--outline`** — a structural pass in the `--tree-only` cost class: for `.py` files, top-level `def`/`class` names with line numbers via `ast` (syntax errors → `[unparsable]`); for `.md`, the heading outline; other types show size only. Rendered as an indented list under each tree entry in md/xml, and as `outline: [...]` per file in json. Incompatible with `--chunk` (exit 2).
- All new fields appear in `--json` and `--stats`; ordering stays deterministic.

## Acceptance
- Index a tmp tree of 6 text files, `pack . --query "sentinel" --json`: only files containing the sentinel appear, ordered by `score`, non-hits absent; `--fail-empty` with a nonsense query exits 5; without an index exits 4.
- Temp git repo: commit A (3 files), commit B modifies 1 and adds 1 → `pack . --since HEAD~1` packs exactly those 2; `--changed` after editing an uncommitted file packs it; `--since` with no `git` on PATH (monkeypatched `have`) exits 3; outside a repo exits 4.
- Negation: `.gitignore` = `*.log` then `!keep.log` → `keep.log` packed, `other.log` not; a `!` rule before its matching ignore rule has no effect (order semantics).
- `--dedupe-content` on two identical text files packs one and marks the other; `--json` `meta.deduped == 1`.
- `--tokenizer exact`: test skips if `tiktoken` is not importable; when present, `tokens` differs from the heuristic for a known string and the header names the tokenizer; when absent (monkeypatched import), exit 3 with the extra's install hint.
- `--outline src/carrel/cli.py` lists `LazyGroup` and `main` with line numbers; on a `.md` fixture lists its headings; `--outline --chunk 100` exits 2.
- All pre-existing `test_pack.py` tests pass unchanged.
