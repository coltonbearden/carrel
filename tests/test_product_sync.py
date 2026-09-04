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
    assert PRODUCT == product_json, (
        "src/carrel/_product.py is out of sync with product.json — "
        "run scripts/sync_product.py"
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
    for path in list(REPO_ROOT.glob("docs/*.md")) + [REPO_ROOT / "README.md", REPO_ROOT / "mkdocs.yml"]:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for match in re.finditer(r"github\.com/([A-Za-z0-9_.-]+)/carrel", line):
                if match.group(1).lower() != owner.lower():
                    stale.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {match.group(0)}")
    assert not stale, "\n".join(stale)
