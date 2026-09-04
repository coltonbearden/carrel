"""carrel umbrella CLI — click root group with lazy command loading."""

from __future__ import annotations

import importlib
import sys

import click

from carrel._product import PRODUCT
from carrel.core.output import CarrelError

# command name -> module under carrel.commands (lazy: a broken optional import
# only breaks its own command, and --help stays fast)
COMMANDS: dict[str, str] = {
    "convert": "convert",
    "ocr": "ocr",
    "inspect": "inspect",
    "diff": "diff",
    "edit": "edit",
    "pack": "pack",
    "index": "index",
    "search": "search",
    "tag": "tag",
    "note": "note",
    "thumb": "thumb",
    "extract-images": "extract_images",
    "watch": "watch",
    "organize": "organize",
    "dedupe": "dedupe",
    "audiobook": "audiobook",
    "redact": "redact",
    "sign": "sign",
    "form": "form",
    "proof": "proof",
    "color": "color",
    "doctor": "doctor",
    "mcp": "mcp",
    "desk": "desk",
}


class LazyGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted(COMMANDS)

    def get_command(self, ctx: click.Context, name: str) -> click.Command | None:
        module_name = COMMANDS.get(name)
        if module_name is None:
            return None
        try:
            module = importlib.import_module(f"carrel.commands.{module_name}")
        except ImportError as e:
            # a broken/missing optional module must only break its own command
            if "--debug" in sys.argv:
                click.echo(f"warning: command '{name}' unavailable: {e}", err=True)
            return None
        return _with_json_flag(module.cmd)


def _set_json(ctx: click.Context, _param: click.Parameter, value: bool) -> bool:
    if value:
        ctx.ensure_object(dict)
        ctx.obj["json"] = True
    return value


def _with_json_flag(command: click.Command) -> click.Command:
    """Accept `--json` after the subcommand too (`carrel pack --json …`).

    Commands that declare their own `--json` keep it; everyone else gets a
    flag that flips the shared ctx.obj["json"] switch `emit()` reads.
    """
    if any("--json" in getattr(p, "opts", ()) for p in command.params):
        return command
    command.params.append(
        click.Option(
            ["--json", "json_flag_"],
            is_flag=True,
            expose_value=False,
            callback=_set_json,
            help="Machine-readable JSON output.",
        )
    )
    return command


@click.group(
    cls=LazyGroup,
    name=PRODUCT["cli"],
    help=f"""{PRODUCT["cli"]} — {PRODUCT["tagline"].lower().rstrip(".")}.

    Every command supports --help; data-producing commands support --json.
    Run `{PRODUCT["cli"]} doctor` to see what your environment enables.
    """,
)
@click.version_option(
    PRODUCT["version"],
    prog_name=PRODUCT["name"],
    message=f"%(prog)s %(version)s — {PRODUCT['tagline']}",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.option("--debug", is_flag=True, help="Show tracebacks on error.")
@click.option(
    "--root",
    type=click.Path(file_okay=False),
    default=".",
    help="Desk root for db-backed commands (default: cwd).",
)
@click.pass_context
def cli(ctx: click.Context, as_json: bool, debug: bool, root: str) -> None:
    # help text comes from the group's `help=` above so it tracks product.json
    ctx.ensure_object(dict)
    ctx.obj.update({"json": as_json, "debug": debug, "root": root})


def main() -> None:
    debug = "--debug" in sys.argv
    try:
        cli(standalone_mode=False)
    except click.exceptions.Exit as e:
        sys.exit(e.exit_code)
    except click.exceptions.Abort:
        sys.exit(1)
    except click.ClickException as e:
        e.show()
        sys.exit(e.exit_code if isinstance(e, click.UsageError) else 1)
    except CarrelError as e:
        if debug:
            raise
        click.echo(f"error: {e}", err=True)
        sys.exit(int(e.exit_code))
    except BrokenPipeError:
        sys.exit(0)
    except Exception as e:
        if debug:
            raise
        click.echo(f"unexpected error: {e} (re-run with --debug for details)", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
