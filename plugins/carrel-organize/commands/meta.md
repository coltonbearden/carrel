---
description: Set, read, remove, find by, or export typed key/value fields (vendor, total, due date, status) on local files in the carrel desk database
argument-hint: <set|get|ls|rm|find|export> <file/fields/conditions>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: meta
---

Handle this file-metadata request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel meta` is a group; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel meta --help` differs, trust the installed version — never invent flags). Fields live in the desk db (`.carrel/carrel.db` under the global `--root`, default cwd), next to tags and notes:

<!-- usage:start -->
```text
Usage: carrel meta [OPTIONS] COMMAND [ARGS]...

  Typed key/value fields on desk files (.carrel/carrel.db under --root).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  export  Export every file's fields as a table: one row per file, one column per key.
  find    List files whose fields satisfy every CONDITION (paths relative to the desk root).
  get     Print one field of PATH (its value alone in human mode; null when absent).
  ls      List PATH's fields with kind/source, or (without PATH) every key with its file count.
  rm      Remove KEY...
  set     Set KEY=VALUE...
```

```text
Usage: carrel meta export [OPTIONS]

  Export every file's fields as a table: one row per file, one column per key.

  Without -o the table goes to stdout as CSV (or as JSON rows with --json); with -o a summary is
  printed instead. Rows are sorted by path, columns by key (or as given with --key); a missing field
  is empty. Exit 4 when no desk db exists under --root.

Options:
  --key KEY       Only these columns, in this order (repeatable).
  -o, --out FILE  Write to FILE (.json → JSON rows, anything else → CSV) instead of stdout.
  --force         Overwrite an existing --out file.
  --json          Machine-readable JSON output.
  --help          Show this message and exit.
```

```text
Usage: carrel meta find [OPTIONS] CONDITION...

  List files whose fields satisfy every CONDITION (paths relative to the desk root).

  A condition is KEY OP VALUE with OP one of = != > >= < <= ~ (contains), or KEY? (has the field):
  `vendor=acme`, `total>1000`, `due<2026-11` (ISO dates compare chronologically, so a year-month
  prefix works), `invoice_no~2026`, `paid?`. Numbers compare numerically, text case-insensitively.
  JSON: [{path, meta: {key: value}}].

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel meta get [OPTIONS] PATH KEY

  Print one field of PATH (its value alone in human mode; null when absent).

Options:
  --fail-empty  Exit 5 when PATH has no such field.
  --json        Machine-readable JSON output.
  --help        Show this message and exit.
```

```text
Usage: carrel meta ls [OPTIONS] [PATH]

  List PATH's fields with kind/source, or (without PATH) every key with its file count.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel meta rm [OPTIONS] PATH KEYS...

  Remove KEY... from PATH (unknown keys/files are a quiet no-op).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel meta set [OPTIONS] PATH KEY=VALUE...

  Set KEY=VALUE... on PATH (registers the file in the desk db if needed).

Options:
  --kind [str|num|date|bool]  Force the kind of every field in this call (default: inferred —
                              true/false → bool, 1234.5 → num, an ISO YYYY-MM-DD date → date, else
                              str; digits with a leading zero such as 02134 stay str).
  --source TEXT               Who is writing the field (automation should pass its own name).
                              [default: user]
  --json                      Machine-readable JSON output.
  --help                      Show this message and exit.
```
<!-- usage:end -->

- Choose the subcommand from intent: "record that X is from Acme and totals 1,234.50" → `set X vendor="Acme" total=1234.50`; "what's the due date on X" → `get X due`; "which files are over 1000 / unpaid / due before November" → `find total>1000`, `find paid=false`, `find due<2026-11-01`; "give me a spreadsheet of these fields" → `export -o fields.csv`.
- Kinds are inferred (`1234.5` → num, `2026-10-01` → date, `true` → bool) so `find` compares numbers numerically and dates chronologically; use `--kind str` to keep a zip code's leading zero.
- `find` conditions AND together: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (contains), `KEY?` (has the field).
- `/carrel-finance:refs --tag` writes `ref:<kind>:<value>` *tags* (not fields); fields and tags combine in `/carrel-inspect:search --tag ... --meta ...`. `/carrel-agent:catalog` exports and imports fields together with tags and notes.
- If the user's desk is elsewhere, put `--root DIR` before `meta` (`carrel --root DIR meta set ...`).

Report what changed (or list the results) conversationally. Fields combine with `/carrel-inspect:search --meta CONDITION` for filtered full-text search — mention that when relevant.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
