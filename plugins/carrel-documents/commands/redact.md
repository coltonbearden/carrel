---
description: Redact sensitive strings (emails, phones, SSNs, IPs, card numbers, or custom regexes) from a text file or PDF using the carrel CLI — PDFs are truly rasterized, not just overlaid
argument-hint: <file> [what to redact: builtin names and/or patterns] [output]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel), Bash(grep:*)
carrel-command: redact
---

Redact the file the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel redact --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel redact [OPTIONS] SRC

  Redact sensitive strings from a text file or PDF.

  Text files get regex replacement (JSON/XML are re-parsed afterwards so they stay valid). PDFs are
  truly redacted: pages are rasterized, matched words are painted over, and the output carries no
  text layer at all. Requires tesseract for PDFs.

Options:
  --pattern REGEX     Custom regex to redact (repeatable).
  --builtin LIST      Comma-separated builtins: email, phone, ssn, ipv4, cc.
  --replacement TEXT  Replacement text for matches (text files only).  [default: █]
  -o, --out PATH      Output file. Default: SRC.redacted.<ext>.
  --fail-empty        Exit 5 when nothing matched.
  --force             Allow overwriting an existing output file.
  --json              Machine-readable JSON output.
  --help              Show this message and exit.
```
<!-- usage:end -->

- `--builtin LIST`: comma-separated `email,phone,ssn,ipv4,cc` — the fast path for "strip PII". `--pattern REGEX` (repeatable) for anything else (names, account numbers, project codenames). Combine both freely.
- Text files (txt/md/html/csv/xml/json) get regex replacement with `--replacement` (default `█`); JSON/XML are re-parsed afterwards so they stay valid.
- **PDFs are truly redacted**: pages are rasterized, matched words are painted over, and the output carries **no text layer at all** — nothing can be recovered by copy-paste or text extraction, but the file is also no longer searchable. Say this to the user; if they need a searchable result afterwards, run `carrel ocr OUT.redacted.pdf --to pdf` on the redacted copy. Needs tesseract (exit 3 → relay the install hint).
- Output defaults to `SRC.redacted.<ext>` next to the source; the original is never modified. `--force` only when the user explicitly wants an existing output overwritten. `--fail-empty` exits 5 when nothing matched — useful when the user expects hits.

Use `--json` and report how many matches were redacted per pattern and the output path. **Verify before declaring success**: for text outputs, `grep -c` the original pattern in the output (expect 0) or run `carrel diff SRC OUT`; for PDFs, `carrel convert OUT --to txt` should yield no text at all. If matches were zero, say so plainly and suggest patterns rather than reporting "done". For a full redact → verify → sign workflow use this plugin's `document-clerk` agent and `redaction-and-provenance` skill.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
