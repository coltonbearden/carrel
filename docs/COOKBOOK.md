# Cookbook & snippets

Real, runnable scripts built on the carrel CLI, straight from the repository. Every
script below is included verbatim from `examples/cookbook/` or `snippets/` at docs
build time, so what you read is what is committed.

- **Recipes** (`examples/cookbook/`) are end-to-end walkthroughs. Each one runs in a
  throwaway `mktemp -d` directory using files from `tests/fixtures/`, cleans up after
  itself, echoes `==>` checkpoints as it goes, and ends with `RECIPE OK`
  (`set -euo pipefail` — any failed step aborts the run).
- **Snippets** (`snippets/`) are small copy-paste utilities you point at your own
  folders. They never overwrite originals; destructive steps are opt-in flags.

Both kinds use `carrel` from PATH when installed, falling back to `uv run carrel`
inside a checkout, and honor a `CARREL` environment variable
(`CARREL="uv run carrel" ./snippets/inbox-triage.sh ~/Downloads`). Run
`carrel doctor` first — it names any external binary a script needs and how to
install it.

Related docs: [Quickstart](QUICKSTART.md) · [Command reference](REFERENCE.md) ·
[Installing](INSTALL.md) · [Configuration](CONFIGURATION.md)

## Recipes

Run any recipe from anywhere: `bash examples/cookbook/01-scan-to-searchable-notes.sh`.

### 01 — Scan to searchable notes

Scanned PDF → `ocr` → Markdown → `index` → `search`. Needs ocrmypdf and tesseract.

```bash
--8<-- "examples/cookbook/01-scan-to-searchable-notes.sh"
```

### 02 — Watch a folder, auto-thumbnail

`watch` a folder and auto-`thumb` every new image for ten hands-off seconds. No
external binaries.

```bash
--8<-- "examples/cookbook/02-watch-auto-thumbs.sh"
```

### 03 — Dedupe sweep

`dedupe`: report → plan → delete the oldest copy, keep the newest. No external
binaries.

```bash
--8<-- "examples/cookbook/03-dedupe-sweep.sh"
```

### 04 — Redact PII

`redact` the built-in PII patterns in a text file, then true PDF redaction plus a
leak test. Needs weasyprint and tesseract.

```bash
--8<-- "examples/cookbook/04-redact-pii.sh"
```

### 05 — Conversion relay

`convert` md → html → pdf → txt, with `inspect --json` folded into a summary. Needs
pandoc, weasyprint, and pdftotext.

```bash
--8<-- "examples/cookbook/05-conversion-relay.sh"
```

### 06 — Form round trip

`form build` (JSON spec → HTML/PDF) plus `form fields` / `form fill` on an AcroForm.
Needs weasyprint for `build --pdf`.

```bash
--8<-- "examples/cookbook/06-form-roundtrip.sh"
```

### 07 — Audiobook from Markdown

`audiobook`: Markdown → per-chapter MP3s (headings spoken, code skipped). Needs
espeak-ng and ffmpeg.

```bash
--8<-- "examples/cookbook/07-audiobook-from-markdown.sh"
```

### 08 — Pack a repo for Claude

`pack` a repository for LLM context: `--stats` token budget first, an XML pack,
then `--chunk` parts. No external binaries.

```bash
--8<-- "examples/cookbook/08-pack-repo-for-claude.sh"
```

### 09 — Provenance chain

`sign manifest` with an ephemeral GPG key, then tamper detection (`sign verify`
exits 1). Needs gpg.

```bash
--8<-- "examples/cookbook/09-provenance-chain.sh"
```

### 10 — Pack what matters

Index a docs tree, then `pack --query` to pack only the files the desk ranks
relevant, with `--stats` for the token table. No optional binaries needed.

```bash
--8<-- "examples/cookbook/10-pack-what-matters.sh"
```

## Snippets

Each file's header comment states what it does, what it needs, and how to run it.
Nothing here imports carrel's internals — everything goes through the CLI.

### inbox-triage.sh

Dry-run sort plan (`organize`) plus a duplicate report (`dedupe`) for a messy
folder. No external binaries.

```bash
--8<-- "snippets/inbox-triage.sh"
```

### pdf-to-searchable.sh

OCR every PDF in a folder to `*.ocr.pdf`, then build the full-text index. Needs
ocrmypdf and tesseract.

```bash
--8<-- "snippets/pdf-to-searchable.sh"
```

### watch-thumbs.sh

Watch a folder and auto-thumbnail every image or PDF dropped in. Needs pdftoppm
for PDFs.

```bash
--8<-- "snippets/watch-thumbs.sh"
```

### redact-pii.sh

Sweep a folder's text files with all built-in PII patterns into redacted copies. No
external binaries.

```bash
--8<-- "snippets/redact-pii.sh"
```

### sign-and-verify.sh

sha256 manifest of a folder, an optional GPG detached signature, then verify. gpg
is optional.

```bash
--8<-- "snippets/sign-and-verify.sh"
```

### csv-to-report.sh

CSV → Markdown table plus a standalone HTML report, with a shape summary. Needs
python3.

```bash
--8<-- "snippets/csv-to-report.sh"
```

### find-untagged.py

Report indexed-type files that carry no tags, via `carrel --json` subprocess calls.
Needs python3.

```python
--8<-- "snippets/find-untagged.py"
```

Packing a repository for an LLM used to have its own snippet; it now lives only as
[recipe 08](#08-pack-a-repo-for-claude).
