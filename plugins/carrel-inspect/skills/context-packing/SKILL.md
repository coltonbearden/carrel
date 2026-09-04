---
name: context-packing
description: When and how to bundle local folders/files into LLM context with carrel pack — query-ranked selection, git-scoped packs for PRs, outline/tree orientation, exact token budgeting, chunking and include/exclude strategy. Use when preparing documents or a codebase-adjacent folder as context for an LLM, or when a pack would blow the context window.
---

# Context packing with `carrel pack`

`carrel pack PATHS...` turns files and folders into a single LLM-ready document. The skill is choosing *which* files and *how much* of them — in that order. Run `carrel pack --help` before composing flags; the slash command `/carrel-inspect:pack` carries the current help.

## When to pack

- The user wants an LLM (this session or another) to "read" a folder of documents.
- You need repeatable, shareable context (a file you can re-attach) rather than ad-hoc Reads.
- Many small files are involved — one pack beats dozens of Read calls.

Don't pack when the user needs 1–2 specific files — just read those.

## Decision procedure

1. **Ask the index first: `--query`.** For "what does this folder say about X", don't pack the folder — pack the hits: `carrel --root DIR pack DIR --query 'X OR "x phrase"' --top 12 -o ctx.md`. Files come out in relevance order (FTS5 syntax: phrases in quotes, AND/OR/NOT, `term*`). This needs a desk index — run `carrel --root DIR index` once (incremental, cheap to repeat). `--fail-empty` turns "no hits" into exit 5 so you notice.
2. **Scope by git for reviews: `--since`.** For a PR or branch, `carrel pack . --since main -o pr.md` packs only what changed since the ref (deleted files are listed in the header as removed, not packed); `--changed` does the same for uncommitted work. Combine with `--query` or globs — filters intersect.
3. **Orient before you commit: `--tree-only` / `--outline`.** On an unknown folder, `carrel pack DIR --outline` costs the same as a tree but shows `.py` def/class names with line numbers and `.md` headings — usually enough to pick `--include` globs. `--tree-only` is the bare structure. `--stats` prints a per-file token table (the pack is still written when `-o` is given).
4. **Choose a format.**
   - `--format xml` for Claude — CDATA-wrapped `<file>` sections parse robustly.
   - `--format md` (default) for humans and most models — fenced sections, fences auto-lengthen on collision.
   - `--format json` when a program will consume the pack.
5. **Trim before you chunk.** Prefer `--exclude`/`--include` globs (repeatable) over huge chunk counts: exclude build output, archives, fixtures. `.gitignore` is honored, including `!pattern` re-includes with git's last-match-wins rule (`--no-gitignore` disables); `.git`/`.carrel` are always skipped. Binaries outside the supported types are tree-listed, never inlined. `--dedupe-content` inlines identical files once.
6. **Count precisely when it matters: `--tokenizer exact`.** The default estimate is `ceil(chars/3.6)` labeled `tokens_est` — fine for sizing. When the pack must fit a hard budget (chunks near the window, billing), add `--tokenizer exact` (tiktoken o200k_base, field `tokens`; needs the `carrel[tokens]` extra — exit 3 tells you).
7. **Set budgets.**
   - Fits comfortably (rule of thumb: ≤ half the model's window, e.g. ≲80k tokens for a 200k window): single pack, `-o context.md`.
   - Too big: `--chunk TOKENS -o out.md` → `out.part1..N`, each ≤ TOKENS under the active tokenizer. Files are never split mid-file unless one alone exceeds the budget (then split on line boundaries with "(continued)" markers). Pick TOKENS ≈ what one turn can afford, e.g. 30000–60000. Not with `--outline`.
   - Hard caps: `--max-bytes N` (total) and `--max-file-bytes N` (skip single huge files); omissions are noted in the pack header — mention them to the user.
8. **Images/scans:** only read with `--ocr` (needs tesseract/ocrmypdf); otherwise they're listed but contribute no text.

## Examples

```bash
# The 12 most relevant files about a topic, Claude-friendly
carrel --root ./papers index
carrel --root ./papers pack ./papers --query 'transformer AND survey' --top 12 --format xml -o topic.xml

# Everything a PR touched, with exact token counts
carrel pack . --since main --tokenizer exact --stats -o pr.md

# Orientation pass on an unknown folder
carrel pack ./unknown-folder --outline

# Big corpus, 40k-token chunks, skip anything over 2 MB
carrel pack ./archive --chunk 40000 --max-file-bytes 2000000 -o archive.md
```

## Interpreting results

Report to the user: output path(s), the token total (`tokens_est` or exact `tokens`), the query/ref that selected the files, and anything the header says was omitted or removed (budget hits, skipped binaries, deleted files). If chunked, say how many parts and suggest feeding them in order.
