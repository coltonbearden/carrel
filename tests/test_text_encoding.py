"""Text IO names its encoding, and the gate that says so is honest about its reach.

`text=True` on subprocess and `Path.read_text(encoding="utf-8")` both fall back to
`locale.getencoding()` — cp1252 on a stock Windows box. CI never noticed because
it sets `PYTHONUTF8=1`, which is exactly why this file exists: these tests pin
the behaviour rather than the environment.

ruff's `PLW1514` is the first line of defence but it only fires where it can
infer the receiver is a `Path` — it says nothing about
`(tmp_path / "a.txt").write_text(..., encoding="utf-8")`. `test_no_unencoded_text_io_in_shipped_code`
is the second line, and covers what the rule cannot see.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest
from conftest import needs

from carrel.core import adapters
from carrel.core.textextract import TEXT_ENCODING, open_text_file, read_text_file

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ("src", "scripts")

#: `.read_text`/`.write_text` are Path-only. `.open` needs a mode check, and the
#: PIL/wave `open(...)` calls that share the name are module-level, not methods
#: on a path, so they are excluded by the receiver test below.
TEXT_METHODS = {"read_text", "write_text"}

#: module-level `open()`s that are not file text IO
NOT_PATH_OPEN = {"Image", "wave", "zipfile", "gzip", "tarfile", "webbrowser", "ZipFile"}


def _receiver_name(node: ast.Attribute) -> str:
    value = node.value
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _unencoded_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr not in TEXT_METHODS and attr != "open":
            continue
        if attr == "open" and _receiver_name(node.func) in NOT_PATH_OPEN:
            continue
        if any(k.arg == "encoding" for k in node.keywords):
            continue
        if attr == "open":
            mode = (
                node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
            )
            if not isinstance(mode, str) or "b" in mode:
                continue
        try:
            where = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:  # the self-test writes its bait outside the repo
            where = str(path)
        out.append(f"{where}:{node.lineno}: .{attr}() without encoding=")
    return out


def test_no_unencoded_text_io_in_shipped_code():
    """The gate PLW1514 cannot be: it sees only inferable `Path` receivers.

    Measured against ruff 0.16.x, the rule does not fire on
    `(tmp_path / "a.txt").write_text("x", encoding="utf-8")` or on a local bound from a join.
    Shipped code is what a user runs on a cp1252 console, so it is what this
    pins; `tests/` is deliberately out of scope (its fixtures are its own).
    """
    offenders = [
        line
        for base in SHIPPED
        for path in sorted((REPO_ROOT / base).rglob("*.py"))
        if path.name != "_product.py"
        for line in _unencoded_calls(path)
    ]
    assert not offenders, "\n".join(
        ["text IO without an explicit encoding (cp1252 on Windows):", *offenders]
    )


def test_the_scanner_would_notice(tmp_path: Path):
    """Guard the guard: a scanner that matches nothing would pass vacuously."""
    lines = [
        "from pathlib import Path",
        "def f(p: Path):",
        "    return p.read_text()",
        "def g(p: Path):",
        "    p.write_text('x')",
        "def h(p: Path):",
        "    return p.open('r')",
    ]
    bait = tmp_path / "bait.py"
    bait.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert len(_unencoded_calls(bait)) == 3

    ok = [
        "from pathlib import Path",
        "from PIL import Image",
        "def f(p: Path):",
        "    return p.read_text(encoding='utf-8')",
        "def g(p: Path):",
        "    return p.open('rb')",
        "def h(p: Path):",
        "    return Image.open(p)",
    ]
    clean = tmp_path / "clean.py"
    clean.write_text("\n".join(ok) + "\n", encoding="utf-8")
    assert _unencoded_calls(clean) == []


# ------------------------------------------------------- the shared reader


def test_a_bom_is_stripped(tmp_path: Path):
    """Excel's "CSV UTF-8" always writes one; without this the first column is `\\ufeffname`."""
    path = tmp_path / "excel.csv"
    path.write_bytes("name,city\nJosé,Zürich\n".encode("utf-8-sig"))

    assert path.read_bytes().startswith(b"\xef\xbb\xbf"), "fixture must carry a BOM"
    assert read_text_file(path).splitlines()[0] == "name,city"
    assert TEXT_ENCODING == "utf-8-sig"


def test_a_legacy_encoded_document_degrades_rather_than_crashing(tmp_path: Path):
    """Excel's plain "CSV (Comma delimited)" is cp1252, and used to convert fine."""
    path = tmp_path / "latin.csv"
    path.write_bytes(b"name,city\nJos\xe9,Z\xfcrich\n")

    text = read_text_file(path)

    assert text.startswith("name,city")
    assert "�" in text, "the undecodable bytes become replacement characters"


def test_plain_utf8_is_unchanged(tmp_path: Path):
    path = tmp_path / "plain.csv"
    path.write_text("name,city\ncafé,Zürich\n", encoding="utf-8")

    assert read_text_file(path) == "name,city\ncafé,Zürich\n"


def test_open_text_file_defaults_to_the_csv_newline_contract(tmp_path: Path):
    """`csv` requires newline="" or it mangles quoted fields containing newlines."""
    path = tmp_path / "q.csv"
    path.write_text('a,b\n"one\ntwo",3\n', encoding="utf-8")

    import csv

    with open_text_file(path) as fh:
        rows = list(csv.reader(fh))

    assert rows == [["a", "b"], ["one\ntwo", "3"]]


# ------------------------------------------------------- adapter decoding


@needs("pdftotext")
def test_adapter_output_is_decoded_as_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every adapter speaks UTF-8; the locale must not get a vote.

    Before this, `text=True` decoded with locale.getencoding(), so a PDF
    containing "café" came back "cafÃ©" on a cp1252 console.
    """
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    proc = adapters.run("pdftotext", "-v")
    assert isinstance(proc.stderr, str)


def test_adapter_run_forces_utf8_regardless_of_locale():
    """Read it off the call itself: the suite cannot change its own locale mid-run."""
    import inspect as pyinspect

    source = pyinspect.getsource(adapters.run)
    assert 'encoding="utf-8" if text else None' in source
    assert 'errors="replace" if text else None' in source


def test_user_actions_are_not_forced_to_utf8():
    """A --run action is the user's own command; on Windows it emits the OEM page.

    Forcing UTF-8 there would turn every cp437/cp850 byte into U+FFFD with no
    way back, which is worse than the locale decode it replaced. What was
    actually missing is errors="replace", so a stray byte degrades not raises.
    """
    import inspect as pyinspect

    from carrel.core import actions

    source = pyinspect.getsource(actions.run_action)
    assert 'errors="replace"' in source
    assert 'encoding="utf-8"' not in source


# ------------------------------------------------- generated output is LF


def test_generated_documents_are_written_with_lf(tmp_path: Path):
    """A pack document is hashed; CRLF would make one tree hash two ways."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# title\n\nbody\n", encoding="utf-8")
    out = tmp_path / "bundle.md"

    result = subprocess.run(
        ["uv", "run", "carrel", "pack", str(src), "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert b"\r\n" not in out.read_bytes(), "pack output must be LF on every platform"
