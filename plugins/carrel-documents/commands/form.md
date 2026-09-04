---
description: Work with forms via the carrel CLI — list or fill a PDF's AcroForm fields from JSON, or build a clean printable HTML (and PDF) form from a JSON spec
argument-hint: <fields|fill|build> <pdf or spec.json> [data.json] [output]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: form
---

Handle this form request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel form` is a group with `fields`, `fill` and `build`; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel form --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
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

```text
Usage: carrel form fields [OPTIONS] SRC

  List a PDF's AcroForm fields (name, type, current value).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel form fill [OPTIONS] SRC DATA.JSON

  Fill a PDF's AcroForm fields from a JSON object {field: value}.

Options:
  -o, --out PATH  Output PDF.  [required]
  --force         Allow overwriting an existing output file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```
<!-- usage:end -->

- **fields SRC.pdf**: lists AcroForm fields as `{name, type, value}`. Always run this first before filling — the user's labels ("Name", "date signed") rarely equal the internal field names.
- **fill SRC.pdf DATA.json -o OUT.pdf**: DATA is a flat JSON object `{field_name: value}` using the exact names from `fields`; checkboxes take their export value (see `fields`). `-o` is required; the original is never modified; `--force` only when the user explicitly wants an existing output replaced. Write DATA.json with the Write tool or a heredoc, then fill.
- **build SPEC.json**: renders a JSON form spec into standalone, print-friendly HTML (`SPEC-stem.html` by default); `--pdf` also renders a PDF via weasyprint (exit 3 → relay the install hint). If the user has no spec yet, draft one from their description, show it, then build.

Use `--json` and report the output path plus, after `fill`, re-run `fields` on the output to show the user the filled values. Exit code 4 means the PDF has no AcroForm (a flat/scanned form) — suggest `carrel ocr` to get text and a `build`-generated form instead.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
