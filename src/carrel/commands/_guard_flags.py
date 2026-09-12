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

from collections.abc import Callable
from typing import Any, TypeVar

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
        func = click.option(
            "--force",
            is_flag=True,
            help="Deprecated spelling of --allow-tracked; warns and behaves identically.",
        )(func)
        return click.option("--allow-tracked", is_flag=True, help=help_text)(func)

    return decorate


def resolve_allow_tracked(ctx: click.Context, *, consulted: bool) -> bool:
    """Fold `--force` into `--allow-tracked`; warn only when the guard is really consulted.

    `consulted` is whether *this* invocation reaches the guard at all. A dry run
    is never guarded, and a `watch` without `--done-dir`/`--error-dir` never asks
    the question, so warning there would tell the user a guard was bypassed when
    none was asked about — and would put stderr noise into scripted dry runs that
    were silent before.

    `ctx.params` is normalised, not just read: `watch --print-service` rebuilds
    its argv from `ctx.params`, and the unit it writes must not carry a spelling
    that prints a deprecation warning on every start — or break outright on the
    day the alias is removed.
    """
    allow_tracked = bool(ctx.params.get("allow_tracked"))
    force = bool(ctx.params.get("force"))
    if force:
        ctx.params["force"] = False
        ctx.params["allow_tracked"] = True
        if consulted:
            click.echo(_DEPRECATION, err=True)
    return allow_tracked or force
