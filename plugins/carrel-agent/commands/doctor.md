---
description: Report what the carrel environment can do — installed optional binaries with versions, per-command ok/degraded/unavailable status, and install hints for what is missing
argument-hint: [what you are trying to do]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: doctor
---

Check the carrel environment: $ARGUMENTS

Run the carrel CLI via Bash. The command takes no arguments beyond `--json` (the `--help` block below is regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel doctor --help` differs, trust the installed version):

<!-- usage:start -->
```text
Usage: carrel doctor [OPTIONS]

  Report environment health: adapters found, versions, per-command capability.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```
<!-- usage:end -->

Always run `carrel --json doctor` and read the report:

- `product.version`, `python`: what is installed.
- `adapters[]`: every optional binary carrel knows about — `found`, `path`, `version`, and an `install_hint` when absent (e.g. `sudo apt install tesseract-ocr`).
- `commands[]`: per carrel command a `status` of `ok`, `degraded` (works with reduced power; `optional` binaries missing) or `unavailable` (a `requires` binary or Python extra is missing), plus `missing` and a `note`.
- `icc_dirs`, `tesseract_langs`: color-profile directories found and OCR languages installed.

Answer the user's actual question: if they asked "can I OCR / convert docx / narrate a PDF", quote that command's status and the exact install hint for whatever is missing rather than dumping the whole table. If they asked generally, summarize: N commands ok / degraded / unavailable, then the two or three most valuable missing binaries with their hints. `doctor` is read-only and always exits 0.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
