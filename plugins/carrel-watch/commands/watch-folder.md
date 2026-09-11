---
description: Watch a folder and run carrel actions (thumbnail, index, convert...) whenever files appear or change
argument-hint: <folder> [event/glob] [action to run]
allowed-tools: Bash(carrel:*), Bash(uv run carrel:*), Bash(command -v carrel)
carrel-command: watch
---

Set up a folder watch for: $ARGUMENTS

Run the carrel CLI via Bash. Map the user's request onto the real flags in the `--help` block below (regenerated from the CLI by `scripts/sync_plugins.py`; if the installed `carrel watch --help` differs, trust the installed version — never invent flags):

<!-- usage:start -->
```text
Usage: carrel watch [OPTIONS] DIRECTORY

  Watch DIRECTORY and run shell actions on file events.

  Events for files an action is currently producing are suppressed via an in-flight set plus an
  output-name heuristic (outputs whose name starts with the source file's stem); other action
  outputs written into the watched directory WILL re-trigger — write outputs elsewhere or use --glob
  to narrow matches. --stable waits for a file to stop growing, --existing processes what is already
  there, --poll works where inotify does not (/mnt/c, shares), --done-dir/--error-dir file sources
  away after their actions, --log keeps a JSON trail. Ctrl-C exits cleanly.

  --done-dir/--error-dir refuse to start (exit 2) when they would move files git is tracking;
  --force overrides. Actions themselves are never guarded — what a --run command does is the user's
  business.

Options:
  --on EVENTS                     Comma-separated events to react to: created, modified, deleted,
                                  moved, existing.  [default: created,modified]
  --glob PATTERN                  Only react to file names matching this glob (e.g. '*.pdf').
  --run CMD                       Shell action to run per event; repeatable, runs in order. {path},
                                  {name}, {stem}, {ext}, {dir} are substituted (shell-quoted).
                                  [required]
  --recursive                     Watch subdirectories too.
  --existing                      Queue the files already in DIRECTORY at start (event 'existing').
  --stable SECS                   Act only once a file's size and mtime have not changed for SECS
                                  (scanners, big copies).  [x>0]
  --stable-timeout SECS           With --stable: give up waiting and act after SECS regardless.
                                  [x>0]
  --poll                          Poll instead of inotify (needed on /mnt/c, network shares, some
                                  containers).
  --poll-interval SECS            With --poll: how often to scan.  [default: 1.0; x>0]
  --done-dir DIRECTORY            Move each source here after its actions all succeed.
  --error-dir DIRECTORY           Move each source here after an action fails.
  --log FILE                      Append one JSON record per action (and per move) to FILE.
  --force                         With --done-dir/--error-dir: move files even when git tracks them.
  --print-service [systemd|schtasks]
                                  Print a service definition that runs this exact watch at login,
                                  then exit.
  --debounce MS                   Coalesce events per path within this window.  [default: 500; x>=0]
  --once                          Exit after the first triggered action batch.
  --timeout SECS                  Hard stop after SECS seconds.  [x>0]
  --action-timeout SECS           Kill an action that runs longer than SECS (logged as rc=124).
                                  [default: 300.0; x>0]
  --json-lines                    Log one JSON object per action to stdout instead of human lines
                                  (--json implies this).
  --json                          Machine-readable JSON output.
  --help                          Show this message and exit.
```
<!-- usage:end -->

- `--on`: comma-separated events (created, modified, deleted, moved); default `created,modified`.
- `--glob`: only react to matching filenames.
- `--run CMD` (required; repeatable, runs in order): the action; `{path}`, `{name}` and `{dir}` are substituted (shell-quoted for you).
- `--once`: exit after the first triggered action batch — use for demos/tests. `--timeout SECS`: hard stop. `--action-timeout SECS`: kill a runaway action (logged as rc=124).
- `--debounce MS` (default 500): coalesce editor save-storms. `--json-lines`: machine-readable event log on stdout.

Example: `carrel watch DIR --on created --glob '*.pdf' --run 'carrel thumb {path} --out-dir thumbs'`.

Important: **this is a long-running foreground process.** Run it via Bash in the background (or with `--timeout`/`--once` for a bounded demo), tell the user how it will keep running and that Ctrl-C/`kill` stops it cleanly. Outputs written into the watched directory can re-trigger the watch — write them elsewhere or narrow `--glob`. Suggest recipes from this plugin's `watch-automation` skill (auto-thumb, auto-index, auto-convert drop folders). Report the watch config back: directory, events, glob, action(s).

**Requires the carrel CLI on PATH.** If `carrel` is not found, tell the user to install it with `uv tool install carrel` (see the repo's INSTALL notes), or run it as `uv run carrel ...` from the carrel repo root.
