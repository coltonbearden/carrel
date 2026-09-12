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

#: `ctx.meta` key recording that the user typed the deprecated spelling. The
#: alias exposes no value of its own, and the warning fires later than the fold,
#: so the fact has to outlive both.
_TYPED_FORCE = "carrel.guard_flags.typed_force"

_DEPRECATION = (
    "warning: --force here means --allow-tracked (bypass the tracked-files guard); "
    "the --force spelling is deprecated"
)


def _remember_force(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Record `--force` without exposing a parameter for it.

    `expose_value=False` rather than a `force: bool` the fold overwrites: a dead
    parameter in four signatures that can only ever be `False` is a trap for
    whoever later gives one of these four the *overwrite* meaning `--force`
    carries on the other seven commands. The flag would parse, `--help` would
    document it, and the callback would receive `False`.
    """
    if value:
        ctx.meta[_TYPED_FORCE] = True


def allow_tracked_options(help_text: str) -> Callable[[F], F]:
    """Declare `--allow-tracked` and the deprecated `--force` alias, and fold them.

    One decorator so a fifth guarded command cannot drift: the pair, the help
    text convention *and* the fold live here. The fold is structural rather than
    a line each command remembers — forgetting it made `--force` parse fine, set
    nothing, and let the guard refuse the very run the user had overridden.
    """

    def decorate(func: F) -> F:
        @functools.wraps(func)
        def folded(*args: Any, **kwargs: Any) -> Any:
            ctx = click.get_current_context()
            kwargs["allow_tracked"] = normalise_guard_flags(ctx)
            return func(*args, **kwargs)

        wrapped = click.option(
            "--force",
            is_flag=True,
            expose_value=False,
            callback=_remember_force,
            help="Deprecated spelling of --allow-tracked; warns when it bypasses the guard.",
        )(folded)
        return cast("F", click.option("--allow-tracked", is_flag=True, help=help_text)(wrapped))

    return decorate


def normalise_guard_flags(ctx: click.Context) -> bool:
    """Resolve the override, rewriting `ctx.params["allow_tracked"]` when the alias was used.

    `ctx.params` is written, not just read, because `watch --print-service`
    rebuilds its argv from it: a unit is installed once and started forever, so
    it must not carry a spelling that warns on every start — or break outright
    the day the alias is removed.
    """
    if ctx.meta.get(_TYPED_FORCE):
        ctx.params["allow_tracked"] = True
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
