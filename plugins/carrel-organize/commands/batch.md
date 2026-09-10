---
description: Run a command over many local files with the carrel CLI — parallel jobs, a resumable manifest, dry-run — using {path}/{name}/{stem}/{ext}/{dir} substitutions
argument-hint: <folder> --run 'carrel convert {path} --to txt' [--glob '*.pdf'] [--jobs 4]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: batch
---

Run the bulk task the user asked about: $ARGUMENTS

Run the carrel CLI via Bash. Map the request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel batch --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel batch [OPTIONS] PATHS...

  Run --run actions over every file in PATH... (files, or directories walked like `index`).

  Exit 0 when every file succeeded, 1 when any failed (its record carries the rc, stdout and
  stderr), 5 with --fail-empty when nothing matched. JSON output is {"summary": {total, ran, ok,
  failed, skipped, seconds}, "results": [{path, cmd, rc, stdout, stderr, seconds, ok}]} (cmd/rc are
  the failing or last action's, stdout/stderr every action's output in order); --json-lines streams
  the records instead. --manifest + --resume make a long run restartable.

Options:
  --run CMD                     Shell action per file; repeatable, runs in order, stops at the first
                                failure. Substituted (shell-quoted): {path}, {name}, {stem}, {ext},
                                {dir}.  [required]
  --glob PATTERN                Only files whose name matches (e.g. '*.pdf').
  --type T1,T2                  Only these detected types (pdf, md, eml, code, …).
  --recursive / --no-recursive  Walk directories (hidden and .gitignored entries skipped).
                                [default: recursive]
  --jobs INTEGER RANGE          Files to process in parallel.  [default: 1; x>=1]
  --dry-run                     Print the rendered commands without running anything.
  --manifest FILE               Append one JSON record per file to this file.
  --resume                      Skip files whose last --manifest record succeeded with the same
                                --run set.
  --fail-fast                   Stop after the first failing file.
  --action-timeout SECS         Kill an action that runs longer than SECS (rc=124).  [default:
                                300.0; x>0]
  --fail-empty                  Exit 5 when no file matched.
  --json-lines                  Stream one JSON record per file as it completes, then a summary
                                line.
  --json                        Machine-readable JSON output.
  --help                        Show this message and exit.
```
<!-- usage:end -->

- Compose the action with the same placeholders as `watch`: `--run 'carrel convert {path} --to txt --out-dir OUT'`; repeated `--run` flags run in order per file and stop at the first failure. `{path}`, `{name}`, `{stem}`, `{ext}` and `{dir}` are shell-quoted for you.
- **Dry-run first for anything that writes or deletes** (`--dry-run` prints every rendered command); narrow with `--glob '*.pdf'` / `--type pdf,docx`; parallelise read-only work with `--jobs 4`.
- Long runs: `--manifest run.jsonl` records every file; `--resume` skips what already succeeded, so a run can be restarted after a crash or a fixed binary. `--fail-fast` stops at the first failure; `--action-timeout` bounds each action.
- Exit 1 means at least one file failed — read its `rc`/`stderr` from `--json` and report which files, not just the count. Exit 5 with `--fail-empty` when nothing matched.

Report the summary (ok/failed/skipped) and list failures with their error text. Never `rm`, overwrite or move in an action without an explicit, confirmed request.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
