---
description: Find invoice, PO, IBAN, routing, VAT and tracking numbers in local files, tag files with them, or show which documents share a reference
argument-hint: <file or folder> [--kind invoice,po] [--tag] [--link]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: refs
---

Find the reference numbers the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel refs --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel refs [OPTIONS] PATHS...

  Find reference numbers (invoice, PO, IBAN, routing, tracking, …) in PATH...

  Directories are walked like `index` (hidden and .gitignored entries skipped; images only with
  --ocr). Every supported file type works; the text comes from the same spine `pack` and `index`
  use. Values with a check digit (iban, routing, isbn, gtin, cc) are reported only when it verifies.
  JSON output is a list of {path, refs: [{kind, value, count, valid, pages, lines}]} — or, with
  --link, [{kind, value, files, count}]. Kinds are shared with `redact --builtin`.

Options:
  --kind K1,K2          Only these kinds, comma-separated. Default: every reference and identifier
                        kind (invoice, po, order, check, account, tracking, ticket, iban, routing,
                        ein, vat, isbn, gtin, doi, ups, usps); PII kinds (email, phone, ssn, ipv4,
                        cc) only when named.
  --pattern NAME=REGEX  Extra kind to look for (repeatable). A (?P<v1>…) group is the value;
                        otherwise the whole match is.
  --tag                 Tag each file in the desk db under --root with ref:<kind>:<value>.
  --link                Group by reference instead of by file: which files share each value.
  --all                 With --link, also list values seen once.
  --ocr                 OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --fail-empty          Exit 5 when no reference was found.
  --json                Machine-readable JSON output.
  --help                Show this message and exit.
```
<!-- usage:end -->

- Start with `carrel --json refs PATH...` on the files or folder in question; every supported type works (PDF, docx, xlsx, md, txt, eml, …) and PDFs report page numbers.
- "Which files mention invoice X" / "what belongs together" → `--link` (values seen in more than one file; `--all` lists every value).
- "Tag them" / "link them in the desk" → `--tag` writes `ref:<kind>:<value>` tags into the desk db under the global `--root` (default cwd); afterwards `carrel tag find ref:invoice:inv-2026-0042` and `carrel search QUERY --tag ref:...` find every document carrying that reference.
- Narrow with `--kind invoice,po,iban`; the PII kinds (email, phone, ssn, ipv4, cc) are only scanned when named. Add a house format with `--pattern NAME=REGEX` (a `(?P<v1>…)` group is the value).
- Values with a check digit (IBAN, routing, ISBN, GTIN, card) are only reported when it verifies (`"valid": true`); other kinds carry `"valid": null`.
- Scanned PDFs and images need `--ocr` (tesseract); a missing binary exits 3 with the install hint — report it rather than guessing.

Report what was found conversationally: per file, the kinds and values (with pages), then any shared references. The same kinds are available to `/carrel-documents:redact --builtin` when the user wants them removed instead.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
