#!/usr/bin/env bash
# 12 — Mail archive: split a mailbox, index it, follow the threads
#
# `.eml` and `.mbox` are ordinary carrel file types (stdlib parsing, no binary),
# so a mailbox can be split into one file per message, indexed, searched, packed
# and cross-referenced with the invoices those messages mention. This recipe
# takes the committed thread fixture apart and puts it back together as an
# archive you can query.
#
# Runs offline in a temp dir. Requires: nothing beyond carrel (only the optional
# `carrel mail pst` step for Outlook exports would need readpst, and this recipe
# does not use it).
#
# Expected: three messages split out of the mailbox, an index that finds a word
# from a message body, a thread grouping of 2 + 1, an attachment written with its
# sha256, references linking the email to the invoice, then RECIPE OK.
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$here/../.."
fixtures="$REPO/tests/fixtures"
if [ -z "${CARREL:-}" ]; then
    if command -v carrel >/dev/null 2>&1; then CARREL="carrel"; else CARREL="uv --project $REPO run carrel"; fi
fi
# intentionally unquoted below: CARREL may hold "uv --project ... run carrel"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
archive="$work/mail"
mkdir -p "$archive"

echo "==> step 1: what is in the mailbox (no binary needed to read it)"
$CARREL inspect "$fixtures/thread.mbox" | sed 's/^/  /'

echo "==> step 2: split it into one .eml per message"
$CARREL --json mail split "$fixtures/thread.mbox" --out-dir "$archive/2021" \
  | python3 -c 'import json,sys; [print("  ", r["n"], r["date"][:10], r["subject"]) for r in json.load(sys.stdin)]'

echo "==> step 3: add the invoice email that belongs with them"
cp "$fixtures/sample.eml" "$archive/2021/invoice-mail.eml"

echo "==> step 4: index the archive and search the message bodies"
$CARREL --root "$archive" index >/dev/null 2>&1
$CARREL --root "$archive" --json search 'quixotic' --type eml \
  | python3 -c 'import json,sys; print("  body hit:", [h["path"] for h in json.load(sys.stdin)])'

echo "==> step 5: the conversations (Message-ID / In-Reply-To / References)"
$CARREL mail threads "$archive/2021" | sed 's/^/  /'

echo "==> step 6: attachments come out as files, with digests"
$CARREL --json mail attachments "$archive/2021/invoice-mail.eml" --out-dir "$work/attachments" \
  | python3 -c 'import json,sys; [print("  ", a["filename"], a["size"], "bytes", a["sha256"][:12]) for r in json.load(sys.stdin) for a in r["attachments"]]'

echo "==> step 7: what links the mail to the rest of the desk"
$CARREL --json refs "$archive/2021" --link \
  | python3 -c 'import json,sys; [print("  ", g["kind"], g["value"], "->", len(g["files"]), "files") for g in json.load(sys.stdin)]'

echo "RECIPE OK"
