---
description: Bundle files or folders into one LLM-ready context document (md/xml/json, token-budgeted, chunkable) using the carrel CLI
argument-hint: <paths...> [format/budget wishes]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Pack these paths into an LLM-ready context document: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel pack` (verify with `carrel pack --help` if unsure — never invent flags):

```
carrel pack PATHS... [-o FILE] [--format md|xml|json] [--include GLOB] [--exclude GLOB]
            [--no-gitignore] [--max-bytes N] [--max-file-bytes N] [--chunk TOKENS]
            [--tree-only] [--ocr] [--stats]
```

- `--format md` (default) = header + fenced tree + per-file fenced sections; `xml` = `<context><tree/><file/></context>` with CDATA (Claude-friendly); `json` = `{meta, tree, files}`.
- `-o FILE`: write to a file instead of stdout — strongly prefer this for anything nontrivial so stdout stays readable.
- `--include`/`--exclude GLOB` (repeatable): narrow what gets packed.
- `--chunk TOKENS` (requires `-o`): split into `OUT.part1..N`, each within the token budget.
- `--max-bytes` / `--max-file-bytes N`: byte budgets; omissions are noted in the pack header.
- `--tree-only`: structure without contents — good first pass on unknown folders.
- `--stats`: per-file token table (the pack is still written when `-o` is given).
- `--ocr`: also read images/scanned PDFs (needs tesseract/ocrmypdf).
- `.gitignore` is honored by default (`--no-gitignore` disables); `.git` and `.carrel` are always skipped; unsupported binaries are listed in the tree, never inlined.

Workflow: for an unfamiliar or large folder, run `--stats` or `--tree-only` first to gauge size, then pack with an appropriate `--chunk`/`--exclude`. Afterwards report the output path(s) and the token estimate, and consult the `context-packing` skill of this plugin for budgeting guidance.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
