---
description: Watch a folder and run carrel actions (thumbnail, index, convert...) whenever files appear or change
argument-hint: <folder> [event/glob] [action to run]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
---

Set up a folder watch for: $ARGUMENTS

Run the carrel CLI via Bash. **First run `carrel watch --help`** to confirm the exact flags available in the installed version, then map the user's request onto them — never invent flags. The expected interface is:

```
carrel watch DIR --on created,modified [--glob '*.pdf'] --run 'carrel thumb {path} --out-dir thumbs'
             [--debounce 500] [--once] [--timeout SECS] [--json-lines]
```

- `--on`: comma-separated events (created, modified, deleted, moved).
- `--glob`: only react to matching filenames.
- `--run CMD` (repeatable, runs in order): the action; `{path}` is replaced with the triggering file (shell-quoted for you).
- `--once`: exit after the first triggered action — use for demos/tests. `--timeout SECS`: hard stop.
- `--json-lines`: machine-readable event log on stdout.

If `carrel watch --help` reports that the command does not exist, the installed carrel predates it — say so instead of guessing flags.

Important: **this is a long-running foreground process.** Run it via Bash in the background (or with `--timeout`/`--once` for a bounded demo), tell the user how it will keep running and that Ctrl-C/`kill` stops it cleanly. Suggest recipes from this plugin's `watch-automation` skill (auto-thumb, auto-index, auto-convert drop folders). Report the watch config back: directory, events, glob, action(s).

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
