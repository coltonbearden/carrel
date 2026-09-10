---
name: mail-archive
description: Turning an email export (eml files, an mbox, or an Outlook .pst) into a searchable, cross-referenced part of a carrel desk — split, index, thread, pull attachments, link messages to the invoices and cases they mention. Use when the user has a mailbox export or a folder of .eml files and wants to search it, find what belongs together, or file its attachments.
---

# From a mail export to a searchable archive

`.eml` and `.mbox` are first-class carrel file types: `inspect`, `convert`, `index`/`search`, `pack`, `refs` and the `carrel-guard` Read hook all read them with the standard library — no binary needed. Run `carrel mail --help` and `carrel doctor` before composing flags; only `mail pst` needs an external tool (`readpst`, `sudo apt install pst-utils`).

## 1. Get one message per file (optional but recommended)

```bash
carrel mail split archive.mbox --out-dir ~/mail/2026 --json      # {n}_{date}_{subject}.eml per message
carrel mail pst export.pst --out-dir ~/mail/outlook               # Outlook → one .eml per message, folders kept
```

One file per message makes every later step addressable: a search hit, a tag, a note and a reference all point at a single `.eml`.

## 2. Index and search

```bash
carrel --root ~/mail index                 # eml/mbox are indexed like any document
carrel --root ~/mail search 'invoice AND overdue' --type eml
carrel --root ~/mail pack ~/mail/2026 --query 'renewal' --top 10 -o ctx.md
```

`--type eml` narrows to messages; the indexed text is headers + body + attachment names, so a search for an attachment's file name finds the message that carried it.

## 3. Threads and attachments

```bash
carrel mail threads ~/mail/2026 --json     # Message-ID / In-Reply-To / References → conversations
carrel mail attachments ~/mail/2026/*.eml --out-dir ~/mail/attachments --json
```

Attachment records carry `sha256`, so `carrel dedupe ~/mail/attachments` finds the copies every reply re-attached.

## 4. Cross-reference with the rest of the desk

```bash
carrel --root ~/desk refs ~/desk --tag       # invoice / PO / IBAN numbers → ref:<kind>:<value> tags
carrel --root ~/desk tag find ref:invoice:inv-2026-0042   # the invoice PDF, the remittance email, the bank export
carrel --root ~/desk refs ~/desk --link      # the same grouping without writing tags
```

A message that mentions `INV-2026-0042` ends up tagged exactly like the invoice PDF that carries it; `search QUERY --tag ref:invoice:inv-2026-0042` then searches only that bundle.

## Caveats

- `.msg` (Outlook item files) are not supported; export the mailbox to `.pst` and use `mail pst`, or save messages as `.eml` from the client.
- `mail split` and `mail attachments` never overwrite (`--force` opts in); file names are sanitised, so a subject full of slashes still yields a valid name.
- The Read guard converts a message to text on the fly when Claude tries to `Read` it; nothing in the mailbox is modified.
