"""Tests for the Claude Code plugin marketplace (specs/12-marketplace-plugins.md, 20-plugins-v2.md).

Covers: marketplace.json + every plugin manifest parse with required fields,
command markdown frontmatter and the generated ``<!-- usage:start/end -->``
blocks (``scripts/sync_plugins.py --check`` must be clean), one slash command per
CLI command, hook script behavior against synthetic PostToolUse / PreToolUse /
SessionStart payloads, the .mcp.json server entry, and — when the `claude` CLI
is available — `claude plugin validate`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from conftest import needs

from carrel.cli import COMMANDS

REPO = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGINS_DIR = REPO / "plugins"
FIXTURES = REPO / "tests" / "fixtures"
SYNC_PLUGINS = REPO / "scripts" / "sync_plugins.py"
USAGE_START = "<!-- usage:start -->"
USAGE_END = "<!-- usage:end -->"

EXPECTED_PLUGINS: dict[str, set[str]] = {
    "carrel-convert": {
        "convert.md",
        "ocr.md",
        "thumb.md",
        "audiobook.md",
        "edit.md",
        "extract-images.md",
    },
    "carrel-inspect": {"inspect.md", "diff.md", "search.md", "pack.md"},
    "carrel-organize": {"organize.md", "dedupe.md", "tag.md", "note-file.md"},
    "carrel-documents": {"redact.md", "sign.md", "form.md", "proof.md", "color.md"},
    "carrel-watch": {"watch-folder.md"},
    "carrel-agent": {"index.md", "doctor.md", "catalog.md", "completion.md"},
    "carrel-guard": set(),
}

# CLI commands that deliberately have no slash command. Every other key of
# carrel.cli.COMMANDS must be wrapped by exactly one plugins/*/commands/*.md.
NOT_SLASH_COMMANDS: dict[str, str] = {
    "mcp": "a stdio MCP server; plugins/carrel-agent/.mcp.json registers it, a slash "
    "command running it in Bash would just block on stdin",
    "desk": "the interactive textual TUI; it needs a real terminal, not a Bash tool call",
}

HOOK_SCRIPT = PLUGINS_DIR / "carrel-agent" / "scripts" / "reindex.sh"
GUARD_DIR = PLUGINS_DIR / "carrel-guard"
READ_GUARD = GUARD_DIR / "scripts" / "read-guard.sh"
CAPABILITIES = GUARD_DIR / "scripts" / "capabilities.sh"
NO_CARREL_PATH = "/usr/bin:/bin"  # keeps jq/python3/coreutils, drops the project venv

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
needs_carrel = pytest.mark.skipif(shutil.which("carrel") is None, reason="carrel not on PATH")


# ---------------------------------------------------------------- helpers


def read_frontmatter(md: Path) -> dict[str, str]:
    """Parse simple `key: value` YAML frontmatter without a yaml dependency."""
    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{md}: missing frontmatter opener"
    body = text[4:]
    assert "\n---" in body, f"{md}: missing frontmatter closer"
    block = body.split("\n---", 1)[0]
    fm: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        assert ":" in line, f"{md}: frontmatter line without a colon: {line!r}"
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm


def run_hook(payload: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        [str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env or os.environ.copy(),
        timeout=30,
    )


def run_guard(
    script: Path,
    payload: str,
    tmp_path: Path,
    *,
    with_carrel: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Drive a carrel-guard hook script with a synthetic payload.

    The cache always lands under tmp_path (XDG_CACHE_HOME) so tests never touch
    the real ~/.cache. with_carrel=False strips the project venv from PATH.
    """
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(tmp_path / "xdg-cache")
    if not with_carrel:
        env["PATH"] = NO_CARREL_PATH
        assert shutil.which("carrel", path=env["PATH"]) is None, "test premise broken"
    env.update(extra_env or {})
    return subprocess.run(
        [str(script)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=90,
    )


def read_payload(path: str | Path, **tool_input: object) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "cwd": str(REPO),
            "tool_input": {"file_path": str(path), **tool_input},
        }
    )


def run_sync_plugins(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SYNC_PLUGINS), *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "COLUMNS": "41"},  # width must come from the script, not the caller
        timeout=120,
    )


