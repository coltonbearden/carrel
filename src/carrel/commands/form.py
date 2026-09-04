"""carrel form — build fillable HTML forms from JSON specs, list/fill PDF AcroForms.

`build` renders a spec ({title, fields: [...]}) into clean standalone HTML —
embedded CSS, system font stack, no action/POST, print-friendly — and can
render that to PDF via the weasyprint adapter. `fields` lists a PDF's AcroForm
fields; `fill` writes values into them with pypdf (NeedAppearances set so
viewers actually render the values) and reports any unmatched data keys.
"""

from __future__ import annotations

import functools
import html
import json as jsonlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carrel.core import adapters
from carrel.core.filetypes import FileType, detect_or_die
from carrel.core.output import CarrelError, CarrelInputError, emit, fail

FIELD_TYPES = ("text", "textarea", "select", "checkbox", "radio", "date", "email", "number")

_PDF_FIELD_TYPES = {"/Tx": "text", "/Btn": "button", "/Ch": "choice", "/Sig": "signature"}


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


@click.group(name="form")
def cmd() -> None:
    """Build HTML forms from JSON specs; list and fill PDF AcroForms."""


# ---------------------------------------------------------------------- build

_CSS = """\
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
               Arial, sans-serif;
  margin: 0; color: #1a1a1a; background: #f4f4f2; line-height: 1.5;
}
main {
  max-width: 42rem; margin: 2rem auto; padding: 2rem;
  background: #fff; border: 1px solid #d9d9d4; border-radius: 8px;
}
h1 { font-size: 1.5rem; margin: 0 0 1.25rem; }
.field { margin-bottom: 1.1rem; }
.field label.main, fieldset legend { display: block; font-weight: 600; margin-bottom: 0.3rem; }
input, textarea, select {
  width: 100%; box-sizing: border-box; padding: 0.5rem;
  border: 1px solid #b5b5ae; border-radius: 4px; font: inherit; background: #fff;
}
label.inline { display: flex; align-items: center; gap: 0.5rem; font-weight: 400; }
label.inline input { width: auto; margin: 0; }
fieldset { border: 1px solid #d9d9d4; border-radius: 4px; padding: 0.6rem 0.8rem; margin: 0; }
fieldset label.inline { margin-bottom: 0.25rem; }
.req { color: #a33; }
@media print {
  body { background: #fff; }
  main { border: none; border-radius: 0; margin: 0; max-width: none; padding: 0; }
  input, textarea, select { border-color: #555; }
}
"""


