---
name: watch-automation
description: Recipes for automating folders with carrel watch — auto-thumbnail new images, auto-index documents into the desk db, auto-convert a drop folder. Use when the user wants something to happen automatically whenever files land in or change inside a directory.
---

# Folder automation recipes with `carrel watch`

`carrel watch DIR --on EVENTS --run CMD` runs shell actions on file events (watchdog-based). `{path}` in the action is substituted with the triggering file, already shell-quoted. Multiple `--run` flags execute in order. `--debounce MS` collapses editor save-storms. Use `--once` or `--timeout SECS` for bounded test runs, `--json-lines` for machine-readable logs. Ctrl-C exits cleanly.

Before composing a recipe, run `carrel watch --help` to confirm the installed version has the flags you plan to use.

## Recipe: auto-thumbnail new images

```bash
carrel watch ~/Pictures/incoming --on created --glob '*.png' \
  --run 'carrel thumb {path} --out-dir ~/Pictures/thumbs'
```

Add a second `--glob`-less watch or broaden the glob for jpg. Thumbnails land in `--out-dir`; the watch ignores files its own actions write.

## Recipe: auto-index documents into the desk db

Keep `carrel search` results fresh as files arrive:

```bash
carrel watch ~/Documents/desk --on created,modified \
  --run 'carrel --root ~/Documents/desk index --update {path} --if-indexed'
```

`--update` (re)indexes just the touched file; `--if-indexed` makes it a silent no-op until someone has run `carrel index` once — safe to leave running.

## Recipe: auto-convert a drop folder

Everything dropped as markdown comes out as PDF:

```bash
carrel watch ~/dropbox/md-in --on created --glob '*.md' \
  --run 'carrel convert {path} --to pdf --out-dir ~/dropbox/pdf-out'
```

Chain steps with repeated `--run` (they execute sequentially per event), e.g. convert then index the output directory.

## Recipe: file an inbox instead of scripting it

When the actions would be "read the document, name it, move it, index it", use `carrel intake` — one command instead of a `--run` chain, and it never overwrites or deletes:

```bash
carrel intake ~/inbox --to ~/archive                       # dry-run: the plan
carrel intake ~/inbox --to ~/archive --apply --stable 5    # file what is there
carrel intake ~/inbox --to ~/archive --watch --stable 5    # keep filing arrivals
```

`--stable SECS` waits for scanners and cloud sync to finish writing; `--by period --fiscal-start 7` files into `FY2027/Q1`; scans are OCRed into a searchable copy with the original kept under `_originals/`.

## Recipe: survive reboots and network shares

```bash
carrel watch ~/inbox --run 'carrel index --update {path} --if-indexed' --print-service systemd > ~/.config/systemd/user/carrel-watch.service
systemctl --user daemon-reload && systemctl --user enable --now carrel-watch
```

`--print-service systemd|schtasks` prints a service definition that re-runs the exact watch you just composed. On `/mnt/c`, network shares and some containers inotify never fires — add `--poll` (with `--poll-interval SECS`) and the watcher scans instead.

## Operational notes

- Long-running: start it in the background (`&`, tmux, or the unit `--print-service systemd` prints) and tell the user how to stop it.
- Debounce editors: `--debounce 500` (ms) avoids double-firing on save; `--stable SECS` is the stronger guard for files that arrive slowly (scanners, large copies, OneDrive).
- `--existing` processes what is already in the folder at start; `--recursive` descends; `--done-dir`/`--error-dir` file each source away after its actions, and `--log FILE` keeps a JSON trail of every action and move.
- Self-triggering is guarded (in-flight outputs are ignored), but keep action outputs out of the watched glob when possible — e.g. write thumbs to a sibling directory.
- Test any recipe first with `--once --timeout 30` and a `touch` in another shell.
