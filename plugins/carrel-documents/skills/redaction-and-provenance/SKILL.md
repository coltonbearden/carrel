---
name: redaction-and-provenance
description: How to redact documents with carrel so the sensitive text is really gone, and how to prove what was delivered — true-raster PDF redaction and its side effects, re-OCR afterwards, the sha256 manifest write/verify flow. Use when removing PII or confidential strings from files, or when a redacted deliverable needs an integrity trail.
---

# Redaction and provenance with carrel

`carrel redact` removes matches; `carrel sign manifest` / `carrel sign verify` prove what left your hands. This skill is the set of caveats that turn those two commands into a defensible process. Run `carrel redact --help` and `carrel sign --help` before composing flags.

## 1. Text files: replacement you can diff

For txt/md/html/csv/xml/json, `carrel redact SRC --builtin email,phone --pattern 'ACME-[0-9]{6}' -o OUT` replaces each match with `--replacement` (default `█`). JSON and XML are re-parsed afterwards so the output stays valid. Verify with `grep -c -E PATTERN OUT` (expect 0) and `carrel diff SRC OUT` to see exactly which lines changed — the diff is your review artifact.

Builtins: `email`, `phone`, `ssn`, `ipv4`, `cc`. Custom `--pattern` is a Python regex; test it on one file first. `--fail-empty` makes zero matches an exit-5 error, which is the right default in scripts.

## 2. PDFs: true-raster redaction, and what that costs

A PDF redaction that draws a black box over text leaves the text in the file — copy-paste or `pdftotext` recovers it. carrel does not do that. `carrel redact SRC.pdf ...` **rasterizes every page, paints over the matched words, and writes a PDF with no text layer at all.** Consequences to tell the user:

- Nothing is recoverable from the output — that is the point.
- The output is an image PDF: **not searchable, not selectable, larger**, and its metadata (title/author) is not carried over. `carrel inspect OUT --json` shows `pages` but no `title`.
- It needs tesseract (matches are located by OCR-ing the render); exit 3 → `sudo apt install tesseract-ocr`. Scanned PDFs work the same way; born-digital ones lose their text layer deliberately.
- Verification: `carrel convert OUT --to txt -o check.txt` must yield an empty/near-empty file. A PDF redaction with **zero matches** still rasterizes — check the JSON match counts, and when they are 0 say so instead of shipping a pointless image PDF.

**Re-OCR afterwards** when the recipient needs a searchable file: `carrel ocr OUT.redacted.pdf --to pdf -o OUT.redacted.searchable.pdf`. OCR reads only what is visible, so painted-over words cannot come back — but grep the OCR text (`carrel convert ... --to txt`) for your patterns anyway; near-misses (a partially covered digit run) are what you are looking for.

## 3. Provenance: the manifest flow

```bash
carrel --json sign manifest OUT.redacted.pdf notes.redacted.md -o delivery.sha256   # sha256sum format
carrel --json sign manifest ./delivery -o delivery.sha256 --gpg                        # dir recurses; + delivery.sha256.asc
carrel --json sign verify delivery.sha256                                              # every file ok? signature good?
```

- The manifest proves *these bytes* were delivered; the gpg signature proves *who* said so. Neither proves the redaction was complete — that is what step 1/2's verification is for. Keep both artifacts together with the verification notes.
- `verify` reports each file as `ok`, `changed`, or `missing`, and the signature status when `MANIFEST.asc` exists. A `changed` entry after delivery means the file was touched — re-verify before answering questions about it.
- `sign stamp` draws a *visible* signature block on a PDF page. It is a mark, not cryptography — use it for "reviewed by" stamps, and the manifest for integrity.
- Never `--force` over an existing manifest: a manifest that silently changes is worse than none. Write `delivery-v2.sha256` instead.

## 4. Order of operations (what the `document-clerk` agent does)

1. `carrel inspect` inputs; `carrel doctor --json` for tesseract/gpg.
2. Redact to a new path; note match counts.
3. Verify on the output (grep / diff / no-text check); re-OCR if searchability is required and verify again.
4. `sign manifest` the deliverables; `sign verify` it; report file → output, counts, verification, manifest path.

Originals stay untouched throughout; every write is a new file.
