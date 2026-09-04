"""Tests for `carrel doctor` and `carrel mcp`.

Wave-1 note: conftest.py / tests/fixtures/ are built concurrently by another
agent, so this file is self-contained — all inputs are synthesized under
tmp_path with stdlib + Pillow.

The mcp classes (spec 15) additionally use the shared fixtures for office
documents and PDFs; the real stdio subprocess test lives in test_mcp_stdio.py.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import needs

from carrel.cli import COMMANDS, cli
from carrel.commands.doctor import CAPABILITIES, build_report
from carrel.commands.mcp import RESOURCE_TEMPLATES, TOOLS, serve
from carrel.core.db import DeskDB

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_tree(root: Path) -> None:
    """Synthesize a small mixed-type input tree (no shared fixtures)."""
    (root / "notes.txt").write_text("the aardvark manifesto\nsecond line\n")
    (root / "doc.md").write_text("# Heading\n\nSome markdown body text.\n")
    (root / "data.json").write_text(json.dumps({"kind": "sample", "n": 3}))
    sub = root / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("buried text content\n")
    from PIL import Image

    Image.new("RGB", (4, 4), (200, 10, 10)).save(root / "img.png")


def rpc(lines: list[dict | str], root: Path | str = ".") -> list[dict]:
    """Drive serve() in-process; accepts dicts or raw (possibly malformed) lines."""
    raw = "".join((line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines)
    out = io.StringIO()
    serve(io.StringIO(raw), out, default_root=root)
    return [json.loads(ln) for ln in out.getvalue().splitlines()]


def call_tool(name: str, arguments: dict, root: Path | str = ".") -> dict:
    """tools/call round-trip; returns {'isError': bool, 'payload': parsed-json}."""
    (resp,) = rpc(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        ],
        root=root,
    )
    result = resp["result"]
    block = result["content"][0]
    assert block["type"] == "text"
    return {"isError": result["isError"], "payload": json.loads(block["text"])}


def read_resource(uri: str, root: Path | str = ".") -> dict:
    (resp,) = rpc(
        [{"jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": uri}}],
        root=root,
    )
    return resp


def seed_index(root: Path, *names: str) -> None:
    """Seed the desk index via the core API (the index command is another module)."""
    with DeskDB(root) as db:
        for name in names:
            path = root / name
            fid = db.upsert_file(path, ftype="txt")
            db.set_content(fid, path, path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


class TestDoctor:
    def test_human_output_exit_zero(self):
        result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "command capabilities" in result.output
        assert "external tools" in result.output

    def test_json_flag_local(self):
        result = CliRunner().invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        report = json.loads(result.output)
        assert {"product", "python", "adapters", "commands", "icc_dirs", "tesseract_langs"} <= set(
            report
        )

    def test_json_flag_global(self):
        result = CliRunner().invoke(cli, ["--json", "doctor"])
        assert result.exit_code == 0
        json.loads(result.output)

    def test_capability_map_covers_all_commands(self):
        assert set(CAPABILITIES) == set(COMMANDS)

    def test_report_structure(self):
        report = build_report()
        assert report["product"]["name"] == "carrel"
        adapter_names = {a["name"] for a in report["adapters"]}
        assert {"pandoc", "tesseract", "pdftoppm", "ffmpeg"} <= adapter_names
        for row in report["adapters"]:
            if row["found"]:
                assert row["path"] and row["version"] is not None
            else:
                assert row["install_hint"]
        for row in report["commands"]:
            assert row["status"] in ("ok", "degraded", "unavailable")
            # missing must be consistent with the status
            if row["status"] == "ok":
                assert not row["missing"]
        # commands with no external requirements are always ok
        by_cmd = {r["command"]: r for r in report["commands"]}
        # desk is gated on the `tui` extra since D-007, so it is not in this list
        for always_ok in ("pack", "index", "search", "tag", "note", "mcp"):
            assert by_cmd[always_ok]["status"] == "ok"


# ---------------------------------------------------------------------------
# mcp: protocol behavior (in-process)
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = [
    "carrel_search",
    "carrel_pack",
    "carrel_inspect",
    "carrel_tag",
    "carrel_note",
    "carrel_index",
    "carrel_convert",
    "carrel_diff",
    "carrel_redact",
    "carrel_doctor",
]


class TestMcpProtocol:
    def test_initialize_echoes_client_protocol_version(self):
        (resp,) = rpc(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "t"},
                    },
                }
            ]
        )
        assert resp["id"] == 1
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["capabilities"] == {"tools": {}, "resources": {}}
        assert resp["result"]["serverInfo"]["name"] == "carrel"

    def test_initialize_default_protocol_version(self):
        (resp,) = rpc([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}])
        assert resp["result"]["protocolVersion"] == "2025-06-18"

    def test_initialized_notification_is_ignored(self):
        responses = rpc(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        assert len(responses) == 1  # nothing emitted for the notification
        assert responses[0] == {"jsonrpc": "2.0", "id": 2, "result": {}}

    def test_tools_list_has_ten_tools(self):
        (resp,) = rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
        tools = resp["result"]["tools"]
        assert [t["name"] for t in tools] == EXPECTED_TOOLS
        assert len(tools) == 10
        assert tools == TOOLS

    @pytest.mark.parametrize("tool", TOOLS, ids=[t["name"] for t in TOOLS])
    def test_tool_schema_is_valid_object_schema(self, tool):
        assert tool["description"]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)
        # required lists only declared properties
        assert set(schema["required"]) <= set(schema["properties"])
        for name, prop in schema["properties"].items():
            assert prop["type"] in ("string", "integer", "boolean", "array"), name
            if prop["type"] == "array":
                assert prop["items"] == {"type": "string"}

    def test_existing_tools_keep_their_required_inputs(self):
        by_name = {t["name"]: t["inputSchema"] for t in TOOLS}
        assert by_name["carrel_search"]["required"] == ["query"]
        assert by_name["carrel_pack"]["required"] == ["path"]
        assert by_name["carrel_inspect"]["required"] == ["path"]
        assert {"max_bytes", "tree_only", "format", "include", "exclude"} <= set(
            by_name["carrel_pack"]["properties"]
        )
        assert {"types", "tags"} <= set(by_name["carrel_search"]["properties"])
        assert "deep" in by_name["carrel_inspect"]["properties"]

    def test_unknown_method_errors_and_server_keeps_serving(self):
        responses = rpc(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        assert responses[0]["error"]["code"] == -32601
        assert "prompts/list" in responses[0]["error"]["message"]
        assert responses[1]["result"] == {}

    def test_malformed_line_errors_and_server_keeps_serving(self):
        responses = rpc(
            [
                "{this is not json",
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        assert responses[0]["error"]["code"] == -32700
        assert responses[0]["id"] is None
        assert responses[1]["result"] == {}

    def test_non_object_message_is_invalid_request(self):
        (resp,) = rpc(["[1, 2, 3]"])
        assert resp["error"]["code"] == -32600

    def test_unknown_tool_errors(self):
        (resp,) = rpc(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "carrel_nope", "arguments": {}},
                }
            ]
        )
        assert resp["error"]["code"] == -32602

    def test_missing_required_argument_is_tool_error(self):
        res = call_tool("carrel_search", {})
        assert res["isError"] is True
        assert "query" in res["payload"]["error"]
        res = call_tool("carrel_diff", {"a": "x"})
        assert res["isError"] is True
        assert "b" in res["payload"]["error"]

    def test_non_object_arguments_is_tool_error(self):
        res = call_tool("carrel_doctor", ["not", "a", "dict"])
        assert res["isError"] is True

    def test_blank_lines_ignored_eof_clean(self):
        out = io.StringIO()
        serve(io.StringIO("\n\n"), out)  # returns without raising on EOF
        assert out.getvalue() == ""

    def test_mcp_module_owns_no_walk_or_token_estimate(self):
        import carrel.commands.mcp as mcp_mod

        source = Path(mcp_mod.__file__).read_text()
        assert "def _walk" not in source
        assert "def _tokens_est" not in source


# ---------------------------------------------------------------------------
# mcp: search / pack / inspect (delegating to the command modules)
# ---------------------------------------------------------------------------


class TestMcpTools:
    def test_inspect_txt(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "notes.txt")})
        assert res["isError"] is False
        p = res["payload"]
        assert p["type"] == "txt"
        assert p["name"] == "notes.txt"
        assert p["size"] > 0
        assert len(p["sha256"]) == 64
        assert p["mime"] == "text/plain"
        assert p["detail"]["lines"] == 2  # per-type detail comes from inspect.inspect_path

    def test_inspect_png(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "img.png")})
        assert res["isError"] is False
        assert res["payload"]["type"] == "png"
        assert res["payload"]["detail"]["width"] == 4

    def test_inspect_deep_never_errors(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "img.png"), "deep": True})
        assert res["isError"] is False
        assert "exiftool" in res["payload"]  # tag table or "not installed"

    def test_inspect_missing_file_is_tool_error_not_crash(self, tmp_path):
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "ghost.txt")})
        assert res["isError"] is True
        assert "ghost.txt" in res["payload"]["error"]
        assert res["payload"]["exit_code"] == 4

    def test_inspect_relative_path_uses_server_root(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": "notes.txt"}, root=tmp_path)
        assert res["isError"] is False
        assert res["payload"]["name"] == "notes.txt"

    def test_inspect_root_argument_overrides_server_root(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": "notes.txt", "root": str(tmp_path)}, root="/")
        assert res["isError"] is False
        assert res["payload"]["name"] == "notes.txt"

    def test_pack_directory(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path)})
        assert res["isError"] is False
        p = res["payload"]
        assert p["format"] == "json"
        entry_paths = {e["path"] for e in p["entries"]}
        assert {"notes.txt", "doc.md", "data.json", "img.png", "sub/deep.txt"} <= entry_paths
        packed = {f["path"]: f for f in p["files"]}
        assert "aardvark" in packed["notes.txt"]["content"]
        assert "buried" in packed["sub/deep.txt"]["content"]
        assert all(f["tokens_est"] > 0 for f in p["files"])
        # binary image is listed in the entries but never inlined
        assert "img.png" not in packed
        img_entry = next(e for e in p["entries"] if e["path"] == "img.png")
        assert img_entry["skipped"] == "binary"
        # the rendered tree and pack meta come straight from pack.pack_paths
        assert "sub/" in p["tree"] and "img.png" in p["tree"]
        assert p["meta"]["files_included"] == len(p["files"])
        assert p["meta"]["generated_by"].startswith("carrel ")

    def test_pack_tree_only(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path), "tree_only": True})
        p = res["payload"]
        assert p["files"] == []
        assert p["meta"]["tree_only"] is True
        assert len(p["entries"]) >= 5

    def test_pack_max_bytes_budget(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path), "max_bytes": 10})
        p = res["payload"]
        assert p["meta"]["bytes"] <= 10
        assert p["omitted"]  # everything textual was over budget
        assert p["omitted"] == p["meta"]["omitted_budget"]

    def test_pack_single_file(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path / "doc.md")})
        p = res["payload"]
        assert len(p["files"]) == 1
        assert "markdown body" in p["files"][0]["content"]

    def test_pack_include_exclude_globs(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path), "include": ["*.txt"]})
        assert {e["path"] for e in res["payload"]["entries"]} == {"notes.txt", "sub/deep.txt"}
        res = call_tool("carrel_pack", {"path": str(tmp_path), "exclude": ["sub", "*.png"]})
        paths = {e["path"] for e in res["payload"]["entries"]}
        assert "sub/deep.txt" not in paths and "img.png" not in paths
        assert "notes.txt" in paths

    @pytest.mark.parametrize("fmt", ["md", "xml"])
    def test_pack_rendered_formats_return_document(self, tmp_path, fmt):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path / "doc.md"), "format": fmt})
        assert res["isError"] is False
        p = res["payload"]
        assert p["format"] == fmt
        assert "files" not in p
        assert "markdown body" in p["document"]
        if fmt == "xml":
            assert p["document"].startswith("<context ")
        else:
            assert p["document"].startswith("# carrel pack")

    def test_pack_bad_format_is_tool_error(self, tmp_path):
        res = call_tool("carrel_pack", {"path": str(tmp_path), "format": "yaml"})
        assert res["isError"] is True
        assert "format" in res["payload"]["error"]

    def test_pack_missing_path_is_tool_error(self, tmp_path):
        res = call_tool("carrel_pack", {"path": str(tmp_path / "nope")})
        assert res["isError"] is True
        assert "no such path" in res["payload"]["error"]

    def test_pack_office_types_are_extractable_not_binary(self, fixtures):
        res = call_tool("carrel_pack", {"path": str(fixtures), "tree_only": True})
        assert res["isError"] is False
        by_path = {e["path"]: e for e in res["payload"]["entries"]}
        for name in ("sample.docx", "sample.odt", "sample.epub", "sample.rtf", "sample.xlsx"):
            assert by_path[name]["skipped"] != "binary", name
        assert by_path["sample.png"]["skipped"] == "binary"

    @needs("pandoc")
    def test_pack_docx_content_via_pandoc(self, fixtures):
        res = call_tool("carrel_pack", {"path": "sample.docx"}, root=fixtures)
        assert res["isError"] is False
        (entry,) = res["payload"]["files"]
        assert entry["path"] == "sample.docx"
        assert "melodious cartography" in entry["content"]

    def test_search_without_index_is_tool_error(self, tmp_path):
        res = call_tool("carrel_search", {"query": "anything", "root": str(tmp_path)})
        assert res["isError"] is True
        assert "carrel index" in res["payload"]["error"]
        assert not (tmp_path / ".carrel").exists()  # never creates a db as a side effect

    def test_search_finds_indexed_content(self, tmp_path):
        make_tree(tmp_path)
        seed_index(tmp_path, "notes.txt")
        res = call_tool("carrel_search", {"query": "aardvark", "root": str(tmp_path)})
        assert res["isError"] is False
        p = res["payload"]
        assert p["count"] == 1
        assert p["results"][0]["path"] == "notes.txt"
        assert "aardvark" in p["results"][0]["snippet"]
        assert isinstance(p["results"][0]["score"], float)

    def test_search_respects_limit(self, tmp_path):
        make_tree(tmp_path)
        with DeskDB(tmp_path) as db:
            for name in ("notes.txt", "doc.md"):
                fid = db.upsert_file(tmp_path / name, ftype="txt")
                db.set_content(fid, tmp_path / name, "shared common token here")
        res = call_tool("carrel_search", {"query": "common", "root": str(tmp_path), "limit": 1})
        assert res["payload"]["count"] == 1

    def test_search_type_and_tag_filters(self, tmp_path):
        make_tree(tmp_path)
        with DeskDB(tmp_path) as db:
            for name, ftype in (("notes.txt", "txt"), ("doc.md", "md")):
                fid = db.upsert_file(tmp_path / name, ftype=ftype)
                db.set_content(fid, tmp_path / name, "shared common token here")
            db.add_tags(tmp_path / "doc.md", ["work"])
        root = str(tmp_path)
        res = call_tool("carrel_search", {"query": "common", "root": root, "types": ["md"]})
        assert [h["path"] for h in res["payload"]["results"]] == ["doc.md"]
        res = call_tool("carrel_search", {"query": "common", "root": root, "tags": ["work"]})
        assert [h["path"] for h in res["payload"]["results"]] == ["doc.md"]
        res = call_tool("carrel_search", {"query": "common", "root": root, "tags": ["absent"]})
        assert res["payload"]["count"] == 0

    def test_search_bad_type_and_bad_query_are_tool_errors(self, tmp_path):
        make_tree(tmp_path)
        seed_index(tmp_path, "notes.txt")
        res = call_tool("carrel_search", {"query": "x", "root": str(tmp_path), "types": ["wav"]})
        assert res["isError"] is True and "wav" in res["payload"]["error"]
        res = call_tool("carrel_search", {"query": 'AND "', "root": str(tmp_path)})
        assert res["isError"] is True and "bad search query" in res["payload"]["error"]


# ---------------------------------------------------------------------------
# mcp: tag / note / index
# ---------------------------------------------------------------------------


class TestMcpDeskTools:
    def test_tag_add_ls_find_rm_round_trip(self, tmp_path):
        make_tree(tmp_path)
        root = str(tmp_path)
        res = call_tool(
            "carrel_tag", {"action": "add", "path": "notes.txt", "tags": ["Work", "urgent"]}, root
        )
        assert res["isError"] is False
        assert res["payload"] == {"path": "notes.txt", "tags": ["urgent", "work"]}

        res = call_tool("carrel_tag", {"action": "ls", "path": "notes.txt"}, root)
        assert res["payload"]["tags"] == ["urgent", "work"]

        call_tool("carrel_tag", {"action": "add", "path": "doc.md", "tags": ["work"]}, root)
        res = call_tool("carrel_tag", {"action": "find", "tags": ["work"]}, root)
        assert res["payload"]["paths"] == ["doc.md", "notes.txt"]
        res = call_tool("carrel_tag", {"action": "find", "tags": ["work", "urgent"]}, root)
        assert res["payload"]["paths"] == ["notes.txt"]

        res = call_tool("carrel_tag", {"action": "rm", "path": "notes.txt", "tags": ["work"]}, root)
        assert res["payload"]["tags"] == ["urgent"]

    def test_tag_without_db_returns_empty_and_creates_nothing(self, tmp_path):
        make_tree(tmp_path)
        root = str(tmp_path)
        assert (
            call_tool("carrel_tag", {"action": "ls", "path": "notes.txt"}, root)["payload"]["tags"]
            == []
        )
        assert (
            call_tool("carrel_tag", {"action": "find", "tags": ["x"]}, root)["payload"]["paths"]
            == []
        )
        assert (
            call_tool("carrel_tag", {"action": "rm", "path": "notes.txt", "tags": ["x"]}, root)[
                "payload"
            ]["tags"]
            == []
        )
        assert not (tmp_path / ".carrel").exists()

    def test_tag_argument_errors(self, tmp_path):
        make_tree(tmp_path)
        root = str(tmp_path)
        assert call_tool("carrel_tag", {"action": "find"}, root)["isError"] is True
        assert call_tool("carrel_tag", {"action": "add", "tags": ["x"]}, root)["isError"] is True
        assert call_tool("carrel_tag", {"action": "add", "path": "notes.txt"}, root)["isError"]
        res = call_tool("carrel_tag", {"action": "add", "path": "ghost.txt", "tags": ["x"]}, root)
        assert res["isError"] is True and "no such file" in res["payload"]["error"]
        res = call_tool("carrel_tag", {"action": "zap", "path": "notes.txt"}, root)
        assert res["isError"] is True and "action" in res["payload"]["error"]
        res = call_tool("carrel_tag", {"action": "ls", "path": "notes.txt", "tags": "nope"}, root)
        assert res["isError"] is False  # a lone string is accepted as a one-item list

    def test_note_add_then_ls(self, tmp_path):
        make_tree(tmp_path)
        root = str(tmp_path)
        res = call_tool(
            "carrel_note", {"action": "add", "path": "notes.txt", "body": "read this twice"}, root
        )
        assert res["isError"] is False
        assert res["payload"]["path"] == "notes.txt"
        assert res["payload"]["body"] == "read this twice"
        assert isinstance(res["payload"]["id"], int)
        assert res["payload"]["created"]

        call_tool("carrel_note", {"action": "add", "path": "notes.txt", "body": "second"}, root)
        res = call_tool("carrel_note", {"action": "ls", "path": "notes.txt"}, root)
        bodies = [n["body"] for n in res["payload"]["notes"]]
        assert set(bodies) == {"read this twice", "second"}
        assert all(n["created"] for n in res["payload"]["notes"])

    def test_note_errors_and_empty_ls(self, tmp_path):
        make_tree(tmp_path)
        root = str(tmp_path)
        res = call_tool("carrel_note", {"action": "ls", "path": "notes.txt"}, root)
        assert res["payload"] == {"path": str(tmp_path / "notes.txt"), "notes": []}
        assert not (tmp_path / ".carrel").exists()
        res = call_tool("carrel_note", {"action": "add", "path": "notes.txt"}, root)
        assert res["isError"] is True and "body" in res["payload"]["error"]
        res = call_tool("carrel_note", {"action": "add", "path": "ghost", "body": "x"}, root)
        assert res["isError"] is True and "no such file" in res["payload"]["error"]
        res = call_tool("carrel_note", {"action": "rm", "path": "notes.txt"}, root)
        assert res["isError"] is True

    @staticmethod
    def _index_paths():
        import carrel.commands.index as index_mod

        return getattr(index_mod, "index_paths", None)

    def test_index_then_search_hits(self, tmp_path):
        if self._index_paths() is None:
            pytest.skip("index.index_paths not in this build (spec 17 seam)")
        make_tree(tmp_path)
        root = str(tmp_path)
        res = call_tool("carrel_index", {}, root)
        assert res["isError"] is False, res["payload"]
        p = res["payload"]
        assert {"indexed", "skipped", "pruned"} <= set(p)
        assert p["indexed"] >= 3
        res = call_tool("carrel_search", {"query": "aardvark"}, root)
        assert res["payload"]["count"] == 1
        # second run: everything fresh → skipped; prune after deleting a file
        (tmp_path / "doc.md").unlink()
        res = call_tool("carrel_index", {"prune": True}, root)
        assert res["payload"]["indexed"] == 0
        assert res["payload"]["pruned"] == 1

    def test_index_update_mode_single_file(self, tmp_path):
        if self._index_paths() is None:
            pytest.skip("index.index_paths not in this build (spec 17 seam)")
        make_tree(tmp_path)
        res = call_tool("carrel_index", {"paths": ["sub/deep.txt"], "update": True}, str(tmp_path))
        assert res["isError"] is False, res["payload"]
        assert res["payload"]["indexed"] == 1
        res = call_tool("carrel_search", {"query": "buried"}, str(tmp_path))
        assert [h["path"] for h in res["payload"]["results"]] == ["sub/deep.txt"]

    def test_index_unavailable_without_index_paths_is_tool_error(self, tmp_path):
        if self._index_paths() is not None:
            pytest.skip("index.index_paths present — the unavailable branch is dead here")
        res = call_tool("carrel_index", {}, str(tmp_path))
        assert res["isError"] is True
        assert "unavailable" in res["payload"]["error"]
        assert "carrel index" in res["payload"]["error"]


# ---------------------------------------------------------------------------
# mcp: convert / diff / redact / doctor
# ---------------------------------------------------------------------------


class TestMcpFileTools:
    def test_convert_md_to_txt_returns_content(self, tmp_path, tmp_copy):
        src = tmp_copy("sample.md")
        res = call_tool("carrel_convert", {"path": "sample.md", "to": "txt"}, str(tmp_path))
        assert res["isError"] is False, res["payload"]
        p = res["payload"]
        assert p["type"] == "txt"
        assert p["output"] == str(src.with_suffix(".txt"))
        assert Path(p["output"]).is_file()
        assert "melodious cartography" in p["content"]
        assert p["truncated"] is False
        assert p["via"]

    def test_convert_out_dir_and_force(self, tmp_path, tmp_copy):
        tmp_copy("sample.json")
        out_dir = tmp_path / "out"
        args = {"path": "sample.json", "to": "csv", "out_dir": "out"}
        res = call_tool("carrel_convert", args, str(tmp_path))
        assert res["isError"] is False, res["payload"]
        assert res["payload"]["output"] == str(out_dir / "sample.csv")
        assert "content" in res["payload"]  # csv is a text type
        res = call_tool("carrel_convert", args, str(tmp_path))
        assert res["isError"] is True and "--force" in res["payload"]["error"]
        res = call_tool("carrel_convert", {**args, "force": True}, str(tmp_path))
        assert res["isError"] is False

    def test_convert_binary_target_has_no_content(self, tmp_path, tmp_copy):
        tmp_copy("sample.png")
        res = call_tool("carrel_convert", {"path": "sample.png", "to": "jpg"}, str(tmp_path))
        assert res["isError"] is False, res["payload"]
        assert res["payload"]["type"] == "jpg"
        assert "content" not in res["payload"]
        assert (tmp_path / "sample.jpg").is_file()

    def test_convert_unsupported_target_is_tool_error(self, tmp_path, tmp_copy):
        tmp_copy("sample.md")
        res = call_tool("carrel_convert", {"path": "sample.md", "to": "wav"}, str(tmp_path))
        assert res["isError"] is True
        assert "unknown target type 'wav'" in res["payload"]["error"]
        res = call_tool("carrel_convert", {"path": "sample.md", "to": "ico"}, str(tmp_path))
        assert res["isError"] is True
        assert "cannot convert md" in res["payload"]["error"]
        assert res["payload"]["exit_code"] == 4

    def test_convert_missing_binary_error_carries_install_hint(self, tmp_path, tmp_copy):
        from carrel.core import adapters

        if adapters.have("pandoc"):
            pytest.skip("pandoc installed — the missing-binary branch is dead here")
        tmp_copy("sample.html")
        res = call_tool("carrel_convert", {"path": "sample.html", "to": "md"}, str(tmp_path))
        assert res["isError"] is True
        assert "pandoc" in res["payload"]["error"]
        assert "install" in res["payload"]["error"]
        assert res["payload"]["exit_code"] == 3

    def test_diff_identical_csv(self, fixtures):
        res = call_tool("carrel_diff", {"a": "sample.csv", "b": "sample.csv"}, str(fixtures))
        assert res["isError"] is False
        p = res["payload"]
        assert p["differ"] is False
        assert p["identical"] is True
        assert p["mode"] == "struct"

    def test_diff_differing_text_is_data_not_error(self, tmp_path):
        (tmp_path / "a.txt").write_text("one\ntwo\n")
        (tmp_path / "b.txt").write_text("one\nthree\n")
        res = call_tool("carrel_diff", {"a": "a.txt", "b": "b.txt", "mode": "text"}, str(tmp_path))
        assert res["isError"] is False
        p = res["payload"]
        assert p["differ"] is True
        assert p["added"] == 1 and p["removed"] == 1
        assert "-two" in p["diff"] and "+three" in p["diff"]

    def test_diff_bad_mode_and_missing_file(self, tmp_path, fixtures):
        res = call_tool(
            "carrel_diff", {"a": "sample.csv", "b": "sample.csv", "mode": "x"}, fixtures
        )
        assert res["isError"] is True and "mode" in res["payload"]["error"]
        res = call_tool("carrel_diff", {"a": "sample.csv", "b": "ghost.csv"}, fixtures)
        assert res["isError"] is True and "ghost.csv" in res["payload"]["error"]

    def test_redact_email_returns_content_and_never_writes(self, tmp_path):
        src = tmp_path / "contacts.txt"
        src.write_text("mail jane.doe@example.com or bob@example.org today\n")
        before = sha256(src)
        res = call_tool("carrel_redact", {"path": "contacts.txt", "builtin": ["email"]}, tmp_path)
        assert res["isError"] is False, res["payload"]
        p = res["payload"]
        assert p["hits"] == 2
        assert p["matches"] == {"email": 2}
        assert "example.com" not in p["content"]
        assert "█" in p["content"]
        assert sha256(src) == before  # original untouched
        assert sorted(x.name for x in tmp_path.iterdir()) == ["contacts.txt"]  # nothing written

    def test_redact_custom_pattern_and_replacement(self, tmp_path):
        (tmp_path / "log.txt").write_text("token=abc123 token=def456\n")
        res = call_tool(
            "carrel_redact",
            {"path": "log.txt", "pattern": [r"token=\w+"], "replacement": "[X]"},
            tmp_path,
        )
        assert res["payload"]["hits"] == 2
        assert res["payload"]["content"] == "[X] [X]\n"

    def test_redact_pdf_is_tool_error_pointing_at_cli(self, fixtures):
        res = call_tool("carrel_redact", {"path": "b.pdf", "builtin": ["email"]}, str(fixtures))
        assert res["isError"] is True
        assert "carrel redact" in res["payload"]["error"]
        assert "-o" in res["payload"]["error"]

    def test_redact_argument_errors(self, tmp_path, fixtures):
        (tmp_path / "t.txt").write_text("x\n")
        res = call_tool("carrel_redact", {"path": "t.txt"}, tmp_path)
        assert res["isError"] is True and "nothing to redact" in res["payload"]["error"]
        res = call_tool("carrel_redact", {"path": "t.txt", "builtin": ["nope"]}, tmp_path)
        assert res["isError"] is True and "nope" in res["payload"]["error"]
        res = call_tool("carrel_redact", {"path": "t.txt", "pattern": ["("]}, tmp_path)
        assert res["isError"] is True and "bad --pattern" in res["payload"]["error"]
        res = call_tool("carrel_redact", {"path": "sample.png", "builtin": ["email"]}, fixtures)
        assert res["isError"] is True and "png" in res["payload"]["error"]

    def test_redact_json_stays_valid_or_errors(self, tmp_path):
        (tmp_path / "d.json").write_text('{"mail": "a@b.co"}')
        res = call_tool("carrel_redact", {"path": "d.json", "builtin": ["email"]}, tmp_path)
        assert res["isError"] is False
        assert json.loads(res["payload"]["content"]) == {"mail": "█"}
        res = call_tool(
            "carrel_redact", {"path": "d.json", "builtin": ["email"], "replacement": '"'}, tmp_path
        )
        assert res["isError"] is True and "syntax" in res["payload"]["error"]

    def test_doctor_payload(self):
        res = call_tool("carrel_doctor", {})
        assert res["isError"] is False
        p = res["payload"]
        assert {"adapters", "capabilities", "commands", "product"} <= set(p)
        assert set(p["capabilities"]) == set(COMMANDS)
        for spec in p["capabilities"].values():
            assert {"required", "optional", "note"} <= set(spec)
        assert p["capabilities"]["mcp"] == {
            "required": [],
            "optional": [],
            "note": CAPABILITIES["mcp"]["note"],
        }
        assert p["commands"] == build_report()["commands"]


# ---------------------------------------------------------------------------
# mcp: resources
# ---------------------------------------------------------------------------


class TestMcpResources:
    def test_templates_list(self):
        (resp,) = rpc([{"jsonrpc": "2.0", "id": 1, "method": "resources/templates/list"}])
        templates = resp["result"]["resourceTemplates"]
        assert templates == RESOURCE_TEMPLATES
        assert [t["uriTemplate"] for t in templates] == [
            "carrel://file/{path}",
            "carrel://search/{query}",
        ]
        assert [t["mimeType"] for t in templates] == ["text/plain", "application/json"]
        assert all(t["name"] for t in templates)

    def test_resources_list_is_empty(self):
        (resp,) = rpc([{"jsonrpc": "2.0", "id": 1, "method": "resources/list"}])
        assert resp["result"] == {"resources": []}

    def test_read_file_returns_fixture_text(self, fixtures):
        resp = read_resource("carrel://file/sample.txt", root=fixtures)
        (block,) = resp["result"]["contents"]
        assert block["uri"] == "carrel://file/sample.txt"
        assert block["mimeType"] == "text/plain"
        assert "quixotic zephyr" in block["text"]

    def test_read_file_url_decodes_and_accepts_absolute(self, tmp_path):
        (tmp_path / "with space.txt").write_text("spaced out\n")
        resp = read_resource("carrel://file/with%20space.txt", root=tmp_path)
        assert resp["result"]["contents"][0]["text"] == "spaced out\n"
        from urllib.parse import quote

        resp = read_resource("carrel://file/" + quote(str(tmp_path / "with space.txt")))
        assert resp["result"]["contents"][0]["text"] == "spaced out\n"

    @pytest.mark.parametrize(
        "uri",
        [
            "bogus://x",
            "carrel://nope/sample.txt",
            "carrel://file/",
            "carrel://file/does-not-exist.txt",
            "carrel://file/sub",  # a directory is not a readable resource
            "carrel://search/",
            "",
        ],
    )
    def test_unknown_uri_is_resource_not_found(self, tmp_path, uri):
        make_tree(tmp_path)
        resp = read_resource(uri, root=tmp_path)
        assert resp["error"]["code"] == -32002
        assert "resource not found" in resp["error"]["message"]

    def test_read_search_returns_search_payload_json(self, tmp_path):
        make_tree(tmp_path)
        seed_index(tmp_path, "notes.txt")
        resp = read_resource("carrel://search/aardvark%20manifesto", root=tmp_path)
        (block,) = resp["result"]["contents"]
        assert block["mimeType"] == "application/json"
        payload = json.loads(block["text"])
        assert payload["query"] == "aardvark manifesto"
        assert payload["count"] == 1
        assert payload["results"][0]["path"] == "notes.txt"

    def test_read_search_without_index_is_rpc_error_not_crash(self, tmp_path):
        responses = rpc(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "resources/read",
                    "params": {"uri": "carrel://search/anything"},
                },
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ],
            root=tmp_path,
        )
        assert responses[0]["error"]["code"] == -32603
        assert "carrel index" in responses[0]["error"]["message"]
        assert responses[1]["result"] == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
