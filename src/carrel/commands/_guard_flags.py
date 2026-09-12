"""The tracked-files guard's CLI surface: `--allow-tracked` and its `--force` alias.

Four commands move files in bulk — `rename`, `organize`, `intake` and
`watch --done-dir/--error-dir` — and each refuses to start when the move would
touch a file git is tracking (spec 29). The override used to be `--force`, which
means "overwrite existing output" on seven *other* commands; those four never
overwrite anything, so the habitual meaning does not apply and reaching for it by
reflex disabled a safety guard. `--allow-tracked` is the spelling now; `--force`
stays as a deprecated alias (D-022).

This lives beside the click options rather than in `core/fsops.py`: spec 29 keeps
`core/` free of the CLI framework, and which spelling the user typed is a CLI
concern from end to end.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar, cast

import click

F = TypeVar("F", bound=Callable[..., Any])

_DEPRECATION = (
    "warning: --force here means --allow-tracked (bypass the tracked-files guard); "
    "the --force spelling is deprecated"
)


def allow_tracked_options(help_text: str) -> Callable[[F], F]:
    """Declare `--allow-tracked` and the deprecated `--force` alias on a guarded command.

    One decorator so a fifth guarded command cannot drift: the pair, the help
    text convention and the fold all live here.
    """

    def decorate(func: F) -> F:
        @functools.wraps(func)
        def fold(*args: Any, **kwargs: Any) -> Any:
            # the fold is structural, not a line each command has to remember:
            # forgetting it made `--force` parse fine, set nothing, and let the
            # guard refuse the very run the user had overridden
            ctx = click.get_current_context()
            kwargs["allow_tracked"] = normalise_guard_flags(ctx)
            kwargs["force"] = False
            return func(*args, **kwargs)

        wrapped = click.option(
            "--force",
            is_flag=True,
            help="Deprecated spelling of --allow-tracked; warns when it bypasses the guard.",
        )(fold)
        return cast("F", click.option("--allow-tracked", is_flag=True, help=help_text)(wrapped))

    return decorate


#: `ctx.meta` key remembering that the user typed the deprecated spelling, so the
#: fold can happen early (every command, unconditionally) and the warning late
#: (only where the guard is actually consulted).
_TYPED_FORCE = "carrel.guard_flags.typed_force"


def normalise_guard_flags(ctx: click.Context) -> bool:
    """Rewrite `--force` to `--allow-tracked` **in `ctx.params`** and return the value.

    The name says "normalise" because this mutates: after it runs, a user who
    typed only `--force` has `ctx.params["allow_tracked"] is True` and
    `ctx.params["force"] is False`. That is deliberate, and it is why the two
    obvious alternatives were not taken. Declaring one option with both
    spellings would make `_watch_command_line` emit the right flag for free but
    leaves no way to tell which spelling was typed, so the deprecation warning
    disappears. Skipping `force` in `_watch_command_line` instead would emit a
    unit carrying *neither* flag, which refuses at every start. Normalising once,
    here, keeps the warning and writes a unit that runs.

    Call it unconditionally, at the top of every guarded command: `ctx.params`
    must not be left in two different shapes depending on which branch a run
    takes. The warning is a separate step — see `warn_if_deprecated_spelling`.
    """
    force = bool(ctx.params.get("force"))
    if force:
        ctx.params["force"] = False
        ctx.params["allow_tracked"] = True
        ctx.meta[_TYPED_FORCE] = True
    return bool(ctx.params.get("allow_tracked"))


def warn_if_deprecated_spelling(ctx: click.Context) -> None:
    """Emit the deprecation once, at the point the guard is actually consulted.

    Call it where the guard runs, after the command's own argument validation. A
    dry run is never guarded, and a `watch` without `--done-dir`/`--error-dir`
    never asks the question, so warning there would tell the user a safety guard
    was bypassed when none was asked about, and would put stderr noise into
    scripted dry runs that were silent before. A bad `--into` should report
    itself rather than the deprecation, too.

    `pop`, so "once per run" is structural rather than a property of where the
    call happens to sit.
    """
    if ctx.meta.pop(_TYPED_FORCE, False):
        click.echo(_DEPRECATION, err=True)
