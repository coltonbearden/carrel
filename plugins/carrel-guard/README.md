# carrel-guard

Two hooks, no slash commands. Install with `claude plugin install carrel-guard@carrel`;
requires the `carrel` CLI on PATH (`uv tool install carrel`), otherwise both hooks are
silent no-ops.

## What it does

**`PreToolUse` on `Read` → `scripts/read-guard.sh`.** Claude's `Read` already handles more
than it gets credit for: per the [tools reference](https://code.claude.com/docs/en/tools-reference),
images come back as pictures Claude can see, and PDFs are read natively (in `pages` ranges past
ten pages). What it cannot open are the zip-and-XML and mailbox formats —
`.docx .odt .epub .rtf .xlsx .eml .mbox .mbx`.

So the guard converts what `Read` cannot open, and makes a cheaper choice for one thing it can:

| Extension | Default | Why |
|---|---|---|
| `.docx .odt .epub .rtf .xlsx .eml .mbox .mbx` | converted to text | `Read` cannot open them at all |
| `.pdf` | converted to text | page images cost far more tokens than the text; `CARREL_GUARD_PDF_TEXT=0` keeps the visual `Read` when layout or diagrams matter |
| `.png .jpg .jpeg .ico` | **left alone** | `Read` shows Claude the image; OCR would replace a chart or a screenshot with a worse transcription. `CARREL_GUARD_OCR_IMAGES=1` turns it on |

When the guard does act, it:

1. converts the file with `carrel convert --to txt` (images: `carrel ocr --to txt`),
2. writes the text into a cache directory (below),
3. returns a hook decision that lets the Read proceed with `file_path` rewritten to the
   text file (`offset`/`limit` pass through unchanged), plus an `additionalContext` line
   telling Claude what happened and where the original still is:

   > carrel-guard: /path/report.pdf was converted to text at ~/.cache/carrel-guard/…/report.txt (18432 chars). The original is untouched at /path/report.pdf — Read it directly when layout, diagrams or images matter.

If the conversion **times out**, the guard says so and lets the Read proceed on the original —
`additionalContext` without `updatedInput`, which the
[hooks reference](https://code.claude.com/docs/en/hooks) allows, since the decision fields are
independent and an omitted `permissionDecision` means the normal permission flow applies.

If anything is off — not one of those extensions, `carrel` missing, file over 64 MiB,
conversion failed, OCR unavailable — the script prints nothing, exits 0, and
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
| `CARREL_GUARD_TIMEOUT` | `15` | seconds allowed for `carrel convert` (needs coreutils `timeout`). A 68 KB docx takes ~6.7 s through pandoc and a 127 KB one ~13.9 s; the old 5 s killed both silently |
| `CARREL_GUARD_OCR_TIMEOUT` | `30` | seconds allowed for `carrel ocr` on images |
| `CARREL_GUARD_OCR_IMAGES` | `0` | `1` OCRs `.png/.jpg/.jpeg/.ico` instead of letting Claude see them |
| `CARREL_GUARD_PDF_TEXT` | `1` | `0` leaves PDFs to the visual `Read` instead of converting them to text |
| `CARREL_GUARD_MAX_BYTES` | `67108864` | files larger than this (64 MiB) are left to the plain Read |

Every toggle reads the same way: `0`, `false`, `no` or `off` (any case) is off, anything else
is on. `hooks/hooks.json` caps this hook at **60 s**, so a `CARREL_GUARD_TIMEOUT` above that
cannot be reached — Claude Code kills the hook first and nothing is printed.
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
