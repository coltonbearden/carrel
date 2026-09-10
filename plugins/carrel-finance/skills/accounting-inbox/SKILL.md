---
name: accounting-inbox
description: The end-to-end recipe for turning a folder of invoices, receipts, statements and billing emails into a searchable archive with carrel — extract fields, cross-reference by invoice/PO/IBAN numbers, name and file by date or fiscal period, then query with meta find and tag find. Use when the user has an accounting inbox, a pile of receipts, or asks which documents belong to a payment.
---

# The accounting inbox with carrel

Five commands do the whole job: `fields` reads a document, `refs` links documents that share a number, `rename` names them, `intake` files them, and `meta`/`search`/`tag` answer questions afterwards. Everything is dry-run first; run `carrel doctor` once to see what your environment can read.

## 1. Read one document before trusting the batch

```bash
carrel --json fields invoice.pdf              # vendor, invoice_no, po, date, due, subtotal, tax, total, currency, iban
carrel --json fields receipts/ --profile receipt --date-order dmy --ocr
```

Each field carries a **confidence**: `high` (it followed its label — `Total Due`, `Invoice Date`), `medium` (a heuristic: the largest amount, the first date, `Net 30` → due date, the first name-like line as vendor), `low` (a fallback: the file's mtime or name). Fix a wrong one with `--set vendor="Acme Corp"` for that run. Only `high`/`medium`/`user` values are ever written to the desk.

## 2. Link the documents that belong together

```bash
carrel --json refs ~/accounting --link        # values that appear in more than one file
carrel --root ~/accounting refs ~/accounting --tag
carrel --root ~/accounting tag find ref:invoice:inv-2026-0042
```

Kinds: label-driven `invoice`, `po`, `order`, `check`, `account`, `tracking`, `ticket`, plus check-digit-verified `iban`, `routing`, `ein`, `vat`, `isbn`, `gtin`, `doi`, `ups`, `usps`. A value with a check digit only appears when the digit verifies, so a nine-digit number is a routing number only when it really is one. Add a house format with `--pattern acme='ACME-(?P<v1>\d+)'`.

## 3. Name and file

```bash
carrel rename ~/inbox/*.pdf --template '{date}_{vendor}_{ref}{ext}'          # dry-run
carrel intake ~/inbox --to ~/accounting                                       # dry-run: the whole pipeline
carrel intake ~/inbox --to ~/accounting --apply --by period --fiscal-start 7  # FY2027/Q1/...
```

`intake` per file: fields → refs → name → move into `YYYY/MM` (or `FY<year>/Q<n>`) → index → save fields → tag. Scans are OCRed into a searchable copy and the original is kept under `_originals/`. Nothing is overwritten; nothing is deleted. `--watch --stable 5` keeps filing what arrives, waiting for slow scanners to finish writing.

## 4. Ask the questions

```bash
carrel --root ~/accounting meta find 'total>1000' 'due<2026-11'
carrel --root ~/accounting meta find 'vendor~acme' 'paid=false'
carrel --root ~/accounting search 'overdue OR reminder' --meta 'total>500' --type pdf,eml
carrel --root ~/accounting meta export -o fields.csv        # the folder as a spreadsheet
```

Numbers compare numerically and ISO dates chronologically (`due<2027` works as a prefix), because `fields --save` and `intake` store them canonically with a kind.

## Caveats worth stating to the user

- Line items are not extracted — `fields` reads document-level facts only.
- `total` is the labelled total, or the largest amount when there is no label; on a statement that may be a balance, not a charge.
- A `low`-confidence date is the file's mtime, which is when it was *copied*, not when it was issued.
- Two-digit and slashed dates are ambiguous: `--date-order dmy` for European documents, and the record says `ambiguous` when both readings are possible.
- carrel files and finds documents; it does not do arithmetic, reconcile ledgers or give accounting advice.
