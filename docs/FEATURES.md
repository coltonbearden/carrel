# FEATURES — capability × strategy matrix

Strategies: `wrap:<tool>` (external binary via adapter) · `lib:<pypi>` · `custom` (pure Python) · `degrade-if-missing` · `stretch`.
Tiers: **MVP** (must ship before flagship), **v1** (shipped in v0.1.0 after MVP), **v0.2.0** (shipped on `feat/v0.2.0`, specs 15–21), **stretch** (attempted last / cut candidates).
File types: pdf md jpg jpeg png ico txt html json xml csv docx odt epub rtf xlsx (xlsm).

| Capability | Command | Strategy | Types | Tier |
|---|---|---|---|---|
| File conversion | `carrel convert` | wrap:pandoc (md/html/txt + docx/odt/epub/rtf read and write), wrap:weasyprint (html→pdf), wrap:poppler pdftotext (pdf→txt/md), lib:Pillow + wrap:imagemagick (jpg/png/ico), custom (json↔csv↔xml via stdlib), lib:openpyxl via `carrel[office]` (xlsx→csv/json) | all | MVP (+ office in v0.2.0) |
| Text recognition (OCR) | `carrel ocr` | wrap:ocrmypdf (pdf), wrap:tesseract (images) | pdf jpg jpeg png | MVP |
| Diff / compare | `carrel diff` | custom (text unified diff, structural JSON/CSV diff), wrap:pdftotext (pdf text diff), lib:Pillow (image pixel/percent diff) | all | MVP |
| General editing | `carrel edit` | wrap:qpdf + lib:pypdf (pdf merge/split/rotate/extract-pages), lib:Pillow (image resize/rotate/crop/strip), custom (text/md find-replace, json set/del via dotted path) | all | MVP |
| Context engineering | `carrel pack` | custom (tree+content dump, include/exclude globs, ignore-file aware, chunking, char/token estimates; md/xml/json output formats) | all text-ish; binaries summarized via inspect | MVP |
| Query-driven & version-control-aware packing | `carrel pack --query / --top / --since / --changed / --dedupe-content / --tokenizer exact / --outline` | custom over FTS5 ranking (relevance order + per-file `score`); wrap:git for changed-file lists; `!pattern` negation in ignore files; lib:tiktoken (`o200k_base`) via `carrel[tokens]`; `ast`-based outline for `.py`, heading outline for `.md` | all indexed types (`--query`); all (`--since`, `--outline`) | v0.2.0 |
| Object/metadata inspection | `carrel inspect` | wrap:exiftool (degrade→lib:Pillow EXIF + lib:pypdf metadata), custom (magic bytes, structure summaries for json/xml/csv/html, docx core props, epub OPF, xlsx sheets) | all | MVP (+ office in v0.2.0) |
| Indexing & search | `carrel index` / `carrel search` | custom (SQLite FTS5; per-type text extractors reuse convert/ocr paths); `index --status` reports stale rows | all | MVP |
| Catalog: schema migrations, export/import, status | `carrel catalog export/import/status`, `carrel index --status` | custom (`PRAGMA user_version` + ordered `MIGRATIONS`; deterministic JSON document of tags + notes; merge or `--replace`) | — | v0.2.0 |
| Thumbnails | `carrel thumb` | wrap:pdftoppm (pdf), lib:Pillow (images), wrap:imagemagick fallback; html thumb = render pdf→ppm | pdf + images (+html via pdf) | MVP |
| Folder watch | `carrel watch` | lib:watchdog (inotify under the hood), custom rule→action mapping (run any carrel command on event) | all | MVP |
| Doctor / env probe | `carrel doctor` | custom (re-probes adapters, prints capability table + apt hints; shows `via CARREL_BIN_*` for pinned binaries and the extra to install for gated commands) | — | MVP |
| Whole desk over MCP | `carrel mcp` | custom stdlib JSON-RPC 2.0 on stdio: 10 tools (search, pack, inspect, tag, note, index, convert, diff, redact, doctor) delegating to the command impl functions + resource templates `carrel://file/{path}`, `carrel://search/{query}` | all | v1 (3 tools) → v0.2.0 (10 tools + resources) |
| Install ergonomics | `carrel completion bash/zsh/fish`; extras `tui/office/tokens/all`; `CARREL_BIN_<NAME>` override; `git` adapter | lib:click completions (in-process); pyproject extras (D-007); env-var override (D-008) | — | v0.2.0 |
| Dedupe | `carrel dedupe` | custom (BLAKE2 content hash groups; `--near` perceptual dHash for images, custom impl, no numpy) | all | v1 |
| File/folder organization | `carrel organize` | custom (rules: by type/date/exif-date; dry-run default) | all | v1 |
| Audiobook (TTS) | `carrel audiobook` | wrap:espeak-ng → wrap:ffmpeg (mp3/ogg, chapters from md headings); adapter prefers piper/edge-tts if present | txt md pdf | v1 |
| Redaction | `carrel redact` | custom (pattern/regex redaction for txt/md/html/json/csv/xml with built-in PII patterns); pdf: true redaction by rasterize→blackbox→rebuild (text layer destroyed by design; documented) | text types + pdf | v1 |
| Signatures | `carrel sign` | lib:pypdf+lib:reportlab (visible PDF stamp), custom (sha256 MANIFEST + wrap:gpg detached sig, verify mode) | pdf + any (manifest) | v1 |
| Notes/comments (annotations) | `carrel note` | lib:pypdf (PDF text annotations, list/add), custom (sidecar notes in index DB for any file) | pdf + all (sidecar) | v1 |
| Tagging | `carrel tag` | custom (tags in index DB; add/rm/ls/find) | all | v1 |
| Form building | `carrel form` | custom (JSON spec → HTML form; → PDF form via weasyprint for print-fill), lib:pypdf (fill existing AcroForm PDF, list fields) | html pdf json | v1 |
| Image extraction | `carrel extract-images` | wrap:pdfimages (pdf), wrap:icotool (ico frames), custom (html `<img>` local refs) | pdf ico html | v1 |
| Soft proofing (ICC) | `carrel proof` | wrap:imagemagick `-profile` with system ICC profiles (probed present); reports ΔE summary via Pillow | jpg jpeg png pdf(raster) | v1 |
| Color management | `carrel color` | lib:Pillow+ImageCms (profile convert/assign, palette extraction, contrast check) | images | v1 |
| Agent workflows & loops | marketplace plugin `carrel-agent` | custom (slash commands + agents + a watch-loop skill that pairs `carrel watch` with `claude -p`) | — | v1 |
| Drift gates & CI matrix | `scripts/sync_reference.py` (generated `docs/REFERENCE.md`, `--check` in CI); `docs/COOKBOOK.md` pulls every recipe/snippet in at build time; Linux 3.12–3.14 with coverage floor, `test-minimal (macos)` required, `test-minimal (windows)` advisory | custom | — | v0.2.0 |
| **Invented:** desk TUI | `carrel desk` | lib:textual via `carrel[tui]` (flagship; drives core library) | all | v1 (flagship) |
| **Invented:** recipes | `carrel run <recipe.yaml>` | custom mini-pipeline runner | — | stretch |
| Cryptographic PDF signing (PAdES) | — | stretch (needs pyHanko + key mgmt) | pdf | stretch |

