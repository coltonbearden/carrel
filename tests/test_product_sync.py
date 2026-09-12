"""Product identity: generated _product.py must mirror /product.json exactly."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from carrel._product import PRODUCT

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_product_matches_json():
    product_json = json.loads((REPO_ROOT / "product.json").read_text())
    assert product_json == PRODUCT, (
        "src/carrel/_product.py is out of sync with product.json — run scripts/sync_product.py"
    )


def test_pyproject_version_matches():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == PRODUCT["version"]
    # distribution name follows the product name; the import package is fixed
    # even across renames (see rename_product.py) — assert it exists on disk
    assert pyproject["project"]["name"] == PRODUCT["name"]
    assert (Path(__file__).parent.parent / "src" / PRODUCT["package"] / "cli.py").is_file()


def test_project_urls_follow_product():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["urls"]["Repository"] == PRODUCT["repository"]


def test_citation_version_matches():
    text = (REPO_ROOT / "CITATION.cff").read_text()
    assert f'version: "{PRODUCT["version"]}"' in text
    assert f'repository-code: "{PRODUCT["repository"]}"' in text


def test_changelog_mentions_current_version():
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    assert f"## v{PRODUCT['version']}" in text, "add a CHANGELOG entry for the current version"


def test_no_stale_repository_owner():
    """Every GitHub link in docs/plugins/manifests must use the product repository owner."""
    owner = PRODUCT["repository"].removeprefix("https://github.com/").split("/")[0]
    stale = []
    for path in [
        *list(REPO_ROOT.glob("docs/*.md")),
        REPO_ROOT / "README.md",
        REPO_ROOT / "mkdocs.yml",
    ]:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for match in re.finditer(r"github\.com/([A-Za-z0-9_.-]+)/carrel", line):
                if match.group(1).lower() != owner.lower():
                    stale.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {match.group(0)}")
    assert not stale, "\n".join(stale)


# `uv.lock` also carries the version, but no test here can gate it: pytest runs
# under `uv run`, which relocks before it starts and so repairs the exact
# staleness it would be asked to detect (checked — a planted 0.4.1 was silently
# rewritten to 0.5.0 before the assertion ran). The gate is the `uv-lock-current`
# pre-commit hook, which shells `uv lock --check` — read-only, and the same
# condition CI's `UV_LOCKED=1` sync trips on.


def test_context7_identity_follows_product():
    """`context7.json` describes carrel to other people's agents — a rename must reach it."""
    cfg = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    assert cfg["projectTitle"] == PRODUCT["displayName"]
    assert cfg["description"] == PRODUCT["description"]


def test_context7_keeps_its_hand_maintained_keys():
    """Guard the sync: it must rewrite identity only, never the indexing scope."""
    cfg = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    assert cfg["folders"] == ["docs", "plugins"]
    assert cfg["rules"], "the agent rules are hand-written and must survive a sync"
    # setting these replaces Context7's defaults, so the defaults worth keeping
    # are re-listed here and their loss would be silent
    assert {"CHANGELOG.md", "LICENSE.md", "CODE_OF_CONDUCT.md"} <= set(cfg["excludeFiles"])
