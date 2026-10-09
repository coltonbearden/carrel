"""`scripts/github-harden.sh` against a stand-in `gh`: what it writes, and what it accepts.

Found reviewing #66: nothing ran the script. Its environment block could only add
the wanted deployment pattern, never remove another, so a drifted environment
(`main` plus `feature/*`, or a lone `*`) stayed open however often it was applied,
and its check read the pattern list without asking whether the environment was in
custom-policy mode at all.

The stand-in keeps the two environments in a JSON file and answers every other
call with `{}`, so only the environment lines of the report are meaningful here;
the rest of the script still has to run through, which is part of the test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "github-harden.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt"
    or not SCRIPT.is_file()
    or shutil.which("bash") is None
    or shutil.which("jq") is None,
    reason="needs bash and jq, and the script (not part of the sdist)",
)

CUSTOM = {"protected_branches": False, "custom_branch_policies": True}
GOOD = {
    "pypi": {"mode": CUSTOM, "policies": [{"id": 1, "name": "v*", "type": "tag"}]},
    "github-pages": {"mode": CUSTOM, "policies": [{"id": 2, "name": "main", "type": "branch"}]},
}

FAKE_GH = """\
import json, os, pathlib, sys

world_file = pathlib.Path(os.environ["FAKE_GH_WORLD"])
log_file = pathlib.Path(os.environ["FAKE_GH_LOG"])
argv = sys.argv[1:]
method = argv[argv.index("-X") + 1] if "-X" in argv else "GET"
path = next((a for a in argv if a.startswith("repos/")), "")
body = sys.stdin.read() if "--input" in argv else ""
with log_file.open("a") as fh:
    fh.write(json.dumps({"method": method, "path": path, "body": body}) + "\\n")

world = json.loads(world_file.read_text())
parts = path.split("/")
out = "{}"
if "environments" in parts:
    env = world.setdefault(parts[parts.index("environments") + 1], {"mode": None, "policies": []})
    tail = parts[parts.index("environments") + 2 :]
    if not tail and method == "PUT":
        env["mode"] = json.loads(body)["deployment_branch_policy"]
    elif not tail:
        out = json.dumps({"deployment_branch_policy": env["mode"]})
    elif tail == ["deployment-branch-policies"] and method == "POST":
        wanted = json.loads(body)
        next_id = 1 + max([p["id"] for e in world.values() for p in e["policies"]] or [0])
        env["policies"].append({"id": next_id, **wanted})
    elif tail == ["deployment-branch-policies"]:
        out = json.dumps({"branch_policies": env["policies"]})
    elif len(tail) == 2 and method == "DELETE":
        env["policies"] = [p for p in env["policies"] if str(p["id"]) != tail[1]]
    world_file.write_text(json.dumps(world))
print("" if "--jq" in argv else out)
"""


def _run(tmp_path: Path, world: dict, *flags: str) -> tuple[str, dict, list[dict]]:
    """Run the script with the stand-in first on PATH: (report, world after, calls made)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    gh = bindir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bindir / "fake_gh.py"}" "$@"\n')
    gh.chmod(0o755)
    world_file, log_file = tmp_path / "world.json", tmp_path / "calls.jsonl"
    world_file.write_text(json.dumps(world), encoding="utf-8")
    log_file.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--repo", "someone/scratch", *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_WORLD": str(world_file),
            "FAKE_GH_LOG": str(log_file),
        },
    )
    calls = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert calls, proc.stderr  # the stand-in was the `gh` that ran
    return proc.stdout + proc.stderr, json.loads(world_file.read_text(encoding="utf-8")), calls


def _patterns(world: dict, env: str) -> list[tuple[str, str]]:
    return sorted((p["type"], p["name"]) for p in world[env]["policies"])


def test_verify_only_writes_nothing_and_accepts_the_intended_state(tmp_path: Path):
    report, world, calls = _run(tmp_path, GOOD, "--verify-only")
    assert {c["method"] for c in calls} == {"GET"}, [c for c in calls if c["method"] != "GET"]
    assert world == GOOD
    assert "✔\x1b[0m pypi environment deploys only from tag v*" in report
    assert "✔\x1b[0m github-pages environment deploys only from branch main" in report


def test_apply_brings_a_drifted_environment_back_to_one_pattern(tmp_path: Path):
    """Adding `main` is not enough: the pattern that lets a branch deploy has to go."""
    drifted = {
        "pypi": {"mode": None, "policies": []},
        "github-pages": {
            "mode": {"protected_branches": True, "custom_branch_policies": False},
            "policies": [
                {"id": 7, "name": "feature/*", "type": "branch"},
                {"id": 8, "name": "main", "type": "branch"},
                {"id": 9, "name": "*", "type": "branch"},
            ],
        },
    }
    report, world, _calls = _run(tmp_path, drifted)
    assert _patterns(world, "github-pages") == [("branch", "main")]
    assert _patterns(world, "pypi") == [("tag", "v*")]
    assert world["github-pages"]["mode"] == world["pypi"]["mode"] == CUSTOM
    assert "✔\x1b[0m github-pages environment deploys only from branch main" in report
    assert "✔\x1b[0m pypi environment deploys only from tag v*" in report


def test_applying_to_the_intended_state_changes_no_pattern(tmp_path: Path):
    _report, world, calls = _run(tmp_path, GOOD)
    assert world == GOOD
    touched = [
        c for c in calls if "deployment-branch-policies" in c["path"] and c["method"] != "GET"
    ]
    assert not touched, touched


@pytest.mark.parametrize(
    "pages",
    [
        {
            "mode": CUSTOM,
            "policies": [
                *GOOD["github-pages"]["policies"],
                {"id": 3, "name": "*", "type": "branch"},
            ],
        },
        {"mode": CUSTOM, "policies": []},
        # the list still says `main`, but nothing enforces it in these two modes
        {"mode": None, "policies": GOOD["github-pages"]["policies"]},
        {
            "mode": {"protected_branches": True, "custom_branch_policies": False},
            "policies": GOOD["github-pages"]["policies"],
        },
    ],
    ids=["an extra pattern", "no pattern", "no restriction", "protected branches only"],
)
def test_verify_only_refuses_an_environment_that_can_deploy_from_elsewhere(tmp_path: Path, pages):
    report, _world, calls = _run(tmp_path, {**GOOD, "github-pages": pages}, "--verify-only")
    assert {c["method"] for c in calls} == {"GET"}
    assert "✘\x1b[0m github-pages deployment policy" in report
    assert "✔\x1b[0m pypi environment deploys only from tag v*" in report
