"""Tests for `carrel doctor` and `carrel mcp`.

Wave-1 note: conftest.py / tests/fixtures/ are built concurrently by another
agent, so this file is self-contained — all inputs are synthesized under
tmp_path with stdlib + Pillow.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from carrel.cli import COMMANDS, cli
from carrel.commands.doctor import CAPABILITIES, build_report
from carrel.commands.mcp import TOOLS, serve
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
        for always_ok in ("pack", "index", "search", "tag", "note", "mcp", "desk"):
            assert by_cmd[always_ok]["status"] == "ok"


# ---------------------------------------------------------------------------
# mcp: protocol behavior (in-process)
# ---------------------------------------------------------------------------


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
        assert resp["result"]["capabilities"] == {"tools": {}}
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

    def test_tools_list_has_three_tools_with_schemas(self):
        (resp,) = rpc([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
        tools = resp["result"]["tools"]
        assert [t["name"] for t in tools] == ["carrel_search", "carrel_pack", "carrel_inspect"]
        for tool in tools:
            assert tool["description"]
            assert tool["inputSchema"]["type"] == "object"
            assert tool["inputSchema"]["required"]
        assert tools == TOOLS

    def test_unknown_method_errors_and_server_keeps_serving(self):
        responses = rpc(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ]
        )
        assert responses[0]["error"]["code"] == -32601
        assert "resources/list" in responses[0]["error"]["message"]
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

    def test_blank_lines_ignored_eof_clean(self):
        out = io.StringIO()
        serve(io.StringIO("\n\n"), out)  # returns without raising on EOF
        assert out.getvalue() == ""


# ---------------------------------------------------------------------------
# mcp: tool bodies
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

    def test_inspect_png(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "img.png")})
        assert res["isError"] is False
        assert res["payload"]["type"] == "png"

    def test_inspect_missing_file_is_tool_error_not_crash(self, tmp_path):
        res = call_tool("carrel_inspect", {"path": str(tmp_path / "ghost.txt")})
        assert res["isError"] is True
        assert "ghost.txt" in res["payload"]["error"]

    def test_inspect_relative_path_uses_server_root(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_inspect", {"path": "notes.txt"}, root=tmp_path)
        assert res["isError"] is False
        assert res["payload"]["name"] == "notes.txt"

    def test_pack_directory(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path)})
        assert res["isError"] is False
        p = res["payload"]
        tree_paths = {e["path"] for e in p["tree"]}
        assert {"notes.txt", "doc.md", "data.json", "img.png", "sub/deep.txt"} <= tree_paths
        packed = {f["path"]: f for f in p["files"]}
        assert "aardvark" in packed["notes.txt"]["content"]
        assert "buried" in packed["sub/deep.txt"]["content"]
        assert all(f["tokens_est"] > 0 for f in p["files"])
        # binary image is listed in the tree but never inlined
        assert "img.png" not in packed
        img_entry = next(e for e in p["tree"] if e["path"] == "img.png")
        assert img_entry["skipped"] == "binary"

    def test_pack_tree_only(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path), "tree_only": True})
        p = res["payload"]
        assert p["files"] == []
        assert p["meta"]["tree_only"] is True
        assert len(p["tree"]) >= 5

    def test_pack_max_bytes_budget(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path), "max_bytes": 10})
        p = res["payload"]
        assert p["meta"]["content_bytes"] <= 10
        assert p["omitted"]  # everything textual was over budget

    def test_pack_single_file(self, tmp_path):
        make_tree(tmp_path)
        res = call_tool("carrel_pack", {"path": str(tmp_path / "doc.md")})
        p = res["payload"]
        assert len(p["files"]) == 1
        assert "markdown body" in p["files"][0]["content"]

    def test_search_without_index_is_tool_error(self, tmp_path):
        res = call_tool("carrel_search", {"query": "anything", "root": str(tmp_path)})
        assert res["isError"] is True
        assert "carrel index" in res["payload"]["error"]

    def test_search_finds_indexed_content(self, tmp_path):
        make_tree(tmp_path)
        with DeskDB(tmp_path) as db:  # seed the index via core API (index cmd is another module)
            fid = db.upsert_file(tmp_path / "notes.txt", ftype="txt")
            db.set_content(fid, tmp_path / "notes.txt", (tmp_path / "notes.txt").read_text())
        res = call_tool("carrel_search", {"query": "aardvark", "root": str(tmp_path)})
        assert res["isError"] is False
        p = res["payload"]
        assert p["count"] == 1
        assert p["results"][0]["path"] == "notes.txt"
        assert "aardvark" in p["results"][0]["snippet"]

    def test_search_respects_limit(self, tmp_path):
        make_tree(tmp_path)
        with DeskDB(tmp_path) as db:
            for name in ("notes.txt", "doc.md"):
                fid = db.upsert_file(tmp_path / name, ftype="txt")
                db.set_content(fid, tmp_path / name, "shared common token here")
        res = call_tool("carrel_search", {"query": "common", "root": str(tmp_path), "limit": 1})
        assert res["payload"]["count"] == 1


# ---------------------------------------------------------------------------
# mcp: real subprocess over stdio pipes
# ---------------------------------------------------------------------------


class TestMcpSubprocess:
    def test_stdio_handshake_and_tool_call(self, tmp_path):
        make_tree(tmp_path)
        lines = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "carrel_inspect",
                    "arguments": {"path": str(tmp_path / "notes.txt")},
                },
            },
            {"jsonrpc": "2.0", "id": 4, "method": "no/such/method"},
        ]
        proc = subprocess.run(  # noqa: PLW1510 — tests inspect returncode
            [
                sys.executable,
                "-c",
                "import sys; sys.argv = ['carrel', 'mcp']; from carrel.cli import main; main()",
            ],
            input="".join(json.dumps(m) + "\n" for m in lines),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr  # EOF -> clean exit
        responses = [json.loads(ln) for ln in proc.stdout.splitlines()]
        assert [r["id"] for r in responses] == [1, 2, 3, 4]

        init = responses[0]["result"]
        assert init["protocolVersion"] == "2025-06-18"
        assert init["serverInfo"]["name"] == "carrel"

        names = [t["name"] for t in responses[1]["result"]["tools"]]
        assert names == ["carrel_search", "carrel_pack", "carrel_inspect"]

        call = responses[2]["result"]
        assert call["isError"] is False
        payload = json.loads(call["content"][0]["text"])
        assert payload["type"] == "txt" and payload["name"] == "notes.txt"

        assert responses[3]["error"]["code"] == -32601


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