## In flight (v0.2.0 wave 3 — see [BUILD_PLAN.md](BUILD_PLAN.md))

| Capability | Command | Strategy | Spec |
|---|---|---|---|
| Plugin surface generated from `--help` | 7 plugins (adds `carrel-documents`, `carrel-guard`); `scripts/sync_plugins.py --check` gate | custom; hooks `PreToolUse(Read)` → text conversion, `SessionStart` → capability summary | 20 |

Not claimed as shipped until it lands; [MARKETPLACE.md](MARKETPLACE.md) is authoritative for the current plugin list.

## Office & ebook formats (spec 18, shipped)

Detection is by bytes (`{\rtf` prefix; zip containers probed for `mimetype` / `[Content_Types].xml`), so a mis-named file is still handled — `carrel inspect mystery.bin` on a renamed docx reports `type: docx`. One `core.textextract` branch feeds `index`, `search`, `pack`, `diff` and `audiobook` for every row. Word-processor and ebook reads/writes go through pandoc (`degrade-if-missing` → exit 3 with `sudo apt install pandoc`); xlsx reads use openpyxl from the `office` extra (`uv tool install 'carrel[office]'`; exit 3 with that hint when absent). Spreadsheet *writing* is out of scope for this release.

| Format | Detect | Text (`extract_text`) | `convert` from | `convert` to | `inspect` detail |
|---|---|---|---|---|---|
| docx | `.docx`; zip with `[Content_Types].xml` + `word/` | wrap:pandoc `-t plain` | md html txt pdf (pandoc → weasyprint) epub | from md html txt (pandoc), from epub | paragraphs, words, title/author/created (`docProps/core.xml`) |
| odt | `.odt`; zip `mimetype` = `application/vnd.oasis.opendocument.text` | wrap:pandoc | md html txt pdf | from md html txt | words |
| epub | `.epub`; zip `mimetype` = `application/epub+zip` | wrap:pandoc | md html txt pdf docx | from docx | title, creator, language, spine_items (OPF), words |
| rtf | `.rtf`; `{\rtf` header | wrap:pandoc | md html txt pdf | — | words |
| xlsx | `.xlsx` `.xlsm`; zip with `[Content_Types].xml` + `xl/` | lib:openpyxl (`# sheet` heading + CSV rows) | csv (`--sheet NAME\|N\|all`) json (`{sheet: [row objects]}`) | — | sheets: [{name, rows, cols}] |

