# spec: fixtures

**Owns:** `tests/fixtures/generate.py`, `tests/fixtures/**` (generated, committed), `tests/conftest.py`.

## Requirements
`python tests/fixtures/generate.py` is idempotent, stdlib+Pillow+reportlab+weasyprint-binary only, creates:
- `sample.txt` (multi-para, contains sentinel words "quixotic zephyr" + planted email/ssn-style strings for redact tests)
- `sample.md` (2 H1 chapters, headings, list, code block, link, sentinel "melodious cartography")
- `sample.html` (title, h1/h2, table, img ref to sample.png, form)
- `sample.json` (nested objects, list-of-objects records key), `records.json` (flat list-of-objects for csv roundtrip)
- `sample.xml` (3 levels), `sample.csv` (5 cols × 20 rows, header)
- `sample.png` (400×300 generated art w/ text), `sample.jpg` (same art + EXIF DateTimeOriginal via piexif? no — Pillow exif build), `sample-copy.jpg` (byte-identical copy for dedupe), `sample-resized.jpg` (75% for near-dupe), `sample.ico` (multi-size from art)
- `scanned.png` (900×1200 white bg, large black text "CARREL OCR FIXTURE 42" — tesseract-friendly)
- `text+image.pdf` (reportlab: page1 text w/ sentinel "palimpsest harbor", embedded PNG; page2 more text)
- `form.pdf` (AcroForm: text field "name", checkbox "agree" — reportlab acroform)
- `scanned.pdf` (image-only pdf from scanned.png — Pillow save)
- `b.pdf` (second small pdf for merge/diff)
- `conftest.py`: `fixtures` path fixture; `needs(binary)` skip helper; `tmp_copy` helper.

## Acceptance
Generator runs clean twice; every file type in the support matrix present; pytest collection imports conftest helpers.
