<div align="center">

<img src="assets/banner.svg" alt="carrel — a library desk for your files, and your agents" width="100%">

<br><br>

<img src="https://img.shields.io/badge/python-3.12%2B-6E9EBF?labelColor=211A11" alt="Python 3.12+">
<img src="https://img.shields.io/badge/license-MIT-B07C24?labelColor=211A11" alt="License: MIT">
<a href="https://github.com/coltonbearden/carrel/actions"><img src="https://img.shields.io/github/actions/workflow/status/coltonbearden/carrel/test.yml?branch=main&label=tests&labelColor=211A11" alt="tests"></a>
<a href="https://github.com/coltonbearden/carrel/releases"><img src="https://img.shields.io/github/v/release/coltonbearden/carrel?labelColor=211A11&color=F2A93C" alt="release"></a>

<br><br>

**Read, index, pack and file your documents — from the terminal, for you and your agents.**

<br>

<img src="assets/demo/pack.gif" alt="carrel pack token stats" width="100%">

*`carrel pack src --stats` — the token table, before you spend a context window on it.*

<img src="assets/demo/redact-proof.gif" alt="carrel redact proof" width="100%">

*`carrel redact` — true raster redaction of a PDF, and the proof: `grep` exits 1.*

</div>

**carrel** turns the documents on your disk — PDFs, Word and OpenDocument files, ebooks, spreadsheets, email, scans — into text you can search, fields you can query, and context you can hand to an LLM. One CLI; every data command speaks `--json` with stable exit codes; dry-run by default; nothing overwritten without `--force`. It ships an MCP server and a [Claude Code plugin marketplace](#the-marketplace) that drive the same commands, so Claude can read your `.docx`, pack the five relevant files out of five hundred, and file an invoice inbox by what the invoices say. Missing pandoc or tesseract? `carrel doctor` tells you what works today and how to unlock the rest.

A *carrel* is a private study desk in a library: your materials close at hand, organized your way.

## Install

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). No checkout needed:

```sh
uv tool install 'carrel[all]'   # or: pipx install 'carrel[all]' — puts `carrel` on your PATH
                                # plain `carrel` skips the TUI and office/token extras (see INSTALL)
carrel doctor                   # what can your desk do today? (+ install hints for the rest)
```

(Contributing or hacking on it? `uv tool install .` from a checkout does the same thing.)

## Three things to try

### Give Claude the right context

Index a folder once, then let the desk's own ranking choose what to send. `--since` does the
same job from git history instead of a query.

```sh
carrel index ~/papers
carrel pack ~/papers --query "attention is all you need" --stats
carrel pack . --since HEAD~5 --stats     # what changed, packed
```

The MCP server (`carrel mcp`, shipped by the `carrel-agent` plugin) exposes the same thing as a
tool, confined to the directory it starts in.

*Limitation:* query terms must appear in the text — FTS5 AND-s them, so a natural-language
question often matches nothing. Under `--json` an empty pack exits non-zero rather than handing
you a valid, empty document.

### Read what the agent can't

```sh
claude plugin marketplace add coltonbearden/carrel
claude plugin install carrel-guard@carrel
```

Office, ebook, email and spreadsheet files become text automatically before Claude's `Read`
sees them; PDFs become cheap text; images stay pictures for Claude's own vision.

*Limitation:* layout-heavy PDFs and diagrams still want the visual `Read` — the guard's note
tells Claude where the original is and when to prefer it (`CARREL_GUARD_PDF_TEXT=0`).

### Turn an inbox into an archive

Read what each document says, then file it by that. The dry run is the default; nothing moves
until `--apply`.

```sh
carrel fields ~/inbox/invoice.pdf              # vendor, dates, totals, with confidence
carrel intake ~/inbox --to ~/archive           # dry run: shows every planned move
carrel intake ~/inbox --to ~/archive --apply   # files into YYYY/MM, indexes, records fields
carrel --root ~/archive meta find 'total>1000' 'due<2026-11'
```

*Limitation:* field extraction is English-label heuristics with a confidence column — read it
before `--apply`. Originals are always kept.

## Status and support

A solo-maintainer project, used daily by its author.

**Stable:** `convert`, `inspect`, `index`/`search`, `pack`, the `carrel-guard` hook, and the
MCP read tools. **Experimental:** the accuracy of `fields`, `refs` and `intake` (heuristics, not
models — check the confidence column), and the desk TUI. Linux and macOS are covered by
required CI checks; Windows CI is advisory until it has been green long enough to promote.

Security reports: see [SECURITY.md](SECURITY.md) — acknowledged within 7 days, fixed or
explicitly declined within 30.

Two things carrel is **not**: a cloud document system (nothing leaves your disk, and there is no
account), and a substitute for reading redaction or financial output before you rely on it.

## Everything on the desk


