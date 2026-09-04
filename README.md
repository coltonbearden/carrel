<div align="center">

<img src="assets/banner.svg" alt="carrel — a library desk for your files, and your agents" width="100%">

<br><br>

<img src="https://img.shields.io/badge/python-3.12%2B-6E9EBF?labelColor=211A11" alt="Python 3.12+">
<img src="https://img.shields.io/badge/license-MIT-B07C24?labelColor=211A11" alt="License: MIT">
<a href="https://github.com/coltonbearden/carrel/actions"><img src="https://img.shields.io/github/actions/workflow/status/coltonbearden/carrel/test.yml?branch=main&label=tests&labelColor=211A11" alt="tests"></a>
<a href="https://github.com/coltonbearden/carrel/releases"><img src="https://img.shields.io/github/v/release/coltonbearden/carrel?labelColor=211A11&color=F2A93C" alt="release"></a>

<br><br>

<img src="assets/demo/desk-tour.gif" alt="carrel desk TUI tour" width="100%">

*`carrel desk` — browse the tree, inspect a file, run an action, search the index.*

<img src="assets/demo/pack.gif" alt="carrel pack token stats" width="100%">

*`carrel pack src --stats` — the token table, before you spend a context window on it.*

<img src="assets/demo/redact-proof.gif" alt="carrel redact proof" width="100%">

*`carrel redact` — true raster redaction of a PDF, and the proof: `grep` exits 1.*

</div>

