# FEATURES — capability × strategy matrix

Strategies: `wrap:<tool>` (external binary via adapter) · `lib:<pypi>` · `custom` (pure Python) · `degrade-if-missing` · `stretch`.
Tiers: **MVP** (must ship before flagship), **v1** (ships this session after MVP), **stretch** (attempted last / cut candidates).
File types: pdf md jpg jpeg png ico txt html json xml csv.

| Capability | Command | Strategy | Types | Tier |
|---|---|---|---|---|
| File conversion | `carrel convert` | wrap:pandoc (md/html/txt), wrap:weasyprint (html→pdf), wrap:poppler pdftotext (pdf→txt/md), lib:Pillow + wrap:imagemagick (jpg/png/ico), custom (json↔csv↔xml via stdlib+mlr) | all | MVP |
| Text recognition (OCR) | `carrel ocr` | wrap:ocrmypdf (pdf), wrap:tesseract (images) | pdf jpg jpeg png | MVP |
| Diff / compare | `carrel diff` | custom (text unified diff, structural JSON/CSV diff), wrap:pdftotext (pdf text diff), lib:Pillow (image pixel/percent diff) | all | MVP |
| General editing | `carrel edit` | wrap:qpdf + lib:pypdf (pdf merge/split/rotate/extract-pages), lib:Pillow (image resize/rotate/crop/strip), custom (text/md find-replace, json set/del via jq-path) | all | MVP |
| Context engineering | `carrel pack` | custom (tree+content dump, include/exclude globs, .gitignore-aware, chunking, char/token estimates; md/xml/json output formats) | all text-ish; binaries summarized via inspect | MVP |
| Object/metadata inspection | `carrel inspect` | wrap:exiftool (degrade→lib:Pillow EXIF + lib:pypdf metadata), custom (magic bytes, structure summaries for json/xml/csv/html) | all | MVP |
| Indexing & search | `carrel index` / `carrel search` | custom (SQLite FTS5; per-type text extractors reuse convert/ocr paths) | all | MVP |
| Thumbnails | `carrel thumb` | wrap:pdftoppm (pdf), lib:Pillow (images), wrap:imagemagick fallback; html→png via weasyprint png? no — degrade: html thumb = render pdf→ppm | pdf + images (+html via pdf) | MVP |
| Folder watch | `carrel watch` | lib:watchdog (inotify under the hood), custom rule→action mapping (run any carrel command on event) | all | MVP |
| Doctor / env probe | `carrel doctor` | custom (re-probes adapters, prints capability table + apt hints) | — | MVP |
| Dedupe | `carrel dedupe` | custom (BLAKE2 content hash groups; `--near` perceptual dHash for images, custom impl, no numpy) | all | v1 |
| File/folder organization | `carrel organize` | custom (rules: by type/date/exif-date; dry-run default) | all | v1 |
| Audiobook (TTS) | `carrel audiobook` | wrap:espeak-ng → wrap:ffmpeg (mp3/ogg, chapters from md headings); adapter prefers piper/edge-tts if present | txt md pdf | v1 |
| Redaction | `carrel redact` | custom (pattern/regex redaction for txt/md/html/json/csv/xml with built-in PII patterns); pdf: true redaction by rasterize→blackbox→rebuild via wrap:gs+Pillow (text layer destroyed by design; documented) | text types + pdf | v1 |
| Signatures | `carrel sign` | lib:pypdf+lib:reportlab (visible PDF stamp), custom (sha256 MANIFEST + wrap:gpg detached sig, verify mode) | pdf + any (manifest) | v1 |
| Notes/comments (annotations) | `carrel note` | lib:pypdf (PDF text annotations, list/add), custom (sidecar notes in index DB for any file) | pdf + all (sidecar) | v1 |
| Tagging | `carrel tag` | custom (tags in index DB; add/rm/ls/find) | all | v1 |
| Form building | `carrel form` | custom (JSON spec → HTML form; → PDF form via weasyprint for print-fill), lib:pypdf (fill existing AcroForm PDF, list fields) | html pdf json | v1 |
| Image extraction | `carrel extract-images` | wrap:pdfimages (pdf), wrap:icotool (ico frames), custom (html `<img>` local refs) | pdf ico html | v1 |
| Soft proofing (ICC) | `carrel proof` | wrap:imagemagick `-profile` with system ICC profiles (probed present); reports ΔE summary via Pillow | jpg jpeg png pdf(raster) | v1 |
| Color management | `carrel color` | lib:Pillow+ImageCms (profile convert/assign, palette extraction, contrast check) | images | v1 |
| Agent workflows & loops | marketplace plugin `carrel-agent` | custom (slash commands + agents + a watch-loop skill that pairs `carrel watch` with `claude -p`) | — | v1 |
| **Invented:** desk TUI | `carrel desk` | lib:textual (flagship; drives core library) | all | v1 (flagship) |
| **Invented:** recipes | `carrel run <recipe.yaml>` | custom mini-pipeline runner | — | stretch |
| Cryptographic PDF signing (PAdES) | — | stretch (needs pyHanko + key mgmt) | pdf | stretch |

