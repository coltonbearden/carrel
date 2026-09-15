"""The workflows' supply-chain rules, asserted so a copy-paste cannot undo them.

Found reviewing Dependabot #49 (setup-uv 10.1.0):

* setup-uv's cache key is arch, platform, OS, Python version, a hash of the
  dependency files and `cache-suffix` — no workflow or job name. With the cache
  on everywhere and no suffix, `publish.yml`'s release build restored whatever a
  `test.yml` job saved after running third-party code, and `uv build`'s isolated
  build environment is not covered by uv.lock's hashes. The release and Pages
  builds now run with no cache; every other job suffixes its key.
* No step pinned uv, so every run installed the newest release. `version-file:
  uv.lock` installs the uv that uv.lock pins through the never-installed `uv-pin`
  group, and setup-uv errors rather than falling back to "latest" when the file
  names none.
* The drift gate after `sync_product.py` diffed a hand-kept pathspec that did not
  include `context7.json`, which the script had been writing since #48, so a
  mangled sync would have been repaired on disk and reported green.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The only workflow allowed a uv cache. Fail closed: a new workflow — a release,
#: a deploy, one holding a secret — runs uncached until someone argues otherwise
#: here, rather than inheriting a cache a test job saved after running PyPI code.
CACHED = {"test.yml"}

#: What makes a cache key this job's own: job ids repeat across workflows.
OWN_KEY = ("${{ github.workflow }}", "${{ github.job }}")


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
    if workflow not in CACHED:
        assert not cached, f"{workflow}:{job} may not use the uv cache; set `enable-cache: false`"
    elif cached:
        suffix = str(inputs.get("cache-suffix", ""))
        assert all(part in suffix for part in OWN_KEY), (
            f"{workflow}:{job} can share a cache key with another job; "
            "set `cache-suffix: ${{ github.workflow }}-${{ github.job }}`"
        )


def test_the_pinned_uv_is_never_installed_into_the_venv():
    """Locked for setup-uv to read, but in no group `uv sync` installs by default.

    In `dev` it put a second uv in `.venv/bin`, first on PATH under `uv run`, so
    every nested `uv` and every `language: system` hook used the pinned copy — and
    on Windows a sync that upgrades uv.exe cannot replace the running binary.
    """
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    default_groups = pyproject.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    groups = pyproject["dependency-groups"]
    carrying_uv = [
        name
        for name, reqs in groups.items()
        if any(isinstance(r, str) and re.match(r"uv\b(?![-_.\w])", r) for r in reqs)
    ]
    assert carrying_uv, "no dependency group pins uv; setup-uv's version-file has nothing to read"
    installed = [g for g in carrying_uv if default_groups == "all" or g in default_groups]
    assert not installed, f"uv is pinned in default-installed groups {installed}"


def test_uv_lock_pins_uv():
    """`version-file: uv.lock` reads the `uv` package entry; without one it errors."""
    import tomllib

    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "uv"]
    assert len(versions) == 1, f"uv.lock must pin exactly one uv, found {versions}"


def _drift_pathspecs(workflow: str) -> list[list[str]]:
    """The pathspec of each `git diff --exit-code` in a step that runs `sync_product.py`."""
    specs = []
    for job in _workflow(workflow)["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run", "")
            if "scripts/sync_product.py" not in run:
                continue
            # shell semantics: backslash-newline joins lines, `#` starts a comment
            for line in run.replace("\\\n", " ").splitlines():
                argv = shlex.split(line, comments=True)
                if argv[:3] == ["git", "diff", "--exit-code"] and "--" in argv:
                    specs.append(argv[argv.index("--") + 1 :])
    return specs


#: Never copied into the probe tree: large, and nothing the sync reads.
_NOT_COPIED = shutil.ignore_patterns(
    ".git", ".venv", "site", "dist", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"
)


def _digests(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture(scope="module")
def sync_targets(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Every file `sync_product.py` changes when product.json changes.

    Observed, not declared: the script runs against a copy of the tree with a
    different identity in its product.json, and the files whose bytes moved are
    the targets — however the script writes them, and without touching the
    checkout.
    """
    tree = tmp_path_factory.mktemp("sync") / "repo"
    shutil.copytree(REPO_ROOT, tree, ignore=_NOT_COPIED)
    product = json.loads((tree / "product.json").read_text(encoding="utf-8"))
    for key, value in {
        "version": "9.9.9",
        "displayName": "Drift Probe",
        "tagline": "A drift probe.",
        "description": "Probe description.",
    }.items():
        assert key in product, f"product.json has no {key!r}; update this probe"
        product[key] = value
    (tree / "product.json").write_text(json.dumps(product, indent=2) + "\n", encoding="utf-8")

    before = _digests(tree)
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(REPO_ROOT / "scripts"))
        import sync_product

        mp.setattr(sync_product, "ROOT", tree)
        sync_product.main()
    after = _digests(tree)
    changed = sorted(p for p in after if before.get(p) != after[p] and p != "product.json")
    assert "context7.json" in changed, f"the probe missed a known target: {changed}"
    return changed


@pytest.mark.parametrize("workflow", ["test.yml", "publish.yml"])
def test_the_sync_drift_gate_diffs_every_file_the_sync_writes(workflow: str, sync_targets):
    specs = _drift_pathspecs(workflow)
    assert len(specs) == 1, (
        f"{workflow}: expected one drift gate after sync_product.py, got {specs}"
    )
    (spec,) = specs
    uncovered = [
        t
        for t in sync_targets
        if not any(t == s or t.startswith(s.rstrip("/") + "/") for s in spec)
    ]
    assert not uncovered, (
        f"{workflow}: sync_product.py writes {uncovered} but the drift gate does not diff them"
    )
