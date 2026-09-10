---
description: File an inbox of documents with the carrel CLI — read each document's fields, name it, move it into dated folders, index it and tag it with its reference numbers
argument-hint: <inbox folder> --to <archive folder> [--apply] [--watch]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: intake
---

Handle this filing request: $ARGUMENTS

Run the carrel CLI via Bash. Map the request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel intake --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel intake [OPTIONS] INBOX

  File everything waiting in INBOX into --to, named after what the documents say.

  Per file: read its fields (vendor, invoice number, dates, totals), find its reference numbers,
  build a name from the --template, move it into --to/YYYY/MM (or FY<year>/Q<n> with --by period),
  then re-index it, save the fields as desk metadata and tag it with every reference — all against
  the desk under the global --root (default: --to).

  Scanned PDFs are OCRed into a searchable copy which becomes the filed document; the untouched
  original moves to --to/_originals. Nothing is overwritten (colliding names get -1, -2, … suffixes)
  and nothing is deleted. JSON: [{src, dest, action: plan|filed|skip|error, fields, refs, tags, ocr,
  reason}]. Exit 3 when a missing optional binary is the reason nothing could be read at all, 1 when
  some files errored during --apply, 5 with --fail-empty when there was nothing to file.

Options:
  --to DIRECTORY          Where filed documents land (created if missing).  [required]
  --apply / --dry-run     Perform the intake. Default is a dry-run that only prints the plan.
  --watch                 Keep watching INBOX and file what arrives (implies --apply; refuses --dry-
                          run).
  --once                  With --watch: stop after the first batch.
  --timeout SECS          With --watch: stop after SECS.  [x>0]
  --glob PATTERN          Only take files whose name matches (e.g. '*.pdf').
  --recursive             Take files from subdirectories of INBOX too.
  --stable SECS           With --watch: wait until a file's size and mtime hold still for SECS.
                          [default: 2.0; x>0]
  --template TEXT         Name template (see `carrel rename --help` for the placeholders).
                          [default: {date}_{vendor}_{ref}{ext}]
  --by [ym|period|flat]   Folder layout under --to: ym = YYYY/MM, period = FY<year>/Q<n>, flat = no
                          subfolders.  [default: ym]
  --fiscal-start MM       With --by period: the month the fiscal year starts in.  [default: 1;
                          1<=x<=12]
  --date-order [mdy|dmy]  How to read an ambiguous slashed date in the document.  [default: mdy]
  --ocr / --no-ocr        Force or forbid OCR of scanned PDFs. Default: OCR them when ocrmypdf is
                          installed.
  --refs / --no-refs      Find reference numbers and tag the filed file with them.  [default: refs]
  --index / --no-index    Re-index the filed file in the desk under --root.  [default: index]
  --tag TAG               Extra tag for every filed file (repeatable).
  --fallback TEXT         Use TEXT for a name placeholder that has no value instead of skipping the
                          file.
  --fail-empty            Exit 5 when no file was filed (or planned).
  --json                  Machine-readable JSON output.
  --help                  Show this message and exit.
```
<!-- usage:end -->

- **Always dry-run first** (`carrel --json intake INBOX --to DEST`) and show the user the plan: which files would be filed where, and every `skip` with its reason (usually a name placeholder with no value — offer `--fallback`). Only add `--apply` once they have seen it.
- One pass does the lot per file: fields (vendor, invoice number, dates, totals) → reference numbers → name from `--template` (default `{date}_{vendor}_{ref}{ext}`) → move into `--to/YYYY/MM` (`--by period` gives `FY<year>/Q<n>`, with `--fiscal-start MM`) → index, save the fields as desk metadata, tag with every `ref:<kind>:<value>`.
- Nothing is destroyed: scanned PDFs are OCRed into a searchable copy that becomes the filed document while the untouched original moves to `--to/_originals`; colliding names get `-1`, `-2`, … suffixes. Without ocrmypdf the scan is filed as-is and the record says `ocr: "unavailable"`.
- `--apply` maintains a desk at `--to` (or the global `--root`), so afterwards `carrel --root DEST search`, `meta find total>1000` and `tag find ref:invoice:...` all work — say so when reporting.
- `--watch` keeps filing what arrives (`--once`/`--timeout` bound it for a test run; `--stable SECS` waits for slow scanners and cloud sync to finish writing).

Report what was filed (or would be), the skips with reasons, and the follow-up queries the user can now run. Confirm before `--apply` on a folder you did not just dry-run.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
