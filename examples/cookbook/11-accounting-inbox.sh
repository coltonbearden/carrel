#!/usr/bin/env bash
# 11 — The accounting inbox: read, file, and then ask questions
#
# A folder of invoices and billing email goes in; a searchable, cross-referenced
# archive comes out. `carrel intake` reads each document's own fields (vendor,
# invoice number, dates, totals), finds its reference numbers, names it, files it
# into DEST/YYYY/MM, indexes it, saves the fields as desk metadata and tags it
# with every reference — one command, no shell in between. Afterwards `meta find`
# answers "which invoices over 1000 are due before November", and `tag find`
# answers "which documents mention this invoice number".
#
# Runs offline in a temp dir against the committed fixtures. Requires: nothing
# beyond carrel (fields, refs, intake, meta and search are pure python; only the
# optional OCR of a scanned PDF would need ocrmypdf, and this recipe uses none).
#
# Expected: a dry-run plan naming each destination, an --apply that files three
# documents, a meta table, two queries that find the invoice by amount and by
# reference number, a CSV export, then RECIPE OK.
set -euo pipefail

CARREL="${CARREL:-carrel}"
command -v carrel >/dev/null 2>&1 || CARREL="uv run carrel"

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
fixtures="$here/../../tests/fixtures"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
inbox="$work/inbox"
archive="$work/accounting"
mkdir -p "$inbox"

cp "$fixtures/invoice.txt" "$inbox/scan_0001.txt"        # an invoice with a useless name
cp "$fixtures/invoice.pdf" "$inbox/acme-sept.pdf"        # the same invoice as a PDF
cp "$fixtures/sample.eml"  "$inbox/message.eml"          # the billing email that carries it
cp "$fixtures/sample.md"   "$inbox/unrelated-note.md"    # no reference: intake leaves it alone

echo "==> step 1: what would happen (dry-run is the default — nothing moves)"
$CARREL intake "$inbox" --to "$archive" 2>/dev/null
[ ! -d "$archive" ] || { echo "dry-run created $archive" >&2; exit 1; }
echo "  inbox still holds: $(ls "$inbox" | tr '\n' ' ')"

echo "==> step 2: file it (fields -> refs -> name -> move -> index -> meta -> tags)"
$CARREL intake "$inbox" --to "$archive" --apply --tag fy2026 2>/dev/null

echo "==> step 3: the archive, filed by document date"
(cd "$archive" && find . -type f -not -path './.carrel/*' | sort | sed 's/^/  /')
echo "  left in the inbox (no reference number to name it by): $(ls "$inbox" | tr '\n' ' ')"

echo "==> step 4: the facts carrel read, as a table"
$CARREL --root "$archive" meta ls

echo "==> step 5: the questions this was all for"
echo "  invoices over 1000:"
$CARREL --root "$archive" --json meta find 'total>1000' \
  | python3 -c 'import json,sys; [print("   ", r["path"], "->", r["meta"]["vendor"], r["meta"]["total"], r["meta"]["currency"]) for r in json.load(sys.stdin)]'
echo "  due before November 2026:"
$CARREL --root "$archive" --json meta find 'due<2026-11' \
  | python3 -c 'import json,sys; [print("   ", r["path"], "due", r["meta"]["due"]) for r in json.load(sys.stdin)]'
echo "  every document mentioning invoice INV-2026-0042:"
$CARREL --root "$archive" tag find ref:invoice:inv-2026-0042 | sed 's/^/    /'

echo "==> step 6: full-text search still works, and combines with the fields"
$CARREL --root "$archive" --json search 'ACME' --meta 'total>1000' \
  | python3 -c 'import json,sys; print("  hits:", [h["path"] for h in json.load(sys.stdin)])'

echo "==> step 7: the folder as a spreadsheet"
$CARREL --root "$archive" meta export -o "$work/fields.csv"
head -2 "$work/fields.csv" | sed 's/^/  /'

echo "RECIPE OK"
