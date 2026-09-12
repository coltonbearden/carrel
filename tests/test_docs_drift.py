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

import pytest

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


@pytest.mark.parametrize("doc", ["REPO_SETTINGS.md", "RELEASING.md"])
def test_doc_names_every_required_check(doc: str):
    """`scripts/github-harden.sh` owns the required checks; the docs must name every one.

    When `test-minimal (macos)` was added to `REQUIRED_CHECKS` and applied to the
    live ruleset, REPO_SETTINGS.md still listed the old five and RELEASING.md told
    a release run to wait for only those — so it would try to merge while the
    required macOS check was still pending.
    """
    script = _read(REPO_ROOT / "scripts" / "github-harden.sh")
    match = re.search(r"REQUIRED_CHECKS='(\[.*?\])'", script)
    assert match, "REQUIRED_CHECKS is no longer a single-line JSON array"
    checks = json.loads(match.group(1))
    assert len(checks) >= 5, f"suspiciously few required checks: {checks}"

    text = _read(DOCS / doc)
    missing = [name for name in checks if f"`{name}`" not in text]
    assert not missing, f"docs/{doc} does not name every required check: {missing}"


def _state_status() -> str:
    """STATE.md's Status bullet, whitespace-normalised across its wrapped lines."""
    text = _read(REPO_ROOT / "STATE.md")
    match = re.search(r"^- \*\*Status:\*\*(.*?)^- \*\*In flight:\*\*", text, re.S | re.M)
    assert match, "STATE.md has no Status bullet followed by In flight"
    return " ".join(match.group(1).split())


def test_state_status_counts_are_current():
    """STATE.md is what a resuming session reads first, and its counts are hand-typed.

    `docs/index.md` said "ten MCP tools" for two releases after it became 14; the
    Status line is the same kind of sentence. Only the Status bullet is checked —
    Done entries are dated history and keep the numbers of their day.
    """
    from carrel.cli import COMMANDS
    from carrel.commands.mcp import TOOLS
    from carrel.core.adapters import ADAPTERS

    live = {
        "commands": len(COMMANDS),
        "MCP tools": len(TOOLS),
        "adapters": len(ADAPTERS),
        "marketplace plugins": len(_plugin_names()),
    }
    status = _state_status()
    unstated: list[str] = []
    wrong: list[str] = []
    for noun, count in live.items():
        stated = [int(n) for n in re.findall(rf"(\d+) {re.escape(noun)}\b", status)]
        if not stated:
            unstated.append(noun)
        wrong += [f"{n} {noun} (live: {count})" for n in stated if n != count]
    assert not unstated, f"STATE.md's Status no longer states: {unstated}"
    assert not wrong, "STATE.md's Status is stale: " + "; ".join(wrong)


# --------------------------------------------------- test and recipe counts


#: "855 tests" in README.md, "501 tests" in CONTRIBUTING.md — both wrong by
#: hundreds, both read as current fact. A count in live prose has to be
#: generated or absent; the `HISTORY` files are dated records and may state
#: whatever was true on their date.
TEST_COUNT_RE = re.compile(r"\b(?P<count>\d[\d,]*)\s+tests\b", re.IGNORECASE)
#: "Wave 1 tests synthesized their own inputs" names a wave, not a quantity. The
#: labels this repo actually numbers, so the scanner does not cry wolf on prose.
LABELLED_NUMBER = re.compile(r"\b(?:wave|phase|round|step|python|v)\s*$", re.IGNORECASE)
RECIPE_COUNT_RE = re.compile(
    r"\b(?P<count>\d+|" + "|".join(_WORD_TO_NUMBER) + r")\s+(?:end-to-end\s+)?recipes\b",
    re.IGNORECASE,
)


def _recipe_count() -> int:
    return len(list((REPO_ROOT / "examples" / "cookbook").glob("*.sh")))


def _test_count() -> int:
    """`def test_` across the suite — only ever used to make the failure message useful."""
    return sum(
        len(re.findall(r"^def test_|^    def test_", _read(p), re.M))
        for p in (REPO_ROOT / "tests").rglob("test_*.py")
    )


@pytest.mark.parametrize("pattern", [TEST_COUNT_RE, RECIPE_COUNT_RE], ids=["tests", "recipes"])
def test_no_live_doc_states_a_test_or_recipe_count(pattern: re.Pattern[str]):
    """A number nobody regenerates is wrong within a week of being written."""
    wrong: list[str] = []
    for path in _live_docs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            for m in pattern.finditer(line):
                before = line[: m.start()]
                if HISTORICAL_COUNT.search(before):
                    continue  # "v0.1.0 shipped 501 tests" — a dated record
                if LABELLED_NUMBER.search(before):
                    continue  # "Wave 1 tests" — a label, not a count
                wrong.append(f"{rel}:{lineno}: {m.group(0).strip()}")
    assert not wrong, "\n".join(
        [
            "these state a count that nothing keeps current — generate it or drop it",
            f"(live now: {_test_count()} tests, {_recipe_count()} recipes)",
            *wrong,
        ]
    )


def test_the_count_scanners_are_not_vacuous():
    """Guard the guard: the exact sentences this repo actually wrote."""
    assert TEST_COUNT_RE.search("uv run pytest           # 501 tests; binary-gated")
    assert TEST_COUNT_RE.search("executed for real (855 tests; cookbook runs)")
    assert RECIPE_COUNT_RE.search("— ten end-to-end recipes, from scan→searchable-notes")
    assert RECIPE_COUNT_RE.search("12 recipes")
    # ...and prose that merely mentions the words is left alone
    assert not TEST_COUNT_RE.search("binary-gated tests skip when a binary is absent")
    assert not RECIPE_COUNT_RE.search("end-to-end recipes, from scan to notes")
    # ...as is a numbered label, which is not a quantity of anything
    assert LABELLED_NUMBER.search("No cross-deps: Wave ")
    assert not LABELLED_NUMBER.search("executed for real (855 ")


def test_the_history_exemption_is_load_bearing():
    """`HISTORY` files really do state counts, so excluding them is not cosmetic."""
    stated = [
        name
        for name in HISTORY
        if any(
            TEST_COUNT_RE.search(line) for line in _read(next(REPO_ROOT.rglob(name))).splitlines()
        )
    ]
    assert stated, "no HISTORY file states a test count — is the exemption still needed?"
