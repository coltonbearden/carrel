---
description: Compare two local files — text diff, structural json/csv/xml diff, PDF text diff, or image pixel diff — using the carrel CLI
argument-hint: <file A> <file B> [mode]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Compare the two files the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel diff` (verify with `carrel diff --help` if unsure — never invent flags):

```
carrel diff A B [--mode auto|text|struct|image|pdf] [--out FILE] --json
```

- `--mode auto` (default) picks by type pair; only override when the user asks for a specific comparison:
  - `text`: unified diff.
  - `struct`: json (dotted-path added/removed/changed), csv (per-row/column cell changes), xml (element-path changes).
  - `pdf`: extracted-text diff plus page counts.
  - `image`: Pillow pixel diff — dimensions, changed-pixel percentage, mean channel delta.
- `--out FILE` (image mode only): writes a per-pixel delta heatmap PNG — offer this when comparing images.

Interpret the exit code first: **0 = identical, 1 = files differ** (that's data, not an error), 2 = bad usage, 3 = missing optional dependency (pdf mode needs pdftotext — relay the install hint), 4 = missing/unsupported input or no mode fits the type pair. Then summarize the differences for the user: what changed, where, and how much — not a raw dump.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
