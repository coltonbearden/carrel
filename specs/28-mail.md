# spec: mail — email as first-class desk files, plus `carrel mail`

**Owns:** new `src/carrel/core/mail.py`, `src/carrel/core/filetypes.py` (EML/MBOX + shape sniff), `src/carrel/core/textextract.py` (mail branch), `src/carrel/commands/inspect.py` (eml/mbox detail), `src/carrel/commands/convert.py` (eml → md/txt/html/pdf, mbox → md/txt), `src/carrel/commands/organize.py` (`mail/` category), `src/carrel/commands/diff.py` (mail is text-like), new `src/carrel/commands/mail.py`, `src/carrel/core/adapters.py` (`readpst`), `src/carrel/commands/mcp.py` (`carrel_mail`), `plugins/carrel-guard/scripts/read-guard.sh`, `tests/fixtures/generate.py` (`sample.eml`, `thread.mbox`), new `tests/test_mail.py`, new plugin `plugins/carrel-mail/`.
**Wave:** v0.4.0, PR B.

## Why
The accounting inbox is half email: the invoice arrives as an attachment, the remittance advice is a reply, the dispute is a thread. Until now a `.eml` was `unsupported file type` to every carrel command. Making it a `FileType` means one `textextract` branch lights up `index`, `search`, `pack`, `diff`, `refs`, `fields`, the desk TUI preview and the `carrel-guard` Read hook at once; the `mail` group covers what those cannot (attachments as files, mbox → messages, threads, Outlook exports).

## Types (D-012)
- `FileType.EML = "eml"`, `FileType.MBOX = "mbox"`, predicate `is_mail`; `is_text` stays False (they are not regex-redaction targets; `redact` would need MIME-aware rewriting).
- `_EXT_MAP`: `.eml`, `.mbox`, `.mbx`.
- Sniff: `detect()` consults `core.mail.looks_like_mbox` (a `From sender date` separator line followed by a header block) then `looks_like_eml` (≥2 well-known header fields before the first blank line) **only for unmapped extensions**, after the source-file check. A `.txt` starting with `From:` stays TXT; an extension-less export is recognised. Binary magic still beats names.
- `.msg` (Outlook item files) is cut (D-011): no pure-Python writer exists, so no fixture can be generated for the support-matrix test; `mail pst` covers Outlook via `readpst`.

## core/mail.py (stdlib `email` + `mailbox`)
`parse_eml`, `iter_mbox` (read-only, never locks or rewrites), `header_date` (ISO 8601 with timezone, None when absent), `addresses`, `message_ids`, `body_text` (text/plain, else html → `html_to_text`, else ""), `body_html`, `attachments` / `attachment_parts`, `summary` (from/to/cc/date/subject/message_id/in_reply_to/references/parts/has_html/attachments), `message_text` (headers block, blank line, body, `attachment: name (type, size)` lines), `eml_text`, `mbox_text` (`# <subject>` block per message), `thread_groups` (union-find over Message-ID / In-Reply-To / References; `depth` = reply-chain length when the parent is present), `safe_filename` (no separators, no leading dots, `attachment` fallback), `slug`. A broken MIME tree degrades to an empty body, never a crash.

## Commands
- `inspect`: eml → the summary; mbox → `{messages, first_date, last_date, senders (top 5)}`; mime guesses are `message/rfc822` / `application/mbox`.
- `convert`: `eml → md` (title, header table, body, attachment list), `→ txt` (exactly `extract_text`), `→ html` (the message's own HTML part, else the text in `<pre>`), `→ pdf` (that HTML through weasyprint); `mbox → md` (one `##` per message) and `→ txt`. No pandoc.
- `organize --by type`: `mail/`. `diff --mode auto`: two mail files diff as text through `extract_text`. `pack`: inlined like any document (fence language `eml`/`mbox`). `search --type eml|mbox`: free.
- `carrel mail attachments FILE... --out-dir DIR [--force] [--fail-empty]` → per message `{message, attachments: [{filename, path, size, sha256, content_type}]}`; names sanitised; collisions suffixed `-1, -2, …` unless `--force`; eml or mbox input (`file#n` per mbox message); a non-mail file → exit 4.
- `carrel mail split BOX.mbox --out-dir DIR [--template '{n}_{date}_{subject}.eml'] [--force]` → `[{n, path, subject, date, message_id}]`; `{n}` zero-padded, `{date}` `YYYY-MM-DD` or `undated`, `{subject}` slug, `{id}` message-id slug; bytes written as stored; refuses to overwrite without `--force`.
- `carrel mail threads PATH...` (eml/mbox files or directories walked like `index`) → `[{root_subject, first_date, messages: [{where, message_id, date, from, subject, depth}]}]`.
- `carrel mail pst FILE.pst --out-dir DIR [--format eml|mbox]` → `readpst -q -e|-r -o DIR FILE` (`-e` one .eml per message, `-r` one `mbox` file per folder; `-M` is MH format and is **not** what `--format mbox` means) (adapter `readpst`, `sudo apt install pst-utils`, `-V` for the version); returns `{src, out_dir, format, files, via}`; exit 3 without readpst, exit 4 for a missing or non-`.pst/.ost` file.
- `doctor`: `mail` row (`readpst` optional). CI's full job installs `pst-utils`; the minimal jobs skip through `needs("readpst")`.

## MCP
`carrel_mail {action: attachments|threads, path, out_dir?, force?, root?}` (13 tools).

## Fixtures
`tests/fixtures/generate.py::gen_mail` writes `sample.eml` (multipart/alternative text+html, one CSV attachment, fixed Date/Message-ID/boundaries; mentions `INV-2026-0042`, `$1,234.56`, `2026-10-01` and a valid IBAN so refs/fields tests can use it) and `thread.mbox` (three messages, two threaded by In-Reply-To/References). Both are byte-identical across runs (stdlib `EmailMessage.as_bytes()` with explicit boundaries).

## Acceptance
- `detect` types the fixtures; `.txt` with a header block stays TXT; an extension-less copy is EML/MBOX.
- `extract_text(sample.eml)` starts with the `From:` line, prefers the plain part, lists the attachment; `index` + `search --type eml` find the body sentinel; `refs --link` over an eml and the mbox reply groups `INV-2026-0042`.
- `inspect`, `convert --to md|txt|html` (pdf with weasyprint), `organize` → `mail/`, `diff` on two messages all work without a binary.
- `mail attachments` writes `remittance.csv` with the right sha256 and suffixes on rerun; `mail split` yields three dated `.eml` files that detect as EML; `mail threads` groups 2 + 1; `mail pst` exits 3 with the pst-utils hint when readpst is absent and counts files with a stand-in binary.
- `test_support_matrix_covered`, `test_every_fixture_returns_sane_json`, the guard hook and the marketplace tests stay green with the new plugin.
