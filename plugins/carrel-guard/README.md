# carrel-guard

Two hooks, no slash commands. Install with `claude plugin install carrel-guard@carrel`;
requires the `carrel` CLI on PATH (`uv tool install carrel`), otherwise both hooks are
silent no-ops.

## What it does

**`PreToolUse` on `Read` → `scripts/read-guard.sh`.** Claude's `Read` tool cannot parse
PDFs, Word/OpenDocument/EPUB/RTF files, spreadsheets or images. When Claude is about to
`Read` one of those (`.pdf .docx .odt .epub .rtf .xlsx`, and `.png .jpg .jpeg .ico` when
OCR is installed), the guard:

1. converts it to text with `carrel convert --to txt` (images: `carrel ocr --to txt`),
2. writes the text into a cache directory (below),
3. returns a hook decision that lets the Read proceed with `file_path` rewritten to the
   text file (`offset`/`limit` pass through unchanged), plus an `additionalContext` line
   telling Claude what happened:

   > carrel-guard: /path/report.pdf was converted to text at ~/.cache/carrel-guard/…/report.txt (18432 chars). Original left untouched.

If anything is off — not one of those extensions, `carrel` missing, file over 64 MiB,
conversion failed or timed out, OCR unavailable — the script prints nothing, exits 0, and
the normal Read happens exactly as it would without the plugin.

**`SessionStart` → `scripts/capabilities.sh`.** Runs `carrel doctor --json` once and adds
a one-paragraph `additionalContext`: carrel version, how many commands are
ok/degraded/unavailable, and the three most useful missing optional binaries with their
install hints. Silent when carrel is absent.

## The guard never modifies your files

Sources are only ever read. Conversions are written to the cache; `--force` applies to
the cached text file only.

## Cache directory

```
${XDG_CACHE_HOME:-$HOME/.cache}/carrel-guard/<sha256 of the file's absolute path>/<stem>.txt
```

A cached text file is reused while it is newer than its source; touching or editing the
source triggers a fresh conversion on the next Read.

Clear it any time — nothing else depends on it:

```bash
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/carrel-guard"
```

## Tunables (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CARREL_GUARD_TIMEOUT` | `5` | seconds allowed for `carrel convert` (needs coreutils `timeout`) |
| `CARREL_GUARD_OCR_TIMEOUT` | `30` | seconds allowed for `carrel ocr` on images |
| `CARREL_GUARD_MAX_BYTES` | `67108864` | files larger than this (64 MiB) are left to the plain Read |
| `CARREL_GUARD_DOCTOR_TIMEOUT` | `20` | seconds allowed for `carrel doctor` at session start |

## Try it by hand

```bash
printf '%s' '{"tool_name":"Read","tool_input":{"file_path":"tests/fixtures/b.pdf"}}' \
  | plugins/carrel-guard/scripts/read-guard.sh | jq .
```

## Turning it off

```bash
claude plugin disable carrel-guard   # keep installed, hooks off
claude plugin enable carrel-guard
```

There is no per-hook toggle; hooks load with their plugin.