def _load_spec(spec_path: Path) -> dict[str, Any]:
    if detect_or_die(spec_path) is not FileType.JSON:
        raise CarrelInputError(f"form build needs a JSON spec, got: {spec_path}")
    try:
        spec = jsonlib.loads(spec_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CarrelInputError(f"{spec_path} is not valid JSON: {e}") from e
    if not isinstance(spec, dict) or not isinstance(spec.get("fields"), list):
        raise CarrelInputError(f'{spec_path}: spec must be {{"title", "fields": [...]}}')
    for i, field in enumerate(spec["fields"]):
        where = f"{spec_path}: fields[{i}]"
        if not isinstance(field, dict) or not field.get("name"):
            raise CarrelInputError(f"{where}: every field needs a non-empty 'name'")
        ftype = field.get("type", "text")
        if ftype not in FIELD_TYPES:
            raise CarrelInputError(
                f"{where}: unknown type {ftype!r} (expected one of: {', '.join(FIELD_TYPES)})"
            )
        if ftype in ("select", "radio") and not field.get("options"):
            raise CarrelInputError(f"{where}: type {ftype!r} needs a non-empty 'options' list")
    return spec


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_field(field: dict[str, Any]) -> str:
    name = _esc(field["name"])
    label = _esc(field.get("label") or field["name"])
    ftype = field.get("type", "text")
    required = bool(field.get("required"))
    req_attr = ' required="required"' if required else ""
    req_mark = ' <span class="req">*</span>' if required else ""

    if ftype == "checkbox":
        control = (
            f'<label class="inline"><input type="checkbox" id="{name}" '
            f'name="{name}" value="yes"{req_attr}/>{label}{req_mark}</label>'
        )
    elif ftype == "radio":
        options = "\n      ".join(
            f'<label class="inline"><input type="radio" name="{name}" '
            f'value="{_esc(opt)}"{req_attr}/>{_esc(opt)}</label>'
            for opt in field["options"]
        )
        control = (
            f"<fieldset>\n      <legend>{label}{req_mark}</legend>\n"
            f"      {options}\n    </fieldset>"
        )
    elif ftype == "select":
        options = "\n        ".join(
            f'<option value="{_esc(opt)}">{_esc(opt)}</option>' for opt in field["options"]
        )
        control = (
            f'<label class="main" for="{name}">{label}{req_mark}</label>\n'
            f'      <select id="{name}" name="{name}"{req_attr}>\n'
            f'        <option value=""></option>\n        {options}\n      </select>'
        )
    elif ftype == "textarea":
        control = (
            f'<label class="main" for="{name}">{label}{req_mark}</label>\n'
            f'      <textarea id="{name}" name="{name}" rows="4"{req_attr}></textarea>'
        )
    else:  # text / date / email / number
        control = (
            f'<label class="main" for="{name}">{label}{req_mark}</label>\n'
            f'      <input type="{ftype}" id="{name}" name="{name}"{req_attr}/>'
        )
    return f'    <div class="field">\n      {control}\n    </div>'


def _render_html(spec: dict[str, Any]) -> str:
    title = _esc(spec.get("title") or "Form")
    fields = "\n".join(_render_field(f) for f in spec["fields"])
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
{_CSS}</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <form autocomplete="off">
{fields}
  </form>
</main>
</body>
</html>
"""


@cmd.command("build")
@click.argument("spec_path", metavar="SPEC.JSON", type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--out",
    type=click.Path(path_type=Path),
    help="Output HTML file. Default: SPEC stem + .html.",
)
@click.option("--pdf", "to_pdf", is_flag=True, help="Also render the HTML to PDF (weasyprint).")
@click.option("--force", is_flag=True, help="Allow overwriting existing output files.")
@click.pass_context
@_handled
def build(ctx: click.Context, spec_path: Path, out: Path | None, to_pdf: bool, force: bool) -> None:
    """Render a JSON form spec into clean, standalone, print-friendly HTML."""
    spec = _load_spec(spec_path)
    dest = out or spec_path.with_suffix(".html")
    pdf_dest = dest.with_suffix(".pdf") if to_pdf else None
    for target in (dest, pdf_dest):
        if target is not None and target.exists() and not force:
            raise CarrelError(f"refusing to overwrite existing file: {target} (pass --force)")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_render_html(spec), encoding="utf-8")
    if pdf_dest is not None:
        proc = adapters.run("weasyprint", str(dest), str(pdf_dest), timeout=300)
        if proc.returncode != 0 or not pdf_dest.is_file():
            raise CarrelError(
                f"weasyprint failed (rc={proc.returncode}): {(proc.stderr or '').strip()}"
            )

    record = {
        "action": "form-build",
        "spec": str(spec_path),
        "fields": len(spec["fields"]),
        "html": str(dest),
        "pdf": str(pdf_dest) if pdf_dest else None,
    }
    emit(
        ctx,
        record,
        human=lambda r: click.echo(
            f"form: {r['fields']} field(s) → {r['html']}"
            + (f"\n  pdf: {r['pdf']}" if r["pdf"] else "")
        ),
    )


# --------------------------------------------------------------------- fields


def _acroform_fields(src: Path) -> dict[str, Any]:
    from pypdf import PdfReader

    if detect_or_die(src) is not FileType.PDF:
        raise CarrelInputError(f"expected a pdf, got: {src}")
    return PdfReader(src).get_fields() or {}


@cmd.command("fields")
@click.argument("src", type=click.Path(path_type=Path))
@click.pass_context
@_handled
def fields(ctx: click.Context, src: Path) -> None:
    """List a PDF's AcroForm fields (name, type, current value)."""
    found = _acroform_fields(src)
    rows = [
        {
            "name": name,
            "type": _PDF_FIELD_TYPES.get(str(fld.field_type), str(fld.field_type)),
            "value": None if fld.value is None else str(fld.value),
            "states": [str(s) for s in fld.get("/_States_", [])] or None,
        }
        for name, fld in found.items()
    ]

    def human(data: list[dict[str, Any]]) -> None:
        if not data:
            click.echo(f"{src}: no AcroForm fields")
            return
        for row in data:
            value = "" if row["value"] is None else f" = {row['value']}"
            click.echo(f"{row['name']} ({row['type']}){value}")

    emit(ctx, rows, human=human)


# ----------------------------------------------------------------------- fill


def _coerce(value: Any, fld: Any) -> str:
    """Map a JSON value onto what pypdf expects for this field."""
    if str(fld.field_type) == "/Btn":
        states = [str(s) for s in fld.get("/_States_", [])]
        on_state = next((s for s in states if s != "/Off"), "/Yes")
        if isinstance(value, bool):
            return on_state if value else "/Off"
        text = str(value)
        if text.startswith("/"):
            return text
        return f"/{text}" if f"/{text}" in states else text
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return jsonlib.dumps(value)
    return str(value)


@cmd.command("fill")
@click.argument("src", type=click.Path(path_type=Path))
@click.argument("data_path", metavar="DATA.JSON", type=click.Path(path_type=Path))
@click.option("-o", "--out", required=True, type=click.Path(path_type=Path), help="Output PDF.")
@click.option("--force", is_flag=True, help="Allow overwriting an existing output file.")
@click.pass_context
@_handled
def fill(ctx: click.Context, src: Path, data_path: Path, out: Path, force: bool) -> None:
    """Fill a PDF's AcroForm fields from a JSON object {field: value}."""
    from pypdf import PdfWriter

    found = _acroform_fields(src)
    if not found:
        raise CarrelInputError(f"{src} has no AcroForm fields to fill")
    if detect_or_die(data_path) is not FileType.JSON:
        raise CarrelInputError(f"form fill needs a JSON data file, got: {data_path}")
    try:
        data = jsonlib.loads(data_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CarrelInputError(f"{data_path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise CarrelInputError(f"{data_path}: top-level JSON must be an object of field values")
    if out.exists() and not force:
        raise CarrelError(f"refusing to overwrite existing file: {out} (pass --force)")

    matched = {k: _coerce(v, found[k]) for k, v in data.items() if k in found}
    unmatched = sorted(k for k in data if k not in found)

    writer = PdfWriter(clone_from=str(src))
    for page in writer.pages:
        if page.get("/Annots"):
            # auto_regenerate=True sets NeedAppearances so viewers render values
            writer.update_page_form_field_values(page, matched, auto_regenerate=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        writer.write(fh)

    record = {
        "action": "form-fill",
        "src": str(src),
        "dest": str(out),
        "filled": sorted(matched),
        "unmatched": unmatched,
    }

    def human(r: dict[str, Any]) -> None:
        click.echo(f"filled {len(r['filled'])} field(s): {', '.join(r['filled']) or '-'}")
        if r["unmatched"]:
            click.echo(f"  unmatched keys (not in the form): {', '.join(r['unmatched'])}")
        click.echo(f"  wrote: {r['dest']}")

    emit(ctx, record, human=human)
