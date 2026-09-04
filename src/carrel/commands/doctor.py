"""carrel doctor — environment and capability report.

Iterates the adapter registry (found path + version, or install hint), then a
capability table: for every carrel command, whether it is ok / degraded /
unavailable given the binaries present. Always exits 0 — it is a report.
"""

from __future__ import annotations

import importlib.util
import platform
from pathlib import Path
from typing import Any

import click

from carrel._product import PRODUCT
from carrel.commands.desk import TUI_INSTALL_HINT
from carrel.core import adapters
from carrel.core.output import CarrelError, emit

# ---------------------------------------------------------------------------
# Static mapping: command -> adapters that gate it.
#   required : any missing  -> "unavailable"
#   optional : any missing  -> "degraded" (command still works, reduced power)
#   neither missing         -> "ok"
#   extra    : (extra_name, import_name) — a Python optional extra (D-007);
#              import failure -> "unavailable", reported as "<module> (carrel[extra])"
# Must cover every entry in carrel.cli.COMMANDS (a test enforces this).
# ---------------------------------------------------------------------------
CAPABILITIES: dict[str, dict[str, Any]] = {
    "convert": {
        "required": (),
        "optional": ("pandoc", "weasyprint"),
        "note": "built-in md→html fallback; pandoc widens formats, weasyprint renders html→pdf",
    },
    "ocr": {
        "required": ("tesseract", "ocrmypdf"),
        "optional": (),
        "note": "tesseract for images, ocrmypdf for PDF text layers",
    },
    "inspect": {
        "required": (),
        "optional": ("exiftool",),
        "note": "exiftool enables --deep metadata",
    },
    "diff": {"required": (), "optional": ("exiftool",), "note": "pure-python core"},
    "edit": {"required": (), "optional": ("exiftool",), "note": "pypdf/Pillow core"},
    "pack": {"required": (), "optional": (), "note": "pure python (textextract)"},
    "index": {"required": (), "optional": (), "note": "sqlite FTS5 (stdlib)"},
    "search": {"required": (), "optional": (), "note": "sqlite FTS5 (stdlib)"},
    "tag": {"required": (), "optional": (), "note": "desk db (stdlib sqlite)"},
    "note": {"required": (), "optional": (), "note": "desk db + pypdf annotations"},
    "thumb": {
        "required": ("pdftoppm",),
        "optional": (),
        "note": "PDF page rasterization (poppler)",
    },
    "extract-images": {
        "required": ("pdfimages", "icotool"),
        "optional": (),
        "note": "pdfimages for PDFs, icotool for .ico frames",
    },
    "watch": {"required": (), "optional": (), "note": "watchdog (bundled python lib)"},
    "organize": {"required": (), "optional": ("exiftool",), "note": "pure-python moves"},
    "dedupe": {"required": (), "optional": ("exiftool",), "note": "hash-based (stdlib)"},
    "audiobook": {
        "required": ("espeak-ng", "ffmpeg"),
        "optional": (),
        "note": "piper/edge-tts upgrade the voice when present",
    },
    "redact": {
        "required": ("pdftoppm", "tesseract"),
        "optional": (),
        "note": "PDF redaction rasterizes pages and re-OCRs",
    },
    "sign": {
        "required": (),
        "optional": ("gpg",),
        "note": "hash manifests always work; gpg adds detached signatures",
    },
    "form": {"required": (), "optional": (), "note": "pypdf (bundled)"},
    "proof": {
        "required": (),
        "optional": (),
        "note": "Pillow (bundled); ICC profile dirs improve accuracy",
    },
    "color": {
        "required": (),
        "optional": (),
        "note": "Pillow (bundled); ICC profile dirs improve accuracy",
    },
    "completion": {
        "required": (),
        "optional": (),
        "note": "shell completion scripts (click, in-process)",
    },
    "catalog": {
        "required": (),
        "optional": (),
        "note": "desk db export/import/status (stdlib sqlite)",
    },
    "doctor": {"required": (), "optional": (), "note": "this report"},
    "mcp": {"required": (), "optional": (), "note": "stdio JSON-RPC (stdlib)"},
    "desk": {
        "required": (),
        "optional": (),
        "extra": ("tui", "textual"),
        "note": f"textual TUI — optional extra: {TUI_INSTALL_HINT}",
    },
}

# Conventional ICC profile locations (Linux + WSL's Windows mount).
ICC_DIR_CANDIDATES: tuple[Path, ...] = (
    Path("/usr/share/color/icc"),
    Path("/usr/local/share/color/icc"),
    Path("/var/lib/color/icc"),
    Path.home() / ".local/share/icc",
    Path.home() / ".color/icc",
    Path("/mnt/c/Windows/System32/spool/drivers/color"),
)


