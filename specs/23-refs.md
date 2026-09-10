# spec: refs — reference numbers, one registry for `redact` and `refs`

**Owns:** new `src/carrel/core/patterns.py`, new `src/carrel/commands/refs.py`, `src/carrel/commands/redact.py` (builtins now read the registry), `src/carrel/commands/mcp.py` (`carrel_refs`), new `tests/test_core_patterns.py`, new `tests/test_refs.py`, `plugins/carrel-finance/` (new plugin: `/refs`).
**Wave:** v0.4.0, PR A (with spec 24).

## Why
Accounting folders are linked by numbers, not names: the invoice PDF, the remittance email and the bank export all carry `INV-2026-0042`, and nothing in carrel could see that. `redact` already owned five PII regexes with a Luhn validator; the natural home for reference numbers is the same registry, so a kind added once is both redactable and findable.

## core/patterns.py
- `Pattern(name, regex, group, purpose, validator, normalize, flags)`; `PATTERNS` (ordered), `GROUPS = ("pii", "reference", "identifier")`, `kinds(group)`, `REFERENCE_KINDS` (reference + identifier), `resolve_kinds(names)`, `parse_extra("NAME=REGEX")`, `find_refs(text, patterns, max_locations=20)`.
- Named groups `v1`/`v2`/`v3` mark alternatives; the first matched one is the **value** (`Pattern.value`, `Pattern.span`). Patterns without one use the whole match (the pii kinds, regexes unchanged from v0.1).
- Validators take the normalised value: `luhn_valid`/`cc_valid`, `iban_valid` (mod-97 + `IBAN_LENGTHS`), `aba_valid` (3-7-1 weights + Federal Reserve prefix ranges), `isbn_valid` (10 and 13), `gtin_valid` (8/12/13/14). A failing validator drops the hit (as redact always did for `cc`).
- Reference kinds are label-driven (`Invoice #`, `PO`, `Order No.`, `Check #`, `Account #`, `Tracking #`) with a value word that must contain a digit, so `Invoice Date` never yields `Date`; `INV-…`/`PO-…` glued prefixes match on their own; `ticket` is `[A-Z]{2,6}-\d{2,6}` excluding the INV/PO prefixes and multi-segment numbers.
- `find_refs` returns `[{kind, value, count, valid (true|null), pages, lines}]` in registry-then-first-occurrence order; pages count `\f` (pdftotext page breaks), lines are 1-based over the whole text.

## redact.py
`BUILTINS = dict(PATTERNS)`; `Rule` carries the `Pattern` and `Rule.span(m)` is the value span, so text redaction replaces `Invoice # INV-1` with `Invoice # █` and the PDF raster path paints only the value's word boxes. Behaviour of the original five kinds is unchanged (existing tests are the guard).

## refs.py
`carrel refs PATH... [--kind K,K] [--pattern NAME=REGEX]* [--tag] [--link] [--all] [--ocr] [--fail-empty]`
- Directories walk like `index` (`index._walk`: hidden and `.gitignore`d entries skipped; images only with `--ocr`); explicit files are scanned as given; text via `extract_text`.
- Default kinds: `REFERENCE_KINDS`; PII kinds only when named. Bad `--kind`/`--pattern` → exit 2; a missing path → exit 4.
- JSON: `[{path, refs: [...], (tags), (error, kind)}]`; `--link`: `[{kind, value, files, count}]` for values in ≥2 files (`--all` lifts). Per-file extraction failures are recorded, never abort the scan; when *every* file failed for a missing binary → exit 3 with the hint; `--fail-empty` → exit 5 when nothing was found.
- `--tag` adds `ref:<kind>:<value>` (whitespace squeezed, lower-cased by DeskDB) to each file that had references, written in **one short transaction after the scan** (a long OCR run never holds the desk locked; a failed run leaves no half-written tags); files without references are not registered. Every path is validated before anything is scanned, so a bad argument exits 4 without creating `.carrel/`. Without `--tag`, no `.carrel/` is ever created.
- Directories are seeded with the ancestor `.gitignore` rules up to `--root` (as `index_paths` does), so `refs repo/sub` honours `repo/.gitignore`. Any exception while extracting one file (permission denied, a non-UTF-8 JSON, a csv field overflow) becomes that file's `{error, kind: "error"}` record.
- `find_refs` precomputes newline and form-feed offsets once and bisects per match, so a 50k-line export with a hit per line stays linear.
- Library seams: `scan_refs(paths, kinds, extra, ocr, tag_root)`, `link_refs(records, all_)`, `tag_for(ref)`.

## MCP
`carrel_refs {path, kinds?, patterns?, tag?, link?, all?, ocr?, root?}` → `{root, path, files}` or `{root, path, references}`.

## Acceptance
- `carrel refs DIR` on a text invoice + markdown remittance lists invoice/po/order/ticket/iban/routing with `valid: true` on the checked kinds; `--link` groups the shared invoice and ticket; `--tag` then `tag find ref:invoice:inv-2026-0042` returns both files.
- `refs --kind invoice,email` includes the email; the default scan does not.
- A two-page PDF reports `pages: [2]` for a number on page 2 (needs pdftotext); with `CARREL_BIN_PDFTOTEXT` pointing nowhere a PDF-only scan exits 3, a mixed scan records the failure per file.
- `redact --builtin invoice` keeps the label; `redact --builtin iban` skips a bad check digit.
- `doctor` lists `refs` (degraded without pdftotext/pandoc/tesseract); `docs/REFERENCE.md` and `plugins/carrel-finance/commands/refs.md` regenerate cleanly.
