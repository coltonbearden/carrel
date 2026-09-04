---
description: Add, remove, list, or find-by tags on local files in the carrel desk database
argument-hint: <add|rm|ls|find> <file/tags>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: tag
---

Handle this tagging request: $ARGUMENTS

Run the carrel CLI via Bash. `carrel tag` is a group; map the user's request onto the real subcommands and flags in the `--help` blocks below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel tag --help` differs, trust the installed version — never invent flags). Tags live in the desk db (`.carrel/carrel.db` under the global `--root`, default cwd):

<!-- usage:start -->
```text
Usage: carrel tag [OPTIONS] COMMAND [ARGS]...

  Tag files in the desk db (.carrel/carrel.db under --root).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.

Commands:
  add   Add TAG...
  find  List files carrying ALL of TAG...
  ls    List tags of PATH, or (without PATH) every tag with its file count.
  rm    Remove TAG...
```

```text
Usage: carrel tag add [OPTIONS] PATH TAGS...

  Add TAG... to PATH (registers the file in the desk db if needed).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel tag find [OPTIONS] TAGS...

  List files carrying ALL of TAG... (paths relative to the desk root).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel tag ls [OPTIONS] [PATH]

  List tags of PATH, or (without PATH) every tag with its file count.

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```

```text
Usage: carrel tag rm [OPTIONS] PATH TAGS...

  Remove TAG... from PATH (unknown tags/files are a quiet no-op).

Options:
  --json  Machine-readable JSON output.
  --help  Show this message and exit.
```
<!-- usage:end -->

- Choose the subcommand from intent: "tag X as invoice" → `add`, "what's tagged urgent" → `find`, "untag" → `rm`, "what tags exist" → `ls`.
- `add` registers the file in the desk db if needed; `rm` on unknown tags/files is a quiet no-op.
- `find` returns paths relative to the desk root; ANDs multiple tags.
- If the user's desk is elsewhere, put `--root DIR` before `tag` (`carrel --root DIR tag add ...`).

Report what changed (or list the results) conversationally. Tags combine well with `/carrel-inspect:search --tag` for filtered full-text search, and `/carrel-agent:catalog` exports/imports them — mention that when relevant.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
