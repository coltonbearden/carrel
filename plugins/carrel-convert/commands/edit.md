---
description: Edit files non-destructively with the carrel CLI — merge/split/rotate/decrypt PDFs, resize/crop/strip images, find-and-replace in text, set/delete JSON values by dotted path
argument-hint: <file> <what to change> [output path]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: edit
---

Edit the file the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. `carrel edit` is a group with four subcommands — `pdf`, `image`, `text`, `json`. Pick the one matching the file type and intent, then map the request onto the real flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel edit <sub> --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
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
<!-- usage:end -->

Choosing the subcommand:

- **pdf**: merge (`--merge` repeatable, appended after SRC in order), split into one file per page (`--split`, `-o` is then a directory), keep pages (`--pages '1-3,7'`), rotate, `--linearize` (qpdf), `--decrypt PW` (qpdf). Pipeline order is decrypt → merge → pages → rotate → write → linearize.
- **image**: `--crop X,Y,W,H`, `--resize WxH|N%`, `--rotate DEG` (applied crop → resize → rotate), `--strip` EXIF, `--quality` for JPEG/WebP.
- **text**: `--find` / `--replace` (`--regex` for Python regex). It **requires** either `-o OUT` or an explicit `-i/--in-place` — it never rewrites SRC silently. Only pass `-i` when the user clearly asked to change the file itself.
- **json**: `--set a.b.0.c=VALUE` (VALUE parsed as JSON, string fallback; repeatable) and `--del PATH` (applied after `--set`).

Every subcommand writes next to the source by default (`SRC.edited.<ext>`, or `SRC-pages/` for `--split`) and refuses to overwrite without `--force` — only pass `--force` when the user explicitly wants that. Use `--json` and report the output path(s) and what changed; verify with `carrel inspect OUT --json` when the edit was nontrivial (page count after merge/split, dimensions after resize). Exit code 3 means qpdf (or another optional binary) is missing — relay the install hint from stderr. Exit code 4 means the input is missing or of the wrong type for that subcommand.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
