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
import itertools
import os
import re
import shlex
import shutil
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
def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _hooks() -> dict[str, dict]:
    """Every hook by id. Ids are unique except where a test says otherwise."""
    found: dict[str, dict] = {}
    for repo in _config()["repos"]:
        for hook in repo["hooks"]:
            found.setdefault(hook["id"], hook)
    return found


def _all_check_yaml() -> list[dict]:
    return [h for r in _config()["repos"] for h in r["hooks"] if h["id"] == "check-yaml"]


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
    """Both are `language: system` hooks, which are handed every staged file.

    Without a `types_or` pin they would see Markdown, and the formatter rewrites
    Python fences there; `extend-exclude` in pyproject.toml is the first guard.
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


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_no_hook_relocks_a_stale_lock_before_uv_lock_current_reads_it(tmp_path: Path):
    """`uv run` repairs a stale uv.lock silently, so a hook reached through it
    makes `uv-lock-current` pass on the file it just fixed.

    That happened in v0.5.0: `mypy` and `product-sync` ran first as plain
    `uv run …`, and the lock check reported "Passed" on a lock that CI then
    rejected. Asserted by running each hook's own `uv` prefix against a
    throwaway project with a stale lock and comparing the lock's bytes — not by
    string-matching a flag: what matters is that the lock survives, however the
    entry spells it.
    """
    prefixes: dict[str, list[str]] = {}
    for repo in _config()["repos"]:
        for hook in repo["hooks"]:
            argv = shlex.split(hook.get("entry", ""))
            if argv[:2] != ["uv", "run"]:
                continue
            flags = list(itertools.takewhile(lambda arg: arg.startswith("-"), argv[2:]))
            prefixes[hook["id"]] = ["uv", "run", *flags]
    assert prefixes, "no hook runs through `uv run`; this test no longer checks anything"

    project = tmp_path / "stale"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "stale-probe"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        "[tool.uv]\npackage = false\n",
        encoding="utf-8",
    )
    # CI exports UV_LOCKED=1, under which a plain `uv run` errors instead of
    # relocking — the defect would then leave the lock alone and pass here.
    # Only the two lock-policy variables go: CI's UV_PYTHON still picks the
    # interpreter, which offline mode cannot download.
    env = {k: v for k, v in os.environ.items() if k not in ("UV_LOCKED", "UV_FROZEN")}
    env["UV_OFFLINE"] = "1"  # a version-only relock resolves nothing
    subprocess.run(["uv", "lock"], cwd=project, env=env, check=True, capture_output=True)
    pyproject.write_text(pyproject.read_text().replace("0.1.0", "0.1.1"), encoding="utf-8")
    stale = (project / "uv.lock").read_bytes()
    check = subprocess.run(["uv", "lock", "--check"], cwd=project, env=env, capture_output=True)
    assert check.returncode != 0, "the probe project's lock is not stale; the test is vacuous"

    relocked = []
    for hook_id, prefix in prefixes.items():
        subprocess.run([*prefix, "python", "-c", "pass"], cwd=project, env=env, capture_output=True)
        if (project / "uv.lock").read_bytes() != stale:
            relocked.append(hook_id)
            (project / "uv.lock").write_bytes(stale)
    assert not relocked, (
        f"{relocked} relock uv.lock before `uv-lock-current` reads it; "
        "run them as `uv run --frozen …`"
    )
