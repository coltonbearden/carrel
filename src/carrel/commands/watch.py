"""carrel watch — react to filesystem events with shell actions.

A watchdog observer monitors DIR (non-recursive). Each matching event is
debounced per path, then every --run template runs sequentially with
`{path}`, `{name}` and `{dir}` substituted (shlex-quoted).

Deviation note (documented in the completion report): the --run action is an
arbitrary user-supplied shell command, so it cannot go through the adapter
registry; this module is the one place a command runs `subprocess` with
`shell=True` directly.

Self-trigger guard and its limits: while actions run for a source file, events
for that file are ignored, as are events for files whose name starts with the
source's stem (catches outputs like `report.thumb.png` from `report.pdf`).
Actions that write *differently named* files into the watched directory will
re-trigger the watcher — point outputs at another directory or narrow --glob.
"""

from __future__ import annotations

import contextlib
import fnmatch
import functools
import json
import os
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core.output import CarrelError, CarrelInputError, fail

EVENT_TYPES = ("created", "modified", "deleted", "moved")
_TICK_SECONDS = 0.05


def _handled(fn: Callable) -> Callable:
    """Convert CarrelError into a clean message + exit code (unless --debug)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = click.get_current_context(silent=True)
        try:
            return fn(*args, **kwargs)
        except CarrelError as e:
            if ctx is not None and ctx.obj and ctx.obj.get("debug"):
                raise
            fail(str(e), e.exit_code)

    return wrapper


def _render(template: str, path: Path) -> str:
    """Substitute {path}/{name}/{dir} into an action template, shlex-quoted."""
    return (
        template.replace("{path}", shlex.quote(str(path)))
        .replace("{name}", shlex.quote(path.name))
        .replace("{dir}", shlex.quote(str(path.parent)))
    )


def _due(
    pending: dict[Path, tuple[str, float]], now: float, window_ms: int
) -> list[tuple[str, Path]]:
    """Pop and return (event_type, path) pairs whose debounce window elapsed.

    `pending` maps path -> (latest event type, monotonic time of last event);
    repeated events for one path within the window coalesce into one entry.
    """
    ready = [p for p, (_evt, last) in pending.items() if (now - last) * 1000.0 >= window_ms]
    return [(pending.pop(p)[0], p) for p in sorted(ready)]


class _Watcher:
    """Event sink + action runner shared between the handler and the loop."""

    def __init__(
        self,
        *,
        on: set[str],
        glob: str | None,
        debounce_ms: int,
        runs: tuple[str, ...],
        json_lines: bool,
        action_timeout: float | None = 300.0,
    ) -> None:
        self.on = on
        self.action_timeout = action_timeout
        self.glob = glob
        self.debounce_ms = debounce_ms
        self.runs = runs
        self.json_lines = json_lines
        self.pending: dict[Path, tuple[str, float]] = {}
        self.inflight: set[Path] = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()

    # -- called from the watchdog observer thread ---------------------------
    def record(self, event_type: str, path: Path) -> None:
        if event_type not in self.on:
            return
        if self.glob and not fnmatch.fnmatch(path.name, self.glob):
            return
        with self.lock:
            if path in self.inflight:
                return
            for src in self.inflight:  # output-path suffix heuristic
                if path != src and path.name.startswith(src.stem):
                    return
            self.pending[path] = (event_type, time.monotonic())

    # -- called from the main loop -------------------------------------------
    def drain(self) -> list[tuple[str, Path]]:
        with self.lock:
            return _due(self.pending, time.monotonic(), self.debounce_ms)

    def fire(self, event_type: str, path: Path) -> None:
        with self.lock:
            self.inflight.add(path)
        try:
            for template in self.runs:
                rendered = _render(template, path)
                proc = _run_action(rendered, self.action_timeout)
                self._log(event_type, path, rendered, proc)
        finally:
            with self.lock:
                self.inflight.discard(path)

    def _log(
        self, event_type: str, path: Path, cmd: str, proc: subprocess.CompletedProcess
    ) -> None:
        if self.json_lines:
            click.echo(
                json.dumps(
                    {
                        "event": event_type,
                        "path": str(path),
                        "cmd": cmd,
                        "rc": proc.returncode,
                        "stdout": proc.stdout.strip(),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            click.echo(f"[{event_type}] {path} :: {cmd} -> rc={proc.returncode}")
            if proc.stdout.strip():
                click.echo(proc.stdout.rstrip())
        if proc.stderr.strip():
            click.echo(proc.stderr.rstrip(), err=True)


def _run_action(rendered: str, timeout: float | None) -> subprocess.CompletedProcess[str]:
    """Run one shell action in its own process group; on timeout kill the whole group.

    `subprocess.run(timeout=…)` only kills /bin/sh and orphans the real worker,
    which keeps writing into the watched directory. start_new_session + killpg
    takes the worker down with it, so a timed-out action leaves no stragglers.
    """
    with subprocess.Popen(
        rendered,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as child:
        try:
            out, err = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
            out, err = child.communicate()
            return subprocess.CompletedProcess(
                rendered,
                returncode=124,
                stdout=out or "",
                stderr=(err or "") + f"\naction timed out after {timeout:g}s (rc=124)",
            )
        return subprocess.CompletedProcess(rendered, child.returncode, out or "", err or "")


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def _make_handler(watcher: _Watcher) -> Any:
    from watchdog.events import FileSystemEventHandler

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event: Any) -> None:
            if event.is_directory:
                return
            event_type = event.event_type
            if event_type not in EVENT_TYPES:
                return  # e.g. closed/opened variants on some platforms
            raw = event.dest_path if event_type == "moved" else event.src_path
            watcher.record(event_type, Path(str(raw)))

    return _Handler()


@click.command(name="watch")
@click.argument("directory", type=click.Path(path_type=Path))
@click.option(
    "--on",
    "on_",
    default="created,modified",
    show_default=True,
    metavar="EVENTS",
    help=f"Comma-separated events to react to: {', '.join(EVENT_TYPES)}.",
)
@click.option(
    "--glob",
    "glob_",
    default=None,
    metavar="PATTERN",
    help="Only react to file names matching this glob (e.g. '*.pdf').",
)
@click.option(
    "--run",
    "runs",
    multiple=True,
    required=True,
    metavar="CMD",
    help="Shell action to run per event; repeatable, runs in order. "
    "{path}, {name} and {dir} are substituted (shell-quoted).",
)
@click.option(
    "--debounce",
    default=500,
    show_default=True,
    metavar="MS",
    type=click.IntRange(min=0),
    help="Coalesce events per path within this window.",
)
@click.option("--once", is_flag=True, help="Exit after the first triggered action batch.")
@click.option(
    "--timeout",
    "timeout_",
    type=click.FloatRange(min_open=True, min=0),
    default=None,
    metavar="SECS",
    help="Hard stop after SECS seconds.",
)
@click.option(
    "--action-timeout",
    type=click.FloatRange(min_open=True, min=0),
    default=300.0,
    show_default=True,
    metavar="SECS",
    help="Kill an action that runs longer than SECS (logged as rc=124).",
)
@click.option(
    "--json-lines",
    is_flag=True,
    help="Log one JSON object per action to stdout instead of human lines (--json implies this).",
)
@click.pass_context
@_handled
def cmd(
    ctx: click.Context,
    directory: Path,
    on_: str,
    glob_: str | None,
    runs: tuple[str, ...],
    debounce: int,
    once: bool,
    timeout_: float | None,
    action_timeout: float,
    json_lines: bool,
) -> None:
    """Watch DIRECTORY (non-recursive) and run shell actions on file events.

    Events for files an action is currently producing are suppressed via an
    in-flight set plus an output-name heuristic (outputs whose name starts
    with the source file's stem); other action outputs written into the
    watched directory WILL re-trigger — write outputs elsewhere or use
    --glob to narrow matches. Ctrl-C exits cleanly.
    """
    json_lines = json_lines or bool(ctx.obj and ctx.obj.get("json"))
    directory = directory.resolve()
    if not directory.is_dir():
        raise CarrelInputError(f"no such directory: {directory}")
    on = {e.strip() for e in on_.split(",") if e.strip()}
    bad = on - set(EVENT_TYPES)
    if bad or not on:
        raise click.UsageError(
            f"--on must be a comma list of {', '.join(EVENT_TYPES)} (got: {on_!r})"
        )

    from watchdog.observers import Observer

    watcher = _Watcher(
        on=on,
        glob=glob_,
        debounce_ms=debounce,
        runs=runs,
        json_lines=json_lines,
        action_timeout=action_timeout,
    )
    observer = Observer()
    observer.schedule(_make_handler(watcher), str(directory), recursive=False)
    click.echo(
        f"watching {directory} (on: {', '.join(sorted(on))}"
        f"{f', glob: {glob_}' if glob_ else ''}) — Ctrl-C to stop",
        err=True,
    )

    deadline = time.monotonic() + timeout_ if timeout_ is not None else None
    observer.start()
    try:
        while not watcher.stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            for event_type, path in watcher.drain():
                watcher.fire(event_type, path)
                if once:
                    watcher.stop.set()
                    break
            watcher.stop.wait(_TICK_SECONDS)
    except KeyboardInterrupt:
        click.echo("stopped", err=True)
    finally:
        observer.stop()
        observer.join(timeout=5)
