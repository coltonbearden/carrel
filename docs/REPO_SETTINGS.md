# Repository settings

What is enforced on `github.com/coltonbearden/carrel`, why, and how to
reproduce it. Applied and verified by `scripts/github-harden.sh` (idempotent;
re-run it any time to re-assert this state).

## Branch ruleset `main` (active)

| rule | effect |
|---|---|
| Restrict deletions | `main` cannot be deleted |
| Block force pushes | history on `main` is append-only |
| Require linear history | squash or rebase merges only, no merge commits |
| Require a pull request | direct pushes are rejected; 0 approvals required (solo maintainer), stale approvals dismissed, review threads must be resolved |
| Require status checks | `lint`, `test (py3.12)`, `test (py3.13)`, `test (py3.14)`, `test-minimal` must pass on the PR head, and the branch must be up to date with `main`. **Pending (v0.2.0):** add `test-minimal (macos)` once the v0.2.0 release PR shows it green; `test-minimal (windows)` stays advisory (`continue-on-error`) per the BUILD_PLAN scope guard |
| Bypass | repository **admin** role, always — for emergencies only; every other actor (bots, collaborators, tokens) is blocked |

## Tag ruleset `release tags` (active, `v*`)

Release tags cannot be deleted, moved, or force-updated. Same admin bypass.

## Security & analysis

- Dependabot alerts + security updates: on (`.github/dependabot.yml` also
  schedules weekly grouped updates for `uv` and `github-actions`).
- Secret scanning + push protection: on. (Non-provider patterns: the API accepts but ignores the toggle on user-owned repos — flip it under *Settings → Advanced Security* if wanted.)
- Private vulnerability reporting: on (`SECURITY.md` links the form).
- CodeQL default setup: on, extended query suite, languages `python` + `actions`.

## Actions

- Allowed actions: GitHub-owned, verified-creator, plus `astral-sh/setup-uv@*`
  and `pypa/gh-action-pypi-publish@*`.
- SHA pinning required (all workflows pin to commit SHAs with a version comment).
- Default `GITHUB_TOKEN` permissions: read-only; Actions cannot approve PRs.
- Environment `pypi`: deployments only from `v*` tags.

## Merge behaviour

- Squash merge (PR title + body) and rebase allowed; merge commits disabled.
- Auto-merge enabled, head branch auto-deleted, "update branch" button on.
- Wiki disabled (docs live in `docs/`, published to GitHub Pages).

## Verified state (2026-09-04)

`scripts/github-harden.sh` applied and read back every setting above after PR #7
merged: both rulesets active, secret scanning + push protection enabled, private
vulnerability reporting on, CodeQL default setup configured (extended), Actions
restricted to the allow-list with SHA pinning required, `pypi` environment
limited to `v*` tags. PR #7 itself was the first change to land under the
required checks (`lint`, `test (py3.12/3.13/3.14)`, `test-minimal`).

## Not enforced (deliberately)

- **Signed commits** — would block unsigned commits from automation; enable
  once every committer signs.
- **Required reviewers on `pypi`** — one maintainer; the ruleset + tag
  protection + version check already gate releases.
