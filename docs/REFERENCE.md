# Carrel command reference

Generated from `--help` of carrel 0.2.0 by `scripts/sync_reference.py` — do not edit.
Regenerate with `uv run python scripts/sync_reference.py`; CI fails when this file drifts.

Related docs: [Install](INSTALL.md) · [Quickstart](QUICKSTART.md) ·
[Configuration](CONFIGURATION.md) · [Troubleshooting](TROUBLESHOOTING.md) ·
[Cookbook & snippets](COOKBOOK.md)

## Global options

These live on the root command, *before* the subcommand
(e.g. `carrel --json inspect report.pdf`):

```text
Usage: carrel [OPTIONS] COMMAND [ARGS]...

  carrel — a library desk for your files — and your agents.

  Every command supports --help; data-producing commands support --json. Run `carrel doctor` to see
  what your environment enables.

Options:
  --version         Show the version and exit.
  --json            Machine-readable JSON output.
  --debug           Show tracebacks on error.
  --root DIRECTORY  Desk root for db-backed commands (default: cwd).
  --help            Show this message and exit.

Commands:
  audiobook       Narrate SRC (txt, md, pdf) into an audiobook.
  catalog         Export, import and check the desk catalog (tags + notes in .carrel/carrel.db).
  color           Color tools: dominant palette, ICC profile conversion, WCAG contrast.
  completion      Print a completion script for SHELL (bash, zsh, or fish).
  convert         Convert SRC...
  dedupe          Report duplicate files under DIRS (recursively; hidden entries skipped).
  desk            Open the interactive desk TUI on ROOT (default: --root, then cwd).
  diff            Compare two files A and B.
  doctor          Report environment health: adapters found, versions, per-command capability.
  edit            Edit files in place-adjacent, non-destructive ways (pdf/image/text/json).
  extract-images  Extract images embedded in / referenced by SRC (pdf, ico, html).
  form            Build HTML forms from JSON specs; list and fill PDF AcroForms.
  index           Index PATH...
  inspect         Show metadata for one file.
  mcp             Serve the desk as an MCP server on stdio: 10 tools (search, pack, inspect,...
  note            Attach notes to files (desk db) and annotations to PDFs (pypdf).
  ocr             OCR an image or PDF into text (txt/md) or a searchable PDF.
  organize        Plan (default) or perform (--apply) sorting DIRECTORY's files.
  pack            Bundle PATH...
  proof           Soft-proof SRC against an ICC PROFILE (simulate print/display output).
  redact          Redact sensitive strings from a text file or PDF.
  search          Full-text search the desk index for QUERY (FTS5 syntax, bm25-ranked).
  sign            Sign things: stamp PDFs, hash manifests, verify both.
  tag             Tag files in the desk db (.carrel/carrel.db under --root).
  thumb           Create thumbnails for SRC...
  watch           Watch DIRECTORY (non-recursive) and run shell actions on file events.
```

- `--json` — where a command produces data, exactly one JSON object or array
  goes to stdout and nothing else (progress goes to stderr). Every command also
  accepts `--json` after its name; both spellings work.
- `--root PATH` — where db-backed commands keep `.carrel/carrel.db`.
  See [Configuration](CONFIGURATION.md).
- `--debug` — show tracebacks instead of one-line errors.

## Commands

26 commands:

