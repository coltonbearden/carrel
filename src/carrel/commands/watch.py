"""carrel watch — react to filesystem events with shell actions.

A watchdog observer monitors DIR (--recursive to descend). Each matching
event is debounced per path (and, with --stable, held until the file stops
changing), then every --run template runs sequentially with `{path}`,
`{name}`, `{stem}`, `{ext}` and `{dir}` substituted (shell-quoted).
--existing queues the files already present at start; --poll swaps inotify
for a polling observer (needed on /mnt/c and network shares); --done-dir /
--error-dir file each processed source away; --log appends JSON records.

Deviation note: the --run action is an arbitrary user-supplied shell command,
so it cannot go through the adapter registry; `core.actions` is the one place
carrel runs `subprocess` with `shell=True`, shared with `carrel batch` (D-013).

Self-trigger guard and its limits: while actions run for a source file, events
for that file are ignored, as are events for files whose name starts with the
source's stem (catches outputs like `report.thumb.png` from `report.pdf`).
Actions that write *differently named* files into the watched directory will
re-trigger the watcher — point outputs at another directory or narrow --glob.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import click

from carrel._product import PRODUCT
from carrel.commands._guard_flags import allow_tracked_options, warn_if_deprecated_spelling
from carrel.core.actions import PLACEHOLDERS, kill_tree, quote, render, run_action
from carrel.core.fsops import guard_worktree, move_file, uncollide
from carrel.core.output import CarrelInputError, CarrelUsageError, handled, root_of

# private aliases: tests and older callers reach the shared implementations by these names
_quote, _render, _run_action, _kill_tree = quote, render, run_action, kill_tree

EVENT_TYPES = ("created", "modified", "deleted", "moved", "existing")
_SUPPRESS_SECONDS = 2.0  # ignore events for a path the watcher itself just moved
_SCHTASKS_TR_BUDGET = 261  # documented practical cap on the /TR value
_TICK_SECONDS = 0.05


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
        stable: float | None = None,
        stable_timeout: float | None = None,
        done_dir: Path | None = None,
        error_dir: Path | None = None,
        log_path: Path | None = None,
        desk_root: Path | None = None,
    ) -> None:
        self.on = on
        self.action_timeout = action_timeout
        self.glob = glob
        self.debounce_ms = debounce_ms
        self.runs = runs
        self.json_lines = json_lines
        self.stable = stable
        self.stable_timeout = stable_timeout
        self.done_dir = done_dir
        self.error_dir = error_dir
        self.log_path = log_path
        self.desk_root = desk_root
        self.pending: dict[Path, tuple[str, float]] = {}
        self.settling: dict[Path, tuple[tuple[int, float] | None, float, float]] = {}
        self.suppress: dict[Path, float] = {}
        self.inflight: set[Path] = set()
        self.lock = threading.Lock()
        self.stop = threading.Event()

    # -- called from the watchdog observer thread ---------------------------
    def record(self, event_type: str, path: Path) -> None:
        if event_type not in self.on:
            return
        self.seed(event_type, path)

    def seed(self, event_type: str, path: Path) -> None:
        """Queue `path` regardless of --on (used by --existing); glob and guards still apply."""
        if self.glob and not fnmatch.fnmatch(path.name, self.glob):
            return
        with self.lock:
            until = self.suppress.get(path)
            if until is not None:
                if time.monotonic() < until:
                    return
                del self.suppress[path]
            if path in self.inflight:
                return
            for src in self.inflight:
                # output-name heuristic, deliberately narrow: an action's output
                # keeps the source's stem and adds a segment (report.pdf ->
                # report.txt, report.thumb.png). `report-2026.pdf` is a new input,
                # not an output, and must never be dropped.
                if path != src and path.name.startswith(f"{src.stem}."):
                    return
            self.pending[path] = (event_type, time.monotonic())

    # -- called from the main loop -------------------------------------------
    def drain(self) -> list[tuple[str, Path]]:
        with self.lock:
            due = _due(self.pending, time.monotonic(), self.debounce_ms)
            if self.stable is None:
                return due
            ready: list[tuple[str, Path]] = []
            for event_type, path in due:
                if event_type == "deleted" or self._settled(path):
                    ready.append((event_type, path))
                else:
                    self.pending[path] = (event_type, time.monotonic())  # look again next tick
            return ready

    def _settled(self, path: Path) -> bool:
        """True once size+mtime have not changed for --stable seconds (or --stable-timeout hit)."""
        now = time.monotonic()
        try:
            st = path.stat()
            sig: tuple[int, float] | None = (st.st_size, st.st_mtime)
        except OSError:
            sig = None
        prev = self.settling.get(path)
        if prev is None or prev[0] != sig:
            self.settling[path] = (sig, now, prev[2] if prev else now)
            return False
        unchanged_since, first_seen = prev[1], prev[2]
        if now - unchanged_since >= (self.stable or 0) or (
            self.stable_timeout is not None and now - first_seen >= self.stable_timeout
        ):
            del self.settling[path]
            return True
        return False

    def fire(self, event_type: str, path: Path) -> None:
        with self.lock:
            self.inflight.add(path)
        ok = True
        try:
            for template in self.runs:
                rendered = _render(template, path)
                proc = _run_action(rendered, self.action_timeout)
                self._log(event_type, path, rendered, proc)
                if proc.returncode != 0:
                    ok = False
        finally:
            with self.lock:
                self.inflight.discard(path)
        self._file_away(path, ok)

    def _file_away(self, path: Path, ok: bool) -> None:
        target = self.done_dir if ok else self.error_dir
        if target is None or not path.is_file():
            return
        dest = uncollide(target / path.name)
        with self.lock:
            self.suppress[dest] = time.monotonic() + _SUPPRESS_SECONDS
            self.suppress[path] = time.monotonic() + _SUPPRESS_SECONDS
        try:
            move_file(path, dest, desk_root=self.desk_root)
        except OSError as e:
            click.echo(f"could not move {path} to {dest}: {e}", err=True)
            return
        self._log_record({"event": "filed", "path": str(path), "dest": str(dest), "ok": ok})

    def _log(
        self, event_type: str, path: Path, cmd: str, proc: subprocess.CompletedProcess
    ) -> None:
        record = {
            "event": event_type,
            "path": str(path),
            "cmd": cmd,
            "rc": proc.returncode,
            "stdout": proc.stdout.strip(),
        }
        if self.json_lines:
            click.echo(json.dumps(record, ensure_ascii=False))
        else:
            click.echo(f"[{event_type}] {path} :: {cmd} -> rc={proc.returncode}")
            if proc.stdout.strip():
                click.echo(proc.stdout.rstrip())
        if proc.stderr.strip():
            click.echo(proc.stderr.rstrip(), err=True)
        self._log_record({**record, "stderr": proc.stderr.strip()})

    def _log_record(self, record: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = json.dumps({"time": stamp, **record}, ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    return data.decode(errors="replace") if isinstance(data, bytes) else data


def _walk_files(
    directory: Path,
    *,
    recursive: bool,
    skip: Sequence[Path] = (),
    glob_: str | None = None,
    hidden: bool = True,
) -> list[Path]:
    """Files under `directory`, pruning `.git` and the `skip` subtrees as it goes.

    One walker for both callers, because they had already drifted apart: the
    guard resolved its destinations and `--existing` did not, so a relative
    `--done-dir` was pruned by one and descended by the other.

    `os.walk` with in-place pruning rather than `rglob`: a raw recursive walk
    of a 200-file repository yielded 425 paths, 225 of them `.git/objects` and
    friends — every one stat'd, resolved and sent through `git ls-files` for an
    answer git can never give, and growing without bound as the archive filled.

    `hidden=False` is the `--existing` set, which skips dotted components.
    The spec-29 guard keeps them (`hidden=True`): `--existing` never queues a
    `.gitkeep`, but a live event reaches `_Watcher.seed`, which applies only
    `--glob`, so a committed one really can be filed into `--done-dir`.

    `skip` is resolved here so a relative `--done-dir` prunes like an absolute
    one; `click.Path` does not resolve it for us.
    """
    bounds = [s.resolve() for s in skip]
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(directory):
        here = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d != ".git"
            and (hidden or not d.startswith("."))
            and not any((here / d).resolve().is_relative_to(s) for s in bounds)
        ]
        out.extend(
            here / name
            for name in filenames
            if (hidden or not name.startswith(".")) and (not glob_ or fnmatch.fnmatch(name, glob_))
        )
        if not recursive:
            break
    return sorted(out)


def _existing_files(directory: Path, recursive: bool, skip: Sequence[Path] = ()) -> list[Path]:
    """Files already in `directory` at start, skipping hidden entries and `skip` subtrees.

    `--done-dir` / `--error-dir` are usually inside the watched folder; without
    skipping them a restart would re-run every action over the whole archive.
    """
    return _walk_files(directory, recursive=recursive, skip=skip, hidden=False)


def _abs(value: Any) -> str:
    """Absolute form of a path-valued option, for an argv that runs from elsewhere.

    A generated service starts in the service manager's working directory — $HOME
    for a systemd *user* unit — so every relative path in the unit resolves
    against the wrong place. `--root` is `click.Path(exists=True)`, so a relative
    one makes the unit die with exit 2 on every start; a `--done-dir` would
    quietly fill a directory under $HOME instead.
    """
    return str(Path(value).resolve()) if isinstance(value, Path) else str(value)


def _launcher_path(argv0: str, *, windows: bool) -> Path | None:
    """The carrel launcher that started this process, or None.

    Absolute but *not* resolved. Homebrew's `/opt/homebrew/bin/carrel` resolves
    into a version-specific Cellar directory that `brew cleanup` deletes, and a
    Nix profile resolves into the store the same way, so a unit naming the
    resolved path fails with 203/EXEC after the next upgrade. On Windows, uv and
    pip console-script launchers strip `.exe` from `sys.argv[0]`, so the bare
    path does not exist and the `.exe` beside it is the file to name.
    """
    if not argv0:
        return None
    me = Path(argv0)
    candidates = [me]
    # `with_name` raises ValueError when there is no final component, which
    # for pathlib means exactly `/` and `.` — a trailing separator is stripped,
    # so `bin/` has the name `bin`. @handled only converts CarrelError, so that
    # ValueError escaped as a traceback.
    if windows and me.name and me.suffix.lower() != ".exe":
        candidates.append(me.with_name(me.name + ".exe"))
    for candidate in candidates:
        if candidate.stem.lower() == PRODUCT["cli"].lower() and candidate.is_file():
            # abspath, not absolute(): `absolute()` prepends the cwd without
            # normalising, so an argv[0] of `bin/../bin/carrel` keeps its `..`
            # and systemd refuses the unit ("Executable path contains special
            # characters" — config_parse_exec requires path_is_normalized).
            # Still not resolve(): that follows the Homebrew/Nix symlink into a
            # versioned store that the next upgrade deletes.
            return Path(os.path.abspath(candidate))
    return None


def _self_command() -> list[str]:
    """argv that re-runs *this* carrel — not whichever one is first on PATH.

    `shutil.which("carrel")` resolved the generated unit against PATH, so a
    0.4.1 venv could print a unit pinned to an older global install and the
    service would then run that version forever, guard and all. `sys.argv[0]`
    is the launcher of the process printing the unit; under a test runner it is
    not a carrel launcher, and the module form is used instead.
    """
    launcher = _launcher_path(sys.argv[0] if sys.argv else "", windows=os.name == "nt")
    if launcher is not None:
        return [str(launcher)]
    return [sys.executable, "-m", f"{PRODUCT['package']}.cli"]


def _watch_command_line(ctx: click.Context, directory: Path) -> list[str]:
    """This invocation as an argv list, rebuilt from click's parsed options (never sys.argv,
    which is the test runner's under CliRunner), without --print-service."""
    argv: list[str] = _self_command()
    parent = ctx.parent
    source = parent.get_parameter_source("root") if parent is not None else None
    if source is not None and source.name != "DEFAULT":
        argv += ["--root", str(root_of(ctx))]
    argv += ["watch", str(directory.resolve())]
    params = ctx.params
    for param in ctx.command.params:
        if not isinstance(param, click.Option) or param.name in ("directory", "print_service"):
            continue
        value = params.get(param.name)
        if value is None or value == param.default:
            continue
        flag = max(param.opts, key=len)  # the long form
        if param.is_flag:
            if value:
                argv.append(flag)
            continue
        if param.multiple:
            for item in value:
                argv += [flag, _abs(item)]
            continue
        argv += [flag, _abs(value)]
    if (ctx.obj or {}).get("json") and "--json-lines" not in argv:
        # the global --json switches a watch's log to JSON lines; a service runs
        # without that parent flag, so carry its effect onto the watch itself
        argv.append("--json-lines")
    return argv