Proof (executed 2026-09-04, [TEST_REPORT.md](TEST_REPORT.md#v020-2026-09-04)): `sample.md → docx → md` keeps the fixture sentinel *melodious cartography*; `sample.xlsx --to csv --sheet 2` yields the `Loans` sheet; `inspect sample.xlsx` lists both sheets with `rows: 4, cols: 3`.

## Explicit scope notes

- **PDF redaction** is true redaction (rasterization destroys the text layer) — documented tradeoff; searchability restorable via `carrel ocr` afterwards.
- **html thumbnails** go through weasyprint→pdf→pdftoppm; if weasyprint missing, degrade with hint.
- **Near-dupe** uses a dependency-free dHash (no numpy/imagehash) to keep install light.
- **Token counts** in `pack` default to a chars/3.6 heuristic labeled `tokens_est`; `--tokenizer exact` counts with tiktoken `o200k_base` (labeled `tokens`, the header names the tokenizer) and needs the `tokens` extra — no network, and the heavy dependency stays opt-in.
- **`pack --query` ranks only indexed files.** `carrel index` walks the supported types and skips everything else (`.py`, `.toml`, `.yaml`, …), so `--query` cannot surface a source file even when it contains the term — the recipe in [`examples/cookbook/10-pack-what-matters.sh`](https://github.com/coltonbearden/carrel/blob/main/examples/cookbook/10-pack-what-matters.sh) shows this on purpose. Query-driven packing fits document trees; for source trees use `--include`/`--exclude`, `--since REF`/`--changed`, or `--outline`. Indexing source types is a planned follow-up.
- **Relevance scores are bm25** from FTS5: lower is better, and on small documents they are tiny (≈ -1.5e-06 in the proofs), so the human `score` column can print `-0.000` while `--json` carries the full value.
- **Spreadsheets** are read-only (xlsx → csv/json); writing xlsx and reading legacy `.xls`/`.doc` are out of scope.

## Cuts (running log — updated through the build)

- `recipes` runner: stretch, cut if time is short (cookbook shell scripts cover the use cases).
- PAdES cryptographic PDF signing: cut to stretch; visible stamp + gpg manifest signing ship instead (rationale: key management UX exceeds session scope).
- v0.2.0: unwired adapter entries removed (`gs`, `pngquant`, `jq`, `mlr`, `rg`, `fd`, `sqlite3`, `inotifywait`, `claude`) — none was referenced by any command, yet `doctor` advertised them. Re-add each together with the command that uses it (spec 19).
