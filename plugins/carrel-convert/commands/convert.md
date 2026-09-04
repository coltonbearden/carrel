---
description: Convert local files between supported types (pdf, md, txt, html, json, xml, csv, png, jpg, ico) using the carrel CLI
argument-hint: <files...> to <target-type> [options in plain words]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Convert the file(s) the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real flags of `carrel convert` (verify with `carrel convert --help` if unsure — never invent flags):

```
carrel --json convert SRC... --to EXT [-o FILE | --out-dir DIR] [--force] [--pages first|all]
```

Note: `--json` is a **global** flag and must come before `convert`.

- `--to EXT` (required): target type, one of pdf, md, txt, html, json, xml, csv, png, jpg, ico.
- `-o/--output FILE`: explicit output path — single SRC only.
- `--out-dir DIR`: output directory — required when converting multiple SRC files.
- `--force`: only pass when the user explicitly wants existing outputs overwritten.
- `--pages first|all`: pdf → png/jpg only; `all` rasterizes every page as DEST-1..N.

Supported conversions (SRC type → targets): csv → html/json/md · html → md/pdf/txt · ico → jpg/pdf/png · jpg → ico/pdf/png · json → csv/html/xml · md → html/pdf/txt · pdf → html/jpg/md/png/txt · png → ico/jpg/pdf · txt → html/md/pdf · xml → json.

Always use `carrel --json convert ...` and interpret the result for the user: report each `{src, dest, via, ok}` record, celebrate what worked, and explain any failures. Exit code 3 means an optional binary is missing — relay the install hint from stderr. Exit code 4 means an unsupported input/conversion pair — suggest a supported target from the table above.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
