"""The workflows' supply-chain rules, asserted so a copy-paste cannot undo them.

Found reviewing Dependabot #49 (setup-uv 10.1.0):

* setup-uv's cache key is arch, platform, OS, Python version, a hash of the
  dependency files and `cache-suffix` — no workflow or job name. With the cache
  on everywhere and no suffix, `publish.yml`'s release build restored whatever a
  `test.yml` job saved after running third-party code, and `uv build`'s isolated
  build environment is not covered by uv.lock's hashes. Only `test.yml` caches
  now, each job under its own key; every other workflow runs uncached.
* No step pinned uv, so every run installed the newest release. `version-file:
  uv.lock` installs the uv that uv.lock pins through the never-installed `uv-pin`
  group, and setup-uv errors rather than falling back to "latest" when the file
  names none.
* The drift gate after `sync_product.py` diffed a hand-kept pathspec that did not
  include `context7.json`, which the script had been writing since #48, so a
  mangled sync would have been repaired on disk and reported green. The gates
  now diff the whole tree, so a new sync target cannot be left out of a list.

The rules fail closed: an unknown workflow is uncached, an expression counts as
a cache switched on, a local action is refused until this module can read it,
and a gate that can be skipped or ignored is no gate.
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The sdist ships tests/ but not the workflows or uv.lock these read.
pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir() or not (REPO_ROOT / "uv.lock").is_file(),
    reason="the workflows and uv.lock are not part of the sdist",
)

#: The only workflow allowed a cache. Fail closed: a new workflow — a release,
#: a deploy, one holding a secret — runs uncached until someone argues otherwise
#: here, rather than inheriting a cache a test job saved after running PyPI code.
CACHED = {"test.yml"}

#: What makes a cache key this job's own: job ids repeat across workflows.
OWN_KEY = ("${{ github.workflow }}", "${{ github.job }}")

#: The scripts that regenerate committed files; each must be followed by a gate.
SYNC_SCRIPTS = ("scripts/sync_product.py", "scripts/sync_reference.py", "scripts/sync_plugins.py")


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def _jobs() -> list[tuple[str, str, dict]]:
    return [
        (path.name, job_id, job)
        for path in _workflow_files()
        for job_id, job in (yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        .get("jobs", {})
        .items()
    ]


def _setup_uv_steps() -> list[tuple[str, str, dict, dict]]:
    return [
        (workflow, job_id, job, step.get("with") or {})
        for workflow, job_id, job in _jobs()
        for step in job.get("steps", [])
        # action references are case-insensitive on GitHub
        if str(step.get("uses", "")).lower().startswith("astral-sh/setup-uv@")
    ]


SETUP_UV_STEPS = _setup_uv_steps()
SETUP_UV_IDS = [f"{workflow}:{job}" for workflow, job, *_ in SETUP_UV_STEPS]


def _switched_on(value: object) -> bool:
    """setup-uv reads the input as a string; anything but "false" may cache."""
    return str(value).strip().lower() != "false"


def test_the_setup_uv_scan_finds_steps():
    """Guard the guard: a renamed action or moved file must fail here."""
    workflows = {workflow for workflow, *_ in SETUP_UV_STEPS}
    assert {"test.yml", "publish.yml", "docs.yml"} <= workflows, workflows


@pytest.mark.parametrize(("workflow", "job", "job_def", "inputs"), SETUP_UV_STEPS, ids=SETUP_UV_IDS)
def test_every_setup_uv_step_installs_the_locked_uv(workflow, job, job_def, inputs):
    assert inputs.get("version-file") == "uv.lock" and "version" not in inputs, (
        f"{workflow}:{job} must install uv with `version-file: uv.lock`, got {inputs}"
    )


@pytest.mark.parametrize(("workflow", "job", "job_def", "inputs"), SETUP_UV_STEPS, ids=SETUP_UV_IDS)
def test_no_job_restores_a_cache_another_job_saved(workflow, job, job_def, inputs):
    # setup-uv's default is `auto`: on for GitHub-hosted runners except release,
    # tag-push, pull_request_target and workflow_run events. publish.yml had set
    # `true` explicitly, overriding that exception. A missing key counts as on.
    cached = _switched_on(inputs.get("enable-cache", "auto"))
    if workflow not in CACHED:
        assert not cached, f"{workflow}:{job} may not use the uv cache; set `enable-cache: false`"
        return
    if not cached:
        return
    suffix = str(inputs.get("cache-suffix", ""))
    assert all(part in suffix for part in OWN_KEY), (
        f"{workflow}:{job} can share a cache key with another job; "
        "set `cache-suffix: ${{ github.workflow }}-${{ github.job }}`"
    )
    matrix = (job_def.get("strategy") or {}).get("matrix") or {}
    assert isinstance(matrix, dict), f"{workflow}:{job}: a computed matrix cannot be checked"
    axes = {k for k in matrix if k not in ("include", "exclude")}
    for extra in matrix.get("include") or []:
        axes |= set(extra) if isinstance(extra, dict) else set()
    python = str(inputs.get("python-version", ""))  # already part of setup-uv's own key
    for axis in sorted(axes):
        ref = f"matrix.{axis}"
        keyed = re.compile(rf"\bmatrix\.{re.escape(axis)}\b")
        assert keyed.search(suffix) or keyed.search(python), (
            f"{workflow}:{job}: matrix legs differing in `{axis}` share one cache key; "
            f"add `${{{{ {ref} }}}}` to `cache-suffix`"
        )


@pytest.mark.parametrize("workflow", sorted({p.name for p in _workflow_files()} - CACHED))
def test_uncached_workflows_use_no_other_cache_either(workflow):
    """`actions/cache` on ~/.cache/uv, a setup action's `cache:`, or a local action
    this module cannot see into, is the same hole."""
    offenders = []
    for wf, job_id, job in _jobs():
        if wf != workflow:
            continue
        for step in job.get("steps", []):
            uses = str(step.get("uses", "")).lower()
            inputs = step.get("with") or {}
            if uses.startswith("./"):
                offenders.append(f"{job_id}: local action {uses} (teach this test to read it)")
            elif uses.startswith("actions/cache"):
                offenders.append(f"{job_id}: {uses}")
            elif (
                "/setup-" in uses
                and not uses.startswith("astral-sh/")
                and str(inputs.get("cache", "")).strip()
                and _switched_on(inputs["cache"])
            ):
                offenders.append(f"{job_id}: {uses} with cache: {inputs['cache']}")
    assert not offenders, f"{workflow} restores a cache another workflow can write: {offenders}"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_the_pinned_uv_is_never_installed_into_the_venv():
    """Locked for setup-uv to read, but not in anything `uv sync` installs.

    In `dev` it put a second uv in `.venv/bin`, first on PATH under `uv run`, so
    every nested `uv` and every `language: system` hook used the pinned copy — and
    on Windows a sync that upgrades uv.exe cannot replace the running binary.
    Asked of uv itself, for everything CI syncs, so an `include-group` or a tool
    that depends on uv is caught as well as a direct entry.
    """
    proc = subprocess.run(
        [
            *("uv", "export", "--frozen", "--no-hashes", "--no-header", "--no-emit-project"),
            *("--all-extras", "--group", "dev", "--group", "docs"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    installed = [line for line in proc.stdout.splitlines() if line.lower().startswith("uv==")]
    assert not installed, f"a synced group installs uv into .venv: {installed}"


def test_uv_lock_pins_uv():
    """`version-file: uv.lock` reads the `uv` package entry; without one it errors."""
    import tomllib

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "uv"]
    assert len(versions) == 1, f"uv.lock must pin exactly one uv, found {versions}"


def _gate_problems(workflow: str) -> tuple[int, list[str]]:
    """Count the sync steps in `workflow` and list every way their gate can fail open."""
    steps, problems = 0, []
    for wf, job_id, job in _jobs():
        if wf != workflow:
            continue
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            if not any(script in run for script in SYNC_SCRIPTS):
                continue
            steps += 1
            where = f"{workflow}:{job_id}:{step.get('name', '?')}"
            if job.get("continue-on-error") or step.get("continue-on-error"):
                problems.append(f"{where}: continue-on-error")
            if "if" in step:
                problems.append(f"{where}: `if:` can skip it")
            if "shell" in step:
                problems.append(f"{where}: a custom shell may not stop on errors")
            if "set +e" in run or "||" in run:
                problems.append(f"{where}: `set +e` or `||` ignores a failure")
            # shell semantics: backslash-newline joins lines, `#` starts a comment
            lines = []
            for line in run.replace("\\\n", " ").splitlines():
                try:
                    lines.append(shlex.split(line, comments=True))
                except ValueError:
                    lines.append([])  # unreadable: counts as not the gate
            lines = [argv for argv in lines if argv]
            if not lines or lines[-1] != ["git", "diff", "--exit-code"]:
                problems.append(
                    f"{where}: must end with a whole-tree `git diff --exit-code`, got {lines[-1:]}"
                )
    return steps, problems


@pytest.mark.parametrize(("workflow", "expected"), [("test.yml", 3), ("publish.yml", 1)])
def test_every_sync_ends_in_a_whole_tree_drift_gate(workflow: str, expected: int):
    """A pathspec is a list to forget a file from; the whole tree cannot be.

    The last command of the step is its exit status, so the gate has to be last,
    unconditional, and not followed by anything that could swallow its failure.
    """
    steps, problems = _gate_problems(workflow)
    assert steps == expected, f"{workflow}: expected {expected} sync steps, found {steps}"
    assert not problems, "\n".join(problems)
