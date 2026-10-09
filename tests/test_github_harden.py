"""`scripts/github-harden.sh` against a stand-in `gh`: what it writes, and what it accepts.

Found reviewing #66: nothing ran the script. Its environment block could only add
the wanted deployment pattern, never remove another, so a drifted environment
(`main` plus `feature/*`, or a lone `*`) stayed open however often it was applied,
and its check read the pattern list without asking whether the environment was in
custom-policy mode at all.

The stand-in serves the state the script itself calls intended, built from the
script's own constants, so the script has to exit 0 on it; a test then changes one
thing. It is a model, not GitHub: it does not page, it refuses a duplicate pattern
outright where the API answers 303, and a PUT on an environment changes the mode
and nothing else. The apply half has not run against the real API (D-029).
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import bash_path, needs_bash

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "github-harden.sh"
REPO = "someone/scratch"

pytestmark = [
    pytest.mark.skipif(os.name == "nt", reason="the stand-in gh is a POSIX shell wrapper"),
    pytest.mark.skipif(not SCRIPT.is_file(), reason="scripts/ is not part of the sdist"),
    pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not on PATH"),
    needs_bash,
]

CUSTOM = {"protected_branches": False, "custom_branch_policies": True}
PROTECTED_ONLY = {"protected_branches": True, "custom_branch_policies": False}


def _constant(name: str) -> object:
    """A JSON constant the script defines as NAME='...'."""
    text = SCRIPT.read_text(encoding="utf-8")
    return json.loads(re.search(rf"^{name}='(.*)'$", text, re.MULTILINE).group(1))


def _intended(default_branch: str = "main") -> dict:
    """Everything the script reads, in the state it asserts."""
    checks = [{"context": c} for c in _constant("REQUIRED_CHECKS")]
    main_rules = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request"},
        {"type": "required_linear_history"},
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": checks,
            },
        },
    ]
    tag_rules = [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "update"}]
    return {
        "fail": [],
        "environments": {
            "pypi": {"mode": CUSTOM, "policies": [{"id": 1, "name": "v*", "type": "tag"}]},
            "github-pages": {
                "mode": CUSTOM,
                "policies": [{"id": 2, "name": default_branch, "type": "branch"}],
            },
        },
        "static": {
            "": {
                "default_branch": default_branch,
                "has_wiki": False,
                "allow_merge_commit": False,
                "allow_auto_merge": True,
                "delete_branch_on_merge": True,
                "allow_update_branch": True,
                "security_and_analysis": {
                    "secret_scanning": {"status": "enabled"},
                    "secret_scanning_push_protection": {"status": "enabled"},
                },
            },
            "private-vulnerability-reporting": {"enabled": True},
            "automated-security-fixes": {"enabled": True},
            "code-scanning/default-setup": {
                "state": "configured",
                "query_suite": "extended",
                "languages": ["actions", "python"],
            },
            "actions/permissions": {"allowed_actions": "selected", "sha_pinning_required": True},
            "actions/permissions/selected-actions": {
                "github_owned_allowed": True,
                "verified_allowed": True,
                "patterns_allowed": _constant("want_patterns"),
            },
            "actions/permissions/workflow": {
                "default_workflow_permissions": "read",
                "can_approve_pull_request_reviews": False,
            },
            "rulesets": [{"id": 11, "name": "main"}, {"id": 12, "name": "release tags"}],
            "rulesets/11": {
                "enforcement": "active",
                "rules": main_rules,
                "bypass_actors": _constant("MAIN_BYPASS"),
            },
            "rulesets/12": {
                "enforcement": "active",
                "rules": tag_rules,
                "bypass_actors": _constant("TAG_BYPASS"),
            },
        },
    }


FAKE_GH = """\
import json, os, pathlib, re, sys

world_file = pathlib.Path(os.environ["FAKE_GH_WORLD"])
log_file = pathlib.Path(os.environ["FAKE_GH_LOG"])
argv = sys.argv[1:]
# as `gh api` decides it: an explicit method, else POST when a body is sent, else GET
explicit = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-X", "--method")]
sends_body = any(a in ("--input", "-f", "-F", "--field", "--raw-field") for a in argv)
method = explicit[0] if explicit else ("POST" if sends_body else "GET")
full = next((a for a in argv if a.startswith("repos/")), "")
path = "/".join(full.split("?")[0].split("/")[3:])   # after repos/<owner>/<name>
body = sys.stdin.read() if "--input" in argv else ""
with log_file.open("a") as fh:
    fh.write(json.dumps({"method": method, "path": path, "body": body}) + "\\n")

world = json.loads(world_file.read_text())
if method == "GET" and path in world["fail"]:
    sys.exit("gh: HTTP 502 (stand-in)")
parts = path.split("/")
out = "{}"
if parts[0] == "environments":
    env = world["environments"].setdefault(parts[1], {"mode": None, "policies": []})
    tail = parts[2:]
    if not tail and method == "PUT":
        env["mode"] = json.loads(body)["deployment_branch_policy"]
    elif not tail:
        out = json.dumps({"deployment_branch_policy": env["mode"]})
    elif tail == ["deployment-branch-policies"] and method == "POST":
        wanted = json.loads(body)
        if any((p["name"], p["type"]) == (wanted["name"], wanted["type"]) for p in env["policies"]):
            sys.exit("gh: that pattern already exists (stand-in)")
        ids = [p["id"] for e in world["environments"].values() for p in e["policies"]]
        env["policies"].append({"id": 1 + max(ids or [0]), **wanted})
    elif tail == ["deployment-branch-policies"]:
        out = json.dumps({"branch_policies": env["policies"]})
    elif len(tail) == 2 and method == "DELETE":
        env["policies"] = [p for p in env["policies"] if str(p["id"]) != tail[1]]
    world_file.write_text(json.dumps(world))
