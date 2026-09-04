---
description: Bundle files or folders into one LLM-ready context document (md/xml/json, token-budgeted, chunkable; query-ranked or git-scoped selection) using the carrel CLI
argument-hint: <paths...> [query/since/format/budget wishes]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: pack
---

Pack these paths into an LLM-ready context document: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel pack --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel pack [OPTIONS] PATHS...

  Bundle PATH... (files or directories) into one LLM-ready context document.

  Formats: md (default: header + fenced tree + per-file fenced sections, fences lengthened on
  collision), xml (<context><tree/><file/></context> with CDATA, Claude-friendly), json ({meta,
  tree, files}). Token counts are ceil(chars / 3.6) labeled tokens_est by default; --tokenizer exact
  counts with tiktoken (o200k_base) and labels the field tokens.

  Selection: --query ranks files through the desk index under --root (build it with the `index`
  command) and emits hits in relevance order; --since REF / --changed narrow to what git reports as
  changed (deleted files are listed in the header as removed). Both may be combined with each other
  and with the usual --include/--exclude filters (intersection).

  .gitignore handling is a deliberately simple per-directory matcher: plain names and `*` globs
  match anywhere below their .gitignore; a trailing `/` restricts a pattern to directories; patterns
  containing `/` match relative to their .gitignore's directory; `!pattern` re-includes, with git's
  ordering rule (last matching line wins) — the negation is honored. `.git` and `.carrel` are always
  skipped. Binaries outside the supported set are listed in the tree as [skipped: binary] with their
  size, never inlined; images are only read (OCR) with --ocr.

Options:
  -o, --output FILE              Write here instead of stdout (with --chunk: OUT.part1..N).
  --format [md|xml|json]         Output format.  [default: md]
  --include GLOB                 Only pack files matching GLOB (repeatable).
  --exclude GLOB                 Drop files/dirs matching GLOB (repeatable).
  --no-gitignore                 Do not honor .gitignore files.
  --max-bytes N                  Stop adding file contents once N total bytes are packed; omissions
                                 are noted in the header.
  --max-file-bytes N             Skip any single file larger than N bytes.
  --chunk TOKENS                 Split into OUT.part1..N, each at most TOKENS tokens under the
                                 active --tokenizer (requires -o). Files are never split mid-file
                                 unless one alone exceeds the budget; then it is split on line
                                 boundaries with (continued) markers.
  --tree-only                    Emit header + tree only, no contents.
  --ocr                          OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --stats                        Print a per-file token table instead of the pack (the pack is still
                                 written when -o is given).
  --query TEXT                   Pack only files the desk index under --root ranks for TEXT (FTS5
                                 syntax), in relevance order. Requires a prior `index` run.
  --top N                        With --query: consider at most the N best-ranked hits.  [default:
                                 20]
  --since REF                    Pack only files changed since git REF (`git diff --name-only REF`);
                                 deleted files are listed as removed, not packed.
  --changed                      Pack only uncommitted changes: files differing from HEAD plus
                                 untracked files (not --since).
  --dedupe-content               Inline identical file contents once; later copies are tree-listed
                                 as [same as <first path>].
  --tokenizer [heuristic|exact]  Token counting: heuristic = ceil(chars/3.6) labeled tokens_est;
                                 exact = tiktoken o200k_base labeled tokens (needs the
                                 'carrel[tokens]' extra).  [default: heuristic]
  --outline                      Structure instead of contents (tree-only cost): .py top-level
                                 def/class names with line numbers, .md headings; other types show
                                 size only. Not with --chunk.
  --fail-empty                   Exit 5 when no file is packed (e.g. --query without hits, --since
                                 with no changes).
  --json                         Machine-readable JSON output.
  --help                         Show this message and exit.
```
<!-- usage:end -->

Selection — reach for these before packing everything:

- `--query TEXT` (with `--top N`, default 20): pack only the files the desk index under `--root` ranks for TEXT (FTS5 syntax), in relevance order. Needs a prior `carrel index`; if there is none, run `carrel --root DIR index` first and say so. This is the right tool for "give me the context about X from this folder".
- `--since REF`: only files git reports changed since REF (branch, tag, commit) — ideal for reviewing a PR or branch; deleted files are listed in the header as removed. `--changed`: uncommitted changes plus untracked files.
- `--include`/`--exclude GLOB` (repeatable) intersect with the above. `.gitignore` is honored, including `!pattern` negation (`--no-gitignore` disables); `.git`/`.carrel` are always skipped; unsupported binaries are tree-listed, never inlined.

Shape and budget:

- `--format md` (default) = header + fenced tree + per-file fenced sections; `xml` = `<context><tree/><file/></context>` with CDATA (Claude-friendly); `json` = `{meta, tree, files}`.
- `-o FILE`: write to a file instead of stdout — strongly prefer this for anything nontrivial so stdout stays readable.
- `--tree-only` (structure) or `--outline` (structure plus `.py` def/class names and `.md` headings, at tree-only cost): the first pass on an unknown folder.
- `--stats`: per-file token table (the pack is still written when `-o` is given).
- `--chunk TOKENS` (requires `-o`): split into `OUT.part1..N`, each within the budget. `--tokenizer exact` counts with tiktoken (field `tokens`) when the budget is tight; the default heuristic labels `tokens_est`.
- `--max-bytes` / `--max-file-bytes N`: byte budgets; omissions are noted in the pack header. `--dedupe-content` inlines identical files once.
- `--ocr`: also read images/scanned PDFs (needs tesseract/ocrmypdf). `--fail-empty`: exit 5 when nothing was packed (e.g. a `--query` with no hits).

Workflow: orient with `--outline`/`--tree-only` or `--stats`, narrow with `--query`/`--since`/globs, then pack with an appropriate `--chunk`. Afterwards report the output path(s), the token total, and anything the header says was omitted or removed; consult the `context-packing` skill of this plugin for budgeting guidance.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
