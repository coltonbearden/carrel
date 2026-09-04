---
description: Attach sidecar notes to local files (carrel desk db) or annotations to PDF pages
argument-hint: <file> <note text> | list notes for <file>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Handle this file-note request: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real subcommands of `carrel note` (verify with `carrel note --help` if unsure — never invent flags):

```
carrel [--root DIR] note add PATH TEXT      # sidecar note, stored in the desk db (any file type)
carrel [--root DIR] note ls PATH            # list PATH's sidecar notes, newest first
carrel note pdf PATH                        # list a PDF's annotations: page, subtype, contents
carrel note pdf-add PATH TEXT ...           # add TEXT as a FreeText annotation to a PDF page
```

- Sidecar notes (`add`/`ls`) work for any file and never modify it — the note lives in `.carrel/carrel.db` under the global `--root` (default cwd).
- PDF annotations (`pdf`/`pdf-add`) live inside the PDF itself. Run `carrel note pdf-add --help` first to confirm its page/position options before using them.
- Choose from intent: "note on this file" → `add`; "what did I note" → `ls`; "annotate this PDF / what's highlighted" → the `pdf` variants.

Quote TEXT carefully in Bash. Afterwards confirm what was attached, or present the listed notes/annotations with their timestamps/pages.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