def usage_block(text: str) -> str:
    start = text.index(USAGE_START) + len(USAGE_START)
    return text[start : text.index(USAGE_END)]


def all_command_files() -> list[Path]:
    return sorted(PLUGINS_DIR.glob("*/commands/*.md"))


def cmd_id(p: Path) -> str:
    return f"{p.parent.parent.name}/{p.name}"


# ---------------------------------------------------------- marketplace.json


def test_marketplace_json_parses_with_required_fields():
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert data["name"] == "carrel"
    assert data["owner"]["name"], "owner.name required"
    assert isinstance(data["plugins"], list)
    assert len(data["plugins"]) == len(EXPECTED_PLUGINS) == 7


def test_marketplace_entries_complete_and_sources_exist():
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    product = json.loads((REPO / "product.json").read_text(encoding="utf-8"))
    names = set()
    for entry in data["plugins"]:
        assert entry["name"], "plugin entry needs a name"
        names.add(entry["name"])
        assert entry["source"].startswith("./plugins/"), entry["source"]
        assert (REPO / entry["source"]).is_dir(), f"missing dir: {entry['source']}"
        assert entry["description"]
        assert entry["version"] == product["version"]
        assert entry["keywords"]
    assert names == set(EXPECTED_PLUGINS)


def test_every_plugin_directory_is_listed():
    listed = {e["name"] for e in json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"]}
    on_disk = {p.name for p in PLUGINS_DIR.iterdir() if p.is_dir()}
    assert on_disk == listed


# ------------------------------------------------------------- plugin.json


@pytest.mark.parametrize("plugin", sorted(EXPECTED_PLUGINS))
def test_plugin_manifest_parses(plugin: str):
    manifest = PLUGINS_DIR / plugin / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["name"] == plugin  # `name` is the only required field
    assert data["description"]
    assert data["version"]
    assert data["author"]["name"]


def test_plugin_versions_match_marketplace_entries():
    market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    by_name = {e["name"]: e for e in market["plugins"]}
    for plugin in EXPECTED_PLUGINS:
        manifest = PLUGINS_DIR / plugin / ".claude-plugin" / "plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["version"] == by_name[plugin]["version"], plugin
        assert data["description"] == by_name[plugin]["description"], plugin


# ---------------------------------------------------------- commands/*.md


def test_expected_command_files_exist():
    for plugin, commands in EXPECTED_PLUGINS.items():
        found = (
            {p.name for p in (PLUGINS_DIR / plugin / "commands").glob("*.md")}
            if (PLUGINS_DIR / plugin / "commands").is_dir()
            else set()
        )
        assert found == commands, f"{plugin}: {found} != {commands}"


@pytest.mark.parametrize("md", all_command_files(), ids=cmd_id)
def test_command_frontmatter(md: Path):
    fm = read_frontmatter(md)
    assert fm.get("description"), f"{md}: frontmatter needs description"
    assert "allowed-tools" in fm, f"{md}: frontmatter needs allowed-tools"
    assert "Bash(carrel" in fm["allowed-tools"], fm["allowed-tools"]
    assert fm.get("carrel-command") in COMMANDS, f"{md}: carrel-command must name a CLI command"
    body = md.read_text(encoding="utf-8")
    assert "carrel" in body
    assert "uv tool install" in body or "uv run carrel" in body, (
        f"{md}: must point users at the carrel install fallback"
    )


@pytest.mark.parametrize("md", all_command_files(), ids=cmd_id)
def test_command_has_generated_usage_block(md: Path):
    """Both markers exactly once, in order, wrapping fenced --help for that command."""
    text = md.read_text(encoding="utf-8")
    assert text.count(USAGE_START) == 1, f"{md}: needs exactly one {USAGE_START}"
    assert text.count(USAGE_END) == 1, f"{md}: needs exactly one {USAGE_END}"
    assert text.index(USAGE_START) < text.index(USAGE_END)
    block = usage_block(text)
    name = read_frontmatter(md)["carrel-command"]
    assert block.startswith("\n```text\nUsage: carrel " + name), f"{md}: block is not --help"
    assert block.rstrip().endswith("```"), f"{md}: block must end with a closed fence"
    assert "--help" in block


def test_every_cli_command_has_exactly_one_slash_command():
    """Every carrel.cli.COMMANDS key is wrapped once, except the documented exclusions."""
    owners: dict[str, list[str]] = defaultdict(list)
    for md in all_command_files():
        owners[read_frontmatter(md)["carrel-command"]].append(cmd_id(md))
    for name in NOT_SLASH_COMMANDS:
        assert name in COMMANDS, f"exclusion list names unknown command {name!r}"
        assert name not in owners, f"{name} is excluded on purpose but has a slash command"
    expected = set(COMMANDS) - set(NOT_SLASH_COMMANDS)
    missing = expected - set(owners)
    assert not missing, f"CLI commands without a slash command: {sorted(missing)}"
    duplicated = {name: files for name, files in owners.items() if len(files) != 1}
    assert not duplicated, f"commands wrapped by more than one plugin: {duplicated}"


def test_group_commands_document_every_subcommand():
    """For click groups the block carries one fenced --help per subcommand."""
    import click

    from carrel.cli import cli

    root = click.Context(cli, info_name="carrel")
    for md in all_command_files():
        name = read_frontmatter(md)["carrel-command"]
        command = cli.get_command(root, name)
        assert command is not None, name
        if not isinstance(command, click.Group):
            continue
        block = usage_block(md.read_text(encoding="utf-8"))
        for sub in command.list_commands(root):
            assert f"Usage: carrel {name} {sub} " in block, f"{md}: missing help for {name} {sub}"


# --------------------------------------------------------- sync_plugins.py


def test_sync_plugins_check_passes_on_checkout():
    result = run_sync_plugins("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "up to date" in result.stdout


def test_sync_plugins_check_fails_after_edit_inside_markers(tmp_path: Path):
    copy = tmp_path / "plugins"
    shutil.copytree(PLUGINS_DIR, copy)
    target = copy / "carrel-inspect" / "commands" / "inspect.md"
    original = target.read_text(encoding="utf-8")
    edited = original.replace("Usage: carrel inspect", "Usage: carrel inspect --bogus", 1)
    assert edited != original
    target.write_text(edited, encoding="utf-8")

    result = run_sync_plugins("--check", "--plugins-dir", str(copy))
    assert result.returncode == 1
    assert "inspect.md" in result.stderr
    assert target.read_text(encoding="utf-8") == edited, "--check must not write"

    result = run_sync_plugins("--plugins-dir", str(copy))
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == original, "regeneration must restore the block"


def test_sync_plugins_preserves_text_outside_markers(tmp_path: Path):
    copy = tmp_path / "plugins"
    shutil.copytree(PLUGINS_DIR, copy)
    target = copy / "carrel-convert" / "commands" / "ocr.md"
    text = target.read_text(encoding="utf-8")
    edited = text.replace(USAGE_START, "Hand-written guidance stays.\n\n" + USAGE_START, 1)
    edited += "\nTrailing hand-written line.\n"
    target.write_text(edited, encoding="utf-8")
    assert run_sync_plugins("--check", "--plugins-dir", str(copy)).returncode == 0
    result = run_sync_plugins("--plugins-dir", str(copy))
    assert result.returncode == 0, result.stderr
    assert target.read_text(encoding="utf-8") == edited


def test_sync_plugins_rejects_missing_frontmatter_key(tmp_path: Path):
    copy = tmp_path / "plugins"
    shutil.copytree(PLUGINS_DIR, copy)
    target = copy / "carrel-watch" / "commands" / "watch-folder.md"
    text = target.read_text(encoding="utf-8").replace("carrel-command: watch\n", "")
    target.write_text(text, encoding="utf-8")
    result = run_sync_plugins("--check", "--plugins-dir", str(copy))
    assert result.returncode == 1
    assert "carrel-command" in result.stderr


def test_sync_plugins_is_deterministic(tmp_path: Path):
    copy = tmp_path / "plugins"
    shutil.copytree(PLUGINS_DIR, copy)
    files = sorted(copy.glob("*/commands/*.md"))
    for path in files:  # blank every block, regenerate twice, compare
        text = path.read_text(encoding="utf-8")
        blanked = (
            text[: text.index(USAGE_START) + len(USAGE_START)]
            + "\n"
            + text[text.index(USAGE_END) :]
        )
        path.write_text(blanked, encoding="utf-8")
    assert run_sync_plugins("--plugins-dir", str(copy)).returncode == 0
    first = {p: p.read_bytes() for p in files}
    assert run_sync_plugins("--plugins-dir", str(copy)).returncode == 0
    assert {p: p.read_bytes() for p in files} == first
    for path in files:
        assert path.read_bytes() == (PLUGINS_DIR / path.relative_to(copy)).read_bytes()


# ------------------------------------------------------- agents + skills


@pytest.mark.parametrize(
    "md",
    sorted(PLUGINS_DIR.glob("*/agents/*.md")) + sorted(PLUGINS_DIR.glob("*/skills/*/SKILL.md")),
    ids=lambda p: (
        f"{p.parent.parent.name}/{p.name}"
        if p.name != "SKILL.md"
        else f"{p.parents[2].name}/{p.parent.name}"
    ),
)
def test_agent_and_skill_frontmatter(md: Path):
    fm = read_frontmatter(md)
    assert fm.get("name"), f"{md}: frontmatter needs name"
    assert fm.get("description"), f"{md}: frontmatter needs description"


def test_expected_agents_and_skills_exist():
    assert (PLUGINS_DIR / "carrel-convert" / "agents" / "doc-converter.md").is_file()
    assert (PLUGINS_DIR / "carrel-agent" / "agents" / "file-librarian.md").is_file()
    assert (PLUGINS_DIR / "carrel-documents" / "agents" / "document-clerk.md").is_file()
    assert (PLUGINS_DIR / "carrel-inspect" / "skills" / "context-packing" / "SKILL.md").is_file()
    assert (PLUGINS_DIR / "carrel-watch" / "skills" / "watch-automation" / "SKILL.md").is_file()
    assert (PLUGINS_DIR / "carrel-agent" / "skills" / "agent-workflows" / "SKILL.md").is_file()
    assert (
        PLUGINS_DIR / "carrel-documents" / "skills" / "redaction-and-provenance" / "SKILL.md"
    ).is_file()
    assert (GUARD_DIR / "README.md").is_file()


def test_context_packing_skill_covers_pack_v2():
    text = (PLUGINS_DIR / "carrel-inspect" / "skills" / "context-packing" / "SKILL.md").read_text()
    for flag in ("--query", "--since", "--tree-only", "--outline", "--tokenizer exact"):
        assert flag in text, f"context-packing skill must cover {flag}"
    assert "no negation" not in text, "pack honors !pattern since spec 16"
    assert "!pattern" in text


def test_agent_workflows_skill_lists_mcp_surface():
    from carrel.commands.mcp import RESOURCE_TEMPLATES, TOOLS

    text = (PLUGINS_DIR / "carrel-agent" / "skills" / "agent-workflows" / "SKILL.md").read_text()
    for tool in TOOLS:
        assert f"`{tool['name']}`" in text, f"skill must list MCP tool {tool['name']}"
    for template in RESOURCE_TEMPLATES:
        assert template["uriTemplate"] in text, f"skill must list {template['uriTemplate']}"
    assert len(TOOLS) == 10


def test_document_clerk_refuses_silent_overwrite():
    text = (PLUGINS_DIR / "carrel-documents" / "agents" / "document-clerk.md").read_text()
    assert "--force" in text
    assert "sign manifest" in text
    assert "sign verify" in text


# ------------------------------------------------------- hooks + .mcp.json


def test_hooks_json_schema():
    hooks_file = PLUGINS_DIR / "carrel-agent" / "hooks" / "hooks.json"
    data = json.loads(hooks_file.read_text(encoding="utf-8"))
    post = data["hooks"]["PostToolUse"]
    assert post[0]["matcher"] == "Write|Edit"
    hook = post[0]["hooks"][0]
    assert hook["type"] == "command"
    assert "${CLAUDE_PLUGIN_ROOT}" in hook["command"]
    assert "scripts/reindex.sh" in hook["command"]


def test_mcp_json():
    data = json.loads((PLUGINS_DIR / "carrel-agent" / ".mcp.json").read_text(encoding="utf-8"))
    server = data["mcpServers"]["carrel"]
    assert server["command"] == "carrel"
    assert server["args"] == ["mcp"]


def test_hook_script_is_executable():
    mode = HOOK_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "reindex.sh must be executable"
    first = HOOK_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("#!"), "reindex.sh needs a shebang"


def test_hook_script_exits_zero_without_desk_db(tmp_path: Path):
    """No .carrel under cwd → silent no-op, exit 0."""
    target = tmp_path / "note.md"
    target.write_text("hello\n")
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "cwd": str(tmp_path),
            "tool_input": {"file_path": str(target)},
            "tool_response": {"success": True},
        }
    )
    proc = run_hook(payload, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("payload", ["", "not json at all", "{}", '{"tool_input": {}}'])
def test_hook_script_exits_zero_on_degenerate_payloads(tmp_path: Path, payload: str):
    proc = run_hook(payload, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_hook_script_exits_zero_when_carrel_missing(tmp_path: Path):
    """carrel off PATH → exit 0 before touching anything."""
    target = tmp_path / "note.md"
    target.write_text("hello\n")
    payload = json.dumps({"cwd": str(tmp_path), "tool_input": {"file_path": str(target)}})
    env = os.environ.copy()
    env["PATH"] = NO_CARREL_PATH
    assert shutil.which("carrel", path=env["PATH"]) is None, "test premise broken"
    proc = run_hook(payload, cwd=tmp_path, env=env)
    assert proc.returncode == 0, proc.stderr


@needs_carrel
def test_hook_script_reindexes_written_file(tmp_path: Path):
    """End to end: index a desk, append to a file, hook refresh, search finds it."""
    target = tmp_path / "note.md"
    target.write_text("hello world\n")
    subprocess.run(
        ["carrel", "--root", str(tmp_path), "index", str(tmp_path)],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    target.write_text("hello world\nxylophone content\n")
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Edit",
            "cwd": str(tmp_path),
            "tool_input": {"file_path": str(target)},
        }
    )
    proc = run_hook(payload, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    hits = json.loads(
        subprocess.run(
            ["carrel", "--json", "--root", str(tmp_path), "search", "xylophone"],
            check=True,
            capture_output=True,
            text=True,
            cwd=tmp_path,
        ).stdout
    )
    assert any(hit["path"] == "note.md" for hit in hits), hits


# ------------------------------------------------------------ carrel-guard


def test_guard_hooks_json_schema():
    data = json.loads((GUARD_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    pre = data["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Read"
    read_hook = pre[0]["hooks"][0]
    assert read_hook["type"] == "command"
    assert "${CLAUDE_PLUGIN_ROOT}" in read_hook["command"]
    assert "scripts/read-guard.sh" in read_hook["command"]
    session = data["hooks"]["SessionStart"]
    assert "matcher" not in session[0], "SessionStart hook runs for every source"
    start_hook = session[0]["hooks"][0]
    assert start_hook["type"] == "command"
    assert "scripts/capabilities.sh" in start_hook["command"]


@pytest.mark.parametrize("script", [READ_GUARD, CAPABILITIES], ids=lambda p: p.name)
def test_guard_scripts_are_executable_bash(script: Path):
    assert script.stat().st_mode & stat.S_IXUSR, f"{script.name} must be executable"
    lines = script.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#!") and "bash" in lines[0]
    assert "set -u" in lines[:40], "hooks use set -u, never set -e"
    assert "set -e" not in "\n".join(lines)


@needs_bash
def test_read_guard_ignores_text_files(tmp_path: Path):
    proc = run_guard(READ_GUARD, read_payload(FIXTURES / "sample.txt"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr == ""


@needs_bash
def test_read_guard_ignores_missing_file(tmp_path: Path):
    proc = run_guard(READ_GUARD, read_payload(tmp_path / "nope.pdf"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@needs_bash
@pytest.mark.parametrize(
    "payload",
    ["", "not json", "{}", '{"tool_input": {}}', '{"tool_input": {"file_path": 7}}', "[1, 2]"],
)
def test_read_guard_exits_zero_on_degenerate_payloads(tmp_path: Path, payload: str):
    proc = run_guard(READ_GUARD, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@needs_bash
def test_read_guard_silent_without_carrel(tmp_path: Path):
    proc = run_guard(READ_GUARD, read_payload(FIXTURES / "b.pdf"), tmp_path, with_carrel=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert not (tmp_path / "xdg-cache").exists(), "must not even create the cache"


@needs_bash
@needs_carrel
def test_read_guard_respects_size_limit(tmp_path: Path):
    proc = run_guard(
        READ_GUARD,
        read_payload(FIXTURES / "b.pdf"),
        tmp_path,
        extra_env={"CARREL_GUARD_MAX_BYTES": "10"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@needs_bash
@needs_carrel
@needs("pdftotext")
def test_read_guard_converts_pdf_and_rewrites_read_input(tmp_path: Path):
    """b.pdf → allow + updatedInput.file_path pointing at cached text == pdftotext's text."""
    src = FIXTURES / "b.pdf"
    proc = run_guard(READ_GUARD, read_payload(src, offset=2, limit=50), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "allow"
    assert set(hso["updatedInput"]) == {"file_path", "offset", "limit"}
    assert hso["updatedInput"]["offset"] == 2
    assert hso["updatedInput"]["limit"] == 50

    txt = Path(hso["updatedInput"]["file_path"])
    assert txt.is_file() and txt.suffix == ".txt"
    expected_dir = (
        tmp_path
        / "xdg-cache"
        / "carrel-guard"
        / hashlib.sha256(str(src.resolve()).encode()).hexdigest()
    )
    assert txt.parent == expected_dir
    assert txt.name == "b.txt"

    reference = subprocess.run(
        ["pdftotext", str(src), "-"], capture_output=True, text=True, check=True
    ).stdout
    assert " ".join(txt.read_text().split()) == " ".join(reference.split())

    ctx = hso["additionalContext"]
    assert ctx.startswith("carrel-guard: ")
    assert str(src.resolve()) in ctx and str(txt) in ctx
    assert f"({len(txt.read_text())} chars)" in ctx
    assert "Original left untouched" in ctx
    assert src.read_bytes() == (REPO / "tests" / "fixtures" / "b.pdf").read_bytes()

    # Second run reuses the cached text (no rewrite) and rewrites only file_path.
    before = txt.stat().st_mtime_ns
    again = run_guard(READ_GUARD, read_payload("tests/fixtures/b.pdf"), tmp_path)
    assert again.returncode == 0, again.stderr
    out2 = json.loads(again.stdout)
    assert out2["hookSpecificOutput"]["updatedInput"] == {"file_path": str(txt)}
    assert txt.stat().st_mtime_ns == before


@needs_bash
@needs_carrel
def test_capabilities_reports_doctor_summary(tmp_path: Path):
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup"})
    proc = run_guard(CAPABILITIES, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""
    out = json.loads(proc.stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    product = json.loads((REPO / "product.json").read_text(encoding="utf-8"))
    assert ctx.startswith(f"carrel {product['version']} is on PATH")
    assert f"of {len(COMMANDS)} commands ok" in ctx
    assert "degraded" in ctx and "unavailable" in ctx
    assert "missing binaries" in ctx or "No optional binaries are missing" in ctx


@needs_bash
def test_capabilities_silent_without_carrel(tmp_path: Path):
    proc = run_guard(CAPABILITIES, "{}", tmp_path, with_carrel=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""


@needs_bash
@pytest.mark.parametrize("payload", ["", "garbage"])
def test_capabilities_tolerates_degenerate_stdin(tmp_path: Path, payload: str):
    proc = run_guard(CAPABILITIES, payload, tmp_path, with_carrel=False)
    assert proc.returncode == 0, proc.stderr


# ------------------------------------------------------ claude plugin validate


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
def test_claude_plugin_validate():
    """Run the real validator over the marketplace and each plugin directory."""
    targets = [REPO, *sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir())]
    for target in targets:
        try:
            proc = subprocess.run(
                ["claude", "plugin", "validate", str(target)],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=REPO,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:  # environmental
            pytest.skip(f"claude plugin validate could not run: {exc}")
        output = proc.stdout + proc.stderr
        if proc.returncode != 0 and "Validation" not in output:
            # CLI failed before validating (login/config issues) — report + skip.
            pytest.skip(f"claude errored for environmental reasons on {target}: {output!r}")
        assert proc.returncode == 0, f"{target}: {output}"
        assert "Validation passed" in output, f"{target}: {output}"
