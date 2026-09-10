# spec: rename + batch — names from documents, actions over many files

**Owns:** new `src/carrel/core/fsops.py`, new `src/carrel/core/actions.py`, new `src/carrel/commands/rename.py`, new `src/carrel/commands/batch.py`, `src/carrel/core/db.py` (`rename_path`), `src/carrel/commands/organize.py` (moves through fsops), `src/carrel/commands/watch.py` (imports actions; keeps `_render`/`_due` aliases), `pyproject.toml` (per-file ignore moves to `core/actions.py`), `tests/test_fields_rename_batch.py`, `plugins/carrel-organize/commands/{rename,batch}.md`.
**Wave:** v0.4.0, PR C.

## core/fsops.py
`uncollide(dest, taken)` (the `organize` rule, now shared) and `move_file(src, dest, *, desk_root)`: parents created, `os.replace` then `shutil.move` across filesystems, never overwrites (`FileExistsError`), and when a desk exists under `desk_root` the row follows through `DeskDB.rename_path(old, new)` (files.path and the FTS row's path; a stale row already at `new` is dropped). `organize --apply` uses it, which fixes the pre-v0.4.0 bug where a move orphaned a file's tags and notes.

## core/actions.py (D-013)
`quote`, `render` (`{path} {name} {stem} {ext} {dir}`), `run_action`, `kill_tree` moved verbatim from `watch.py`; `watch` re-exports them under the old private names for its tests. `batch` is the second and last user of `shell=True`.

## rename.py
`carrel rename PATH... [--template T] [--apply] [--date-order] [--fallback TEXT] [--lower] [--max-len N] [--ocr]`, default template `{date}_{vendor}_{ref}{ext}`.
- `build_name(path, template, *, fields, meta, refs, fallback, lower, max_len) -> (name, {placeholder: source})`; placeholders `{date}` / `{date:%Y-%m}` / `{yyyy}` / `{mm}` (fields.date → meta.date → mtime), `{vendor}`, `{total}` (fields → meta), `{ref}` (fields.invoice_no → first `find_refs` value), `{fields.NAME}`, `{meta.KEY}`, `{type}`, `{stem}`, `{name}`, `{ext}` (dot kept), `{sha8}`. Values slugified (`[A-Za-z0-9._-]`, runs of anything else → `_`); unknown placeholder → `CarrelInputError` (exit 2 at the CLI); unresolved → `UnresolvedPlaceholderError` → the file is skipped with the reason unless `--fallback`.
- `plan_renames` walks like `refs`, reads fields once per file, reads desk meta once, renders, `uncollide`s within the plan, and never aborts on one bad file (its entry becomes a `skip`). A file already named that way is a `skip` too.
- `--apply` moves in place via `fsops.move_file(desk_root=--root)`. JSON: `[{src, dest, action: rename|renamed|skip, reason?, sources?}]`.

## batch.py
`carrel batch PATH... --run CMD... [--glob G] [--type T,T] [--recursive/--no-recursive] [--jobs N] [--dry-run] [--manifest F.jsonl] [--resume] [--fail-fast] [--action-timeout SECS] [--fail-empty] [--json-lines]`.
- Files: explicit files; directories walked like `index` (hidden and `.gitignore`d skipped; `--no-recursive` = top level only); every regular file is a candidate, `--glob` filters names, `--type` filters detected types (`code` included).
- Per file the templates run in order and stop at the first non-zero rc; record `{path, runs, cmd, rc, stdout, stderr (each capped at 16 KiB, `truncated` flag), seconds, ok, time}`. `--jobs N` runs files concurrently (ThreadPool); results keep input order. `--manifest` appends every record; `--resume` skips files whose last record succeeded with the same `runs`. `--dry-run` prints the rendered commands (JSON: `{path, cmds}` lines). `--fail-fast` stops scheduling after the first failure.
- Output: `--json` one object `{summary: {total, ran, ok, failed, skipped, seconds}, results: [...]}`; `--json-lines` streams records then `{summary}`; human `[ok]`/`[FAIL]` lines and a totals line. Exit 0 all ok; 1 any failed; 2 bad template (no placeholder), `--resume` without `--manifest`, unknown `--type`; 4 missing path; 5 nothing matched with `--fail-empty`.

## Acceptance
- `rename` on the invoice fixture plans `2026-09-10_ACME_Corp_INV-2026-0042.txt`; a note without a reference is skipped with `no value for {ref}`; `--apply --fallback misc --lower` renames both and `tag find` returns the new name; two identical invoices get `-1` suffixes.
- `move_file` carries tags, meta and the FTS row; `organize --apply` keeps a tagged PDF findable at `pdf/doc.pdf`.
- `batch` over a three-file tree with `--run 'echo {name}' --run 'test {ext} != .json' --jobs 2` exits 1 with two ok and one failed record in input order; `--manifest` + `--resume` skips the two; `--dry-run` prints commands; `--json-lines` ends with a summary line; a 0.3 s `--action-timeout` yields rc 124.
- `carrel watch --help` still shows `{path}`; `tests/test_watch_org_dedupe.py` passes unchanged.