elif method == "GET" and "-i" in argv:
    out = "HTTP/2.0 204 No Content"
elif method == "GET" and path in world["static"]:
    answer = world["static"][path]
    if "--jq" in argv:   # the one filter the script hands to gh: a ruleset's id by name
        name = re.search(r'name == "(.*?)"', argv[argv.index("--jq") + 1]).group(1)
        out = "\\n".join(str(r["id"]) for r in answer if r["name"] == name)
    else:
        out = json.dumps(answer)
print(out)
"""


def _run(tmp_path: Path, world: dict, *flags: str) -> tuple[int, str, dict, list[dict]]:
    """Run the script with the stand-in first on PATH: (exit code, report, world after, calls)."""
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
        [bash_path(), str(SCRIPT), "--repo", REPO, *flags],
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
    after = json.loads(world_file.read_text(encoding="utf-8"))
    return proc.returncode, proc.stdout + proc.stderr, after, calls


def _patterns(world: dict, env: str) -> list[tuple[str, str]]:
    return sorted((p["type"], p["name"]) for p in world["environments"][env]["policies"])


def _pattern_writes(calls: list[dict]) -> list[dict]:
    return [c for c in calls if "deployment-branch-policies" in c["path"] and c["method"] != "GET"]


def test_verify_only_writes_nothing_and_accepts_the_intended_state(tmp_path: Path):
    world = _intended()
    code, report, after, calls = _run(tmp_path, world, "--verify-only")
    assert code == 0 and "all settings verified" in report, report
    assert {c["method"] for c in calls} == {"GET"}, [c for c in calls if c["method"] != "GET"]
    assert after == world
    assert "✔\x1b[0m pypi environment deploys only from tag v*" in report
    assert "✔\x1b[0m github-pages environment deploys only from branch main" in report


def test_apply_brings_a_drifted_environment_back_to_one_pattern(tmp_path: Path):
    """Adding `main` is not enough: the pattern that lets a branch deploy has to go."""
    world = _intended()
    world["environments"] = {
        "pypi": {"mode": None, "policies": []},
        "github-pages": {
            "mode": PROTECTED_ONLY,
            "policies": [
                {"id": 7, "name": "feature/*", "type": "branch"},
                {"id": 8, "name": "main", "type": "branch"},
                {"id": 9, "name": "*", "type": "branch"},
            ],
        },
    }
    code, report, after, _calls = _run(tmp_path, world)
    assert _patterns(after, "github-pages") == [("branch", "main")]
    assert _patterns(after, "pypi") == [("tag", "v*")]
    assert after["environments"]["github-pages"]["mode"] == CUSTOM
    assert after["environments"]["pypi"]["mode"] == CUSTOM
    # the one deletion the script makes is said out loud, pattern by pattern
    assert "removed deployment pattern branch:feature/* from github-pages" in report
    assert "removed deployment pattern branch:* from github-pages" in report
    assert code == 0 and "all settings verified" in report, report


def test_applying_to_the_intended_state_changes_no_pattern(tmp_path: Path):
    world = _intended()
    code, report, after, calls = _run(tmp_path, world)
    assert code == 0, report
    assert after == world
    assert not _pattern_writes(calls), _pattern_writes(calls)


OPEN_STATES = {
    "an extra pattern": {
        "mode": CUSTOM,
        "policies": [
            {"id": 2, "name": "main", "type": "branch"},
            {"id": 3, "name": "*", "type": "branch"},
        ],
    },
    "no pattern": {"mode": CUSTOM, "policies": []},
    # the list still says `main`, but nothing enforces it in these two modes
    "no restriction": {"mode": None, "policies": [{"id": 2, "name": "main", "type": "branch"}]},
    "protected branches only": {
        "mode": PROTECTED_ONLY,
        "policies": [{"id": 2, "name": "main", "type": "branch"}],
    },
}


@pytest.mark.parametrize("state", sorted(OPEN_STATES))
def test_verify_only_refuses_an_environment_that_can_deploy_from_elsewhere(tmp_path: Path, state):
    world = _intended()
    world["environments"]["github-pages"] = copy.deepcopy(OPEN_STATES[state])
    code, report, _after, calls = _run(tmp_path, world, "--verify-only")
    assert code == 1 and "all settings verified" not in report, report
    assert {c["method"] for c in calls} == {"GET"}
    assert "✘\x1b[0m github-pages deployment policy" in report
    assert "✔\x1b[0m pypi environment deploys only from tag v*" in report


def test_a_failed_read_stops_the_apply_instead_of_passing_for_an_empty_list(tmp_path: Path):
    world = _intended()
    world["environments"]["github-pages"]["policies"].append(
        {"id": 3, "name": "*", "type": "branch"}
    )
    world["fail"] = ["environments/github-pages/deployment-branch-policies"]
    code, report, after, calls = _run(tmp_path, world)
    assert code != 0 and "all settings verified" not in report, report
    assert not _pattern_writes(calls), _pattern_writes(calls)
    assert _patterns(after, "github-pages") == [("branch", "*"), ("branch", "main")]


def test_the_pages_policy_follows_the_default_branch(tmp_path: Path):
    """`--repo` may name a repository whose default branch is not `main`."""
    world = _intended(default_branch="master")
    code, report, after, calls = _run(tmp_path, world)
    assert code == 0, report
    assert _patterns(after, "github-pages") == [("branch", "master")]
    assert not _pattern_writes(calls), _pattern_writes(calls)
    assert "✔\x1b[0m github-pages environment deploys only from branch master" in report
