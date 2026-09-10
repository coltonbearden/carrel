"""Shell actions authored by the user: `carrel watch --run` and `carrel batch --run`.

This is the one place carrel runs `subprocess` with `shell=True` — a user's
action is an arbitrary command line, so it cannot go through the adapter
registry (D-013). Substitutions are shell-quoted for the platform's shell
(`sh` gets `shlex.quote`; cmd.exe has no single quotes, so Windows gets the
CreateProcess rules via `subprocess.list2cmdline`). Each action runs in its
own process group so a timeout kills the whole tree, never just the shell.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
import subprocess
from pathlib import Path

PLACEHOLDERS: tuple[str, ...] = ("{path}", "{name}", "{stem}", "{ext}", "{dir}")


def quote(value: str) -> str:
    """Quote one substitution for the shell `run_action` uses on this platform."""
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def render(template: str, path: Path) -> str:
    """Substitute {path}/{name}/{stem}/{ext}/{dir} into an action template, shell-quoted."""
    return (
        template.replace("{path}", quote(str(path)))
        .replace("{name}", quote(path.name))
        .replace("{stem}", quote(path.stem))
        .replace("{ext}", quote(path.suffix))
        .replace("{dir}", quote(str(path.parent)))
    )


def run_action(rendered: str, timeout: float | None) -> subprocess.CompletedProcess[str]:
    """Run one shell action in its own process group; on timeout kill the whole group.

    `subprocess.run(timeout=…)` only kills /bin/sh and orphans the real worker,
    which keeps writing into a watched directory. start_new_session + killpg
    takes the worker down with it, so a timed-out action leaves no stragglers
    (rc 124, the same code `timeout(1)` uses).
    """
    if os.name == "nt":
        # no process groups to signal on Windows; a new group at least keeps
        # Ctrl-C in the caller's console from reaching the action, and
        # kill_tree walks the tree by pid instead
        child = subprocess.Popen(
            rendered,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    else:
        child = subprocess.Popen(
            rendered,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    with child:
        try:
            out, err = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(child)
            out, err = child.communicate()
            return subprocess.CompletedProcess(
                rendered,
                returncode=124,
                stdout=out or "",
                stderr=(err or "") + f"\naction timed out after {timeout:g}s (rc=124)",
            )
        return subprocess.CompletedProcess(rendered, child.returncode, out or "", err or "")


def kill_tree(child: subprocess.Popen[str]) -> None:
    """Kill the shell and everything it spawned."""
    if hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        return
    # Windows: taskkill /T takes the whole tree rooted at the shell's pid.
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(child.pid)], capture_output=True, check=False
    )
    with contextlib.suppress(OSError):
        child.kill()
