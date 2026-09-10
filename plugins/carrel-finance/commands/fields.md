---
description: Extract vendor, invoice number, PO, dates, subtotal, tax, total and currency from invoices, receipts and statements with the carrel CLI, and optionally save them as desk fields
argument-hint: <file or folder> [--profile invoice|receipt|statement] [--save]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: fields
---

Extract the document fields the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel fields --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel fields [OPTIONS] PATHS...

  Extract vendor, invoice number, dates and totals from PATH... (invoices, receipts, statements).

  Directories are walked like `refs`. Fields: vendor, invoice_no, po, date, due, subtotal, tax,
  total, currency, iban, account_last4 — each with a confidence (high: after its label; medium:
  heuristic; low: fallback) and the evidence line. Amounts are plain decimals, dates ISO. JSON
  output is a list of {path, profile, fields: {name: {value, confidence, evidence}}}.

Options:
  --profile [auto|invoice|receipt|statement]
                                  Document kind; auto picks by keywords.  [default: auto]
  --date-order [mdy|dmy]          How to read an ambiguous slashed date such as 03/04/2026.
                                  [default: mdy]
  --ocr                           OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --set FIELD=VALUE               Override an extracted field (repeatable).
  --save                          Write the fields into the desk db under --root (source: fields).
  --fail-empty                    Exit 5 when no file yielded any field.
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```
<!-- usage:end -->

- Start with `carrel --json fields PATH...`; every supported type works (PDF, docx, eml, txt, …). Each field carries a `confidence`: `high` followed its label (`Total Due`, `Invoice Date`), `medium` was a heuristic (largest amount, first date), `low` a fallback (file mtime, file name) — report the confidence with the value and never present a `low` field as fact.
- European dates (`10.09.2026` meaning 10 September) need `--date-order dmy`; scans and images need `--ocr`.
- Wrong guess? `--set vendor="Acme Corp"` overrides a field for this run; with `--save` the fields land in the desk db under the global `--root` (`carrel meta ls FILE` shows them, `carrel meta find total>1000` queries them, `/carrel-organize:rename` names files from them).
- A missing binary exits 3 with the install hint — report it rather than guessing.

Report the fields conversationally (vendor, number, dates, amounts with currency) and flag anything `medium`/`low` so the user can confirm it. Line items are not extracted — say so if asked.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
