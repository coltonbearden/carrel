"""The formatting hooks must not fight the repository's own generators.

Two incidents, both found by running `pre-commit run --all-files` for the
first time:

* `ruff-format` reformats Python fences *inside Markdown* — its upstream
  `types_or` has included `markdown` since ruff-pre-commit v0.14. On this repo
  that rewrote `docs/COOKBOOK.md`'s mkdocs snippet directive
  `--8<-- "snippets/find-untagged.py"` into `--8 < --"..."`, which silently
  dropped the whole example from the published page. `mkdocs build --strict`
  still exited 0: `pymdownx.snippets`' own `check_paths` never fires, because
  the mangled text is no longer recognised as a directive at all.
* `end-of-file-fixer` stripped the trailing blank line from
  `tests/fixtures/thread.mbox`, which `tests/fixtures/generate.py` writes back
  on the next run (1058 bytes → 1057 → 1058). Fixtures are generated, never
  hand-edited (CLAUDE.md), so a whitespace hook can only lose that fight.

`test_ruff_leaves_markdown_alone` is the one that matters: it asserts the
*outcome* rather than the config shape, so it fails however the mangling comes
back — an editor's format-on-save, a bare `ruff format .`, a new CI step, or a
renamed hook. The config-shape tests below it explain why, and keep the
second line of defence in place.
"""

from __future__ import annotations

import functools
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

#: Hooks that rewrite the files they are given; each must skip generated trees.
MUTATING = ("end-of-file-fixer", "trailing-whitespace", "ruff-check", "ruff-format")

#: A path the exclude must cover, and one it must not.
GENERATED = "tests/fixtures/thread.mbox"
NOT_GENERATED = "src/carrel/cli.py"

#: Hand-written, and the one file in that tree nobody regenerates.
THE_GENERATOR = "tests/fixtures/generate.py"


@functools.cache
def _hooks() -> dict[str, dict]:
    """Every hook by id. Ids are unique except where a test says otherwise."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            found.setdefault(hook["id"], hook)
    return found


def _all_check_yaml() -> list[dict]:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [h for r in config["repos"] for h in r["hooks"] if h["id"] == "check-yaml"]


# --------------------------------------------------------------- the outcome


def test_ruff_leaves_markdown_alone():
    """The incident itself, asserted end to end rather than through the config.

    `docs/COOKBOOK.md` line 202 is the snippet directive that was mangled.
    Guarding this in `pyproject.toml` (`extend-exclude`) rather than only in
    the hook file is what makes it hold for every ruff invocation.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "--no-cache", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        "`ruff format` wants to rewrite files — if any are Markdown, it is "
        f"mangling snippet directives again:\n{proc.stdout}{proc.stderr}"
    )
    cookbook = (REPO_ROOT / "docs" / "COOKBOOK.md").read_text(encoding="utf-8")
    assert '--8<-- "snippets/find-untagged.py"' in cookbook, (
        "the mkdocs snippet directive is mangled; the built page loses the example"
    )


# ----------------------------------------------------------- the config shape


def test_the_config_defines_every_hook_these_tests_index():
    """Guard the guard: a renamed id must fail here, not as a KeyError below."""
    indexed = {*MUTATING, "check-yaml"}
    missing = sorted(indexed - set(_hooks()))
    assert not missing, f".pre-commit-config.yaml no longer defines: {missing}"


@pytest.mark.parametrize("hook_id", ["ruff-check", "ruff-format"])
def test_the_ruff_hooks_never_see_markdown(hook_id: str):
    """`ruff-format`'s upstream `types_or` includes `markdown`; this drops it.

    `ruff-check`'s upstream does *not* — its pin is belt-and-braces against a
    future upstream change, not a fix for today's behaviour.
    """
    types = _hooks()[hook_id].get("types_or")
    assert types is not None, (
        f"{hook_id} must pin `types_or` rather than inherit the upstream default"
    )
    assert "markdown" not in types, f"{hook_id} would reformat Markdown: {types}"
    # dropping `jupyter` while removing `markdown` would exempt notebooks silently
    assert "jupyter" in types, f"{hook_id} no longer covers notebooks: {types}"


@pytest.mark.parametrize("hook_id", MUTATING)
def test_the_mutating_hooks_skip_generated_fixtures(hook_id: str):
    """Asserted by matching the regex, not by searching its text.

    `exclude: ^(?!tests/fixtures/)` contains the substring "tests/fixtures/"
    and means the exact opposite; a substring check would pass it.
    """
    exclude = _hooks()[hook_id].get("exclude")
    assert exclude, f"{hook_id} has no `exclude`; the generator rewrites its output back"
    assert re.search(exclude, GENERATED), f"{hook_id} would rewrite {GENERATED}"
    assert not re.search(exclude, NOT_GENERATED), f"{hook_id} is excluded from {NOT_GENERATED}"
    assert not re.search(exclude, THE_GENERATOR), (
        f"{hook_id} skips {THE_GENERATOR}, which is hand-written, not generated"
    )


def test_check_yaml_reads_mkdocs_without_going_unsafe_everywhere():
    """`--unsafe` drops duplicate-key detection, so it is scoped to one file.

    mkdocs-material's `!relative` tag has no safe-load constructor, so the
    strict hook cannot read `mkdocs.yml`. Applying `--unsafe` repo-wide to
    accommodate it would stop the workflows being checked for the duplicate
    keys a bad merge leaves behind.
    """
    entries = _all_check_yaml()
    assert len(entries) == 2, f"expected a strict and an mkdocs-only check-yaml, got {entries}"
    strict = [e for e in entries if "--unsafe" not in e.get("args", [])]
    unsafe = [e for e in entries if "--unsafe" in e.get("args", [])]
    assert len(strict) == 1 and len(unsafe) == 1, entries

    assert re.search(strict[0]["exclude"], "mkdocs.yml"), "the strict hook must skip mkdocs.yml"
    assert not re.search(strict[0]["exclude"], ".github/workflows/test.yml"), (
        "the strict hook must still cover the workflows"
    )
    assert re.search(unsafe[0]["files"], "mkdocs.yml"), "the unsafe hook must cover mkdocs.yml"
    assert not re.search(unsafe[0]["files"], ".github/workflows/test.yml"), (
        "`--unsafe` must not reach the workflows: it stops catching duplicate keys"
    )
