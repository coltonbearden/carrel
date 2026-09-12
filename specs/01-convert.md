# spec: convert

**Owns:** `src/carrel/commands/convert.py`, `tests/test_convert.py`.

## CLI
`carrel convert SRC... --to EXT [-o OUT|--out-dir DIR] [--json] [--force]`
Multiple SRC allowed only with `--out-dir`. Default output: `SRC` with new extension alongside source; refuse overwrite without `--force`.

## Routing matrix (strategy per pair)
- md/html/txt ↔ each other: pandoc (degrade md→html: markdown-it-py; html→txt: textextract; txt→md: identity copy w/ fence? no—plain copy).
- md/html/txt → pdf: weasyprint (md first → html via pandoc/markdown-it).
- pdf → txt: pdftotext. pdf → md: pdftotext + light structure (form feeds → `---`, keep blank lines). pdf → html: pdftotext -layout wrapped in `<pre>` (honest, documented) OR pandoc if available from txt.
- pdf → png/jpg: pdftoppm (first page unless `--pages all`).
- jpg/jpeg/png/ico ↔ each other: Pillow (ico: sizes 16..256; multi-frame read via icotool degrade note).
- image → pdf: Pillow save PDF.
- json ↔ csv: custom (list-of-objects ↔ rows; nested json flattened with dotted keys). json ↔ xml: custom minimal (documented shape). csv → md table, csv/json → html table: custom.
- Unsupported pair → exit 4 with the supported-target list for that source type.

## JSON output
`[{"src":..., "dest":..., "via":"pandoc", "ok":true}, ...]`

## Acceptance
- md→html→pdf chain works on fixtures (weasyprint present). pdf→txt non-empty on text fixture. png→ico→png roundtrip. json→csv→json preserves flat data. Overwrite refused without --force (exit 1). Bad pair → exit 4. All via CliRunner tests + ≥1 subprocess test.
