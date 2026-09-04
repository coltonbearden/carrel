"""Regression tests for the v0.2.0 integration review findings (wave 3).

Each test names the finding it pins down; see docs/BUILD_PLAN.md (v0.2.0, V3.2).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import cli
from carrel.core.db import DeskDB
from carrel.core.output import CarrelInputError

FIXTURES = Path(__file__).parent / "fixtures"


def run(*args: str) -> object:
    return CliRunner().invoke(cli, list(args))


# 1. nonexistent --root -------------------------------------------------------


def test_missing_root_is_a_usage_error(tmp_path: Path):
    res = run("--root", str(tmp_path / "nope"), "index", "--status")
    assert res.exit_code == 2
    assert "nope" in res.output


def test_deskdb_refuses_missing_root(tmp_path: Path):
    with pytest.raises(CarrelInputError, match="not a directory"), DeskDB(tmp_path / "nope"):
        pass
    assert not (tmp_path / "nope").exists()


# 2. diff / audiobook accept documents ---------------------------------------


@needs("pandoc")
def test_diff_two_documents_uses_extracted_text(tmp_path: Path):
    a = tmp_path / "a.docx"
    shutil.copy(FIXTURES / "sample.docx", a)
    res = run("diff", str(a), str(FIXTURES / "sample.odt"), "--json")
    assert res.exit_code in (0, 1), res.output
    data = json.loads(res.output)
    assert data["mode"] == "text"
    assert "PK\\u0003" not in res.output  # never raw zip bytes


def test_audiobook_no_longer_rejects_documents(tmp_path: Path):
    from carrel.commands.audiobook import audiobook_file

    # only the input-type gate is under test: stop at the engine check that follows it
    with pytest.raises(CarrelInputError, match="unknown engine"):
        audiobook_file(FIXTURES / "sample.docx", tmp_path / "unused.mp3", engine="nope")
    with pytest.raises(CarrelInputError, match="cannot narrate"):
        audiobook_file(FIXTURES / "sample.png", tmp_path / "unused.mp3", engine="nope")


# 3. exit codes agree across search / pack --query ----------------------------


def test_search_without_index_exits_4(tmp_path: Path):
    res = run("--root", str(tmp_path), "search", "anything")
    assert res.exit_code == 4


def test_pack_query_bad_fts_syntax_is_usage_error(tmp_path: Path):
    (tmp_path / "a.txt").write_text("alpha beta\n")
    assert run("--root", str(tmp_path), "index", str(tmp_path)).exit_code == 0
    res = run("--root", str(tmp_path), "pack", str(tmp_path), "--query", 'AND OR "')
    assert res.exit_code == 2, res.output


# 4. catalog import stays inside the root ------------------------------------


def test_catalog_import_skips_paths_outside_root(tmp_path: Path):
    root = tmp_path / "desk"
    root.mkdir()
    (root / "in.txt").write_text("inside\n")
    outside = tmp_path / "out.txt"
    outside.write_text("outside\n")
    doc = tmp_path / "cat.json"
    doc.write_text(
        json.dumps(
            {
                "schema": 1,
                "files": [
                    {"path": "in.txt", "tags": ["ok"], "notes": []},
                    {"path": "../out.txt", "tags": ["bad"], "notes": []},
                    {"path": str(outside), "tags": ["bad"], "notes": []},
                ],
            }
        )
    )
    res = run("--root", str(root), "catalog", "import", str(doc), "--json")
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["tags_added"] == 1
    assert data["skipped_outside"] == 2
    export = run("--root", str(root), "catalog", "export")
    assert "out.txt" not in export.output


# 5. xlsx detected by bytes still opens --------------------------------------


def test_misnamed_xlsx_converts(tmp_path: Path):
    pytest.importorskip("openpyxl")
    src = tmp_path / "mystery.zip"
    shutil.copy(FIXTURES / "sample.xlsx", src)
    res = run("convert", str(src), "--to", "csv", "-o", str(tmp_path / "out.csv"))
    assert res.exit_code == 0, res.output
    assert (tmp_path / "out.csv").read_text().strip()


# 7. ocr reports the input type before any overwrite complaint ----------------


def test_ocr_unsupported_type_beats_overwrite_check(tmp_path: Path):
    shutil.copy(FIXTURES / "sample.docx", tmp_path / "sample.docx")
    (tmp_path / "sample.txt").write_text("would be overwritten\n")
    res = run("ocr", str(tmp_path / "sample.docx"))
    assert res.exit_code == 4
    assert "docx" in res.output


# 9. mcp carrel_redact: type check first --------------------------------------


def test_mcp_redact_pdf_without_patterns_points_at_cli():
    import io

    from carrel.commands.mcp import serve

    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "carrel_redact", "arguments": {"path": "b.pdf"}},
    }
    out = io.StringIO()
    serve(io.StringIO(json.dumps(req) + "\n"), out, default_root=FIXTURES)
    result = json.loads(out.getvalue())["result"]
    assert result["isError"] is True
    assert "redact PDFs from the CLI" in result["content"][0]["text"]


# doctor human table keeps [tui] / [office] literally -------------------------


def test_doctor_human_output_keeps_extra_brackets():
    res = run("doctor")
    assert res.exit_code == 0
    assert "carrel[tui]" in res.output


# db: migration path still intact after the root check -----------------------


def test_deskdb_opens_existing_root_and_reports_version(tmp_path: Path):
    with DeskDB(tmp_path) as db:
        assert db.schema_version() == 1
    assert (
        sqlite3.connect(tmp_path / ".carrel" / "carrel.db")
        .execute("PRAGMA user_version")
        .fetchone()[0]
        == 1
    )
