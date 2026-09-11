"""carrel batch — run a shell action over many files, with a manifest you can resume.

The action language is `watch`'s: `--run 'carrel convert {path} --to txt'`
with `{path}`, `{name}`, `{stem}`, `{ext}` and `{dir}` substituted and
shell-quoted (core.actions, D-013). Repeated `--run` flags execute in order
per file and stop at the first non-zero exit. Directories are walked like
`index` (hidden and .gitignored entries skipped; every regular file is a
candidate, narrow with --glob / --type). `--jobs N` runs files in parallel;
`--manifest FILE` appends one JSON record per file so `--resume` can skip
what already succeeded; `--dry-run` prints the rendered commands only.
"""

from __future__ import annotations

import fnmatch
import json
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import click

from carrel.core.actions import PLACEHOLDERS, render, run_action
from carrel.core.filetypes import FileType, detect
from carrel.core.output import CarrelInputError, ExitCode, fail, handled, root_of

OUTPUT_CAP = 16 * 1024  # bytes of stdout/stderr kept per record


def _walk_files(top: Path, recursive: bool, root: Path | None) -> Iterator[Path]:
    from carrel.commands.index import _walk
    from carrel.core.ignore import ancestor_ignores

    if not recursive:
        yield from sorted(
            (p for p in top.iterdir() if p.is_file() and not p.name.startswith(".")),
            key=lambda p: p.name,
        )
        return
    yield from _walk(top, ancestor_ignores(top.resolve(), root))


def collect_files(
    paths: Sequence[Path | str],
    *,
    glob: str | None = None,
    types: set[str] | None = None,
    recursive: bool = True,
    root: Path | None = None,
) -> list[Path]:
    """Explicit files as given; directories walked; then --glob / --type filters."""
    out: list[Path] = []
    for p in (Path(x) for x in paths):
        if not p.exists():
            raise CarrelInputError(f"no such path: {p}")
        candidates = [p] if p.is_file() else list(_walk_files(p, recursive, root))
        for f in candidates:
            if glob and not fnmatch.fnmatch(f.name, glob):
                continue
            if types is not None and detect(f).value not in types:
                continue
            out.append(f)
    return out


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= OUTPUT_CAP:
        return text, False
    return text[:OUTPUT_CAP], True


