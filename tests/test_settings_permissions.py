"""`.claude/settings.json` is a safety surface, and nothing read it until now.

The file is committed so an unattended run does not stall on a prompt
(docs/CONTRIBUTING.md, "Permissions for an unattended agent run"). That makes
its deny list load-bearing: `Bash(git push:*)` pre-approves *every* push, so
whatever the deny side fails to name runs with no human in the loop.

The review that prompted these tests found the deny side naming only `--force`
and `-f`, which left `git push origin +main` (a `+refspec` is a force push),
`--mirror`, `--delete`, `--receive-pack=<cmd>`, the bundled `-fu` spelling and
git's own `git -C … push` prefix form all silently allowed — against
CLAUDE.md's rule that changes reach `main` only through a reviewed PR.

The matcher below implements the documented semantics from
https://code.claude.com/docs/en/permissions ("Wildcard patterns"):

* a rule with no `*` is an exact match;
* `*` stands in for any text, at any position;
* a trailing ` *` also matches the bare command, but **only** when it is the
  rule's only wildcard;
* the `:*` suffix is an equivalent way to write a trailing ` *`.

Tests assert on real command strings rather than on rule spellings, so a rule
rewritten into a different but equivalent shape keeps passing and a rule that
stops covering a command fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def _rules(kind: str) -> list[str]:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return data["permissions"][kind]


def _matches(rule: str, command: str) -> bool:
    """True when `rule` (the text inside `Bash(...)`) covers `command`."""
    if rule.endswith(":*"):
        rule = rule[: -len(":*")] + " *"
    if "*" not in rule:
        return rule == command
    if rule.endswith(" *") and rule.count("*") == 1:
        # sole trailing wildcard: matches the bare command too
        return re.fullmatch(re.escape(rule[:-2]) + r"(?: .*)?", command) is not None
    return re.fullmatch(".*".join(re.escape(p) for p in rule.split("*")), command) is not None


def _covered(kind: str, command: str) -> bool:
    return any(
        _matches(m.group(1), command)
        for rule in _rules(kind)
        if (m := re.fullmatch(r"Bash\((.*)\)", rule))
    )


def test_the_matcher_reproduces_the_documented_examples():
    """Guard the guard: every assertion below is worthless if this is wrong."""
    # a sole trailing wildcard also matches the bare command
    assert _matches("ls *", "ls")
    assert _matches("git log *", "git log")
    assert _matches("ls:*", "ls")
    # ...but not when the rule has another wildcard
    assert _matches("* --help *", "npm --help x")
    assert not _matches("* --help *", "npm --help")
    # the space before a trailing wildcard is part of the rule
    assert not _matches("ls *", "lsof")
    assert _matches("ls*", "lsof")
    # no wildcard is an exact match
    assert _matches("git push --force", "git push --force")
    assert not _matches("git push --force", "git push --force origin main")
    # and the shape this repo got wrong once: `:*` DOES cover the bare command
    assert _matches("git push --force:*", "git push --force")
    # ...and its corollary, which costs one rule in this very file: a trailing
    # `:*` is *always* read as the wildcard suffix, so no rule can end in a
    # literal colon-plus-wildcard. `Bash(git push * :*)` therefore reads as
    # `git push *  *` (two spaces) and is dead config, not a guard against
    # `git push origin :feature`. Deleting `main` is covered by the literal
    # `git push *:main` and by the ruleset's own "Restrict deletions".
    assert not _matches("git push * :*", "git push origin :feature")


#: Commands that must never run without a human. Each was reachable through
#: `Bash(git push:*)` before the deny list named its shape.
MUST_BE_DENIED = [
    # force pushes, both spellings, bare and with arguments
    "git push --force",
    "git push --force origin main",
    "git push -f",
    "git push -f origin main",
    "git push origin main --force",
    "git push origin --force",
    # bundled short options: parse-options accepts -fu as -f -u
    "git push -fu origin feature",
    # a leading `+` on a refspec is a force push with no flag
    "git push origin +main",
    "git push origin +refs/heads/main:refs/heads/main",
    # wholesale rewrite / deletion of remote refs
    "git push --mirror origin",
    "git push --delete origin feature",
    "git push origin :main",
    # arbitrary program execution on a local or file:// remote
    "git push --receive-pack=sh /tmp/repo",
    "git push --exec=sh /tmp/repo",
    # anything landing on main: the PR gate is the only documented way in
    "git push origin main",
    "git push origin HEAD:main",
    "git push origin feature:refs/heads/main",
    # git's own prefix forms, which no rule anchored on "git push" can see
    "git -C . push --force origin main",
    "git -c push.default=current push origin main",
]


def test_every_dangerous_push_is_denied():
    missed = [cmd for cmd in MUST_BE_DENIED if not _covered("deny", cmd)]
    assert not missed, "\n".join(
        ["these run unprompted under `Bash(git push:*)` — no deny rule covers them:", *missed]
    )


#: The grants the release loop actually needs must keep working; a deny rule
#: added to close a gap above must not swallow them (deny beats allow).
MUST_STAY_USABLE = [
    "git push -u origin fix/pack-first-five-minutes",
    "git push origin docs/state-v0.5.0",
    "git push",
]


def test_the_deny_rules_do_not_swallow_an_ordinary_branch_push():
    broken = [cmd for cmd in MUST_STAY_USABLE if _covered("deny", cmd)]
    assert not broken, "\n".join(["a deny rule blocks an ordinary feature-branch push:", *broken])


def test_the_destructive_git_verbs_stay_denied():
    for cmd in (
        "git reset --hard HEAD~1",
        "git clean -fdx",
        "git checkout .",
        "git stash drop",
        "git filter-branch --tree-filter true HEAD",
        # same data loss as reset --hard, reached through a different verb
        "git worktree remove --force .claude/worktrees/x",
        "git worktree remove .claude/worktrees/x --force",
        # skipping the hooks is how unformatted or fixture-corrupting work lands
        "git commit --no-verify -m wip",
        "git commit -m wip --no-verify",
        "git commit -n -m wip",
        # stage-everything publishes whatever .gitignore happens to miss
        "git add -A",
        "git add --all",
        "git add .",
    ):
        assert _covered("deny", cmd), f"no deny rule covers {cmd!r}"


def test_the_ordinary_forms_of_those_verbs_still_work():
    """A deny added above must not take the everyday spelling with it."""
    for cmd in (
        "git commit -m 'fix: thing'",
        "git add src/carrel/commands/pack.py tests/test_pack.py",
        "git worktree remove .claude/worktrees/x",
    ):
        assert not _covered("deny", cmd), f"a deny rule blocks the ordinary {cmd!r}"
        assert _covered("allow", cmd), f"no allow rule covers {cmd!r}"


def test_the_release_loop_commands_are_allowed():
    """Anything here that stops being allowed makes an unattended run stall."""
    for cmd in (
        "uv run pytest -q",
        "git switch -c fix/thing",
        "git commit -m wip",
        "gh pr create --title x --body y",
        "gh pr checks 38 --watch",
        "gh release create v0.5.0 --target abc",
        "claude plugin validate .",
    ):
        assert _covered("allow", cmd), f"no allow rule covers {cmd!r}"


def test_contributing_describes_the_git_grant_it_actually_ships():
    """The doc drifted once: it named `switch/fetch/rebase/worktree` only."""
    text = (REPO_ROOT / "docs" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for verb in ("git add", "git commit", "git push"):
        assert f"`{verb}`" in text, (
            f"docs/CONTRIBUTING.md does not mention the {verb!r} grant this file ships"
        )
