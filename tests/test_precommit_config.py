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


#: How every hook that runs a locked tool must start. `--locked` never writes
#: uv.lock and fails loudly when it is stale; plain `uv run` relocks silently,
#: and `--frozen` runs a stale lock quietly and overrides an exported UV_LOCKED.
LOCKED_RUN = ["uv", "run", "--locked"]

#: The lock check's exact entry: read-only, never reached through `uv run`.
LOCK_CHECK = ["uv", "lock", "--check"]


def _config() -> dict:
    """Parsed fresh on every call, so no test can leak a mutation into another."""
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _ordered_hooks() -> list[dict]:
    return [hook for repo in _config()["repos"] for hook in repo["hooks"]]


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


def test_every_hook_that_invokes_uv_uses_an_approved_shape():
    """Fail closed: a uv spelling this module does not know is refused, not skipped.

    The relock probe below runs the `uv run` prefix these hooks use. A hook
    spelled any other way — a flag before `run` (`uv --no-progress run`), an
    option that takes a value (`uv run --group dev`), `uv sync`, or `uv` inside
    `bash -c` — would not be probed, so it has to fail here instead.
    """
    offenders = []
    for hook in _ordered_hooks():
        entry = hook.get("entry", "")
        if not re.search(r"\buv\b", entry):
            continue
        argv = shlex.split(entry)
        if argv == LOCK_CHECK:
            continue
        if argv[: len(LOCKED_RUN)] == LOCKED_RUN and not argv[len(LOCKED_RUN)].startswith("-"):
            continue
        offenders.append(f"{hook['id']}: {entry}")
    assert not offenders, (
        f"hooks must invoke uv as `{shlex.join(LOCK_CHECK)}` or "
        f"`{shlex.join(LOCKED_RUN)} <tool> …`: {offenders}"
    )


@pytest.mark.parametrize(
    ("hook_id", "command"),
    [("ruff-check", ["ruff", "check"]), ("ruff-format", ["ruff", "format"]), ("mypy", ["mypy"])],
)
def test_locked_tools_run_from_the_lock(hook_id: str, command: list[str]):
    """One version per tool: the hook runs what uv.lock pins, as CI's lint job does.

    A remote `repo:` hook with its own `rev` is a second copy of the version that
    every Dependabot bump of uv.lock leaves behind.
    """
    remote = [r["repo"] for r in _config()["repos"] if r["repo"] != "local"]
    assert not any("ruff-pre-commit" in url or "mirrors-mypy" in url for url in remote), (
        f"a remote hook repo pins its own version of a locked tool: {remote}"
    )
    argv = shlex.split(_hooks()[hook_id]["entry"])
    assert argv[: len(LOCKED_RUN) + len(command)] == [*LOCKED_RUN, *command], (
        f"{hook_id} must run `{shlex.join([*LOCKED_RUN, *command])}`, got {argv}"
    )
    if command[0] == "ruff":
        # pre-commit passes filenames explicitly, and ruff applies pyproject's
        # `extend-exclude` (`**/*.md`) to explicit paths only with this flag
        assert "--force-exclude" in argv, f"{hook_id} ignores pyproject's exclude: {argv}"


def test_the_lock_check_is_read_only_and_runs_before_any_other_uv_hook():
    """`uv-lock-current` is what reports a stale lock locally; CI would fail every job."""
    hooks = _ordered_hooks()
    ids = [h["id"] for h in hooks]
    assert "uv-lock-current" in ids, ".pre-commit-config.yaml no longer checks uv.lock"
    hook = hooks[ids.index("uv-lock-current")]
    assert shlex.split(hook["entry"]) == LOCK_CHECK, f"not the read-only check: {hook['entry']}"
    assert hook.get("pass_filenames") is False, "`uv lock --check` takes no filenames"
    for path in ("pyproject.toml", "uv.lock"):
        assert re.search(hook["files"], path), f"uv-lock-current does not fire on {path}"
    first_uv = next(i for i, h in enumerate(hooks) if re.search(r"\buv\b", h.get("entry", "")))
    assert ids[first_uv] == "uv-lock-current", (
        f"{ids[first_uv]} runs uv before the lock check; put uv-lock-current first"
    )


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_hooks_uv_prefix_cannot_repair_a_stale_lock(tmp_path: Path):
    """`uv run` repairs a stale uv.lock silently; the hooks' prefix must not.

    In v0.5.0 `mypy` and `product-sync` ran first as plain `uv run …`, relocked,
    and `uv-lock-current` then reported "Passed" on a lock that CI rejected. The
    prefix is taken from the config and run against a throwaway project with a
    stale lock. A control run of plain `uv run` has to relock that same project
    first, so an interpreter or network failure cannot pass for "left it alone".
    """
    prefixes = {
        tuple(shlex.split(h["entry"])[: len(LOCKED_RUN)])
        for h in _ordered_hooks()
        if shlex.split(h.get("entry", ""))[:2] == ["uv", "run"]
    }
    assert prefixes, "no hook runs through `uv run`; this test no longer checks anything"

    project = tmp_path / "stale"
    project.mkdir()
    pyproject = project / "pyproject.toml"
    lock = project / "uv.lock"
    pyproject.write_text(
        '[project]\nname = "stale-probe"\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        "[tool.uv]\npackage = false\n",
        encoding="utf-8",
    )
    # CI exports UV_LOCKED=1, under which a plain `uv run` errors instead of
    # relocking — the control below would fail rather than prove anything.
    # Only the two lock-policy variables go: CI's UV_PYTHON still picks the
    # interpreter, which offline mode cannot download.
    env = {k: v for k, v in os.environ.items() if k not in ("UV_LOCKED", "UV_FROZEN")}
    env["UV_OFFLINE"] = "1"  # a version-only relock resolves nothing

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8"
        )

    locked = run("uv", "lock")
    assert locked.returncode == 0, locked.stderr
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace("0.1.0", "0.1.1"), encoding="utf-8"
    )
    stale = lock.read_bytes()
    check = run(*LOCK_CHECK)
    assert "needs to be updated" in check.stderr, f"the probe lock is not stale: {check.stderr}"

    control = run("uv", "run", "python", "-c", "pass")
    assert control.returncode == 0 and lock.read_bytes() != stale, (
        f"plain `uv run` did not relock the probe, so this test proves nothing: {control.stderr}"
    )

    for prefix in sorted(prefixes):
        lock.write_bytes(stale)
        probe = run(*prefix, "python", "-c", "pass")
        assert lock.read_bytes() == stale, f"`{shlex.join(prefix)}` rewrote a stale uv.lock"
        assert probe.returncode == 0 or "needs to be updated" in probe.stderr, (
            f"`{shlex.join(prefix)}` failed for a reason other than the stale lock: {probe.stderr}"
        )
