# Snippets

Self-contained, copy-paste utilities built on the carrel CLI. Each file's header
comment states what it does, what it needs, and how to run it — nothing here
imports carrel's internals; everything goes through the CLI.

Conventions:

- Every shell snippet honors `CARREL` so you can point it at a non-PATH install,
  e.g. `CARREL="uv run carrel" ./inbox-triage.sh ~/Downloads`.
- Snippets never overwrite your originals; destructive steps (deletes, moves)
  are always opt-in flags.
- Run `carrel doctor` first if a snippet complains about a missing binary.

| Snippet | What it does | Extra requirements |
|---|---|---|
| [inbox-triage.sh](inbox-triage.sh) | Dry-run sort plan (`organize`) + duplicate report (`dedupe`) for a messy folder | — |
| [pdf-to-searchable.sh](pdf-to-searchable.sh) | OCR every PDF in a folder to `*.ocr.pdf`, then build the full-text index | ocrmypdf, tesseract |
| [watch-thumbs.sh](watch-thumbs.sh) | Watch a folder and auto-thumbnail every image/PDF dropped in | pdftoppm (for PDFs) |
| [redact-pii.sh](redact-pii.sh) | Sweep a folder's text files with all built-in PII patterns into redacted copies | — |
| [sign-and-verify.sh](sign-and-verify.sh) | sha256 manifest of a folder + optional GPG detached signature + verify | gpg (optional) |
| [csv-to-report.sh](csv-to-report.sh) | CSV → Markdown table + standalone HTML report, with a shape summary | python3 |
| [find-untagged.py](find-untagged.py) | Report indexed-type files that carry no tags, via `carrel --json` subprocess calls | python3 |

Packing a repository into chunked LLM context is a cookbook recipe, not a snippet:
[`examples/cookbook/08-pack-repo-for-claude.sh`](../examples/cookbook/08-pack-repo-for-claude.sh)
(token-budget table, XML pack, `--chunk` parts).

For longer, end-to-end walkthroughs with expected output, see the
[cookbook recipes](../examples/cookbook/README.md). Both sets are rendered with
their full source on the docs site under *Cookbook & snippets*.