def _tesseract_langs() -> list[str]:
    if not adapters.have("tesseract"):
        return []
    try:
        proc = adapters.run("tesseract", "--list-langs", timeout=15)
    except (CarrelError, OSError, ValueError):
        return []
    # header line ends with ':'; langs follow, one per line (older builds use stderr)
    out = (proc.stdout or "") + (proc.stderr or "")
    return sorted(
        ln.strip() for ln in out.splitlines() if ln.strip() and not ln.strip().endswith(":")
    )


def _icc_dirs() -> list[dict[str, Any]]:
    found = []
    for d in ICC_DIR_CANDIDATES:
        if d.is_dir():
            try:
                profiles = sum(1 for p in d.iterdir() if p.suffix.lower() in (".icc", ".icm"))
            except OSError:
                profiles = 0
            found.append({"path": str(d), "profiles": profiles})
    return found


def _extra_missing(spec: dict[str, Any]) -> list[str]:
    """['<module> (carrel[extra])'] when the command's optional extra is not importable."""
    extra = spec.get("extra")
    if not extra:
        return []
    extra_name, module = extra
    if importlib.util.find_spec(module) is not None:
        return []
    return [f"{module} ({PRODUCT['cli']}[{extra_name}])"]


def build_report() -> dict[str, Any]:
    """Full doctor report as one JSON-serializable structure."""
    resolved: dict[str, str | None] = {name: a.resolve() for name, a in adapters.ADAPTERS.items()}

    adapter_rows = []
    for name, adapter in adapters.ADAPTERS.items():
        path = resolved[name]
        override = adapter.override()
        install_hint = None if path else adapter.install_hint
        if path is None and override is not None:
            # D-008: a stale override is reported, never silently bypassed
            install_hint = f"override {adapter.env_var}={override} not found; {install_hint}"
        adapter_rows.append(
            {
                "name": name,
                "purpose": adapter.purpose,
                "found": path is not None,
                "path": path,
                "version": adapters.version_of(name) if path else None,
                "install_hint": install_hint,
                "override": {"var": adapter.env_var, "path": override} if override else None,
            }
        )

    command_rows = []
    for command in sorted(CAPABILITIES):
        spec = CAPABILITIES[command]
        req_missing = [a for a in spec["required"] if resolved[a] is None]
        req_missing += _extra_missing(spec)
        opt_missing = [a for a in spec["optional"] if resolved[a] is None]
        if req_missing:
            status = "unavailable"
        elif opt_missing:
            status = "degraded"
        else:
            status = "ok"
        command_rows.append(
            {
                "command": command,
                "status": status,
                "requires": list(spec["required"]),
                "optional": list(spec["optional"]),
                "missing": req_missing + opt_missing,
                "note": spec["note"],
            }
        )

    return {
        "product": {"name": PRODUCT["name"], "version": PRODUCT["version"]},
        "python": platform.python_version(),
        "adapters": adapter_rows,
        "commands": command_rows,
        "icc_dirs": _icc_dirs(),
        "tesseract_langs": _tesseract_langs(),
    }


_STATUS_STYLE = {"ok": "green", "degraded": "yellow", "unavailable": "red"}


def _render(report: dict[str, Any]) -> None:
    from rich.console import Console
    from rich.markup import escape
    from rich.table import Table

    console = Console()
    console.print(
        f"[bold]{report['product']['name']}[/bold] "
        f"{report['product']['version']} · python {report['python']}"
    )

    tools = Table(title="external tools", show_lines=False)
    tools.add_column("adapter")
    tools.add_column("status")
    tools.add_column("version / install hint", overflow="fold")
    for row in report["adapters"]:
        via = f" via {row['override']['var']}" if row.get("override") else ""
        if row["found"]:
            tools.add_row(row["name"], f"[green]found[/green]{via}", row["version"] or "?")
        else:
            tools.add_row(
                row["name"], f"[red]MISSING[/red]{via}", escape(row["install_hint"] or "")
            )
    console.print(tools)

    caps = Table(title="command capabilities")
    caps.add_column("command")
    caps.add_column("status")
    caps.add_column("gated by", overflow="fold")
    for row in report["commands"]:
        style = _STATUS_STYLE[row["status"]]
        gate = escape(", ".join(row["missing"]) if row["missing"] else row["note"])
        caps.add_row(row["command"], f"[{style}]{row['status']}[/{style}]", gate)
    console.print(caps)

    if report["icc_dirs"]:
        dirs = ", ".join(f"{d['path']} ({d['profiles']} profiles)" for d in report["icc_dirs"])
        console.print(f"ICC profile dirs: {dirs}")
    else:
        console.print("ICC profile dirs: none found")
    langs = report["tesseract_langs"]
    console.print(f"tesseract languages: {', '.join(langs) if langs else 'n/a'}")


@click.command(name="doctor")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def cmd(ctx: click.Context, as_json: bool) -> None:
    """Report environment health: adapters found, versions, per-command capability."""
    ctx.ensure_object(dict)
    if as_json:
        ctx.obj["json"] = True
    emit(ctx, build_report(), human=_render)
    # exit 0 always — doctor is a report, not a gate