A *carrel* is a private study desk in a library: your materials close at hand, organized your way. **carrel** is that desk for your local files — pdf, docx, odt, epub, rtf, xlsx, md, html, txt, json, xml, csv, and png/jpg/ico images — with 26 commands to convert, OCR, inspect, diff, index, search, pack, watch, and more. And it treats AI agents as first-class users of the desk: every data-producing command speaks `--json` with stable exit codes, `carrel pack` turns file trees into LLM-ready context, and the repo doubles as a [Claude Code plugin marketplace](#the-marketplace) whose plugins drive the same CLI.

## What can it do

| Domain | Command | What it does |
|---|---|---|
| **Convert & transform** | `carrel convert` | Conversion across pdf, md, html, txt, docx, odt, epub, rtf, png/jpg/ico, json, xml, csv, plus xlsx → csv/json; the full SRC → target matrix is in `carrel convert --help` |
| | `carrel ocr` | Images and scanned PDFs → text, markdown, or a searchable PDF |
| | `carrel edit` | PDF merge/split/rotate/extract-pages, image resize/rotate/crop, text find-replace, json set/del |
| | `carrel extract-images` | Pull embedded images out of pdf, ico, and html |
| | `carrel audiobook` | Narrate txt/md/pdf into mp3/ogg, chapters from markdown headings |
| **Inspect & prove** | `carrel inspect` | Metadata + per-type structure summary: sha256, pages, EXIF, json shape, csv dialect, docx paragraphs, xlsx sheets… |
| | `carrel diff` | Unified text diffs, structural json/csv diffs, pdf text diffs, image pixel diffs |
| | `carrel thumb` | Thumbnails for pdfs, images, and html |
| | `carrel proof` | Soft-proof against an ICC profile, with a ΔE summary |
| | `carrel color` | Dominant palette extraction, ICC conversion, contrast checks |
| **The desk index** | `carrel index` | SQLite FTS5 index of everything under a root (`.carrel/carrel.db`, versioned schema); `--status` reports stale rows |
| | `carrel search` | bm25-ranked full-text search with type and tag filters |
| | `carrel tag` | Tag files; find by tag |
| | `carrel note` | Sidecar notes on any file; real text annotations on PDFs |
| | `carrel catalog` | Export/import tags + notes as JSON (move a desk, commit it next to a repo); `status` shows schema version and stale index rows |
| **Agents & context** | `carrel pack` | Bundle files/trees into one LLM-ready document — md/xml/json; `--query` packs what the desk index ranks relevant, `--since REF`/`--changed` packs what git touched; include/exclude globs, `.gitignore`-aware (with `!` negation), chunking, `--dedupe-content`, `--outline`, token estimates or exact counts (`--tokenizer exact`) |
| | `carrel mcp` | Serve the whole desk over MCP on stdio: 10 tools (search, pack, inspect, tag, note, index, convert, diff, redact, doctor) plus `carrel://file/{path}` and `carrel://search/{query}` resources |
| **Housekeeping** | `carrel organize` | Sort a folder by type/date/EXIF date — dry-run by default |
| | `carrel dedupe` | Exact (BLAKE2) and near (perceptual hash) duplicate detection |
| | `carrel watch` | Watch a folder and run shell actions on file events |
| | `carrel redact` | Pattern/PII redaction for text formats; true raster redaction for PDFs |
| | `carrel sign` | Visible PDF stamps, sha256 manifests, gpg-backed verify |
| | `carrel form` | Build html/pdf forms from JSON specs; list and fill AcroForm PDFs |
| **The desk itself** | `carrel desk` | The flagship TUI — see [below](#the-desk-tui); needs the `tui` extra |
| | `carrel doctor` | What your environment enables today, with install hints for the rest |
| | `carrel completion` | Tab-completion scripts for bash, zsh, and fish |

carrel wraps the masters — pandoc, poppler, qpdf, tesseract/ocrmypdf, ImageMagick, exiftool, ffmpeg… — behind one adapter layer with capability detection. Missing binary? Commands degrade with an install hint (exit 3), never a crash. Several copies of a tool on `PATH`? Pin one with `CARREL_BIN_<NAME>` ([docs/CONFIGURATION.md](docs/CONFIGURATION.md#pinning-a-binary-carrel_bin_name)).

## Quickstart

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). No checkout needed:

```sh
uv tool install 'carrel[all]'   # or: pipx install 'carrel[all]' — puts `carrel` on your PATH
                                # plain `carrel` skips the TUI and office/token extras (see INSTALL)
carrel doctor         # what can your desk do today? (+ apt hints for the rest)
```

(Contributing or hacking on it? `uv tool install .` from a checkout does the same thing.)

A first taste:

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
| `carrel-convert` | `/convert`, `/ocr`, `/thumb`, `/audiobook` + a batch doc-converter agent |
| `carrel-organize` | `/organize`, `/dedupe`, `/tag`, `/note-file` |
| `carrel-watch` | `/watch-folder` + a watch-automation recipe skill |
| `carrel-agent` | A file-librarian agent, the carrel MCP server, and a hook that re-indexes files Claude writes |

Install the CLI first (see [Quickstart](#quickstart)) so the plugins can call it. Works headless too:

```sh
claude -p "/carrel-inspect:inspect text+image.pdf" --allowedTools "Bash(carrel:*)"
```

The full validated flow (with real output) is in [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## The desk TUI

```sh
carrel desk
```

<div align="center"><img src="assets/logo.svg" alt="carrel mark" width="96"></div>

The flagship: a three-pane [Textual](https://textual.textualize.io/) desk. A file tree on the left, an inspector in the middle (metadata, preview, tags, notes), an action palette on the right (convert, ocr, pack, thumbnail…) — all driving the same core library as the CLI, with full-text search along the bottom. Theme: warm lamplight on dark wood, per [docs/BRAND.md](docs/BRAND.md).

## Learn more

- **[The docs site](https://coltonbearden.github.io/carrel/)** — everything below, browsable
- [docs/HOW_THIS_WAS_BUILT.md](docs/HOW_THIS_WAS_BUILT.md) — the autonomous single-day build, from the primary sources
- [docs/VISION.md](docs/VISION.md) — why a library desk, and the product principles
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the adapter layer, the index, the plugin design
- [docs/FEATURES.md](docs/FEATURES.md) — the capability × strategy matrix
- [docs/TEST_REPORT.md](docs/TEST_REPORT.md) — everything above, executed for real (855 tests; cookbook runs; office and `pack --query` proofs)
- [examples/cookbook/](examples/cookbook/) — ten end-to-end recipes, from scan→searchable-notes to pack-what-matters
- [docs/BRAND.md](docs/BRAND.md) — palette, typography, logo usage, voice

## License

MIT © Colton Bearden

## Related projects

- [brainrot](https://github.com/coltonbearden/brainrot) — Self-audit toolkit for Claude: mine your own chat history for corrections and wins, arbitrate findings into a lean rule set, keep memory tidy