## v0.2.0 — planned rows (specs/15–21; status tracked in docs/BUILD_PLAN.md)

| Capability | Command | Strategy | Types | Spec |
|---|---|---|---|---|
| Office & ebook input/output | `carrel convert` / `inspect` / `index` / `search` / `pack` / `diff` / `audiobook` via `core.textextract` | wrap:pandoc (docx/odt/epub/rtf read + write), lib:openpyxl via `carrel[office]` (xlsx→csv/json) | docx odt epub rtf xlsx | 18 |
| Query-driven & git-aware packing | `carrel pack --query / --since / --changed / --dedupe-content / --outline` | custom over FTS5 ranking; wrap:git; lib:tiktoken via `carrel[tokens]` for `--tokenizer exact`; `.gitignore` negation | all | 16 |
| Whole desk over MCP | `carrel mcp` (10 tools + 2 resource templates) | custom stdlib JSON-RPC, delegating to command impl functions | all | 15 |
| Catalog: schema migrations, export/import, status | `carrel catalog export/import/status`, `carrel index --status` | custom (`PRAGMA user_version`, JSON sidecar of tags+notes) | — | 17 |
| Install ergonomics | `carrel completion bash/zsh/fish`; extras `tui/office/tokens/all`; `CARREL_BIN_<NAME>` override | lib:click completions; pyproject extras | — | 19 |
| Plugin surface generated from `--help` | 7 plugins (adds `carrel-documents`, `carrel-guard`); `scripts/sync_plugins.py --check` gate | custom; hooks `PreToolUse(Read)` → text conversion, `SessionStart` → capability summary | — | 20 |
| Drift gates & CI matrix | `scripts/sync_reference.py`; COOKBOOK nav page; macOS required, Windows advisory; coverage floor | custom | — | 21 |

## Explicit scope notes

- **PDF redaction** is true redaction (rasterization destroys the text layer) — documented tradeoff; searchability restorable via `carrel ocr` afterwards.
- **html thumbnails** go through weasyprint→pdf→pdftoppm; if weasyprint missing, degrade with hint.
- **Near-dupe** uses a dependency-free dHash (no numpy/imagehash) to keep install light.
- **Token estimates** in `pack` use a chars/3.6 heuristic labeled as estimate; exact tokenizers are out of scope (no network, no heavy deps).
- **Office formats** (docx/xlsx) are out of scope — not in the required type list; libreoffice absent.

## Cuts (running log — updated through the build)

- `recipes` runner: stretch, cut if time is short (cookbook shell scripts cover the use cases).
- PAdES cryptographic PDF signing: cut to stretch; visible stamp + gpg manifest signing ship instead (rationale: key management UX exceeds session scope).
