# spec: office and ebook formats — docx, odt, epub, rtf, xlsx

**Owns:** `src/carrel/core/filetypes.py`, `src/carrel/core/textextract.py`, `src/carrel/commands/convert.py`, `src/carrel/commands/inspect.py` (new `_docx_detail/_xlsx_detail/_epub_detail` + dispatch entries only — spec 15 later adds a public wrapper), `tests/fixtures/generate.py` (+ the generated fixtures), new `tests/test_office.py`, `docs/FEATURES.md` (matrix rows; delete the out-of-scope bullet that cites libreoffice).
**Depends on:** spec 19 declares the `office` extra (`openpyxl`) in `pyproject.toml`; this spec must not edit `pyproject.toml`. **Wave:** 1 (import `openpyxl` lazily and skip tests when it is absent, so wave 1 runs green before the extra lands).

## Why
The 11-type ceiling excluded Office formats because "libreoffice is absent". pandoc — already an adapter (`adapters.py:70`) — reads docx, odt, epub and rtf natively, and openpyxl reads xlsx in pure Python. One `textextract` branch lights up index, search, pack, diff and audiobook for all of them.

## filetypes.py
- `FileType` adds `DOCX`, `ODT`, `EPUB`, `RTF`, `XLSX`; new `.is_document` property is true for docx/odt/epub/rtf only (PDF keeps its own code paths); `is_text` unchanged. Extension map: `.docx .odt .epub .rtf .xlsx` (+ `.xlsm` → XLSX).
- Sniffing: `{\rtf` → RTF. `PK\x03\x04` → open as zip (read-only, first 64 entries): `mimetype` entry equal to `application/epub+zip` → EPUB, `application/vnd.oasis.opendocument.text` → ODT; else `[Content_Types].xml` present and any name starting `word/` → DOCX, `xl/` → XLSX; otherwise fall back to extension (an unknown zip stays UNKNOWN). Bytes still beat names; the zip probe must never raise (bad zip → extension fallback).
- Docstring and `SUPPORTED_EXTENSIONS` updated; the "11 supported file types" phrasing goes.

## textextract.py
- `document_text(path)` — `pandoc -t plain --wrap=none` via `adapters.run("pandoc", …)` for docx/odt/epub/rtf (input format from the detected type, never from the extension). Missing pandoc → `MissingDependencyError` (exit 3) as elsewhere.
- `xlsx_text(path)` — `openpyxl.load_workbook(read_only=True, data_only=True)`; each sheet as a `# <sheet name>` heading followed by CSV-flattened rows (reuse the existing CSV flattener's shape). `ImportError` → `MissingDependencyError` whose hint is `uv tool install 'carrel[office]'` (from a checkout: `uv sync --extra office`).
- `extract_text` dispatches on the new types. Empty extraction is not an error.

## convert.py
- Sources docx/odt/epub/rtf → `md`, `html`, `txt` via pandoc; → `pdf` via pandoc-to-html then the existing `_to_pdf` (weasyprint chain, same degradation). Also docx → epub and epub → docx (pandoc both sides) since it is free.
- Targets: `md`/`html`/`txt` → `docx` and `odt` via pandoc (`normalize_target` accepts them).
- xlsx → `csv` (default first sheet; `--sheet NAME|N` selects; `--out-dir` + all sheets when `--sheet all`) and → `json` (`{sheet: [row objects keyed by header]}`). Never the reverse in this release.
- The conversion matrix in `--help` and the unsupported-pair error list the new types.

## inspect.py
- docx: `paragraphs`, `words` (from extracted text), `title`/`author`/`created` from `docProps/core.xml` when present. xlsx: `sheets: [{name, rows, cols}]`. epub: `title`, `creator`, `language` from the OPF, `spine_items`. odt/rtf: size + words only. All under the existing per-type `detail` key; `--deep` unchanged.

## Fixtures (`tests/fixtures/generate.py`)
- `sample.docx`, `sample.odt`, `sample.epub`, `sample.rtf` generated from `sample.md` with pandoc; `sample.xlsx` (2 sheets, header row + 3 data rows, one numeric column) with openpyxl. Each step prints `skip: <tool> missing` and continues when its tool is absent. Generated files are committed once (sdist `exclude` in `pyproject.toml` is spec 19's file — ask the orchestrator to add `tests/fixtures/*.docx …` there; do not edit it here).
- Tests use `needs("pandoc")` from `conftest.py` and `pytest.importorskip("openpyxl")`.

## Acceptance
- `detect()` on each new fixture copied to a wrong extension (`sample.docx` → `x.bin`, `sample.xlsx` → `y.zip`, `sample.epub` → `z.docx`) returns the type from bytes; a plain zip of text files stays UNKNOWN; a truncated zip does not raise.
- Sentinel survives `sample.md → docx → md` (pandoc); `sample.md → odt → txt`; `docx → pdf` when weasyprint present (else the test asserts exit 3 with hint).
- `index` a tmp dir holding `sample.docx` and `sample.epub`; `search <sentinel> --json` returns both; `pack --json` inlines their text.
- xlsx → csv: row count equals the generated sheet's rows + header; `--sheet 2` picks the second sheet; → json has both sheet keys; `inspect sample.xlsx --json` lists 2 sheets with correct dimensions.
- Without pandoc (monkeypatch `adapters.have`), `convert sample.docx --to md` exits 3 naming pandoc; without openpyxl (monkeypatch import), `convert sample.xlsx --to csv` exits 3 with the `carrel[office]` hint.
- `docs/FEATURES.md` gains a row per format and loses the libreoffice out-of-scope bullet; README's type list is left for the wave-3 doc pass.
