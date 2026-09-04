---
description: Attach sidecar notes to local files (carrel desk db) or annotations to PDF pages
argument-hint: <file> <note text> | list notes for <file>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: note
---

Handle this file-note request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel note` is a group; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel note --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
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

```text
Usage: carrel note add [OPTIONS] PATH TEXT

  Attach TEXT as a sidecar note to PATH (stored in the desk db).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel note ls [OPTIONS] PATH

  List PATH's sidecar notes, newest first (ISO timestamps).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel note pdf [OPTIONS] PATH

  List PATH's PDF annotations: page, subtype, contents.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

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
<!-- usage:end -->

- Sidecar notes (`add`/`ls`) work for any file and never modify it — the note lives in `.carrel/carrel.db` under the global `--root` (default cwd; `carrel --root DIR note add ...`).
- PDF annotations (`pdf`/`pdf-add`) live inside the PDF itself. `pdf-add` writes `PATH.annotated.pdf` by default; pass `-o PATH` only when the user explicitly wants the original annotated in place. `--page` is 1-based, `--pos X,Y` is the lower-left corner in PDF points.
- Choose from intent: "note on this file" → `add`; "what did I note" → `ls`; "annotate this PDF / what's highlighted" → the `pdf` variants.

Quote TEXT carefully in Bash. Afterwards confirm what was attached, or present the listed notes/annotations with their timestamps/pages.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
