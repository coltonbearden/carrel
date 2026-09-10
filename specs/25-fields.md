# spec: fields — vendor, numbers, dates and totals out of documents

**Owns:** new `src/carrel/core/money.py`, new `src/carrel/core/dates.py`, new `src/carrel/commands/fields.py`, `src/carrel/commands/mcp.py` (`carrel_fields`), `tests/fixtures/generate.py` (`invoice.txt`, `invoice.pdf`), `tests/test_fields_rename_batch.py` (fields part), `plugins/carrel-finance/commands/fields.md`.
**Wave:** v0.4.0, PR C.

## Why
`meta` (spec 24) can hold `vendor`, `total`, `due`; nothing filled it. Invoices, receipts and statements state those facts next to labels, and a label-driven heuristic gets most of them right with an honest confidence attached — enough for `rename` and `intake` to name and file documents, and for `meta find total>1000` to mean something.

## core/money.py
`parse_number` (`1,234.56`, `1.234,56`, `1 234,56`, `1'234.50`; both separators → the last is decimal; one separator followed by exactly 1–2 digits is decimal, 3-digit groups are thousands), `parse_amount` (full-string: symbol or ISO code before/after, leading minus, parentheses, trailing `-`/`CR`), `find_amounts` (only money-looking numbers: a currency marker, decimals or grouping; never a bare integer, never a number glued to `-`/`/`/letters — so years, ids and quantities are left alone). `Amount(value: Decimal, currency, raw, start, end)`.

## core/dates.py
`find_dates(text, order="mdy")` for ISO, `Y/M/D`, slashed `a/b/y` (`.`/`-` too; two-digit years → 20xx; `ambiguous` when both parts ≤ 12; a part > 12 decides on its own), `10 Oct 2026`, `September 10, 2026`. `parse_date` is the full-string form. Invalid calendar dates are skipped.

## fields.py
`extract_fields(path | label, *, profile="auto", date_order="mdy", ocr=False, text=None) -> {path, profile, fields: {name: {value, confidence, evidence}}}`.
- Fields in order: `vendor, invoice_no, po, date, due, subtotal, tax, total, currency, iban, account_last4`; only found ones are present.
- Labels (`_LABELS`, most specific first) matched at line start: `total` ← Total Due / Amount Due / Balance Due / Grand Total / … / Total / Amount; `subtotal`; `tax` (Tax, VAT, GST, HST, MwSt, TVA, IVA); `date` (Invoice Date, Date of Issue, …, Date); `due` (Due Date, Payment Due, Due By, Pay By, Due). A label on its own line takes the next line. The amount is the last one on the line; the date the first.
- Confidence: `high` after a label (also references from `core/patterns`: invoice_no, po, iban, account_last4 = last 4 digits of a masked account; an email's `From:` display name as vendor); `medium` by heuristic (largest amount = total; first date = date; `Net N` → due = date + N days; first name-like line = vendor, skipping greetings, headings, labels, lines with `:`/`@`/long digit runs); `low` fallback (mtime → date, file stem → vendor). `currency`: the most frequent currency marker.
- `profile=auto` scores keyword sets (invoice / receipt / statement; invoice wins ties); explicit profiles only relabel the record today (the label set is shared).
- Amounts are canonical decimals (`1234.56`), dates ISO — the same forms `meta` stores.
- `fields_for(paths, ..., overrides, save_root)`: directories walk like `refs`; per-file failures are records (`missing_dependency` / `bad_input` / `error`); `--set FIELD=VALUE` replaces a field with confidence `user`; `--save` writes every field through `DeskDB.set_meta` (kinds: num for subtotal/tax/total, date for date/due, str otherwise; source `fields`), adding `saved: [keys]` to the record.

## CLI
`carrel fields PATH... [--profile auto|invoice|receipt|statement] [--date-order mdy|dmy] [--ocr] [--set FIELD=VALUE]* [--save] [--fail-empty]`. JSON: a list of records. Human: one table per file with value, confidence, evidence. Exit 2 for a bad `--set`; 3 when every file needed a missing binary; 5 with `--fail-empty` and nothing found.

## MCP
`carrel_fields {path, profile?, date_order?, ocr?, save?, root?}` → `{root, path, files}` (14 tools).

## Fixtures
`invoice.txt` and `invoice.pdf` (reportlab, Courier, invariant) carry the same labelled invoice: ACME Corp, `INV-2026-0042`, `PO-4471`, dates `09/10/2026` / `10/10/2026`, subtotal/tax/total `$1,150.00` / `$84.56` / `$1,234.56`, a valid IBAN.

## Acceptance
- Both invoice fixtures yield every field above with `high` confidence except vendor (`medium`), and `list(fields) == ["vendor", "invoice_no", "po", "date", "due", "subtotal", "tax", "total", "currency", "iban"]`.
- `sample.eml` → vendor `Acme Billing` (high, from `From:`), total `1234.56` (medium).
- A receipt with `Net 30` gets a medium `due`; an empty file gets only the low fallbacks.
- `--save` produces `meta find total>1000` hits; a PDF with pdftotext pinned to nowhere exits 3.
