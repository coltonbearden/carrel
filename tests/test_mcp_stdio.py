"""`carrel mcp` over real stdio pipes: spawn the CLI, speak newline-delimited
JSON-RPC to it, and check the transport contract end to end (spec 15).

The in-process protocol/tool tests live in test_mcp_doctor.py; this file only
exercises what a subprocess can prove: framing (one JSON object per stdout
line, nothing else on stdout), --root plumbing, resources over the wire, and a
clean exit 0 on EOF.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import needs

from carrel.commands.mcp import DEFAULT_PROTOCOL_VERSION, TOOLS

TIMEOUT = 60


def make_tree(root: Path) -> None:
    (root / "notes.txt").write_text("the aardvark manifesto\nsecond line\n")
    (root / "doc.md").write_text("# Heading\n\nSome markdown body text.\n")
    sub = root / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("buried text content\n")


def run_server(
    messages: list[dict | str], root: Path, *, args: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Spawn `python -m carrel.cli --root ROOT mcp [args]`, feed messages, close stdin (EOF)."""
    raw = "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages)
    return subprocess.run(
        [sys.executable, "-m", "carrel.cli", "--root", str(root), "mcp", *args],
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
        assert len(tools) == 14
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


def tool_call(mid: int, name: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def resource_read(mid: int, uri: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "method": "resources/read", "params": {"uri": uri}}


class TestMcpRootBoundary:
    """`carrel mcp` reads and writes only under the directory it was started in.

    SECURITY.md counts a read outside that directory as a vulnerability, so
    every one of these is a claim the docs make on the server's behalf.
    """

    @staticmethod
    def desk_and_secret(tmp_path: Path) -> tuple[Path, Path]:
        desk = tmp_path / "desk"
        desk.mkdir()
        make_tree(desk)
        secret = tmp_path / "secret.txt"
        secret.write_text("the passphrase is hunter2\n")
        return desk, secret

    def test_tool_paths_outside_the_root_are_refused(self, tmp_path):
        desk, secret = self.desk_and_secret(tmp_path)
        proc = run_server(
            [
                tool_call(1, "carrel_inspect", {"path": str(secret)}),
                tool_call(2, "carrel_inspect", {"path": "/etc/hostname"}),
                tool_call(3, "carrel_inspect", {"path": "../secret.txt"}),
                tool_call(4, "carrel_inspect", {"path": "notes.txt"}),
            ],
            desk,
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        for resp in responses[:3]:
            is_error, payload = tool_payload(resp)
            assert is_error is True, payload
            assert "outside the server root" in payload["error"], payload
            assert payload["exit_code"] == 2, payload
        # nothing was read: the refusal names the path, never its contents
        assert "hunter2" not in proc.stdout
        is_error, payload = tool_payload(responses[3])  # inside the root, unaffected
        assert is_error is False and payload["name"] == "notes.txt"

    def test_a_client_root_outside_the_server_root_is_refused(self, tmp_path):
        desk, _ = self.desk_and_secret(tmp_path)
        proc = run_server(
            [tool_call(1, "carrel_search", {"query": "x", "root": str(tmp_path)})], desk
        )
        is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
        assert is_error is True
        assert "outside the server root" in payload["error"], payload

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_a_symlink_out_of_the_root_is_refused_not_followed(self, tmp_path):
        desk, secret = self.desk_and_secret(tmp_path)
        (desk / "escape.txt").symlink_to(secret)
        proc = run_server([tool_call(1, "carrel_inspect", {"path": "escape.txt"})], desk)
        is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
        assert is_error is True, payload
        assert "outside the server root" in payload["error"], payload
        assert "hunter2" not in proc.stdout

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_a_walk_does_not_follow_a_symlinked_file_out_of_the_root(self, tmp_path):
        """Skipping symlinked *directories* is not enough: the file loop reads links.

        `Desk.resolve` only covers paths the client names. `pack`, `index`,
        `refs` and `fields` find their own by walking, and every one of those
        walkers followed a symlinked file — so a link planted in the desk read
        a file outside it, and `index` then stored the contents where
        `carrel_search` would serve them.
        """
        desk, secret = self.desk_and_secret(tmp_path)
        (desk / "sub" / "leak.txt").symlink_to(secret)

        proc = run_server(
            [
                tool_call(1, "carrel_pack", {"path": "."}),
                tool_call(2, "carrel_index", {}),
                # "passphrase", not "hunter2": the query is echoed in the reply,
                # so searching for the marker would defeat the stdout assertion
                tool_call(3, "carrel_search", {"query": "passphrase"}),
                tool_call(4, "carrel_refs", {"path": "."}),
                tool_call(5, "carrel_fields", {"path": "."}),
            ],
            desk,
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        assert "hunter2" not in proc.stdout

        _, pack = tool_payload(responses[0])
        assert "sub/leak.txt" not in {e["path"] for e in pack["entries"]}
        assert "sub/deep.txt" in {e["path"] for e in pack["entries"]}, "the real file still packs"
        _, search = tool_payload(responses[2])
        assert search["count"] == 0, search
        for resp in (responses[3], responses[4]):
            _, payload = tool_payload(resp)
            names = {Path(f["path"]).name for f in payload["files"]}
            assert "leak.txt" not in names, payload
            # both directions: `not any(...)` over an empty list passes, and an
            # unbounded ancestor-.gitignore walk really does empty these two
            assert "deep.txt" in names, payload

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_allow_outside_root_also_lifts_the_walk_boundary(self, tmp_path):
        """The flag means one thing, so it must lift the walk too, not only named paths."""
        desk, secret = self.desk_and_secret(tmp_path)
        (desk / "sub" / "leak.txt").symlink_to(secret)

        proc = run_server(
            [tool_call(1, "carrel_pack", {"path": "."})], desk, args=("--allow-outside-root",)
        )
        _, pack = tool_payload(parse_lines(proc.stdout)[0])
        assert "sub/leak.txt" in {e["path"] for e in pack["entries"]}

    def test_write_arguments_outside_the_root_are_refused(self, tmp_path):
        """`out_dir` and the `paths` array are the write surface; they need the boundary too."""
        desk, _ = self.desk_and_secret(tmp_path)
        (desk / "note.md").write_text("# hi\n")
        outside = tmp_path / "escape"

        proc = run_server(
            [
                tool_call(2, "carrel_index", {"paths": [str(tmp_path / "secret.txt")]}),
                tool_call(
                    1, "carrel_convert", {"path": "note.md", "to": "txt", "out_dir": str(outside)}
                ),
            ],
            desk,
        )
        for resp in parse_lines(proc.stdout):
            is_error, payload = tool_payload(resp)
            assert is_error is True, payload
            assert "outside the server root" in payload["error"], payload
        assert not outside.exists(), "a refused write must create nothing"

    @pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
    def test_mail_threads_does_not_walk_out_of_the_root(self, tmp_path):
        """`carrel_mail action=threads` is the fifth tree-walking tool.

        It was missed when the other four were bounded, and it reports a
        message's subject, sender and Message-ID — so the escape leaked header
        content, not just a path.
        """
        desk, _ = self.desk_and_secret(tmp_path)
        (tmp_path / "outside.eml").write_text(
            "From: leaker@example.com\nSubject: TOPSECRET-SUBJECT\nMessage-ID: <x@y>\n\nbody\n"
        )
        (desk / "sub" / "leak.eml").symlink_to(tmp_path / "outside.eml")

        proc = run_server([tool_call(1, "carrel_mail", {"action": "threads", "path": "."})], desk)

        assert proc.returncode == 0, proc.stderr
        assert "TOPSECRET-SUBJECT" not in proc.stdout
        assert "leaker@example.com" not in proc.stdout

    @needs("git")
    def test_the_walk_is_not_emptied_by_a_gitignore_above_the_root(self, tmp_path):
        """A confined server must not read `.gitignore` files above its own root.

        `refs` and `fields` left the ancestor walk unbounded, so a `*` rule one
        directory up — the v0.3.1 desk-blanking shape (D-019), reached through
        MCP — silently returned zero files. Whether `fields` was bounded at all
        depended on the unrelated `save` flag.

        The `git init` is load-bearing: `ancestor_ignores` only climbs inside a
        work tree, so without it the unbounded walk returns `()` anyway and this
        test passes with the fix reverted. Checked by reverting it.
        """
        (tmp_path / ".gitignore").write_text("*\n")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=TIMEOUT)
        desk, _ = self.desk_and_secret(tmp_path)

        proc = run_server(
            [
                tool_call(1, "carrel_refs", {"path": "."}),
                tool_call(2, "carrel_fields", {"path": "."}),
                tool_call(3, "carrel_pack", {"path": "."}),
            ],
            desk,
        )
        assert proc.returncode == 0, proc.stderr
        for resp in parse_lines(proc.stdout)[:2]:
            is_error, payload = tool_payload(resp)
            assert is_error is False, payload
            assert payload["files"], "an ignore rule above the confined root emptied the walk"
        _, pack = tool_payload(parse_lines(proc.stdout)[2])
        assert pack["entries"], pack

    @pytest.mark.parametrize("params", [[1, 2], [], "nope", "", 0, False])
    def test_a_non_object_params_is_an_error_not_a_crash(self, tmp_path, params):
        """JSON-RPC 2.0 allows an array here; every handler reads it with .get().

        The falsy values matter as much as the truthy ones: `params or {}`
        coerced `[]`, `""`, `0` and `false` to an empty dict, so a malformed
        request came back as "unknown tool" — or, for `resources/read`, with the
        not-found shape reserved for real lookups.
        """
        proc = run_server(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
                {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": params},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        assert [r["id"] for r in responses] == [1, 2, 3]
        for resp in responses[:2]:
            assert resp["error"]["code"] == -32602, resp
        assert responses[2]["result"] == {}, "the server kept serving"

    def test_an_absent_or_null_params_is_still_fine(self, tmp_path):
        """`params` is optional in JSON-RPC 2.0; only a present non-object is an error."""
        proc = run_server(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": None},
            ],
            tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        assert len(responses) == 2, proc.stdout  # an empty list would pass the loop
        for resp in responses:
            assert resp["result"]["protocolVersion"] == DEFAULT_PROTOCOL_VERSION, resp

    def test_resources_outside_the_root_are_not_found(self, tmp_path):
        desk, secret = self.desk_and_secret(tmp_path)
        proc = run_server(
            [
                resource_read(1, f"carrel://file/{secret}"),
                resource_read(2, "carrel://file/../secret.txt"),
                resource_read(3, "carrel://file/sub/deep.txt"),
            ],
            desk,
        )
        responses = parse_lines(proc.stdout)
        for resp in responses[:2]:
            assert resp["error"]["code"] == -32002, resp
        assert "hunter2" not in proc.stdout
        (block,) = responses[2]["result"]["contents"]  # inside the root, unaffected
        assert block["text"] == "buried text content\n"

    def test_allow_outside_root_lifts_the_boundary(self, tmp_path):
        desk, secret = self.desk_and_secret(tmp_path)
        proc = run_server(
            [
                tool_call(1, "carrel_inspect", {"path": str(secret)}),
                resource_read(2, f"carrel://file/{secret}"),
            ],
            desk,
            args=("--allow-outside-root",),
        )
        assert proc.returncode == 0, proc.stderr
        responses = parse_lines(proc.stdout)
        is_error, payload = tool_payload(responses[0])
        assert is_error is False, payload
        assert payload["name"] == "secret.txt"
        (block,) = responses[1]["result"]["contents"]
        assert block["text"] == "the passphrase is hunter2\n"


class TestMcpProtocolVersion:
    @staticmethod
    def initialize(tmp_path: Path, requested: object) -> str:
        params: dict = {"capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}}
        if requested is not None:
            params["protocolVersion"] = requested
        proc = run_server(
            [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}], tmp_path
        )
        assert proc.returncode == 0, proc.stderr
        return parse_lines(proc.stdout)[0]["result"]["protocolVersion"]

    @pytest.mark.parametrize("version", ["2025-06-18", "2025-03-26", "2024-11-05"])
    def test_a_supported_version_is_echoed(self, tmp_path, version):
        assert self.initialize(tmp_path, version) == version

    @pytest.mark.parametrize("requested", ["2099-01-01", "", "not-a-version", 7, None])
    def test_anything_else_gets_the_newest_supported_version(self, tmp_path, requested):
        """Echoing an unknown string would claim a revision never run against."""
        assert self.initialize(tmp_path, requested) == "2025-06-18"


# --------------------------------------------------------------------------
# the boundary, checked against every tool the registry declares
#
# Both boundary escapes found in review were "one more tool also does this":
# symlinked files in four walkers, then `carrel_mail` as a fifth. Naming the
# tools in a test reproduces that failure — the next tool is missed the same
# way. These two drive the whole of `TOOLS` and derive their arguments from each
# tool's own schema, so a tool added tomorrow is covered the day it is added.
# --------------------------------------------------------------------------


def tool_cases() -> list[tuple[str, str | None]]:
    """Every (tool, action) pair the registry declares.

    A tool is not the unit of behaviour here: `carrel_mail attachments` reads the
    files it is handed while `carrel_mail threads` walks a directory, and only the
    second could escape the root. A per-tool test exercised the first action of
    each and passed with the `threads` boundary reverted — checked, not assumed.
    """
    cases: list[tuple[str, str | None]] = []
    for tool in TOOLS:
        action = tool["inputSchema"]["properties"].get("action")
        if action:
            cases += [(tool["name"], value) for value in action["enum"]]
        else:
            cases.append((tool["name"], None))
    return cases


TOOL_CASES = tool_cases()
CASE_IDS = [f"{name}:{action}" if action else name for name, action in TOOL_CASES]


def minimal_args(tool: dict, action: str | None, *, outside_file: Path, outside_dir: Path) -> dict:
    """Arguments satisfying `tool`'s required set, every path-shaped one outside the root."""
    values: dict[str, object] = {
        "query": "anything",
        "path": str(outside_file),
        "paths": [str(outside_file)],
        "a": str(outside_file),
        "b": str(outside_file),
        "to": "txt",
        "out_dir": str(outside_dir),
        "body": "a note",
        "tags": ["t"],
        "keys": ["k"],
        "key": "k",
        "fields": {"k": "v"},
        "conditions": ["k?"],
    }
    schema = tool["inputSchema"]
    args = {k: values[k] for k in schema.get("required", []) if k in values}
    if action is not None:
        # the action under test, plus everything any action of this tool needs
        args["action"] = action
        args |= {
            k: values[k]
            for k in ("path", "tags", "body", "fields", "keys", "key", "conditions", "out_dir")
            if k in schema["properties"]
        }
    return args


@pytest.mark.parametrize(("name", "action"), TOOL_CASES, ids=CASE_IDS)
def test_every_tool_refuses_a_root_outside_the_server_root(tmp_path, name, action):
    """`root` is on all fourteen schemas, so all fourteen must refuse an outside one."""
    desk = tmp_path / "desk"
    desk.mkdir()
    make_tree(desk)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("the passphrase is hunter2\n")

    tool = next(t for t in TOOLS if t["name"] == name)
    if "root" not in tool["inputSchema"]["properties"]:
        pytest.skip(f"{name} takes no root")  # carrel_doctor
    args = minimal_args(tool, action, outside_file=outside / "secret.txt", outside_dir=outside)
    args["root"] = str(outside)

    proc = run_server([tool_call(1, name, args)], desk)

    assert proc.returncode == 0, proc.stderr
    is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert is_error is True, payload
    assert "outside the server root" in payload["error"], payload
    assert "hunter2" not in proc.stdout


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
@pytest.mark.parametrize(("name", "action"), TOOL_CASES, ids=CASE_IDS)
def test_no_tool_reads_through_a_symlink_planted_in_the_desk(tmp_path, name, action):
    """Whatever a tool does with a directory, it must not read out of the root doing it.

    The tools that walk are not identifiable from the schema, so this runs all of
    them against a desk holding links to a secret and asserts the marker never
    reaches stdout. A sixth walker is caught the day it lands.
    """
    desk = tmp_path / "desk"
    desk.mkdir()
    make_tree(desk)  # creates desk/sub
    secret = tmp_path / "secret.txt"
    secret.write_text("the passphrase is hunter2\n")
    (tmp_path / "secret.eml").write_text("Subject: hunter2-subject\n\nhunter2 body\n")
    for link in ("sub/leak.txt", "sub/leak.md", "sub/leak.eml", "sub/leak.csv"):
        (desk / link).symlink_to(secret if not link.endswith(".eml") else tmp_path / "secret.eml")

    tool = next(t for t in TOOLS if t["name"] == name)
    args = minimal_args(tool, action, outside_file=desk, outside_dir=desk / "out")
    for key in ("path", "a", "b"):  # aim every tool at the desk directory itself
        if key in args:
            args[key] = "."
    if "paths" in args:
        args["paths"] = ["."]

    # "passphrase", not the marker: a search echoes its own query back
    proc = run_server(
        [tool_call(1, name, args), tool_call(2, "carrel_search", {"query": "passphrase"})], desk
    )

    assert proc.returncode == 0, proc.stderr
    assert "hunter2" not in proc.stdout, f"{name} read through the symlink"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("carrel_convert", {"path": "note.md", "to": "txt", "force": True}),
        (
            "carrel_mail",
            {"action": "attachments", "path": "mail.eml", "out_dir": ".", "force": True},
        ),
    ],
)
def test_no_tool_writes_through_a_symlink_at_its_destination(tmp_path, tool, args):
    """The read side's twin. A write *follows* a symlink, and the destination is derived.

    `Desk.resolve` sees only the paths a client names, and neither the converted
    file's name nor an attachment's is one of them — so a link planted at the
    destination sent the confined server's writes outside the root, and a
    *dangling* link created the outside file with nothing to force past.
    `test_no_tool_reads_through_a_symlink_planted_in_the_desk` aims everything at
    `"."`, so both tools failed input detection before they ever reached a write.
    """
    desk = tmp_path / "desk"
    desk.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "victim.txt").write_text("ORIGINAL\n")
    (desk / "note.md").write_text("hello\n\nsome markdown\n")
    _write_eml(desk / "mail.eml")
    # the destination each tool derives, pre-planted as a link out of the desk
    (desk / "note.txt").symlink_to(outside / "victim.txt")
    (desk / "report.txt").symlink_to(outside / "victim.txt")

    proc = run_server([tool_call(1, tool, args)], desk)

    assert proc.returncode == 0, proc.stderr
    is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert is_error is True, payload
    assert "resolves outside" in payload["error"], payload
    assert (outside / "victim.txt").read_text() == "ORIGINAL\n", "wrote through the link"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_a_dangling_symlink_destination_creates_nothing_outside(tmp_path):
    """No existing file means no overwrite to force past — the quiet half of the same hole."""
    desk = tmp_path / "desk"
    desk.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (desk / "note.md").write_text("hello\n\nsome markdown\n")
    (desk / "note.txt").symlink_to(outside / "created.txt")

    proc = run_server([tool_call(1, "carrel_convert", {"path": "note.md", "to": "txt"})], desk)

    is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert is_error is True, payload
    assert not (outside / "created.txt").exists(), "created a file outside the root"


@needs("git")
@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_stored_rows_pointing_outside_the_root_are_not_served(tmp_path):
    """Confining the walk stops the server *writing* such rows; it cannot unwrite them.

    The CLI follows symlinks by design (D-021), so a desk indexed from the shell
    can hold rows pointing anywhere — and `--prune` keeps them, because the target
    still exists. Every tool that returns stored paths filters them.
    """
    desk = tmp_path / "desk"
    desk.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("the passphrase is hunter2\n")
    (desk / "inside.txt").write_text("ordinary desk note about passphrase policy\n")
    (desk / "leak.txt").symlink_to(outside / "secret.txt")
    subprocess.run(
        [sys.executable, "-m", "carrel.cli", "--root", str(desk), "index", str(desk)],
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )

    proc = run_server([tool_call(1, "carrel_search", {"query": "passphrase"})], desk)
    _, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert [h["path"] for h in payload["results"]] == ["inside.txt"], payload
    assert "hunter2" not in proc.stdout

    # ...and the escape hatch still reaches them, or it would not be one
    proc = run_server(
        [tool_call(1, "carrel_search", {"query": "passphrase"})],
        desk,
        args=("--allow-outside-root",),
    )
    _, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert len(payload["results"]) == 2, payload


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_a_symlinked_desk_dir_does_not_move_the_database_outside(tmp_path):
    """`<root>/.carrel` is derived from the root, not named by the client.

    So `Desk.resolve` never saw it, and a symlink there sent the index — the
    extracted full text of every file in the desk — plus every tag, note and
    field to wherever it pointed, with `carrel_search` reading it back. Eleven
    tools open a `DeskDB`; the check sits where the root is established.
    """
    desk = tmp_path / "desk"
    desk.mkdir()
    stash = tmp_path / "outside" / "stash"
    stash.mkdir(parents=True)
    (desk / "a.txt").write_text("the passphrase is hunter2\n")
    (desk / ".carrel").symlink_to(stash)

    proc = run_server(
        [
            tool_call(1, "carrel_index", {}),
            tool_call(2, "carrel_note", {"action": "add", "path": "a.txt", "body": "n"}),
            tool_call(3, "carrel_tag", {"action": "add", "path": "a.txt", "tags": ["t"]}),
        ],
        desk,
    )

    assert proc.returncode == 0, proc.stderr
    for resp in parse_lines(proc.stdout):
        is_error, payload = tool_payload(resp)
        assert is_error is True, payload
        assert "resolves outside" in payload["error"], payload
    assert list(stash.iterdir()) == [], "wrote the desk database outside the root"


@needs("git")
@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_an_in_root_hit_survives_higher_ranked_outside_rows(tmp_path):
    """Filtering a `limit`-sized page loses in-root hits that ranked below it.

    Outside rows often rank higher — they are what a symlink farm looks like —
    so a confined search returned "no results" for a desk that did match, the one
    answer an agent reads as "nothing here".
    """
    desk = tmp_path / "desk"
    desk.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    for i in range(3):
        (outside / f"o{i}.txt").write_text("aardvark aardvark aardvark\n")
        (desk / f"l{i}.txt").symlink_to(outside / f"o{i}.txt")
    (desk / "inside.txt").write_text("aardvark mentioned once\n")
    subprocess.run(
        [sys.executable, "-m", "carrel.cli", "--root", str(desk), "index", str(desk)],
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )

    proc = run_server([tool_call(1, "carrel_search", {"query": "aardvark", "limit": 2})], desk)
    _, payload = tool_payload(parse_lines(proc.stdout)[0])

    assert [h["path"] for h in payload["results"]] == ["inside.txt"], payload
    assert payload["count"] == 1, payload


def test_an_unexpected_failure_still_carries_an_exit_code(tmp_path):
    """A client cannot tell a bad request from a server fault without one."""
    proc = run_server([tool_call(1, "carrel_inspect", {"path": 123})], tmp_path)
    is_error, payload = tool_payload(parse_lines(proc.stdout)[0])
    assert is_error is True
    assert payload["exit_code"] >= 1, payload


def _write_eml(path: Path) -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "a@b.c"
    msg["Subject"] = "s"
    msg.set_content("body")
    msg.add_attachment(b"ATTACKER BYTES", maintype="text", subtype="plain", filename="report.txt")
    path.write_bytes(bytes(msg))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
