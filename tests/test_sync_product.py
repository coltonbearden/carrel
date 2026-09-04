"""scripts/sync_product.py must be safe with odd metadata and touch only plugin versions."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "sync_product.py"


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A minimal copy of the repo files the script touches (scripts resolve ROOT from __file__)."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "sync_product.py")
    for rel in (
        "product.json",
        "pyproject.toml",
        "CITATION.cff",
        ".claude-plugin/marketplace.json",
    ):
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dest)
    for manifest in REPO_ROOT.glob("plugins/*/.claude-plugin/plugin.json"):
        dest = root / manifest.relative_to(REPO_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(manifest, dest)
    (root / "src" / "carrel").mkdir(parents=True)
    return root


def run_sync(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "sync_product.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_backslashes_in_description_survive(repo_copy: Path):
    product = json.loads((repo_copy / "product.json").read_text())
    product["description"] = r"matches \d digits, paths like C:\files and a \n here"
    (repo_copy / "product.json").write_text(json.dumps(product, indent=2))
    proc = run_sync(repo_copy)
    assert proc.returncode == 0, proc.stderr
    pyproject = tomllib.loads((repo_copy / "pyproject.toml").read_text())
    assert pyproject["project"]["description"].endswith(product["description"])


def test_marketplace_metadata_version_is_left_alone(repo_copy: Path):
    mp = repo_copy / ".claude-plugin" / "marketplace.json"
    data = json.loads(mp.read_text())
    data["metadata"]["version"] = "1"
    mp.write_text(json.dumps(data, indent=2) + "\n")
    product = json.loads((repo_copy / "product.json").read_text())
    product["version"] = "9.9.9"
    (repo_copy / "product.json").write_text(json.dumps(product, indent=2))
    proc = run_sync(repo_copy)
    assert proc.returncode == 0, proc.stderr
    after = json.loads(mp.read_text())
    assert after["metadata"]["version"] == "1"
    assert {p["version"] for p in after["plugins"]} == {"9.9.9"}
    for manifest in repo_copy.glob("plugins/*/.claude-plugin/plugin.json"):
        assert json.loads(manifest.read_text())["version"] == "9.9.9"


def test_sync_is_idempotent_on_the_real_tree(repo_copy: Path):
    first = run_sync(repo_copy)
    assert first.returncode == 0, first.stderr
    snapshot = {p: p.read_bytes() for p in repo_copy.rglob("*") if p.is_file()}
    second = run_sync(repo_copy)
    assert second.returncode == 0, second.stderr
    assert snapshot == {p: p.read_bytes() for p in repo_copy.rglob("*") if p.is_file()}
