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
  mangled sync would have been repaired on disk and reported green.

The rules fail closed: an unknown workflow is uncached, an expression counts as
a cache switched on, and a gate line the parser cannot read is a missing gate.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The sdist ships tests/ but not the workflows, uv.lock or scripts/ these read.
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

#: Characters that turn a pathspec token into shell control flow (`|| true`).
SHELL_CONTROL = set("|;&<>")


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
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]


def _ids(steps: list[tuple]) -> list[str]:
    return [f"{workflow}:{job}" for workflow, job, *_ in steps]


def _switched_on(value: object) -> bool:
    """setup-uv reads the input as a string; anything but "false" may cache."""
    return str(value).strip().lower() != "false"


def test_the_setup_uv_scan_finds_steps():
    """Guard the guard: a renamed action or moved file must fail here."""
    workflows = {workflow for workflow, *_ in _setup_uv_steps()}
    assert {"test.yml", "publish.yml", "docs.yml"} <= workflows, workflows


@pytest.mark.parametrize(
    ("workflow", "job", "job_def", "inputs"), _setup_uv_steps(), ids=_ids(_setup_uv_steps())
)
def test_every_setup_uv_step_installs_the_locked_uv(workflow, job, job_def, inputs):
    assert inputs.get("version-file") == "uv.lock" and "version" not in inputs, (
        f"{workflow}:{job} must install uv with `version-file: uv.lock`, got {inputs}"
    )


@pytest.mark.parametrize(
    ("workflow", "job", "job_def", "inputs"), _setup_uv_steps(), ids=_ids(_setup_uv_steps())
)
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
    python = str(inputs.get("python-version", ""))  # already part of setup-uv's own key
    for axis in (k for k in matrix if k not in ("include", "exclude")):
        ref = f"matrix.{axis}"
        assert ref in suffix or ref in python, (
            f"{workflow}:{job}: matrix legs differing in `{axis}` share one cache key; "
            f"add `${{{{ {ref} }}}}` to `cache-suffix`"
        )


@pytest.mark.parametrize("workflow", sorted({p.name for p in _workflow_files()} - CACHED))
def test_uncached_workflows_use_no_other_cache_either(workflow):
    """`actions/cache` on ~/.cache/uv, or a setup action's `cache:`, is the same hole."""
    offenders = []
    for wf, job_id, job in _jobs():
        if wf != workflow:
            continue
        for step in job.get("steps", []):
            uses = str(step.get("uses", ""))
            inputs = step.get("with") or {}
            if uses.startswith("actions/cache"):
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


def _drift_gates(workflow: str) -> list[list[str]]:
    """The pathspec of each `git diff --exit-code` that follows `sync_product.py` in a step.

    Lines the shell parser cannot read are skipped, which fails closed: a gate
    that cannot be read is a gate that is not found.
    """
    gates = []
    for wf, job_id, job in _jobs():
        if wf != workflow:
            continue
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            if "scripts/sync_product.py" not in run:
                continue
            assert not step.get("continue-on-error"), f"{workflow}:{job_id}: the gate cannot fail"
            synced = False
            # shell semantics: backslash-newline joins lines, `#` starts a comment
            for line in run.replace("\\\n", " ").splitlines():
                try:
                    argv = shlex.split(line, comments=True)
                except ValueError:
                    continue
                if "scripts/sync_product.py" in argv:
                    synced = True
                elif synced and argv[:3] == ["git", "diff", "--exit-code"] and "--" in argv:
                    spec = argv[argv.index("--") + 1 :]
                    controls = [t for t in spec if SHELL_CONTROL & set(t)]
                    assert not controls, (
                        f"{workflow}:{job_id}: the gate is neutralised by {controls}"
                    )
                    gates.append(spec)
    return gates


def _tracked_files() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True, timeout=60
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [p for p in proc.stdout.decode("utf-8").split("\0") if p]


def _digests(root: Path, paths: list[str]) -> dict[str, str]:
    return {
        p: hashlib.sha256((root / p).read_bytes()).hexdigest()
        for p in paths
        if (root / p).is_file()
    }


@pytest.fixture(scope="module")
def sync_targets(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Every tracked file `sync_product.py` changes when product.json changes.

    Observed, not declared: the script runs against a copy of the tracked tree
    whose product.json has every identity field altered, and the files whose
    bytes moved are the targets — however the script writes them, and without
    touching the checkout.
    """
    tracked = _tracked_files()
    tree = tmp_path_factory.mktemp("sync") / "repo"
    for rel in tracked:
        src = REPO_ROOT / rel
        if src.is_file() and not src.is_symlink():
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, tree / rel)

    product = json.loads((tree / "product.json").read_text(encoding="utf-8"))
    # `package` names the source directory the script writes into, so it stays
    altered = {k: f"{v}probe" for k, v in product.items() if isinstance(v, str) and k != "package"}
    assert {"version", "description", "repository"} <= altered.keys(), altered.keys()
    product.update(altered)
    (tree / "product.json").write_text(json.dumps(product, indent=2) + "\n", encoding="utf-8")

    before = _digests(tree, tracked)
    with pytest.MonkeyPatch.context() as mp:
        mp.syspath_prepend(str(REPO_ROOT / "scripts"))
        import sync_product

        mp.setattr(sync_product, "ROOT", tree)
        sync_product.main()
    after = _digests(tree, tracked)
    changed = sorted(p for p in after if before.get(p) != after[p] and p != "product.json")
    assert "context7.json" in changed, f"the probe missed a known target: {changed}"
    return changed


@pytest.mark.parametrize("workflow", ["test.yml", "publish.yml"])
def test_the_sync_drift_gate_diffs_every_file_the_sync_writes(workflow, sync_targets):
    gates = _drift_gates(workflow)
    assert len(gates) == 1, (
        f"{workflow}: expected one drift gate after sync_product.py, got {gates}"
    )
    (spec,) = gates
    uncovered = [
        t
        for t in sync_targets
        if not any(t == s or t.startswith(s.rstrip("/") + "/") for s in spec)
    ]
    assert not uncovered, (
        f"{workflow}: sync_product.py writes {uncovered} but the drift gate does not diff them"
    )