def _systemd_word(word: str) -> str:
    """One argv word as a systemd `ExecStart=` item.

    Double-quoted, with C escapes for backslash, double quote, newline, tab and
    carriage return, because systemd unescapes inside quotes and a lone
    backslash in an action would be eaten. Then `%` is doubled, because
    specifiers expand on the whole line (`date +%Y-%m` became the unit directory
    and the machine ID), and `$` is doubled, because environment substitution
    ignores quoting. A word that is exactly a semicolon must be backslash-escaped
    (systemd.service(5)). `shlex.join` got every one of these wrong: it
    single-quotes, leaves `%` and `$` alone, and splices `'"'"'` for an
    apostrophe, which systemd rejects because a closing quote must be followed
    by whitespace. Verified by round-tripping argv through a real systemd 259 unit.
    """
    if word == ";":
        return r"\;"
    escaped = (
        word.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("%", "%%")
        .replace("$", "$$")
    )
    return f'"{escaped}"'


def _systemd_setting(value: str) -> str:
    """A **bare** systemd setting value, for `Description=`/`WorkingDirectory=`.

    These are not unquoted the way `ExecStart=` is — checked against systemd
    259, not against a model of it. A quoted `WorkingDirectory="/tmp/x"` is
    rejected outright ("path is not absolute"), a quoted `Description=` keeps
    its quotation marks verbatim in `systemctl show`, and `\t` is not
    C-unescaped. Only `%` needs doubling; `$` is not expanded in either.

    Refusing lives here rather than in a separate validator because *this* is
    the function that makes a value bare, so every bare emission is safe by
    construction. Three shapes a bare line cannot carry, each confirmed
    against systemd 259:

    * a newline ends the line, and the rest of the value becomes further unit
      directives — an attacker-chosen `[Service]` / `ExecStart=` in the file
      the user is told to `systemctl --user enable`;
    * a trailing backslash continues the line, swallowing the directive that
      follows (`After=default.target` vanished, leaving `After=` at defaults);
    * trailing whitespace is stripped by the config parser, so
      `WorkingDirectory=/srv/inbox ` silently becomes `/srv/inbox` — a
      different directory that either fails the unit with 200/CHDIR under
      `Restart=on-failure`, or exists and quietly becomes the action's cwd.
    """
    if "\n" in value or "\r" in value:
        raise CarrelUsageError(
            "--print-service: the path contains a newline, which a systemd unit "
            "file cannot represent — rename the directory first"
        )
    if value != value.rstrip() or value.endswith("\\"):
        raise CarrelUsageError(
            "--print-service: the path ends in whitespace or a backslash, which a "
            "systemd unit file silently strips or treats as a line continuation — "
            "rename the directory first"
        )
    return value.replace("%", "%%")


