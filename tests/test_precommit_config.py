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

import re
import shlex
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


#: How every local hook must start. `--locked` never writes uv.lock and fails
#: when it is stale (uv's documented contract); plain `uv run` relocks silently,
#: and `--frozen` runs a stale lock quietly and overrides an exported UV_LOCKED.
LOCKED_RUN = ["uv", "run", "--locked"]

#: The lock check's exact entry: read-only, never reached through `uv run`.
LOCK_CHECK = ["uv", "lock", "--check"]

#: The only hook repos allowed to pin their own versions: none of their tools
#: is in uv.lock. Everything else is a local hook that runs from the lock.
REMOTE_REPOS = {"https://github.com/pre-commit/pre-commit-hooks"}


def _config() -> dict:
    """Parsed fresh on every call, so no test can leak a mutation into another."""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _ordered_hooks() -> list[dict]:
    return [hook for repo in _config()["repos"] for hook in repo["hooks"]]


def _hooks() -> dict[str, dict]:
    """Every hook by id. Ids are unique except where a test says otherwise."""
    found: dict[str, dict] = {}
    for hook in _ordered_hooks():
        found.setdefault(hook["id"], hook)
    return found


def _all_check_yaml() -> list[dict]:
    return [h for h in _ordered_hooks() if h["id"] == "check-yaml"]


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
    indexed = {*MUTATING, "check-yaml", "mypy", "uv-lock-current"}
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
        f"{hook_id} must pin `types_or`: a `language: system` hook without it is "
        "handed every staged file, Markdown included"
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


# ------------------------------------------------------------ the locked toolchain


def test_no_hook_repo_pins_its_own_version_of_a_locked_tool():
    """A remote `repo:` with a `rev` is a second copy of a version uv.lock owns.

    ruff-pre-commit was one: every Dependabot bump of ruff in uv.lock left the
    hook a version behind the ruff CI's lint job runs.
    """
    remote = sorted({r["repo"] for r in _config()["repos"]} - {"local"} - REMOTE_REPOS)
    assert not remote, (
        f"remote hook repos outside the allowlist: {remote}. Run the tool as a local "
        f"`{shlex.join(LOCKED_RUN)} <tool>` hook, or add the repo to REMOTE_REPOS if "
        "nothing in uv.lock provides it"
    )


def test_every_local_hook_runs_from_the_lock():
    """Fail closed: every local hook matches one of two shapes, or it is refused.

    Refusing everything else is what catches the spellings that dodge a narrower
    check — a flag before `run` (`uv --no-progress run`), an option that takes a
    value (`uv run --group dev`), `uv sync`, `uvx ruff@0.15.0`, `bash -c`, or a
    `language: python` hook installing its own `additional_dependencies`.
    `args` are appended because pre-commit appends them: that is what runs.
    """
    offenders = []
    for repo in _config()["repos"]:
        if repo["repo"] != "local":
            continue
        for hook in repo["hooks"]:
            argv = [*shlex.split(hook["entry"]), *hook.get("args", [])]
            tool = argv[len(LOCKED_RUN) : len(LOCKED_RUN) + 1]
            locked_run = (
                argv[: len(LOCKED_RUN)] == LOCKED_RUN and tool and not tool[0].startswith("-")
            )
            if (
                hook.get("language") != "system"
                or hook.get("additional_dependencies")
                or not (argv == LOCK_CHECK or locked_run)
            ):
                offenders.append(f"{hook['id']}: {shlex.join(argv)}")
    assert not offenders, (
        f"local hooks must be `language: system` and run `{shlex.join(LOCK_CHECK)}` or "
        f"`{shlex.join(LOCKED_RUN)} <tool> …`: {offenders}"
    )


@pytest.mark.parametrize(
    ("hook_id", "command"),
    [("ruff-check", ["ruff", "check"]), ("ruff-format", ["ruff", "format"]), ("mypy", ["mypy"])],
)
def test_the_linters_are_the_locked_ones_ci_runs(hook_id: str, command: list[str]):
    hook = _hooks()[hook_id]
    argv = [*shlex.split(hook.get("entry", "")), *hook.get("args", [])]
    assert argv[: len(LOCKED_RUN) + len(command)] == [*LOCKED_RUN, *command], (
        f"{hook_id} must run `{shlex.join([*LOCKED_RUN, *command])}`, got {argv}"
    )
    if command[0] == "ruff":
        # pre-commit passes filenames explicitly, and ruff applies pyproject's
        # `extend-exclude` (`**/*.md`) to explicit paths only with this flag
        assert "--force-exclude" in argv, f"{hook_id} ignores pyproject's exclude: {argv}"


def test_the_lock_check_is_read_only_and_runs_first():
    """`uv-lock-current` is what reports a stale lock locally; CI would fail every job.

    It runs before every other local hook so its failure is the first thing a
    committer reads, not a `--locked` error from whichever tool happened to run.
    """
    local = [h for r in _config()["repos"] if r["repo"] == "local" for h in r["hooks"]]
    ids = [h["id"] for h in local]
    assert "uv-lock-current" in ids, ".pre-commit-config.yaml no longer checks uv.lock"
    hook = local[ids.index("uv-lock-current")]
    assert shlex.split(hook["entry"]) == LOCK_CHECK, f"not the read-only check: {hook['entry']}"
    assert not hook.get("args"), f"`uv lock --check` takes no args: {hook['args']}"
    assert hook.get("pass_filenames") is False, "`uv lock --check` takes no filenames"
    for path in ("pyproject.toml", "uv.lock"):
        assert re.search(hook["files"], path), f"uv-lock-current does not fire on {path}"
    assert ids[0] == "uv-lock-current", f"{ids[0]} runs before the lock check; put it first"
