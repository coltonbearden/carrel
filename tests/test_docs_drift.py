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