[audiobook](#carrel-audiobook) ·
[catalog](#carrel-catalog) ·
[color](#carrel-color) ·
[completion](#carrel-completion) ·
[convert](#carrel-convert) ·
[dedupe](#carrel-dedupe) ·
[desk](#carrel-desk) ·
[diff](#carrel-diff) ·
[doctor](#carrel-doctor) ·
[edit](#carrel-edit) ·
[extract-images](#carrel-extract-images) ·
[form](#carrel-form) ·
[index](#carrel-index) ·
[inspect](#carrel-inspect) ·
[mcp](#carrel-mcp) ·
[note](#carrel-note) ·
[ocr](#carrel-ocr) ·
[organize](#carrel-organize) ·
[pack](#carrel-pack) ·
[proof](#carrel-proof) ·
[redact](#carrel-redact) ·
[search](#carrel-search) ·
[sign](#carrel-sign) ·
[tag](#carrel-tag) ·
[thumb](#carrel-thumb) ·
[watch](#carrel-watch)

## carrel audiobook

```text
Usage: carrel audiobook [OPTIONS] SRC

  Narrate SRC (txt, md, pdf) into an audiobook.

  Markdown is stripped for speech: headings become spoken chapter announcements, code blocks become
  "[code omitted]", links read their text. mp3/ogg need ffmpeg; --format wav works with espeak-ng
  alone. Existing outputs are never overwritten without --force. With --json, prints {src, outputs,
  engine, duration_s, chars}.

Options:
  -o, --output FILE               Output audio file (default: SRC with audio extension).
  --voice TEXT                    Voice: espeak voice name, piper model path, or edge-tts voice.
  --rate INTEGER RANGE            Speech rate in words per minute.  [default: 170; 80<=x<=450]
  --engine [auto|espeak|piper|edge-tts]
                                  TTS engine; auto prefers piper > edge-tts > espeak-ng.  [default:
                                  auto]
  --split-chapters                One file per chapter (markdown H1/H2, or the PDF outline).
  --force                         Overwrite existing output files.
  --format [mp3|ogg|wav]          Audio format (default: from -o extension, else mp3).
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```

## carrel catalog

```text
Usage: carrel catalog [OPTIONS] COMMAND [ARGS]...

  Export, import and check the desk catalog (tags + notes in .carrel/carrel.db).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  export  Export every tagged or annotated file's tags and notes as JSON.
  import  Merge FILE (a `catalog export` document) into the desk under --root.
  status  Report the desk db: schema version, row counts, and stale index entries.
```

### carrel catalog export

```text
Usage: carrel catalog export [OPTIONS]

  Export every tagged or annotated file's tags and notes as JSON.

  Document: {"schema", "product", "version", "exported", "root", "files": [{"path": <root-relative>,
  "tags": [...sorted], "notes": [{"created", "body"}]}]}, sorted by path — byte-identical across
  runs apart from "exported". Without -o the document itself is printed (always JSON); with -o a
  short summary is printed instead. Exit 4 when no desk db exists.

Options:
  -o, --out FILE  Write the catalog to FILE instead of stdout (refuses to overwrite without
                  --force).
  --force         Overwrite an existing --out file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

### carrel catalog import

```text
Usage: carrel catalog import [OPTIONS] FILE

  Merge FILE (a `catalog export` document) into the desk under --root.

  Tags already present are kept (INSERT OR IGNORE); notes are deduplicated on (file, created, body),
  so importing the same document twice adds nothing. Entries whose path does not exist under the
  root are counted in skipped_missing and not created. Exit 4 for unreadable/invalid JSON or a
  "schema" newer than this build supports. JSON output: {tags_added, notes_added, files_touched,
  skipped_missing, tags_removed, notes_removed}.

Options:
  --replace  Delete ALL existing tags and notes first, then import (prints what was removed).
  --json     Machine-readable JSON output.
  --help     Show this message and exit.
```

### carrel catalog status

```text
Usage: carrel catalog status [OPTIONS]

  Report the desk db: schema version, row counts, and stale index entries.

  JSON: {schema_version, db_path, counts: {files, docs, tags, notes}, stale: {changed, missing,
  unindexed}, examples: {changed, missing, unindexed} (up to 5 paths each)}. Always exit 0 (it is a
  report); exit 4 when no .carrel/carrel.db exists under --root.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel color

```text
Usage: carrel color [OPTIONS] COMMAND [ARGS]...

  Color tools: dominant palette, ICC profile conversion, WCAG contrast.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  check    WCAG contrast ratio of FG on BG (hex colors, e.g.
  convert  Convert SRC into an ICC profile and embed the profile in the output.
  palette  Dominant colors of SRC as hex + proportion (median-cut quantization).
```

### carrel color check

```text
Usage: carrel color check [OPTIONS] FG BG

  WCAG contrast ratio of FG on BG (hex colors, e.g. #333 #fafafa).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel color convert

```text
Usage: carrel color convert [OPTIONS] SRC

  Convert SRC into an ICC profile and embed the profile in the output.

  CMYK targets are written as JPEG/TIFF (PNG cannot store CMYK).

Options:
  --to-profile P  Target ICC profile: .icc path or builtin alias (cmyk, gray, p3, srgb).  [required]
  -o, --out FILE  Output path [default: <SRC>.<profile>.png/.jpg].
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

### carrel color palette

```text
Usage: carrel color palette [OPTIONS] SRC

  Dominant colors of SRC as hex + proportion (median-cut quantization).

  Human mode shows rich color swatches; --json prints one JSON array of {"hex", "proportion"} sorted
  by coverage.

Options:
  --n INTEGER RANGE  Number of colors to extract.  [default: 8; 1<=x<=256]
  --json             Machine-readable JSON output.
  --help             Show this message and exit.
```

## carrel completion

```text
Usage: carrel completion [OPTIONS] {bash|zsh|fish}

  Print a completion script for SHELL (bash, zsh, or fish).

    eval "$(carrel completion bash)"      # ~/.bashrc
    eval "$(carrel completion zsh)"       # ~/.zshrc, after compinit
    carrel completion fish > ~/.config/fish/completions/carrel.fish

  The script is produced in-process by click; an unknown shell exits 2. With --json, emits {"shell":
  ..., "script": ...}.

Options:
  --install-hint  Append, as a comment block, how to enable the script in that shell.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

## carrel convert

```text
Usage: carrel convert [OPTIONS] SRC...

  Convert SRC... to another supported type.

  By default the output lands next to each SRC with the new extension. Existing outputs are never
  overwritten without --force. With --json, prints one JSON array of {"src", "dest", "via", "ok"}
  records.

  Office and ebook sources (docx, odt, epub, rtf) are read by pandoc and can go to md/html/txt/pdf
  (pdf also needs weasyprint); md/html/txt can be written as docx or odt, and docx <-> epub round-
  trips. xlsx reads need the `office` extra (openpyxl) and go to csv or json only.

Options:
  --to EXT             Target type: pdf, md, txt, html, json, xml, csv, png, jpg, ico, docx, odt,
                       epub.  [required]
  -o, --output FILE    Explicit output path (single SRC only).
  --out-dir DIRECTORY  Write outputs into this directory (required for multiple SRC).
  --force              Overwrite existing outputs.
  --pages [first|all]  pdf → png/jpg only: rasterize the first page, or every page as DEST-1..N.
                       [default: first]
  --sheet NAME|N|all   xlsx → csv/json only: pick a sheet by name or 1-based number (default: first;
                       json defaults to every sheet). 'all' with csv writes DEST-<sheet>.csv per
                       sheet.
  --json               Machine-readable JSON output.
  --help               Show this message and exit.

  Supported conversions (SRC type → --to targets):
    csv   → html, json, md
    docx  → epub, html, md, pdf, txt
    epub  → docx, html, md, pdf, txt
    html  → docx, md, odt, pdf, txt
    ico   → jpg, pdf, png
    jpg   → ico, pdf, png
    json  → csv, html, xml
    md    → docx, html, odt, pdf, txt
    odt   → html, md, pdf, txt
    pdf   → html, jpg, md, png, txt
    png   → ico, jpg, pdf
    rtf   → html, md, pdf, txt
    txt   → docx, html, md, odt, pdf
    xlsx  → csv, json
    xml   → json
```

## carrel dedupe

```text
Usage: carrel dedupe [OPTIONS] DIRS...

  Report duplicate files under DIRS (recursively; hidden entries skipped).

  Default is report-only. Deletion needs BOTH --delete newest|oldest AND --apply; without --apply
  the deletions are only planned. The kept member of each group is never deleted. JSON output is a
  list of {hash, files, kept, deleted}.

Options:
  --near                    Perceptual matching for images (64-bit dHash, Hamming distance <= 8)
                            instead of exact content hashing. Non-image files are ignored in this
                            mode.
  --delete [newest|oldest]  Which duplicates to delete per group (by mtime); the other end of the
                            range is kept. Requires --apply to actually remove files.
  --apply                   Actually delete (only together with --delete).
  --json                    Machine-readable JSON output.
  --help                    Show this message and exit.
```

## carrel desk

```text
Usage: carrel desk [OPTIONS] [ROOT]

  Open the interactive desk TUI on ROOT (default: --root, then cwd).

  Three panes: a directory tree of supported files, an inspector (metadata, text preview,
  tags/notes), and an actions list (convert / OCR / thumbnail / pack / index / tag / note). Action
  outputs land in ROOT/carrel-out/. Keys: q quit, / search, t tag, n note.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel diff

```text
Usage: carrel diff [OPTIONS] A B

  Compare two files A and B.

  Modes: text (unified diff), struct (json: dotted-path added/removed/changed; csv: per-row/column
  cell changes; xml: element-path changes), pdf (extracted text diff + page counts), image (Pillow
  pixel diff: dimensions, changed-pixel percentage, mean channel delta; sizes are padded to a common
  canvas and the mismatch reported). auto picks by type pair and falls back to a text diff when both
  files are text-like.

  Exit status:
    0  files are identical
    1  files differ
    2  bad usage
    3  missing optional dependency (pdf mode needs pdftotext)
    4  missing/unsupported input, or no mode fits the type pair

Options:
  --json                          Machine-readable JSON output.
  --mode [auto|text|struct|image|pdf]
                                  Comparison strategy; auto picks by type pair.  [default: auto]
  --out FILE                      Image mode: write a per-pixel delta heatmap PNG here.
  --help                          Show this message and exit.
```

## carrel doctor

```text
Usage: carrel doctor [OPTIONS]

  Report environment health: adapters found, versions, per-command capability.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel edit

```text
Usage: carrel edit [OPTIONS] COMMAND [ARGS]...

  Edit files in place-adjacent, non-destructive ways (pdf/image/text/json).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  image  Resize, rotate, crop, re-encode or strip metadata from an image.
  json   Set or delete values in a JSON file by dotted path (a.b.0.c).
  pdf    Merge, split, extract pages, rotate, linearize or decrypt a PDF.
  text   Find & replace in a text file (txt/md/html/csv/xml/json-as-text).
```

### carrel edit image

```text
Usage: carrel edit image [OPTIONS] SRC

  Resize, rotate, crop, re-encode or strip metadata from an image.

  Operation order: crop → resize → rotate.

Options:
  --resize WxH|N%          Resize to WxH or by percent.
  --rotate DEG             Rotate clockwise by DEG degrees (canvas expands).
  --crop X,Y,W,H           Crop box: left,top,width,height.
  --strip                  Drop EXIF/metadata from the output.
  --quality INTEGER RANGE  JPEG/WebP quality (1-100).  [1<=x<=100]
  -o, --out PATH           Output file. Default: SRC.edited.<ext>.
  --force                  Allow overwriting existing files.
  --json                   Machine-readable JSON output.
  --help                   Show this message and exit.
```

### carrel edit json

```text
Usage: carrel edit json [OPTIONS] SRC

  Set or delete values in a JSON file by dotted path (a.b.0.c).

Options:
  --set PATH=VALUE  Set dotted PATH to VALUE (parsed as JSON, string fallback). Repeatable.
  --del PATH        Delete dotted PATH. Repeatable; applied after --set.
  -o, --out PATH    Output file. Default: SRC.edited.json.
  --force           Allow overwriting existing files.
  --json            Machine-readable JSON output.
  --help            Show this message and exit.
```

### carrel edit pdf

```text
Usage: carrel edit pdf [OPTIONS] SRC

  Merge, split, extract pages, rotate, linearize or decrypt a PDF.

  Pipeline: decrypt → merge → --pages selection → rotate → write (--split writes one file per page)
  → linearize. --pages extracts: the output contains only the selected pages, so --rotate applies to
  that selection.

Options:
  --merge PATH    Append these PDFs after SRC (repeatable, in order).
  --split         Write one PDF per page into OUT (a directory).
  --pages SPEC    Keep only these pages, e.g. '1-3,7' (1-based).
  --rotate DEG    Rotate output pages clockwise (multiple of 90).
  --linearize     Linearize output for fast web view (qpdf).
  --decrypt PW    Decrypt SRC with password (qpdf).
  -o, --out PATH  Output file (or directory with --split). Default: SRC.edited.pdf / SRC-pages/.
  --force         Allow overwriting existing files.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

### carrel edit text

```text
Usage: carrel edit text [OPTIONS] SRC

  Find & replace in a text file (txt/md/html/csv/xml/json-as-text).

  Requires -o OUT or an explicit -i/--in-place — never silently rewrites SRC.

Options:
  --find PAT      Text (or regex) to find.  [required]
  --replace REP   Replacement text (may be empty).  [required]
  --regex         Treat PAT as a Python regular expression.
  -i, --in-place  Rewrite SRC itself.
  -o, --out PATH  Output file.
  --force         Allow overwriting an existing output file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

## carrel extract-images

```text
Usage: carrel extract-images [OPTIONS] SRC

  Extract images embedded in / referenced by SRC (pdf, ico, html).

  pdf uses pdfimages, ico uses icotool (or a Pillow fallback), html copies local <img src> files
  that exist next to the document — remote URLs are never fetched. With --json, prints one JSON
  object {"src", "out_dir", "count", "extracted"}.

Options:
  --out-dir DIRECTORY       Output directory [default: <SRC>-images next to the source].
  --min-size INTEGER RANGE  pdf mode: discard images smaller than this on either edge.  [default:
                            32; x>=1]
  --json                    Machine-readable JSON output.
  --help                    Show this message and exit.
```

## carrel form

```text
Usage: carrel form [OPTIONS] COMMAND [ARGS]...

  Build HTML forms from JSON specs; list and fill PDF AcroForms.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  build   Render a JSON form spec into clean, standalone, print-friendly HTML.
  fields  List a PDF's AcroForm fields (name, type, current value).
  fill    Fill a PDF's AcroForm fields from a JSON object {field: value}.
```

### carrel form build

```text
Usage: carrel form build [OPTIONS] SPEC.JSON

  Render a JSON form spec into clean, standalone, print-friendly HTML.

Options:
  -o, --out PATH  Output HTML file. Default: SPEC stem + .html.
  --pdf           Also render the HTML to PDF (weasyprint).
  --force         Allow overwriting existing output files.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

### carrel form fields

```text
Usage: carrel form fields [OPTIONS] SRC

  List a PDF's AcroForm fields (name, type, current value).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel form fill

```text
Usage: carrel form fill [OPTIONS] SRC DATA.JSON

  Fill a PDF's AcroForm fields from a JSON object {field: value}.

Options:
  -o, --out PATH  Output PDF.  [required]
  --force         Allow overwriting an existing output file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

## carrel index

```text
Usage: carrel index [OPTIONS] [PATHS]...

  Index PATH... (default: the desk root) into .carrel/carrel.db.

  Walks directories for the supported file types, skipping hidden entries (.carrel, .git, dotfiles).
  Files unchanged since the last run (same size + mtime) are skipped. Text comes from
  core.textextract; images are registered but only get searchable text with --ocr. Progress goes to
  stderr; the JSON summary is {"indexed", "skipped", "pruned", "errors"}. `--status` prints the
  `carrel catalog status` report instead.

Options:
  --ocr         OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --prune       Remove index rows whose files no longer exist on disk.
  --update      Treat PATH... as individual files to (re)index — no directory walking; unsupported
                or missing files are silently skipped.
  --if-indexed  Exit 0 silently when no desk db exists yet under --root (for hooks: only refresh an
                index someone already created).
  --status      Report index health instead of indexing (alias of `carrel catalog status`); other
                options are ignored. Exit 4 when no desk db exists under --root.
  --json        Machine-readable JSON output.
  --help        Show this message and exit.
```

## carrel inspect

```text
Usage: carrel inspect [OPTIONS] PATH

  Show metadata for one file.

  Always: name, size, mtime, detected type, sha256 (files under 512 MB) and a mime guess. Plus per-
  type detail: pdf (pages, title/author/producer, encryption, form fields, annotations), images
  (dimensions, mode, EXIF summary), json (shape, key count, depth), csv (dialect, columns, rows),
  xml (root tag, element count, depth), html (title, headings outline, link/img counts), md
  (headings outline, word count), txt (lines/words/chars), docx (paragraphs, words,
  title/author/created), epub (title, creator, language, spine items, words), odt/rtf (words), xlsx
  (sheets with row/column counts; needs the `office` extra). Word counts for office/ebook files use
  pandoc and are null without it.

Options:
  --json  Machine-readable JSON output.
  --deep  Add exiftool's full tag table when exiftool is installed; without it the output notes 'not
          installed' (never an error).
  --help  Show this message and exit.
```

## carrel mcp

```text
Usage: carrel mcp [OPTIONS]

  Serve the desk as an MCP server on stdio: 10 tools (search, pack, inspect, tag, note, index,
  convert, diff, redact, doctor) and carrel:// file/search resources.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel note

```text
Usage: carrel note [OPTIONS] COMMAND [ARGS]...

  Attach notes to files (desk db) and annotations to PDFs (pypdf).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  add      Attach TEXT as a sidecar note to PATH (stored in the desk db).
  ls       List PATH's sidecar notes, newest first (ISO timestamps).
  pdf      List PATH's PDF annotations: page, subtype, contents.
  pdf-add  Add TEXT as a FreeText annotation to a PDF page.
```

### carrel note add

```text
Usage: carrel note add [OPTIONS] PATH TEXT

  Attach TEXT as a sidecar note to PATH (stored in the desk db).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel note ls

```text
Usage: carrel note ls [OPTIONS] PATH

  List PATH's sidecar notes, newest first (ISO timestamps).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel note pdf

```text
Usage: carrel note pdf [OPTIONS] PATH

  List PATH's PDF annotations: page, subtype, contents.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel note pdf-add

```text
Usage: carrel note pdf-add [OPTIONS] PATH TEXT

  Add TEXT as a FreeText annotation to a PDF page.

  The result is verified by reading the output back with pypdf and checking the annotation is listed
  (same reader the `pdf` subcommand uses).

Options:
  --page INTEGER  1-based page to annotate.  [default: 1]
  --pos X,Y       Lower-left corner of the note box in PDF points.  [default: 72,72]
  -o, --out FILE  Output PDF (default: PATH with an .annotated.pdf suffix; pass PATH itself to
                  annotate in place).
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

## carrel ocr

```text
Usage: carrel ocr [OPTIONS] SRC

  OCR an image or PDF into text (txt/md) or a searchable PDF.

  Images (jpg/png) run through tesseract; PDFs through ocrmypdf, which passes born-digital pages
  through untouched unless --redo is given.

Options:
  -o, --out PATH     Output file. Default: SRC with the target extension (SRC.ocr.pdf for pdf →
                     pdf).
  --lang LANG        OCR language(s), tesseract codes, e.g. eng or eng+deu.  [default: eng]
  --to [txt|pdf|md]  Output: extracted text (txt/md) or a searchable PDF.  [default: txt]
  --redo             Re-OCR PDF pages even if they already have text (ocrmypdf --force-ocr; default
                     skips them).
  --force            Allow overwriting an existing output file.
  --json             Machine-readable JSON output.
  --help             Show this message and exit.
```

## carrel organize

```text
Usage: carrel organize [OPTIONS] DIRECTORY

  Plan (default) or perform (--apply) sorting DIRECTORY's files.

  Only files directly inside DIRECTORY are considered; subdirectories and hidden files stay put.
  Existing files are never overwritten — colliding names get a -1, -2, … suffix. JSON output is a
  list of {src, dest, action} ('move' planned, 'moved' executed, 'skip').

Options:
  --by [type|date|exif-date]  Grouping: 'type' -> pdf/, images/ (jpg, png, ico), data/ (json, xml,
                              csv), docs/ (md, txt, html); 'date' -> YYYY/MM from mtime; 'exif-date'
                              -> YYYY/MM from EXIF DateTimeOriginal, mtime fallback (images only;
                              other files are skipped).  [default: type]
  --into CATEGORY=DIR         Override a type category's destination subdir, e.g. --into images=pics
                              (only with --by type; repeatable).
  --apply / --dry-run         Execute the moves. Default is a dry-run that only prints the plan.
  --json                      Machine-readable JSON output.
  --help                      Show this message and exit.
```

## carrel pack

```text
Usage: carrel pack [OPTIONS] PATHS...

  Bundle PATH... (files or directories) into one LLM-ready context document.

  Formats: md (default: header + fenced tree + per-file fenced sections, fences lengthened on
  collision), xml (<context><tree/><file/></context> with CDATA, Claude-friendly), json ({meta,
  tree, files}). Token counts are ceil(chars / 3.6) labeled tokens_est by default; --tokenizer exact
  counts with tiktoken (o200k_base) and labels the field tokens.

  Selection: --query ranks files through the desk index under --root (build it with the `index`
  command) and emits hits in relevance order; --since REF / --changed narrow to what git reports as
  changed (deleted files are listed in the header as removed; --since REF compares REF with the
  working tree). --query combines with either git selector and with the usual --include/--exclude
  filters (intersection); --since and --changed exclude each other.

  .gitignore handling is a deliberately simple per-directory matcher: plain names and `*` globs
  match anywhere below their .gitignore; a trailing `/` restricts a pattern to directories; patterns
  containing `/` match relative to their .gitignore's directory; `!pattern` re-includes, with git's
  ordering rule (last matching line wins) — the negation is honored. `.git` and `.carrel` are always
  skipped. Binaries outside the supported set are listed in the tree as [skipped: binary] with their
  size, never inlined; images are only read (OCR) with --ocr.

Options:
  -o, --output FILE              Write here instead of stdout (with --chunk: OUT.part1..N).
  --format [md|xml|json]         Output format.  [default: md]
  --include GLOB                 Only pack files matching GLOB (repeatable).
  --exclude GLOB                 Drop files/dirs matching GLOB (repeatable).
  --no-gitignore                 Do not honor .gitignore files.
  --max-bytes N                  Stop adding file contents once N total bytes are packed; omissions
                                 are noted in the header.
  --max-file-bytes N             Skip any single file larger than N bytes.
  --chunk TOKENS                 Split into OUT.part1..N, each at most TOKENS tokens under the
                                 active --tokenizer (requires -o). Files are never split mid-file
                                 unless one alone exceeds the budget; then it is split on line
                                 boundaries with (continued) markers.
  --tree-only                    Emit header + tree only, no contents.
  --ocr                          OCR images and scanned PDFs (needs tesseract / ocrmypdf).
  --stats                        Print a per-file token table instead of the pack (the pack is still
                                 written when -o is given).
  --query TEXT                   Pack only files the desk index under --root ranks for TEXT (FTS5
                                 syntax), in relevance order. Requires a prior `index` run.
  --top N                        With --query: consider at most the N best-ranked hits.  [default:
                                 20]
  --since REF                    Pack only files changed since git REF (`git diff --name-only REF`);
                                 deleted files are listed as removed, not packed.
  --changed                      Pack only uncommitted changes: files differing from HEAD plus
                                 untracked files (not --since).
  --dedupe-content               Inline identical file contents once; later copies are tree-listed
                                 as [same as <first path>].
  --tokenizer [heuristic|exact]  Token counting: heuristic = ceil(chars/3.6) labeled tokens_est;
                                 exact = tiktoken o200k_base labeled tokens (needs the
                                 'carrel[tokens]' extra).  [default: heuristic]
  --outline                      Structure instead of contents (tree-only cost): .py top-level
                                 def/class names with line numbers, .md headings; other types show
                                 size only. Not with --chunk.
  --fail-empty                   Exit 5 when no file is packed (e.g. --query without hits, --since
                                 with no changes).
  --json                         Machine-readable JSON output.
  --help                         Show this message and exit.
```

## carrel proof

```text
Usage: carrel proof [OPTIONS] SRC

  Soft-proof SRC against an ICC PROFILE (simulate print/display output).

  Writes the proofed image and reports the color shift: mean/max per-channel delta and the share of
  pixels that moved visibly. With --json, prints the report as one JSON object.

Options:
  --profile PROFILE               Path to a .icc file, or builtin alias: cmyk, gray, p3, srgb.
                                  [required]
  --out FILE                      Proofed image path [default: <SRC>.proof.png].
  --intent [perceptual|relative]  Rendering intent.  [default: perceptual]
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```

## carrel redact

```text
Usage: carrel redact [OPTIONS] SRC

  Redact sensitive strings from a text file or PDF.

  Text files get regex replacement (JSON/XML are re-parsed afterwards so they stay valid). PDFs are
  truly redacted: pages are rasterized, matched words are painted over, and the output carries no
  text layer at all. Requires tesseract for PDFs.

Options:
  --pattern REGEX     Custom regex to redact (repeatable).
  --builtin LIST      Comma-separated builtins: email, phone, ssn, ipv4, cc.
  --replacement TEXT  Replacement text for matches (text files only).  [default: █]
  -o, --out PATH      Output file. Default: SRC.redacted.<ext>.
  --fail-empty        Exit 5 when nothing matched.
  --force             Allow overwriting an existing output file.
  --json              Machine-readable JSON output.
  --help              Show this message and exit.
```

## carrel search

```text
Usage: carrel search [OPTIONS] QUERY

  Full-text search the desk index for QUERY (FTS5 syntax, bm25-ranked).

  Matched terms are bracketed in the snippet. Filters combine with AND. JSON output is a list of
  {"path", "score", "snippet"} (lower bm25 score = better match). Run the `index` command first to
  build the index under --root.

Options:
  --limit INTEGER  Maximum number of hits.  [default: 20]
  --type T1,T2     Only these file types, comma-separated (e.g. pdf,md).
  --tag TAG        Only files carrying TAG (repeatable — every TAG must match).
  --fail-empty     Exit 5 when there are no hits.
  --json           Machine-readable JSON output.
  --help           Show this message and exit.
```

## carrel sign

```text
Usage: carrel sign [OPTIONS] COMMAND [ARGS]...

  Sign things: stamp PDFs, hash manifests, verify both.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  manifest  Write a sha256 manifest for PATHS (directories recurse).
  stamp     Stamp a visible signature block onto a PDF page.
  verify    Recompute a sha256 manifest (and its gpg signature, if present).
```

### carrel sign manifest

```text
Usage: carrel sign manifest [OPTIONS] PATHS...

  Write a sha256 manifest for PATHS (directories recurse).

Options:
  -o, --out PATH  Manifest file to write (sha256sum format).  [default: MANIFEST.sha256]
  --gpg           Also write a detached armored signature (OUT.asc).
  --key ID        gpg key id/email to sign with (implies --gpg).
  --force         Allow overwriting an existing manifest.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

### carrel sign stamp

```text
Usage: carrel sign stamp [OPTIONS] SRC

  Stamp a visible signature block onto a PDF page.

Options:
  --text TEXT                     Stamp text. Default: "Signed by <user> on <ISO date>".
  --image PATH                    Signature image (png/jpg) drawn above the text.
  --page PAGE                     Page to stamp: 'first', 'last' or a 1-based number.  [default:
                                  last]
  --pos [top-left|top-right|bottom-left|bottom-right]
                                  Page corner for the stamp.  [default: bottom-right]
  -o, --out PATH                  Output file. Default: SRC.signed.pdf.
  --force                         Allow overwriting an existing output file.
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```

### carrel sign verify

```text
Usage: carrel sign verify [OPTIONS] MANIFEST

  Recompute a sha256 manifest (and its gpg signature, if present).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel tag

```text
Usage: carrel tag [OPTIONS] COMMAND [ARGS]...

  Tag files in the desk db (.carrel/carrel.db under --root).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  add   Add TAG...
  find  List files carrying ALL of TAG...
  ls    List tags of PATH, or (without PATH) every tag with its file count.
  rm    Remove TAG...
```

### carrel tag add

```text
Usage: carrel tag add [OPTIONS] PATH TAGS...

  Add TAG... to PATH (registers the file in the desk db if needed).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel tag find

```text
Usage: carrel tag find [OPTIONS] TAGS...

  List files carrying ALL of TAG... (paths relative to the desk root).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel tag ls

```text
Usage: carrel tag ls [OPTIONS] [PATH]

  List tags of PATH, or (without PATH) every tag with its file count.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

### carrel tag rm

```text
Usage: carrel tag rm [OPTIONS] PATH TAGS...

  Remove TAG... from PATH (unknown tags/files are a quiet no-op).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

## carrel thumb

```text
Usage: carrel thumb [OPTIONS] SRC...

  Create thumbnails for SRC... (pdf, png, jpg, ico, html).

  Thumbnails land in --out-dir as <name>.<format>, aspect preserved, never larger than --size on
  either edge. With --json, prints one JSON array of {"src", "thumb", "w", "h"} records.

Options:
  --size INTEGER RANGE  Maximum edge length in pixels.  [default: 256; x>=1]
  --out-dir DIRECTORY   Directory for the thumbnails.  [default: thumbs]
  --format [png|jpg]    Thumbnail image format.  [default: png]
  --json                Machine-readable JSON output.
  --help                Show this message and exit.
```

## carrel watch

```text
Usage: carrel watch [OPTIONS] DIRECTORY

  Watch DIRECTORY (non-recursive) and run shell actions on file events.

  Events for files an action is currently producing are suppressed via an in-flight set plus an
  output-name heuristic (outputs whose name starts with the source file's stem); other action
  outputs written into the watched directory WILL re-trigger — write outputs elsewhere or use --glob
  to narrow matches. Ctrl-C exits cleanly.

Options:
  --on EVENTS            Comma-separated events to react to: created, modified, deleted, moved.
                         [default: created,modified]
  --glob PATTERN         Only react to file names matching this glob (e.g. '*.pdf').
  --run CMD              Shell action to run per event; repeatable, runs in order. {path}, {name}
                         and {dir} are substituted (shell-quoted).  [required]
  --debounce MS          Coalesce events per path within this window.  [default: 500; x>=0]
  --once                 Exit after the first triggered action batch.
  --timeout SECS         Hard stop after SECS seconds.  [x>0]
  --action-timeout SECS  Kill an action that runs longer than SECS (logged as rc=124).  [default:
                         300.0; x>0]
  --json-lines           Log one JSON object per action to stdout instead of human lines (--json
                         implies this).
  --json                 Machine-readable JSON output.
  --help                 Show this message and exit.
```

## Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | `OK` | success |
| 1 | `ERROR` | general/unexpected error (message to stderr, no traceback unless `--debug`) |
| 2 | `USAGE` | bad usage/arguments |
| 3 | `MISSING_DEP` | missing optional dependency (message names the binary + install hint) |
| 4 | `BAD_INPUT` | input file not found / unreadable / unsupported type |
| 5 | `EMPTY` | operation produced no result (e.g. `search --fail-empty` with no hits) |

Note: `carrel diff` deliberately reuses `1` to mean "inputs differ" — its help
text above spells out the full mapping.
