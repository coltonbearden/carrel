"""Product identity: generated _product.py must mirror /product.json exactly."""

from __future__ import annotations

import json
import re
import sys
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


def test_context7_sync_rewrites_identity_only(tmp_path, monkeypatch):
    """Guard the sync by *running* it, not by reading the file it last produced.

    The first version asserted the committed file's content, so a regression in
    `sync_context7` that dropped `folders` or `rules` passed on any tree where the
    script had not yet run — and CI's lint job, which does run it, diffs a pathspec
    that does not include `context7.json`, so the damage was invisible there too.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import sync_product

    original = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    stale = {**original, "projectTitle": "old name", "description": "old description"}
    (tmp_path / "context7.json").write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(sync_product, "ROOT", tmp_path)

    sync_product.sync_context7(PRODUCT)

    after = json.loads((tmp_path / "context7.json").read_text(encoding="utf-8"))
    assert after["projectTitle"] == PRODUCT["displayName"]
    assert after["description"] == PRODUCT["description"]
    untouched = {k: v for k, v in original.items() if k not in ("projectTitle", "description")}
    assert {k: after[k] for k in untouched} == untouched, "the sync rewrote a hand-maintained key"


def test_context7_sync_ignores_a_directory_in_its_place(tmp_path, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import sync_product

    (tmp_path / "context7.json").mkdir()
    monkeypatch.setattr(sync_product, "ROOT", tmp_path)
    sync_product.sync_context7(PRODUCT)  # must not raise IsADirectoryError mid-sync


def test_context7_exclusions_keep_what_replacing_the_defaults_would_lose():
    """Setting either list REPLACES Context7's defaults, so every re-listed name is load-bearing."""
    cfg = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    defaults = {
        "CHANGELOG.md",
        "changelog.md",
        "CHANGELOG.mdx",
        "changelog.mdx",
        "LICENSE.md",
        "license.md",
        "CODE_OF_CONDUCT.md",
        "code_of_conduct.md",
    }
    records = {"STATE.md", "CLAUDE.md", "DECISIONS.md", "TEST_REPORT.md", "HOW_THIS_WAS_BUILT.md"}
    assert defaults | records <= set(cfg["excludeFiles"])
    assert set(cfg["excludeFolders"]) == {"docs/assets", "docs/stylesheets"}
    assert cfg["folders"] == ["docs", "plugins"]
    assert len(cfg["rules"]) == 5


def test_context7_rules_name_only_flags_that_exist():
    """The rules are what other people's agents read, so each claim is checked against --help.

    The first version told agents that `dedupe` refuses tracked files and takes
    `--allow-tracked`. It has neither; an agent trusting it would delete tracked
    duplicates inside a checkout. REFERENCE.md and the plugin docs are pinned to
    `--help` already — this was the one CLI-behaviour surface with no gate.
    """
    from click.testing import CliRunner

    from carrel.cli import cli

    cfg = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    runner = CliRunner()
    helps: dict[str, str] = {}
    problems: list[str] = []
    for rule in cfg["rules"]:
        for cmd in re.findall(r"`carrel ([a-z-]+)", rule):
            if cmd not in helps:
                result = runner.invoke(cli, [cmd, "--help"])
                if result.exit_code != 0:
                    problems.append(f"`carrel {cmd}` does not exist")
                    continue
                helps[cmd] = result.output
        mentioned = re.findall(r"`carrel ([a-z-]+)", rule)
        for flag in set(re.findall(r"(--[a-z][a-z-]+)", rule)) - {"--json"}:
            if not any(
                re.search(rf"(^|[\s,/]){re.escape(flag)}\b", helps.get(c, "")) for c in mentioned
            ):
                problems.append(f"{flag} is not in --help for any of {mentioned}: {rule[:60]}…")
    assert not problems, "\n".join(problems)


def test_context7_rules_do_not_promise_a_guard_on_an_unguarded_command():
    """The specific false claim, pinned: only commands that call the guard may be said to have it."""
    guarded = {
        path.stem
        for path in (REPO_ROOT / "src" / "carrel" / "commands").glob("*.py")
        if "guard_worktree(" in path.read_text(encoding="utf-8")
    }
    commands = {p.stem for p in (REPO_ROOT / "src" / "carrel" / "commands").glob("*.py")}
    cfg = json.loads((REPO_ROOT / "context7.json").read_text(encoding="utf-8"))
    checked = 0
    for rule in cfg["rules"]:
        if "git is tracking" not in rule:
            continue
        # everything before the claim, in either spelling: `carrel rename` or bare `rename`
        # (the original false rule used the bare form, which a `carrel`-only regex missed)
        head = rule.split("git is tracking")[0]
        clause = head.rsplit(";", 1)[-1] if "no tracked-files guard" not in head else head
        tokens = set(re.findall(r"`(?:carrel )?([a-z][a-z-]*)`", clause)) & commands
        checked += 1
        assert tokens <= guarded, f"rule claims a tracked-files guard on {sorted(tokens - guarded)}"
    assert checked, "no rule mentions the tracked-files guard — this test would be vacuous"
