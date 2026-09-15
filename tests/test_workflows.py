"""The workflows' supply-chain rules, asserted so a copy-paste cannot undo them.

Found reviewing Dependabot #49 (setup-uv 10.1.0):

* setup-uv's cache key is arch, platform, OS, Python version, a hash of the
  dependency files and `cache-suffix` — no workflow or job name. With the cache
  on everywhere and no suffix, `publish.yml`'s release build restored whatever a
  `test.yml` job saved after running third-party code, and `uv build`'s isolated
  build environment is not covered by uv.lock's hashes. The release and Pages
  builds now run with no cache; every other job suffixes its key.
* No step pinned uv, so every run installed the newest release. `version-file:
  uv.lock` installs the uv that uv.lock pins as a dev dependency, and setup-uv
  errors rather than falling back to "latest" when the file names none.
* The drift gate after `sync_product.py` diffed a hand-kept pathspec that did not
  include `context7.json`, which the script had been writing since #48, so a
  mangled sync would have been repaired on disk and reported green.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: Workflows whose output leaves the repository: a PyPI upload, a Pages deploy.
NO_CACHE = {"publish.yml", "docs.yml"}


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _setup_uv_steps() -> list[tuple[str, str, dict]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in _workflow(path.name)["jobs"].items():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                    found.append((path.name, job_id, step.get("with") or {}))
    return found


def test_the_setup_uv_scan_finds_steps():
    """Guard the guard: a renamed action or moved file must fail here."""
    workflows = {name for name, _, _ in _setup_uv_steps()}
    assert {"test.yml", "publish.yml", "docs.yml"} <= workflows, workflows


@pytest.mark.parametrize(("workflow", "job", "inputs"), _setup_uv_steps())
def test_every_setup_uv_step_installs_the_locked_uv(workflow: str, job: str, inputs: dict):
    assert inputs.get("version-file") == "uv.lock" and "version" not in inputs, (
        f"{workflow}:{job} must install uv with `version-file: uv.lock`, got {inputs}"
    )


@pytest.mark.parametrize(("workflow", "job", "inputs"), _setup_uv_steps())
def test_no_job_restores_a_cache_another_job_saved(workflow: str, job: str, inputs: dict):
    # setup-uv's default is `auto`: on for GitHub-hosted runners except release,
    # tag-push, pull_request_target and workflow_run events. publish.yml had set
    # `true` explicitly, overriding that exception. A missing key counts as on.
    cached = inputs.get("enable-cache", "auto") is not False
    if workflow in NO_CACHE:
        assert not cached, f"{workflow}:{job} publishes its output; set `enable-cache: false`"
    else:
        assert not cached or "${{ github.job }}" in str(inputs.get("cache-suffix", "")), (
            f"{workflow}:{job} shares one cache key with every other job; "
            "set `cache-suffix: ${{ github.job }}`"
        )


def test_uv_lock_pins_uv():
    """`version-file: uv.lock` reads the `uv` package entry; without one it errors."""
    import tomllib

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "uv"]
    assert len(versions) == 1, f"uv.lock must pin exactly one uv, found {versions}"


def _drift_pathspecs(workflow: str) -> list[list[str]]:
    """The pathspec of each `git diff --exit-code` that follows `sync_product.py`."""
    specs = []
    for job in _workflow(workflow)["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "scripts/sync_product.py" not in run:
                continue
            for line in run.splitlines():
                argv = shlex.split(line)
                if argv[:3] == ["git", "diff", "--exit-code"] and "--" in argv:
                    specs.append(argv[argv.index("--") + 1 :])
    return specs


@pytest.mark.parametrize("workflow", ["test.yml", "publish.yml"])
def test_the_sync_drift_gate_diffs_every_file_the_sync_writes(workflow, monkeypatch):
    """Recorded from the script itself, so a new target cannot be forgotten twice."""
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import sync_product

    written: list[Path] = []
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: written.append(self))
    sync_product.main()
    targets = sorted({p.relative_to(REPO_ROOT).as_posix() for p in written})
    assert "context7.json" in targets, f"the recorder missed a known target: {targets}"

    specs = _drift_pathspecs(workflow)
    assert len(specs) == 1, (
        f"{workflow}: expected one drift gate after sync_product.py, got {specs}"
    )
    (spec,) = specs
    uncovered = [
        t for t in targets if not any(t == s or t.startswith(s.rstrip("/") + "/") for s in spec)
    ]
    assert not uncovered, (
        f"{workflow}: sync_product.py writes {uncovered} but the drift gate does not diff them"
    )
