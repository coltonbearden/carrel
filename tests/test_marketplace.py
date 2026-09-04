"""Tests for the Claude Code plugin marketplace (specs/12-marketplace-plugins.md).

Covers: marketplace.json + every plugin manifest parse with required fields,
command markdown frontmatter, hook script behavior against synthetic
PostToolUse payloads, the .mcp.json server entry, and — when the `claude`
CLI is available — `claude plugin validate`.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGINS_DIR = REPO / "plugins"

EXPECTED_PLUGINS: dict[str, set[str]] = {
    "carrel-convert": {"convert.md", "ocr.md", "thumb.md", "audiobook.md"},
    "carrel-inspect": {"inspect.md", "diff.md", "search.md", "pack.md"},
    "carrel-organize": {"organize.md", "dedupe.md", "tag.md", "note-file.md"},
    "carrel-watch": {"watch-folder.md"},
    "carrel-agent": set(),
}

HOOK_SCRIPT = PLUGINS_DIR / "carrel-agent" / "scripts" / "reindex.sh"


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


# ---------------------------------------------------------- marketplace.json


def test_marketplace_json_parses_with_required_fields():
    data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    assert data["name"] == "carrel"
    assert data["owner"]["name"], "owner.name required"
    assert isinstance(data["plugins"], list) and len(data["plugins"]) == 5


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


# ---------------------------------------------------------- commands/*.md


def all_command_files() -> list[Path]:
    return sorted(PLUGINS_DIR.glob("*/commands/*.md"))


def test_expected_command_files_exist():
    for plugin, commands in EXPECTED_PLUGINS.items():
        found = (
            {p.name for p in (PLUGINS_DIR / plugin / "commands").glob("*.md")}
            if (PLUGINS_DIR / plugin / "commands").is_dir()
            else set()
        )
        assert found == commands, f"{plugin}: {found} != {commands}"


@pytest.mark.parametrize(
    "md", all_command_files(), ids=lambda p: f"{p.parent.parent.name}/{p.name}"
)
def test_command_frontmatter(md: Path):
    fm = read_frontmatter(md)
    assert fm.get("description"), f"{md}: frontmatter needs description"
    assert "allowed-tools" in fm, f"{md}: frontmatter needs allowed-tools"
    assert "Bash(carrel" in fm["allowed-tools"], fm["allowed-tools"]
    body = md.read_text(encoding="utf-8")
    assert "carrel" in body
    assert "uv tool install" in body or "uv run carrel" in body, (
        f"{md}: must point users at the carrel install fallback"
    )


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
    assert (PLUGINS_DIR / "carrel-inspect" / "skills" / "context-packing" / "SKILL.md").is_file()
    assert (PLUGINS_DIR / "carrel-watch" / "skills" / "watch-automation" / "SKILL.md").is_file()
    assert (PLUGINS_DIR / "carrel-agent" / "skills" / "agent-workflows" / "SKILL.md").is_file()


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
    env["PATH"] = "/usr/bin:/bin"  # keep jq/python3, drop the project venv
    assert shutil.which("carrel", path=env["PATH"]) is None, "test premise broken"
    proc = run_hook(payload, cwd=tmp_path, env=env)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("carrel") is None, reason="carrel not on PATH")
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