| Domain | Command | What it does |
|---|---|---|
| **Convert & transform** | `carrel convert` | Conversion across pdf, md, html, txt, docx, odt, epub, rtf, png/jpg/ico, json, xml, csv, plus xlsx → csv/json; the full SRC → target matrix is in `carrel convert --help` |
| | `carrel ocr` | Images and scanned PDFs → text, markdown, or a searchable PDF |
| | `carrel edit` | PDF merge/split/rotate/extract-pages, image resize/rotate/crop, text find-replace, json set/del |
| | `carrel extract-images` | Pull embedded images out of pdf, ico, and html |
| | `carrel audiobook` | Narrate txt/md/pdf and docx/odt/epub/rtf into mp3/ogg, chapters from markdown headings |
| **Inspect & prove** | `carrel inspect` | Metadata + per-type structure summary: sha256, pages, EXIF, json shape, csv dialect, docx paragraphs, xlsx sheets… |
| | `carrel diff` | Unified text diffs, structural json/csv diffs, pdf text diffs, image pixel diffs |
| | `carrel thumb` | Thumbnails for pdfs, images, and html |
| | `carrel proof` | Soft-proof against an ICC profile, with a ΔE summary |
| | `carrel color` | Dominant palette extraction, ICC conversion, contrast checks |
| **The desk index** | `carrel index` | SQLite FTS5 index of everything under a root (`.carrel/carrel.db`, versioned schema); `--status` reports stale rows |
| | `carrel search` | bm25-ranked full-text search with type and tag filters |
| | `carrel tag` | Tag files; find by tag |
| | `carrel note` | Sidecar notes on any file; real text annotations on PDFs |
| | `carrel meta` | Typed fields on files — `vendor=Acme`, `total=1234.56`, `due=2026-10-01` — queried with `meta find 'total>1000' 'due<2026-11'`, exported as a CSV of the folder |
| | `carrel catalog` | Export/import tags + notes + fields as JSON (move a desk, commit it next to a repo); `status` shows schema version and stale index rows |
| **Read the documents** | `carrel fields` | Vendor, invoice number, PO, dates, subtotal/tax/total, currency and IBAN out of invoices, receipts and statements — each with a confidence and the line it came from; `--save` records them as desk fields |
| | `carrel refs` | Reference numbers anywhere in a folder: invoice, PO, order, check, account, tracking, ticket, plus check-digit-verified IBAN, ABA routing, EIN, VAT, ISBN, GTIN, DOI, UPS, USPS. `--tag` links every document that shares one; `--link` shows the grouping |
| **Email** | `carrel mail` | `.eml`/`.mbox` are ordinary desk files (inspect, convert, index, search, pack, refs all read them, stdlib only). `mail` adds the rest: save attachments with digests, split a mailbox into messages, group messages into threads, convert Outlook `.pst` exports |
| **Agents & context** | `carrel pack` | Bundle files/trees into one LLM-ready document — md/xml/json; `--query` packs what the desk index ranks relevant, `--since REF`/`--changed` packs what git touched; include/exclude globs, `.gitignore`-aware (with `!` negation), chunking, `--dedupe-content`, `--outline`, token estimates or exact counts (`--tokenizer exact`) |
| | `carrel mcp` | Serve the whole desk over MCP on stdio: 14 tools (search, pack, inspect, tag, note, index, convert, diff, redact, doctor, meta, fields, mail, refs) plus `carrel://file/{path}` and `carrel://search/{query}` resources |
| **Housekeeping** | `carrel organize` | Sort a folder by type/date/EXIF date — dry-run by default |
| | `carrel dedupe` | Exact (BLAKE2) and near (perceptual hash) duplicate detection |
| | `carrel rename` | Rename files from what they say — `{date}_{vendor}_{ref}{ext}` — dry-run first, collision-safe, and the desk's tags and notes follow the file |
| | `carrel batch` | Run any command over many files: parallel jobs, a resumable manifest, dry-run, per-file JSON records |
| | `carrel watch` | Watch a folder and run shell actions on file events — recursive, settle-wait for slow writers, polling for `/mnt/c` and network shares, done/error folders, a printable systemd or Task Scheduler unit |
| | `carrel intake` | The inbox in one command: read each document, name it, file it into `YYYY/MM` (or fiscal quarters), index it, record its fields and tag its references. Scans are OCRed into a searchable copy, the original is kept |
| | `carrel redact` | Pattern/PII redaction for text formats; true raster redaction for PDFs |
| | `carrel sign` | Visible PDF stamps, sha256 manifests, gpg-backed verify |
| | `carrel form` | Build html/pdf forms from JSON specs; list and fill AcroForm PDFs |
| **The desk itself** | `carrel desk` | A companion TUI — see [below](#the-desk-tui); needs the `tui` extra |
| | `carrel doctor` | What your environment enables today, with install hints for the rest |
| | `carrel completion` | Tab-completion scripts for bash, zsh, and fish |

carrel wraps the masters — pandoc, poppler, qpdf, tesseract/ocrmypdf, ImageMagick, exiftool, ffmpeg… — behind one adapter layer with capability detection. Missing binary? Commands degrade with an install hint (exit 3), never a crash. Several copies of a tool on `PATH`? Pin one with `CARREL_BIN_<NAME>` ([docs/CONFIGURATION.md](docs/CONFIGURATION.md#pinning-a-binary-carrel_bin_name)).

### A first taste

```sh
carrel inspect paper.pdf                              # pages, sha256, producer, form fields…
carrel convert minutes.docx --to md                   # office/ebook formats read and write via pandoc
carrel index . && carrel search "marginal notes"      # FTS5 over your whole desk
carrel pack src/ --format xml -o context.xml --stats  # LLM-ready context + token table
carrel pack docs/ --query "release checklist" --stats # only the files the index ranks relevant
carrel catalog export -o desk.json                    # tags + notes, portable and diff-able
```

Add `--json` to any of these and you get machine-readable output on stable exit codes — that's the whole agent contract. Tab completion: `eval "$(carrel completion bash)"` (zsh and fish too).

## The marketplace

This repo is also a Claude Code plugin marketplace: plugins whose slash commands, agents, skills, and hooks all delegate to the CLI above. The table below is a snapshot — [docs/MARKETPLACE.md](docs/MARKETPLACE.md) is authoritative for the current plugin list.

```sh
claude plugin marketplace add coltonbearden/carrel
claude plugin install carrel-inspect@carrel
```

| Plugin | Gives Claude |
|---|---|
| `carrel-inspect` | `/inspect`, `/diff`, `/search`, `/pack` + a context-packing skill |
| `carrel-convert` | `/convert`, `/ocr`, `/thumb`, `/edit`, `/extract-images`, `/audiobook` + a batch doc-converter agent |
| `carrel-organize` | `/organize`, `/dedupe`, `/tag`, `/note-file`, `/meta`, `/rename`, `/batch` |
| `carrel-finance` | `/refs`, `/fields` — find and cross-link invoice, PO, IBAN, routing and tracking numbers; extract vendor, dates and totals from invoices, receipts and statements + a bookkeeper agent and an accounting-inbox skill |
| `carrel-documents` | `/redact`, `/sign`, `/form`, `/proof`, `/color` + a document-clerk agent (redact → verify → sign) and a redaction-and-provenance skill |
| `carrel-mail` | `/mail` — attachments, mbox split, threads, Outlook .pst via readpst; eml/mbox are desk file types + a mail-archive skill |
| `carrel-watch` | `/watch-folder`, `/intake` — file an inbox by what the documents say + a watch-automation recipe skill |
| `carrel-agent` | `/index`, `/doctor`, `/catalog`, `/completion`, a file-librarian agent, the carrel MCP server, and a hook that re-indexes files Claude writes |
| `carrel-guard` | A `PreToolUse` hook that turns the files `Read` cannot open — Office/ebook/RTF, spreadsheets, email — into text before it sees them, and PDFs into cheap text by default; images are left to Claude's vision. Plus a `SessionStart` hook that reports what carrel can do here |

Install the CLI first (see [Quickstart](#quickstart)) so the plugins can call it. Works headless too:

```sh
claude -p "/carrel-inspect:inspect text+image.pdf" --allowedTools "Bash(carrel:*)"
```

The full validated flow (with real output) is in [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## The desk TUI

```sh
carrel desk
```

<img src="assets/demo/desk-tour.gif" alt="carrel desk TUI tour" width="100%">

*`carrel desk` — browse the tree, inspect a file, run an action, search the index.*

A companion to the CLI: a three-pane [Textual](https://textual.textualize.io/) desk. A file tree on the left, an inspector in the middle (metadata, preview, tags, notes), an action palette on the right (convert, ocr, pack, thumbnail…) — all driving the same core library as the CLI, with full-text search along the bottom. Theme: warm lamplight on dark wood, per [docs/BRAND.md](docs/BRAND.md).

## Learn more

- **[The docs site](https://coltonbearden.github.io/carrel/)** — everything below, browsable
- [docs/VISION.md](docs/VISION.md) — why a library desk, and the product principles
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the adapter layer, the index, the plugin design
- [docs/FEATURES.md](docs/FEATURES.md) — the capability × strategy matrix
- [docs/TEST_REPORT.md](docs/TEST_REPORT.md) — everything above, executed for real (the v0.1.0 record: cookbook runs, office and `pack --query` proofs)
- [examples/cookbook/](examples/cookbook/) — end-to-end recipes, from scan→searchable-notes to pack-what-matters
- [docs/BRAND.md](docs/BRAND.md) — palette, typography, logo usage, voice
- [docs/HOW_THIS_WAS_BUILT.md](docs/HOW_THIS_WAS_BUILT.md) — how this was built

## License

MIT © Colton Bearden

## Related projects

- [brainrot](https://github.com/coltonbearden/brainrot) — Self-audit toolkit for Claude: mine your own chat history for corrections and wins, arbitrate findings into a lean rule set, keep memory tidy
