"""`carrel mcp` over real stdio pipes: spawn the CLI, speak newline-delimited
JSON-RPC to it, and check the transport contract end to end (spec 15).

The in-process protocol/tool tests live in test_mcp_doctor.py; this file only
exercises what a subprocess can prove: framing (one JSON object per stdout
line, nothing else on stdout), --root plumbing, resources over the wire, and a
clean exit 0 on EOF.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TIMEOUT = 60


def make_tree(root: Path) -> None:
    (root / "notes.txt").write_text("the aardvark manifesto\nsecond line\n")
    (root / "doc.md").write_text("# Heading\n\nSome markdown body text.\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("buried text content\n")


def run_server(messages: list[dict | str], root: Path) -> subprocess.CompletedProcess[str]:
    """Spawn `python -m carrel.cli --root ROOT mcp`, feed messages, close stdin (EOF)."""
    raw = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
    return subprocess.run(
        [sys.executable, "-m", "carrel.cli", "--root", str(root), "mcp"],
        input=raw,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )


def parse_lines(stdout: str) -> list[dict]:
    """Every stdout line must be exactly one JSON object (no banners, no prompts)."""
    responses = []
    for line in stdout.splitlines():
        obj = json.loads(line)
        assert isinstance(obj, dict), line
        assert obj["jsonrpc"] == "2.0", line
        responses.append(obj)
    return responses


def tool_payload(resp: dict) -> tuple[bool, dict]:
    result = resp["result"]
    (block,) = result["content"]
    assert block["type"] == "text"
    return result["isError"], json.loads(block["text"])


class TestMcpStdio:
    def test_full_session_over_pipes(self, tmp_path):
        make_tree(tmp_path)
        proc = run_server(
            [
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
                    "params": {"name": "carrel_inspect", "arguments": {"path": "notes.txt"}},
                },
                {"jsonrpc": "2.0", "id": 4, "method": "resources/templates/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "resources/read",
                    "params": {"uri": "carrel://file/sub/deep.txt"},
                },
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "resources/read",
                    "params": {"uri": "carrel://nope/x"},
                },
                {"jsonrpc": "2.0", "id": 7, "method": "no/such/method"},
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stderr  # EOF -> clean exit
        assert proc.stderr == "", proc.stderr  # nothing leaks onto stderr in a normal session
        responses = parse_lines(proc.stdout)
        # the notification produced no line; every request got exactly one
        assert [r["id"] for r in responses] == [1, 2, 3, 4, 5, 6, 7]

        init = responses[0]["result"]
        assert init["protocolVersion"] == "2025-06-18"
        assert init["capabilities"] == {"tools": {}, "resources": {}}
        assert init["serverInfo"]["name"] == "carrel"
        assert init["serverInfo"]["version"]

        tools = responses[1]["result"]["tools"]
        assert len(tools) == 10
        assert tools[0]["name"] == "carrel_search"
        assert {"carrel_tag", "carrel_note", "carrel_convert", "carrel_doctor"} <= {
            t["name"] for t in tools
        }

        is_error, payload = tool_payload(responses[2])
        assert is_error is False
        assert payload["type"] == "txt" and payload["name"] == "notes.txt"
        assert payload["path"] == str(tmp_path / "notes.txt")  # relative path -> --root

        templates = responses[3]["result"]["resourceTemplates"]
        assert [t["uriTemplate"] for t in templates] == [
            "carrel://file/{path}",
            "carrel://search/{query}",
        ]

        (block,) = responses[4]["result"]["contents"]
        assert block["mimeType"] == "text/plain"
        assert block["text"] == "buried text content\n"

        assert responses[5]["error"]["code"] == -32002
        assert responses[6]["error"]["code"] == -32601

    def test_tool_error_and_parse_error_keep_server_alive(self, tmp_path):
        make_tree(tmp_path)
        proc = run_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "carrel_search", "arguments": {"query": "x"}},
                },
                "{not json at all",
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "carrel_inspect", "arguments": {}},
                },
                {"jsonrpc": "2.0", "id": 4, "method": "ping"},
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        assert [r.get("id") for r in responses] == [1, None, 3, 4]

        is_error, payload = tool_payload(responses[0])  # no index under --root
        assert is_error is True
        assert "carrel index" in payload["error"]
        assert not (tmp_path / ".carrel").exists()

        assert responses[1]["error"]["code"] == -32700

        is_error, payload = tool_payload(responses[2])  # missing required arg
        assert is_error is True
        assert "path" in payload["error"]

        assert responses[3]["result"] == {}

    def test_eof_without_messages_exits_zero(self, tmp_path):
        proc = run_server([], tmp_path)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == ""

    def test_pack_over_pipes_uses_pack_paths(self, tmp_path):
        make_tree(tmp_path)
        proc = run_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "carrel_pack", "arguments": {"path": ".", "format": "md"}},
                },
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        (resp,) = parse_lines(proc.stdout)
        is_error, payload = tool_payload(resp)
        assert is_error is False
        assert payload["document"].startswith("# carrel pack")
        assert "buried text content" in payload["document"]
        assert {e["path"] for e in payload["entries"]} == {"notes.txt", "doc.md", "sub/deep.txt"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