def _schtasks_representable(text: str) -> None:
    """Refuse what a pasted `schtasks` line cannot carry.

    `subprocess.list2cmdline` quotes for MSVCRT's argv splitter and leaves
    shell metacharacters alone, so a newline in the watched path ends the
    pasted command and the remainder runs as a second one — the same injection
    the systemd arm refuses, on the target whose own first line says "Paste
    into cmd.exe".
    """
    if "\n" in text or "\r" in text:
        raise CarrelUsageError(
            "--print-service schtasks: the path contains a newline, which would end "
            "the pasted command line — rename the directory first"
        )


def render_service(kind: str, directory: Path, ctx: click.Context) -> str:
    """A systemd user unit or a Windows `schtasks` line that runs this watch at login."""
    argv = _watch_command_line(ctx, directory)
    cli, unit = PRODUCT["cli"], f"{PRODUCT['cli']}-watch"
    if kind == "systemd":
        cmd = " ".join(_systemd_word(word) for word in argv)
        description = _systemd_setting(f"{cli} watch {directory}")
        # The unit has to reproduce *this* invocation. A systemd user unit
        # starts in $HOME, so a --run action holding a relative path
        # (`cp {path} backups/`) resolved against the home directory instead of
        # wherever the user ran carrel, and filed every document into the wrong
        # tree, silently. `_abs` covered the option values and left the action
        # template, the one relative-path surface remaining.
        #
        # The cwd, not the watched directory: `_abs` already resolves option
        # paths against the cwd, so pinning the watch directory here would make
        # the unit resolve `--done-dir archive` and `cp {path} backups/` against
        # two different roots — and under --recursive the second one lands
        # inside the watch, re-triggering it.
        workdir = _systemd_setting(str(Path.cwd()))
        return (
            f"# Save as ~/.config/systemd/user/{unit}.service, then:\n"
            f"#   systemctl --user daemon-reload && systemctl --user enable --now {unit}\n"
            f"#   journalctl --user -u {unit} -f   # follow the log\n"
            "[Unit]\n"
            f"Description={description}\n"
            "After=default.target\n\n"
            "[Service]\n"
            f"WorkingDirectory={workdir}\n"
            f"ExecStart={cmd}\n"
            "Restart=on-failure\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )
    # Windows parses this line twice: schtasks splits its own command line to
    # find the /TR value, then Task Scheduler hands that value to CreateProcess,
    # which splits it again for carrel. Both follow MSVCRT rules, so the command
    # is list2cmdline'd once for carrel and once more as schtasks' single /TR
    # argument. That second pass doubles the backslashes in front of each quote,
    # which a bare quote-to-backslash-quote replace did not, so an action with an
    # embedded quote or a trailing backslash was still corrupted.
    inner = subprocess.list2cmdline(argv)
    tr = subprocess.list2cmdline([inner])
    _schtasks_representable(tr)
    task = f"{cli} watch"
    # schtasks truncates or rejects a /TR value past roughly 261 characters, and
    # a real Windows launcher path plus a --done-dir and a --log reach that with
    # no exotic arguments at all. Saying so beats a task silently registered
    # against half a command line.
    # measured on the value schtasks stores, not on the doubly-quoted form we
    # print: the outer list2cmdline adds quotes and doubles backslashes, which
    # would fire the warning on a line schtasks would have accepted.
    over = (
        f"REM WARNING: the /TR value is {len(inner)} characters; schtasks rejects or\n"
        f"REM truncates past about {_SCHTASKS_TR_BUDGET}. Shorten the paths, or register\n"
        "REM the task from an XML definition (schtasks /Create /XML FILE) instead.\n"
        if len(inner) > _SCHTASKS_TR_BUDGET
        else ""
    )
    return (
        "REM Paste into cmd.exe, not PowerShell, to start this watch at logon.\n"
        "REM Not safe to paste when ANY part of the line — the watched path,\n"
        "REM --done-dir, --error-dir, --log or a --run action — contains an\n"
        "REM ampersand, pipe, angle bracket, caret or percent sign: cmd.exe acts\n"
        "REM on those first. `C:\\R&D\\inbox` is enough to split the line.\n"
        f"{over}"
        f'schtasks /Create /SC ONLOGON /TN "{task}" /TR {tr} /F\n'
        f'REM   schtasks /Run /TN "{task}"      (start now)\n'
        f'REM   schtasks /Delete /TN "{task}" /F (remove)\n'
    )


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
    f"{', '.join(PLACEHOLDERS)} are substituted (shell-quoted).",
)
@click.option("--recursive", is_flag=True, help="Watch subdirectories too.")
@click.option(
    "--existing",
    is_flag=True,
    help="Queue the files already in DIRECTORY at start (event 'existing').",
)
@click.option(
    "--stable",
    type=click.FloatRange(min_open=True, min=0),
    default=None,
    metavar="SECS",
    help="Act only once a file's size and mtime have not changed for SECS (scanners, big copies).",
)
@click.option(
    "--stable-timeout",
    type=click.FloatRange(min_open=True, min=0),
    default=None,
    metavar="SECS",
    help="With --stable: give up waiting and act after SECS regardless.",
)
@click.option(
    "--poll",
    is_flag=True,
    help="Poll instead of inotify (needed on /mnt/c, network shares, some containers).",
)
@click.option(
    "--poll-interval",
    type=click.FloatRange(min_open=True, min=0),
    default=1.0,
    show_default=True,
    metavar="SECS",
    help="With --poll: how often to scan.",
)
@click.option(
    "--done-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Move each source here after its actions all succeed.",
)
@click.option(
    "--error-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Move each source here after an action fails.",
)
@click.option(
    "--log",
    "log_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Append one JSON record per action (and per move) to FILE.",
)
@allow_tracked_options("With --done-dir/--error-dir: move files even when git tracks them.")
@click.option(
    "--print-service",
    type=click.Choice(["systemd", "schtasks"]),
    default=None,
    help="Print a service definition that runs this exact watch at login, then exit.",
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
@handled
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
    recursive: bool,
    existing: bool,
    stable: float | None,
    stable_timeout: float | None,
    poll: bool,
    poll_interval: float,
    done_dir: Path | None,
    error_dir: Path | None,
    log_path: Path | None,
    allow_tracked: bool,
    force: bool,
    print_service: str | None,
) -> None:
    """Watch DIRECTORY and run shell actions on file events.

    Events for files an action is currently producing are suppressed via an
    in-flight set plus an output-name heuristic (outputs whose name starts
    with the source file's stem); other action outputs written into the
    watched directory WILL re-trigger — write outputs elsewhere or use
    --glob to narrow matches. --stable waits for a file to stop growing,
    --existing processes what is already there, --poll works where inotify
    does not (/mnt/c, shares), --done-dir/--error-dir file sources away
    after their actions, --log keeps a JSON trail. Ctrl-C exits cleanly.

    --done-dir/--error-dir refuse to start (exit 2) when they would move files
    git is tracking; --allow-tracked overrides. Actions themselves are never guarded —
    what a --run command does is the user's business.
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
    if stable_timeout is not None and stable is None:
        raise click.UsageError("--stable-timeout needs --stable")
    # The guard is only consulted when something would be moved, so that is the
    # only place the deprecated spelling is worth a warning.
    moves_files = done_dir is not None or error_dir is not None
    if moves_files:
        # the guard is only consulted when something would be moved, so that is
        # the only place the deprecated spelling is worth a warning
        warn_if_deprecated_spelling(ctx)
    if not allow_tracked and moves_files:
        # the fourth bulk mover (spec 29), and the only one with no dry-run to
        # fall back on: --done-dir empties the watched directory as it goes.
        # Checked before --print-service returns, so carrel never hands back a
        # systemd unit whose command would refuse with exit 2 at every start —
        # Restart=on-failure would then loop it until the start limit trips.
        #
        # Only what this watch could move: files at the level it watches (the
        # whole tree with --recursive, the top level without) that its --glob
        # can match, plus the destinations. Files rather than the directory,
        # because `ls-files -- DIR` matches recursively (a tracked sub/ would
        # refuse a watch that never descends into it) and because a recursive
        # watch over a plain directory can still reach a nested repository.
        # Skipped entirely under --allow-tracked, which is what the flag is for.
        #
        # `_walk_files` prunes `.git` and the destination subtrees while
        # walking; a raw rglob spent most of its work stat'ing and resolving
        # `.git/objects` for an answer `ls-files` can never give.
        destinations = [d for d in (done_dir, error_dir) if d is not None]
        present = _walk_files(directory, recursive=recursive, skip=destinations, glob_=glob_)
        # no allow_tracked= here: the whole block is gated on `not allow_tracked`
        # above, and the default says so without a literal that needs explaining.
        guard_worktree([*present, *destinations], what="watch --done-dir/--error-dir")
    if print_service:
        click.echo(render_service(print_service, directory, ctx), nl=False)
        return
    for target in (done_dir, error_dir):
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)

    if poll:
        from watchdog.observers.polling import PollingObserver

        observer: Any = PollingObserver(timeout=poll_interval)
    else:
        from watchdog.observers import Observer

        observer = Observer()

    desk_root = root_of(ctx)
    watcher = _Watcher(
        on=on,
        glob=glob_,
        debounce_ms=debounce,
        runs=runs,
        json_lines=json_lines,
        action_timeout=action_timeout,
        stable=stable,
        stable_timeout=stable_timeout,
        done_dir=done_dir.resolve() if done_dir else None,
        error_dir=error_dir.resolve() if error_dir else None,
        log_path=log_path,
        desk_root=desk_root,
    )
    observer.schedule(_make_handler(watcher), str(directory), recursive=recursive)
    if existing:
        filed_away = [d for d in (watcher.done_dir, watcher.error_dir) if d is not None]
        for f in _existing_files(directory, recursive, filed_away):
            watcher.seed("existing", f)
    click.echo(
        f"watching {directory} (on: {', '.join(sorted(on))}"
        f"{f', glob: {glob_}' if glob_ else ''}{', recursive' if recursive else ''}"
        f"{', polling' if poll else ''}) — Ctrl-C to stop",
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
