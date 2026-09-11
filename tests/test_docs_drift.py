"""Prose docs must not drift from the manifests or the product version (D-g, 2026-09-09).

`mkdocs build --strict` catches broken anchors and links; it does not notice a README
plugin table missing two plugins, or sample output that still prints a version three
releases old. These checks are the mechanical half of the doc-drift gate; the `lint`
CI job runs them alongside `mkdocs build --strict`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from carrel._product import PRODUCT

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
README = REPO_ROOT / "README.md"
DOCS = REPO_ROOT / "docs"

# Dated history: each quotes the version that was current when it was written.
HISTORY = {"CHANGELOG.md", "TEST_REPORT.md", "HOW_THIS_WAS_BUILT.md"}

# Sample-output shapes that carry the product version. `vX.Y.Z` prose ("since v0.2.0")
# is deliberately not matched — it names a release, not the running binary.
VERSION_PATTERNS = (
    re.compile(r"\bcarrel (\d+\.\d+\.\d+)\b"),  # banner, doctor header, pack, hook summary
    re.compile(r"\bVersion:? (\d+\.\d+\.\d+)\b"),  # `claude plugin list`
    re.compile(r'"version": "(\d+\.\d+\.\d+)"'),  # catalog export JSON, plugin.json templates
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _plugin_names() -> list[str]:
    return [entry["name"] for entry in json.loads(_read(MARKETPLACE))["plugins"]]


def _live_docs() -> list[Path]:
    docs = [README, *sorted(DOCS.glob("*.md")), *sorted(REPO_ROOT.glob("plugins/*/README.md"))]
    return [path for path in docs if path.name not in HISTORY]


def test_readme_plugin_table_lists_every_marketplace_plugin():
    text = _read(README)
    missing = [
        name for name in _plugin_names() if not re.search(rf"(?m)^\| `{re.escape(name)}` \|", text)
    ]
    assert not missing, f"README.md plugin table lacks a row for: {missing}"


def test_marketplace_doc_lists_every_marketplace_plugin():
    text = _read(DOCS / "MARKETPLACE.md")
    missing = [
        name
        for name in _plugin_names()
        if not re.search(rf"(?m)^\| \*\*{re.escape(name)}\*\* \|", text)
    ]
    assert not missing, f"docs/MARKETPLACE.md plugin table lacks a row for: {missing}"


def test_features_has_no_in_flight_section():
    stale = [
        f"docs/FEATURES.md:{lineno}: {line}"
        for lineno, line in enumerate(_read(DOCS / "FEATURES.md").splitlines(), 1)
        if re.match(r"^##\s+In flight\b", line, re.IGNORECASE)
    ]
    assert not stale, "\n".join(
        ["FEATURES.md is a shipped/cut matrix, not a status board:", *stale]
    )


def test_doc_samples_show_the_current_version():
    version = PRODUCT["version"]
    stale: list[str] = []
    for path in _live_docs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            for pattern in VERSION_PATTERNS:
                stale.extend(
                    f"{rel}:{lineno}: {m.group(0)}"
                    for m in pattern.finditer(line)
                    if m.group(1) != version
                )
    assert not stale, "\n".join(
        [f"sample output must show carrel {version} — re-run the command and paste it:", *stale]
    )


def test_history_exclusions_name_real_files():
    """A renamed history doc would otherwise silently fall back into the gate — or out of it."""
    for name in sorted(HISTORY):
        assert (DOCS / name).is_file(), f"docs/{name} is excluded but does not exist"


# --------------------------------------------------------------- MCP surface

#: Every live doc is scanned, minus these. The first three are dated history
#: (`HISTORY` already excludes them from the version gate); `BUILD_PLAN.md` is
#: the wave checklist that shipped the 10-tool server. Hand-listing the docs to
#: *include* was the original mistake: six live statements of the count sat
#: outside the list, including a plugin skill's frontmatter.
MCP_COUNT_EXCLUDES = {*HISTORY, "BUILD_PLAN.md"}

#: number words carrel could plausibly reach, hyphenated forms included
NUMBER_WORDS = {
    3: "three",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
    21: "twenty-one",
    22: "twenty-two",
    23: "twenty-three",
    24: "twenty-four",
    25: "twenty-five",
    26: "twenty-six",
    27: "twenty-seven",
    28: "twenty-eight",
    29: "twenty-nine",
    30: "thirty",
}
_WORD_TO_NUMBER = {word: n for n, word in NUMBER_WORDS.items()}

#: "14 tools", "fourteen MCP tools", "**fourteen** tools", "`14` tools",
#: "Fourteen tools" — the count may be a numeral or a (possibly hyphenated)
#: word, and markdown may wrap it in emphasis or backticks.
COUNT_RE = re.compile(
    r"(?:\*\*|`|_)?(?P<count>\d+|[A-Za-z]+(?:-[a-z]+)?)(?:\*\*|`|_)?\s+(?:MCP\s+)?tools\b"
)

#: "v1 (3 tools) → v0.2.0 (10 tools + resources)" in the FEATURES tier column is
#: a record of what shipped when, not a claim about the current server.
HISTORICAL_COUNT = re.compile(r"v[\d.]+\s*\($")


def _mcp_docs() -> list[Path]:
    """Live docs, plus the plugin skills whose frontmatter states the count."""
    extra = sorted(REPO_ROOT.glob("plugins/*/skills/*/SKILL.md"))
    return [p for p in _live_docs() if p.name not in MCP_COUNT_EXCLUDES] + extra


def _tool_names() -> list[str]:
    from carrel.commands.mcp import TOOLS

    return [tool["name"] for tool in TOOLS]


def _display_name(tool: str) -> str:
    """`carrel_extract_images` -> `extract-images`, the spelling docs use."""
    return tool.removeprefix("carrel_").replace("_", "-")


def test_every_stated_mcp_tool_count_is_current():
    """`docs/index.md` said "ten MCP tools" for two releases after it became 14.

    Only tokens that *are* numbers are checked, so ordinary prose ("all MCP
    tools accept a root") is ignored while a stale count in any spelling fails.
    """
    count = len(_tool_names())
    ok = {str(count), NUMBER_WORDS.get(count, str(count))}
    wrong: list[str] = []
    for path in _mcp_docs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            if "tool" not in line.lower():
                continue
            for m in COUNT_RE.finditer(line):
                if HISTORICAL_COUNT.search(line[: m.start()]):
                    continue  # "v0.2.0 (10 tools)" — a release, not today
                token = m.group("count")
                lowered = token.lower()
                is_number = token.isdigit() or lowered in _WORD_TO_NUMBER
                if is_number and lowered not in ok:
                    wrong.append(f"{rel}:{lineno}: {m.group(0).strip()}")
    assert not wrong, "\n".join(
        [f"`carrel mcp` serves {count} tools — these say otherwise:", *wrong]
    )


def test_the_count_scanner_is_not_vacuous():
    """Guard the guard: prove the pattern matches the shapes this repo writes."""
    matched = {
        m.group("count")
        for text in ("14 tools", "fourteen MCP tools", "**fourteen** tools", "`26` tools")
        for m in COUNT_RE.finditer(text)
    }
    assert matched == {"14", "fourteen", "26"}
    # a hyphenated word survives intact rather than capturing only its tail
    assert [m.group("count") for m in COUNT_RE.finditer("twenty-six MCP tools")] == ["twenty-six"]
    # ordinary prose carries no number and is therefore not a count
    assert all(
        not (t.isdigit() or t.lower() in _WORD_TO_NUMBER)
        for t in (m.group("count") for m in COUNT_RE.finditer("all MCP tools accept a root"))
    )
    # and the docs really do state it somewhere, or the whole test is vacuous
    stated = sum(
        1
        for path in _mcp_docs()
        for line in _read(path).splitlines()
        if "tool" in line.lower() and COUNT_RE.search(line)
    )
    assert stated >= 5, f"only {stated} lines state a tool count; the scan is too narrow"


def test_the_agent_docs_name_every_mcp_tool():
    """docs/AGENTS.md is the table agents read; a missing row makes a tool invisible."""
    text = _read(DOCS / "AGENTS.md")
    missing = [name for name in _tool_names() if name not in text]
    assert not missing, f"docs/AGENTS.md lacks a row for: {missing}"


def test_the_prose_tool_lists_name_every_mcp_tool():
    """README and FEATURES list the tools inline, by bare command name.

    Checked only against the lines that describe the MCP surface: those command
    names occur all over both files for unrelated reasons, so scanning the whole
    document made this test impossible to fail.
    """
    missing: list[str] = []
    for rel in ("README.md", "docs/FEATURES.md"):
        path = REPO_ROOT / rel
        surface = " ".join(line for line in _read(path).splitlines() if "mcp" in line.lower())
        assert surface, f"{rel} says nothing about MCP"
        missing += [
            f"{rel}: {_display_name(name)}"
            for name in _tool_names()
            if not re.search(rf"\b{re.escape(_display_name(name))}\b", surface)
        ]
    assert not missing, "\n".join(["the MCP tool list is incomplete:", *missing])


def test_the_prose_lists_would_notice_a_deletion():
    """Guard the guard: strip the tool list out of the surface and it must fail.

    Scanning the whole document cannot work — `search`, `pack` and `diff` are
    ordinary command names that appear all over both files — which is why the
    check above narrows to the lines describing MCP. This proves that narrowing
    is enough to make a deletion visible.
    """
    surface = " ".join(
        line for line in _read(REPO_ROOT / "README.md").splitlines() if "mcp" in line.lower()
    )
    names = [_display_name(n) for n in _tool_names()]
    assert all(re.search(rf"\b{re.escape(n)}\b", surface) for n in names), "fixture assumption"

    gutted = re.sub(r"\(([^)]*)\)", "()", surface)  # drop the parenthesised list
    absent = [n for n in names if not re.search(rf"\b{re.escape(n)}\b", gutted)]
    assert len(absent) >= 10, f"removing the list left {len(absent)} names missing; expected most"


def test_repo_settings_doc_names_every_required_check():
    """`scripts/github-harden.sh` says it asserts what REPO_SETTINGS.md documents.

    When `test-minimal (macos)` was added to `REQUIRED_CHECKS` and applied to the
    live ruleset, the doc still listed the old five and still called macOS
    "Pending" — drift inside the very PR whose subject is a doc-drift gate.
    """
    script = _read(REPO_ROOT / "scripts" / "github-harden.sh")
    match = re.search(r"REQUIRED_CHECKS='(\[.*?\])'", script)
    assert match, "REQUIRED_CHECKS is no longer a single-line JSON array"
    checks = json.loads(match.group(1))
    assert len(checks) >= 5, f"suspiciously few required checks: {checks}"

    doc = _read(DOCS / "REPO_SETTINGS.md")
    missing = [name for name in checks if f"`{name}`" not in doc]
    assert not missing, (
        "docs/REPO_SETTINGS.md does not mention every required check "
        f"the hardening script applies: {missing}"
    )
