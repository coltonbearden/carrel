<div align="center">

<img src="assets/banner.svg" alt="carrel — a library desk for your files, and your agents" width="100%">

<br><br>

<img src="https://img.shields.io/badge/python-3.12%2B-6E9EBF?labelColor=211A11" alt="Python 3.12+">
<img src="https://img.shields.io/badge/license-MIT-B07C24?labelColor=211A11" alt="License: MIT">
<a href="https://github.com/FirstCastSolutions423/carrel/actions"><img src="https://img.shields.io/github/actions/workflow/status/FirstCastSolutions423/carrel/test.yml?branch=main&label=tests&labelColor=211A11" alt="tests"></a>
<a href="https://github.com/FirstCastSolutions423/carrel/releases"><img src="https://img.shields.io/github/v/release/FirstCastSolutions423/carrel?labelColor=211A11&color=F2A93C" alt="release"></a>

<br><br>

<img src="assets/demo/desk-tour.gif" alt="carrel desk TUI tour" width="100%">

*`carrel desk` — browse the tree, inspect a file, run an action, search the index.*

<img src="assets/demo/pack.gif" alt="carrel pack token stats" width="100%">

*`carrel pack src --stats` — the token table, before you spend a context window on it.*

<img src="assets/demo/redact-proof.gif" alt="carrel redact proof" width="100%">

*`carrel redact` — true raster redaction of a PDF, and the proof: `grep` exits 1.*

</div>

A *carrel* is a private study desk in a library: your materials close at hand, organized your way. **carrel** is that desk for your local files — pdf, md, images, html, json, xml, csv — with 24 commands to convert, OCR, inspect, diff, index, search, pack, watch, and more. And it treats AI agents as first-class users of the desk: every data-producing command speaks `--json` with stable exit codes, `carrel pack` turns file trees into LLM-ready context, and the repo doubles as a [Claude Code plugin marketplace](#the-marketplace) whose plugins drive the same CLI.

## What can it do

| Domain | Command | What it does |
|---|---|---|
| **Convert & transform** | `carrel convert` | Any-to-any conversion across pdf, md, html, txt, png/jpg/ico, json, xml, csv |
| | `carrel ocr` | Images and scanned PDFs → text, markdown, or a searchable PDF |
| | `carrel edit` | PDF merge/split/rotate/extract-pages, image resize/rotate/crop, text find-replace, json set/del |
| | `carrel extract-images` | Pull embedded images out of pdf, ico, and html |
| | `carrel audiobook` | Narrate txt/md/pdf into mp3/ogg, chapters from markdown headings |
| **Inspect & prove** | `carrel inspect` | Metadata + per-type structure summary: sha256, pages, EXIF, json shape, csv dialect… |
| | `carrel diff` | Unified text diffs, structural json/csv diffs, pdf text diffs, image pixel diffs |
| | `carrel thumb` | Thumbnails for pdfs, images, and html |
| | `carrel proof` | Soft-proof against an ICC profile, with a ΔE summary |
| | `carrel color` | Dominant palette extraction, ICC conversion, contrast checks |
| **The desk index** | `carrel index` | SQLite FTS5 index of everything under a root (`.carrel/carrel.db`, portable) |
| | `carrel search` | bm25-ranked full-text search with type and tag filters |
| | `carrel tag` | Tag files; find by tag |
| | `carrel note` | Sidecar notes on any file; real text annotations on PDFs |
| **Agents & context** | `carrel pack` | Bundle files/trees into one LLM-ready document — md/xml/json, include/exclude globs, `.gitignore`-aware, chunking, token estimates |
| | `carrel mcp` | Serve search/pack/inspect as an MCP server on stdio |
| **Housekeeping** | `carrel organize` | Sort a folder by type/date/EXIF date — dry-run by default |
| | `carrel dedupe` | Exact (BLAKE2) and near (perceptual hash) duplicate detection |
| | `carrel watch` | Watch a folder and run shell actions on file events |
| | `carrel redact` | Pattern/PII redaction for text formats; true raster redaction for PDFs |
| | `carrel sign` | Visible PDF stamps, sha256 manifests, gpg-backed verify |
| | `carrel form` | Build html/pdf forms from JSON specs; list and fill AcroForm PDFs |
| **The desk itself** | `carrel desk` | The flagship TUI — see [below](#the-desk-tui) |
| | `carrel doctor` | What your environment enables today, with install hints for the rest |

carrel wraps the masters — pandoc, poppler, qpdf, tesseract/ocrmypdf, ImageMagick, exiftool, ffmpeg… — behind one adapter layer with capability detection. Missing binary? Commands degrade with an install hint (exit 3), never a crash.

## Quickstart

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/). No checkout needed:

```sh
uv tool install git+https://github.com/FirstCastSolutions423/carrel   # puts `carrel` on your PATH
carrel doctor         # what can your desk do today? (+ apt hints for the rest)
```

(Contributing or hacking on it? `uv tool install .` from a checkout does the same thing.)

A first taste:

```sh
carrel inspect paper.pdf                              # pages, sha256, producer, form fields…
carrel index . && carrel search "marginal notes"      # FTS5 over your whole desk
carrel pack src/ --format xml -o context.xml --stats  # LLM-ready context + token table
```

Add `--json` to any of these and you get machine-readable output on stable exit codes — that's the whole agent contract.

## The marketplace

This repo is also a Claude Code plugin marketplace: five plugins whose slash commands, agents, skills, and hooks all delegate to the CLI above.

```sh
claude plugin marketplace add FirstCastSolutions423/carrel
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

- **[The docs site](https://firstcastsolutions423.github.io/carrel/)** — everything below, browsable
- [docs/HOW_THIS_WAS_BUILT.md](docs/HOW_THIS_WAS_BUILT.md) — the autonomous single-day build, from the primary sources
- [docs/VISION.md](docs/VISION.md) — why a library desk, and the product principles
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the adapter layer, the index, the plugin design
- [docs/FEATURES.md](docs/FEATURES.md) — the capability × strategy matrix
- [docs/TEST_REPORT.md](docs/TEST_REPORT.md) — everything above, executed for real (501 tests, 7 cookbook runs)
- [examples/cookbook/](examples/cookbook/) — nine end-to-end recipes, from scan→searchable-notes to markdown→audiobook
- [docs/BRAND.md](docs/BRAND.md) — palette, typography, logo usage, voice

## License

MIT © Colton Bearden

## Related projects

- [brainrot](https://github.com/coltonbearden/brainrot) — Self-audit toolkit for Claude: mine your own chat history for corrections and wins, arbitrate findings into a lean rule set, keep memory tidy
