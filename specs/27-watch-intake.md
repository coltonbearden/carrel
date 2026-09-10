# spec: watch v2 + intake — the inbox that files itself

**Owns:** `src/carrel/commands/watch.py` (flags), new `src/carrel/commands/intake.py` (PR D), `tests/test_fields_rename_batch.py` (watch v2 part), `tests/test_intake.py` (PR D), `plugins/carrel-watch/commands/{watch-folder,intake}.md`, `plugins/carrel-watch/skills/watch-automation/SKILL.md`.
**Wave:** v0.4.0, PR C (watch), PR D (intake).

## watch v2
- `--recursive` (observer descends), `--existing` (files present at start are queued with event type `existing`, regardless of `--on`; `EVENT_TYPES` gains `existing`), `--stable SECS` (a due path is acted on only once its size and mtime have not changed for SECS; `deleted` events pass straight through; `--stable-timeout SECS` gives up waiting), `--poll` / `--poll-interval SECS` (watchdog `PollingObserver` — inotify never fires on `/mnt/c`, network shares and some containers), `--done-dir DIR` / `--error-dir DIR` (after all actions: rc 0 everywhere → done, else error; collision-safe `fsops.move_file` with the desk row following; the moved path is suppressed for two seconds so the watcher does not re-trigger on its own move), `--log FILE` (one JSON record per action and per move, with a `time` stamp, regardless of stdout mode), `--print-service systemd|schtasks` (prints a user unit / a `schtasks /Create` line that re-runs this exact invocation without `--print-service`, then exits 0).
- Substitutions gain `{stem}` and `{ext}` (core/actions).

## intake (PR D)
`carrel intake INBOX --to DEST [--apply] [--watch] [--once] [--timeout] [--glob] [--stable SECS] [--template T] [--by ym|period|flat] [--fiscal-start MM] [--ocr/--no-ocr] [--refs/--no-refs] [--index/--no-index] [--tag TAG]* [--date-order] [--fail-empty]` — see the plan (D-014): settle → detect → OCR if scanned and ocrmypdf is present → fields → refs → name (rename's `build_name`) → `DEST/YYYY/MM` or `FY{yyyy}/Q{n}` → `move_file` → index/meta/tags when a desk exists under `--root` (default DEST). Dry-run default; per-file JSON records.

## Acceptance (watch v2)
- `--existing --stable 0.2 --done-dir --error-dir --log` on an inbox with a good and a bad file: both are processed, land in done/err respectively, the log has action and `filed` records, and a tag on the good file follows it to `done/`.
- `--existing` without `--recursive` ignores a nested file; with `--recursive --poll` it is processed and the banner says `polling`.
- `--print-service systemd` starts with the install comment and contains `ExecStart=` with the original flags minus `--print-service`; `schtasks` prints a `schtasks /Create /SC ONLOGON` line.
- `--stable-timeout` without `--stable` is a usage error; `_Watcher.drain` defers a growing file and releases it after the settle window (or the timeout).
