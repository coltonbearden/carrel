---
description: Add, remove, list, or find-by tags on local files in the carrel desk database
argument-hint: <add|rm|ls|find> <file/tags>
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Handle this tagging request: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto these real subcommands of `carrel tag` (verify with `carrel tag --help` if unsure — never invent flags). Tags live in the desk db (`.carrel/carrel.db` under the global `--root`, default cwd):

```
carrel [--root DIR] tag add PATH TAGS...    # tag a file (registers it in the desk db if needed)
carrel [--root DIR] tag rm PATH TAGS...     # remove tags (unknown tags/files are a quiet no-op)
carrel [--root DIR] tag ls [PATH]           # tags of PATH, or every tag with its file count
carrel [--root DIR] tag find TAGS...        # files carrying ALL of the given tags
```

- Choose the subcommand from intent: "tag X as invoice" → `add`, "what's tagged urgent" → `find`, "untag" → `rm`, "what tags exist" → `ls`.
- `find` returns paths relative to the desk root; ANDs multiple tags.
- If the user's desk is elsewhere, put `--root DIR` before `tag`.

Report what changed (or list the results) conversationally. Tags combine well with `/carrel-inspect:search --tag` for filtered full-text search — mention that when relevant.

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
