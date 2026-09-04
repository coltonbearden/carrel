"""carrel completion — print a shell completion script for bash, zsh, or fish.

The script comes from click's own shell-completion classes, generated
in-process (the equivalent of `_CARREL_COMPLETE=bash_source carrel`) — no
subprocess, no dependency on carrel being on PATH at generation time.
"""

from __future__ import annotations

from typing import Any

import click

from carrel._product import PRODUCT
from carrel.core.output import emit

SHELLS: tuple[str, ...] = ("bash", "zsh", "fish")

_PROG = PRODUCT["cli"]
COMPLETE_VAR = f"_{_PROG.upper().replace('-', '_')}_COMPLETE"

_INSTALL_HINTS: dict[str, str] = {
    "bash": (
        f"Add to ~/.bashrc (needs bash-completion >= 2.x / bash >= 4.4):\n"
        f'  eval "$({_PROG} completion bash)"\n'
        f"or, to avoid re-generating on every shell start:\n"
        f"  {_PROG} completion bash > ~/.{_PROG}-complete.bash\n"
        f"  echo '. ~/.{_PROG}-complete.bash' >> ~/.bashrc"
    ),
    "zsh": (
        f"Add to ~/.zshrc, AFTER `autoload -Uz compinit && compinit`:\n"
        f'  eval "$({_PROG} completion zsh)"\n'
        f"or, to avoid re-generating on every shell start:\n"
        f"  {_PROG} completion zsh > ~/.{_PROG}-complete.zsh\n"
        f"  echo '. ~/.{_PROG}-complete.zsh' >> ~/.zshrc"
    ),
    "fish": (
        f"Fish loads completions from ~/.config/fish/completions automatically:\n"
        f"  {_PROG} completion fish > ~/.config/fish/completions/{_PROG}.fish"
    ),
}


def install_hint(shell: str) -> str:
    """Human-readable one-liner(s) for enabling completion in SHELL."""
    return _INSTALL_HINTS[shell]


def completion_script(shell: str) -> str:
    """Generate the completion script for SHELL in-process via click."""
    from click.shell_completion import get_completion_class

    from carrel.cli import cli  # the root group: completion needs the real command tree

    completion_cls = get_completion_class(shell) if shell in SHELLS else None
    if completion_cls is None:  # click.Choice guards the CLI; this guards library callers
        raise click.BadParameter(
            f"unsupported shell {shell!r} (choose from {', '.join(SHELLS)})",
            param_hint="SHELL",
        )
    # Note: for bash, click's own source() probes `bash --version` to warn about
    # bash < 4.4; that is click's check, not carrel re-invoking itself.
    return completion_cls(cli, {}, _PROG, COMPLETE_VAR).source()


def _as_comment(text: str) -> str:
    return "\n".join(f"# {line}".rstrip() for line in text.splitlines())


@click.command(name="completion")
@click.argument("shell", type=click.Choice(SHELLS, case_sensitive=False))
@click.option(
    "--install-hint",
    "with_hint",
    is_flag=True,
    help="Append, as a comment block, how to enable the script in that shell.",
)
@click.pass_context
def cmd(ctx: click.Context, shell: str, with_hint: bool) -> None:
    """Print a completion script for SHELL (bash, zsh, or fish).

    \b
      eval "$(carrel completion bash)"      # ~/.bashrc
      eval "$(carrel completion zsh)"       # ~/.zshrc, after compinit
      carrel completion fish > ~/.config/fish/completions/carrel.fish

    The script is produced in-process by click; an unknown shell exits 2.
    With --json, emits {"shell": ..., "script": ...}.
    """
    shell = shell.lower()
    script = completion_script(shell)
    data: dict[str, Any] = {"shell": shell, "script": script}
    if with_hint:
        data["install_hint"] = install_hint(shell)

    def human(d: dict[str, Any]) -> None:
        out = d["script"].rstrip("\n")
        if "install_hint" in d:
            out += "\n\n" + _as_comment(f"To enable:\n{d['install_hint']}")
        click.echo(out)

    emit(ctx, data, human=human)