def run_one(path: Path, runs: Sequence[str], *, timeout: float | None) -> dict[str, Any]:
    """Run every template for one file, stopping at the first failure; the record `batch` emits."""
    started = time.monotonic()
    record: dict[str, Any] = {
        "path": str(path),
        "runs": list(runs),
        "cmd": None,
        "rc": 0,
        "stdout": "",
        "stderr": "",
        "seconds": 0.0,
        "ok": True,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    outs: list[str] = []
    errs: list[str] = []
    for template in runs:
        rendered = render(template, path)
        proc = run_action(rendered, timeout)
        outs.append(proc.stdout or "")
        errs.append(proc.stderr or "")
        record.update({"cmd": rendered, "rc": proc.returncode})
        if proc.returncode != 0:
            record["ok"] = False
            break
    out, out_cut = _clip("".join(outs))  # every action's output, in order
    err, err_cut = _clip("".join(errs))
    record.update({"stdout": out, "stderr": err})
    if out_cut or err_cut:
        record["truncated"] = True
    record["seconds"] = round(time.monotonic() - started, 3)
    return record


def load_manifest_done(manifest: Path, runs: Sequence[str]) -> set[str]:
    """Paths whose last manifest record succeeded with the same run templates."""
    last: dict[str, dict[str, Any]] = {}
    if not manifest.is_file():
        return set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and "path" in rec:
            last[str(rec["path"])] = rec
    return {p for p, rec in last.items() if rec.get("ok") and rec.get("runs") == list(runs)}


def run_batch(
    files: Sequence[Path],
    runs: Sequence[str],
    *,
    jobs: int = 1,
    timeout: float | None = 300.0,
    fail_fast: bool = False,
    on_record: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run `runs` over `files` (in input order in the result), `jobs` at a time."""
    results: list[dict[str, Any] | None] = [None] * len(files)
    if jobs <= 1:
        for i, f in enumerate(files):
            rec = run_one(f, runs, timeout=timeout)
            results[i] = rec
            if on_record:
                on_record(rec)
            if fail_fast and not rec["ok"]:
                break
        return [r for r in results if r is not None]

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        pending: dict[Future[dict[str, Any]], int] = {}
        queue = list(enumerate(files))
        stop = False
        while queue or pending:
            while queue and len(pending) < jobs and not stop:
                i, f = queue.pop(0)
                pending[pool.submit(run_one, f, runs, timeout=timeout)] = i
            if not pending:
                break
            done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                i = pending.pop(fut)
                rec = fut.result()
                results[i] = rec
                if on_record:
                    on_record(rec)
                if fail_fast and not rec["ok"]:
                    stop = True
                    queue.clear()
    return [r for r in results if r is not None]


def summarize(results: Sequence[dict[str, Any]], *, total: int, skipped: int) -> dict[str, Any]:
    ok = sum(1 for r in results if r["ok"])
    return {
        "total": total,
        "ran": len(results),
        "ok": ok,
        "failed": len(results) - ok,
        "skipped": skipped,
        "seconds": round(sum(float(r["seconds"]) for r in results), 3),
    }


def _human_record(rec: dict[str, Any]) -> None:
    if rec["ok"]:
        click.echo(f"[ok]   {rec['path']}")
    else:
        click.echo(f"[FAIL] {rec['path']} :: {rec['cmd']} -> rc={rec['rc']}")
    if rec["stderr"].strip():
        click.echo(rec["stderr"].rstrip(), err=True)


@click.command(name="batch")
@click.argument("paths", nargs=-1, required=True, type=click.Path(path_type=Path))
@click.option(
    "--run",
    "runs",
    multiple=True,
    required=True,
    metavar="CMD",
    help="Shell action per file; repeatable, runs in order, stops at the first failure. "
    f"Substituted (shell-quoted): {', '.join(PLACEHOLDERS)}.",
)
@click.option(
    "--glob",
    "glob_",
    default=None,
    metavar="PATTERN",
    help="Only files whose name matches (e.g. '*.pdf').",
)
@click.option(
    "--type",
    "types_csv",
    default=None,
    metavar="T1,T2",
    help="Only these detected types (pdf, md, eml, code, …).",
)
@click.option(
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="Walk directories (hidden and .gitignored entries skipped).",
)
@click.option(
    "--jobs",
    default=1,
    show_default=True,
    type=click.IntRange(min=1),
    help="Files to process in parallel.",
)
@click.option(
    "--dry-run", is_flag=True, help="Print the rendered commands without running anything."
)
@click.option(
    "--manifest",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Append one JSON record per file to this file.",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Skip files whose last --manifest record succeeded with the same --run set.",
)
@click.option("--fail-fast", is_flag=True, help="Stop after the first failing file.")
@click.option(
    "--action-timeout",
    type=click.FloatRange(min_open=True, min=0),
    default=300.0,
    show_default=True,
    metavar="SECS",
    help="Kill an action that runs longer than SECS (rc=124).",
)
@click.option("--fail-empty", is_flag=True, help="Exit 5 when no file matched.")
@click.option(
    "--json-lines",
    is_flag=True,
    help="Stream one JSON record per file as it completes, then a summary line.",
)
@click.pass_context
@handled
def cmd(
    ctx: click.Context,
    paths: tuple[Path, ...],
    runs: tuple[str, ...],
    glob_: str | None,
    types_csv: str | None,
    recursive: bool,
    jobs: int,
    dry_run: bool,
    manifest: Path | None,
    resume: bool,
    fail_fast: bool,
    action_timeout: float,
    fail_empty: bool,
    json_lines: bool,
) -> None:
    """Run --run actions over every file in PATH... (files, or directories walked like `index`).

    Exit 0 when every file succeeded, 1 when any failed (its record carries
    the rc, stdout and stderr), 5 with --fail-empty when nothing matched.
    JSON output is {"summary": {total, ran, ok, failed, skipped, seconds},
    "results": [{path, cmd, rc, stdout, stderr, seconds, ok}]} (cmd/rc are the
    failing or last action's, stdout/stderr every action's output in order);
    --json-lines streams the records instead. --manifest + --resume make a long run
    restartable.
    """
    types: set[str] | None = None
    if types_csv:
        types = {t.strip().lower() for t in types_csv.split(",") if t.strip()}
        valid = {ft.value for ft in FileType if ft is not FileType.UNKNOWN}
        unknown = types - valid
        if unknown:
            raise click.UsageError(
                f"unknown --type value(s): {', '.join(sorted(unknown))} (choose from {', '.join(sorted(valid))})"
            )
    if resume and manifest is None:
        raise click.UsageError("--resume needs --manifest FILE")
    for template in runs:
        if not any(ph in template for ph in PLACEHOLDERS):
            raise click.UsageError(f"--run {template!r} uses none of {', '.join(PLACEHOLDERS)}")

    files = collect_files(
        list(paths), glob=glob_, types=types, recursive=recursive, root=root_of(ctx)
    )
    done = load_manifest_done(manifest, runs) if (resume and manifest is not None) else set()
    todo = [f for f in files if str(f) not in done]
    skipped = len(files) - len(todo)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    if dry_run:
        plan = [{"path": str(f), "cmds": [render(t, f) for t in runs]} for f in todo]
        if as_json or json_lines:
            for entry in plan:
                click.echo(json.dumps(entry, ensure_ascii=False))
        else:
            for entry in plan:
                for c in entry["cmds"]:
                    click.echo(c)
            click.echo(
                f"dry-run: {len(plan)} file(s), {len(runs)} action(s) each; {skipped} skipped via --resume."
            )
        if fail_empty and not files:
            fail("no files matched (--fail-empty)", ExitCode.EMPTY)
        return

    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest_fh = manifest.open("a", encoding="utf-8") if manifest is not None else None

    def on_record(rec: dict[str, Any]) -> None:
        if manifest_fh is not None:
            manifest_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            manifest_fh.flush()
        if json_lines:
            click.echo(json.dumps(rec, ensure_ascii=False))
        elif not as_json:
            _human_record(rec)

    try:
        results = run_batch(
            todo, runs, jobs=jobs, timeout=action_timeout, fail_fast=fail_fast, on_record=on_record
        )
    finally:
        if manifest_fh is not None:
            manifest_fh.close()
    summary = summarize(results, total=len(files), skipped=skipped)
    if json_lines:
        click.echo(json.dumps({"summary": summary}, ensure_ascii=False))
    elif as_json:
        click.echo(
            json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False)
        )
    else:
        click.echo(
            f"{summary['ok']} ok, {summary['failed']} failed, {summary['skipped']} skipped "
            f"of {summary['total']} file(s) in {summary['seconds']}s"
        )
    if fail_empty and not files:
        fail("no files matched (--fail-empty)", ExitCode.EMPTY)
    if summary["failed"]:
        raise SystemExit(int(ExitCode.ERROR))
