# Cookbook

Runnable, end-to-end recipes for common carrel pipelines. Every script:

- runs from anywhere (`bash examples/cookbook/01-scan-to-searchable-notes.sh`),
- works in a throwaway `mktemp -d` dir and cleans up after itself — the repo and
  your files are never touched,
- uses fixture files from [`tests/fixtures/`](../../tests/fixtures/),
- uses `carrel` from PATH when installed, falling back to `uv run` inside this
  repo automatically,
- echoes `==>` checkpoints as it goes and ends with `RECIPE OK` on success
  (`set -euo pipefail` — any failed step aborts the run).

| Recipe | Pipeline | Extra requirements |
|---|---|---|
| [01-scan-to-searchable-notes.sh](01-scan-to-searchable-notes.sh) | scanned pdf → `ocr` → md → `index` → `search` | ocrmypdf, tesseract |
| [02-watch-auto-thumbs.sh](02-watch-auto-thumbs.sh) | `watch` a folder → auto-`thumb` new images (10 s, hands-off) | — |
| [03-dedupe-sweep.sh](03-dedupe-sweep.sh) | `dedupe`: report → plan → delete oldest, keep newest | — |
| [04-redact-pii.sh](04-redact-pii.sh) | `redact` built-in PII patterns in txt, then true PDF redaction + leak test | weasyprint, tesseract |
| [05-conversion-relay.sh](05-conversion-relay.sh) | `convert` md → html → pdf → txt, `inspect --json` folded into a summary | pandoc, weasyprint, pdftotext |
| [06-form-roundtrip.sh](06-form-roundtrip.sh) | `form build` (JSON spec → HTML/PDF) + `form fill`/`fields` on an AcroForm | weasyprint (build --pdf) |
| [07-audiobook-from-markdown.sh](07-audiobook-from-markdown.sh) | `audiobook`: markdown → per-chapter MP3s (headings spoken, code skipped) | espeak-ng, ffmpeg |
| [08-pack-repo-for-claude.sh](08-pack-repo-for-claude.sh) | `pack` a repo for LLM context: `--stats` budget, XML pack, `--chunk` parts | — |
| [09-provenance-chain.sh](09-provenance-chain.sh) | `sign manifest` + ephemeral GPG key + tamper detection (`sign verify` → exit 1) | gpg |
| [10-pack-what-matters.sh](10-pack-what-matters.sh) | `index` a docs tree → `pack --query` (relevance-ranked, `--stats` score column, `--fail-empty` → exit 5) | — |

Run `carrel doctor` first — it tells you which external binaries each command
needs and how to install anything missing (`sudo apt install …`).

For small copy-paste utilities rather than walkthroughs, see
[`snippets/`](../../snippets/README.md).
