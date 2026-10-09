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

import copy
import functools
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

#: The events each workflow starts on. Fail closed: a new workflow, or a new
#: event on an old one, is refused until it is argued for here; the filters on
#: `push` and `release` are held by their own test below. `docs.yml`
#: deploys Pages on every event but `pull_request` and `publish.yml` uploads to
#: PyPI, so neither may gain a timer, and a timer by proxy (`workflow_run` after
#: a scheduled workflow, or being called by one) is a timer.
TRIGGERS = {
    "context7-refresh.yml": {"push", "workflow_dispatch"},
    "docs.yml": {"push", "pull_request", "workflow_dispatch"},
    "publish.yml": {"release"},
    "test.yml": {"push", "pull_request", "workflow_dispatch", "workflow_call"},
    "weekly.yml": {"schedule", "workflow_dispatch"},
}

#: The only reusable-workflow call: the weekly run is `test.yml` and nothing else.
CALLS = {("weekly.yml", "tests", "./.github/workflows/test.yml")}


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


@functools.cache
def _parsed(workflow: str) -> dict:
    return yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8")) or {}


def _load(workflow: str) -> dict:
    """A workflow file, parsed once; a copy, so no test can change what another reads."""
    return copy.deepcopy(_parsed(workflow))


def _jobs() -> list[tuple[str, str, dict]]:
    return [
        (path.name, job_id, job)
        for path in _workflow_files()
        for job_id, job in _load(path.name).get("jobs", {}).items()
    ]


def _triggers(workflow: str) -> dict:
    """The workflow's `on:` block as a mapping, whichever way it was written."""
    data = _load(workflow)
    # YAML 1.1 reads a bare `on` key as the boolean True, and PyYAML follows it
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return dict(on or {})


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


def test_every_setup_uv_step_uses_the_same_pin():
    """Dependabot moves all the steps together; a pasted job or a hand-resolved merge may not.

    The step is copied into every job rather than shared, and a copy left on an
    older ref still passes the pin and cache rules above, so `publish.yml` could
    run a setup-uv no pull request exercised.
    """
    refs = {
        str(step["uses"])
        for _workflow, _job_id, job in _jobs()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).lower().startswith("astral-sh/setup-uv@")
    }
    assert len(refs) == 1, f"setup-uv is pinned to more than one ref: {sorted(refs)}"


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


@pytest.mark.parametrize("workflow", [path.name for path in _workflow_files()])
def test_every_workflow_starts_only_the_ways_listed(workflow):
    assert workflow in TRIGGERS, f"{workflow} is new: list its triggers in TRIGGERS, with a reason"
    assert set(_triggers(workflow)) == TRIGGERS[workflow], (
        f"{workflow} starts on {sorted(_triggers(workflow))}, expected {sorted(TRIGGERS[workflow])}"
    )


def test_the_weekly_run_is_the_only_reusable_call():
    """A job that calls a workflow runs it on the caller's events, a timer included."""
    calls = {
        (workflow, job_id, str(job["uses"])) for workflow, job_id, job in _jobs() if "uses" in job
    }
    assert calls == CALLS, f"reusable-workflow calls changed: {sorted(calls)}"


def test_main_is_tested_weekly_as_well_as_on_push():
    """A push-only `main` is only as fresh as its last merge.

    With no merge between 2026-09-24 and 2026-10-09, `main` showed a green run
    while a test tied to the calendar failed on every branch from 2026-10-01.
    One run a week: a wildcard hour would be hourly, a wildcard day daily. The
    cron lives in `weekly.yml`, which GitHub may disable in a quiet repository,
    and never in `test.yml`, which reports the required checks (D-028).
    """
    assert _triggers("test.yml")["push"] == {"branches": ["main"]}
    crons = [entry.get("cron") for entry in _triggers("weekly.yml")["schedule"]]
    assert len(crons) == 1, f"weekly.yml must have exactly one schedule, found {crons}"
    fields = str(crons[0]).split()
    assert len(fields) == 5, crons
    minute, hour, day_of_month, month, day_of_week = fields
    assert re.fullmatch(r"[0-5]?[0-9]", minute), f"{crons[0]!r}: minute is not one of 0-59"
    assert re.fullmatch(r"[01]?[0-9]|2[0-3]", hour), f"{crons[0]!r}: hour is not one of 0-23"
    assert (day_of_month, month) == ("*", "*"), f"{crons[0]!r} is not weekly"
    assert re.fullmatch(r"[0-6]|SUN|MON|TUE|WED|THU|FRI|SAT", day_of_week, re.IGNORECASE), (
        f"{crons[0]!r} is not one day a week"
    )


def test_no_job_can_sit_out_the_weekly_run():
    """A condition could skip the suite on `schedule`, leaving a green run that tested nothing.

    The same goes for a failure that is waved through: only the Windows job is
    advisory, and that is a decision with a date (D-028).
    """
    problems = []
    for workflow, job_id, job in _jobs():
        if workflow not in ("test.yml", "weekly.yml"):
            continue
        where = f"{workflow}:{job_id}"
        if "if" in job:
            problems.append(f"{where}: job-level `if:`")
        if job.get("continue-on-error") and job_id != "test-minimal-windows":
            problems.append(f"{where}: continue-on-error")
        for step in job.get("steps", []):
            if "pytest" not in str(step.get("run", "")):
                continue
            name = step.get("name", "?")
            if "if" in step:
                problems.append(f"{where}:{name}: the suite is behind an `if:`")
            if step.get("continue-on-error"):
                problems.append(f"{where}:{name}: the suite's failure is ignored")
    assert not problems, "\n".join(problems)


def test_push_and_release_triggers_stay_narrow():
    """An event name says nothing about its filter: `push` with no `branches` is every push.

    `docs.yml` deploys Pages on push, so a widened filter there is a deploy from
    any branch or tag, and `publish.yml` must upload on `published` only.
    """
    for workflow in sorted(TRIGGERS):
        push = _triggers(workflow).get("push", {"branches": ["main"]})
        assert isinstance(push, dict) and push.get("branches") == ["main"], (
            f"{workflow}: `push` must be limited to `branches: [main]`, got {push}"
        )
        assert not {"tags", "tags-ignore", "branches-ignore"} & set(push), f"{workflow}: {push}"
    assert _triggers("publish.yml") == {"release": {"types": ["published"]}}
