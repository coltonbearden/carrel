# Releasing

carrel ships to PyPI from GitHub Actions through
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no API
token exists anywhere. A release is four steps; only the last one touches PyPI.

## 1. Bump the version (one file)

**Which number moves (D-023):** if an invocation that succeeded before can now
exit non-zero, it is a **minor** bump — a refusal, a new exit code on an existing
path, a default that flips from permissive to strict. Everything else is a patch,
including new flags, new output fields and fixed crashes. "The new behaviour is
better" and "the escape hatch is documented" were both true of the v0.4.1 guard
that shipped as a patch and could start failing a cron job; neither is the test.

```sh
# edit product.json → "version": "X.Y.Z"
uv run python scripts/sync_product.py   # _product.py, pyproject, manifests, CITATION
uv lock                                 # uv.lock pins carrel's own version, and sync_product does not write it
```

**`uv.lock` is one of the derived copies, and `sync_product.py` does not write
it.** CI runs `uv sync` under `UV_LOCKED=1`, so a stale lock fails *every* job
before a single test runs; locally `uv run` relocks silently and hides it. Check
before pushing a version bump — read-only, no venv churn:

```sh
uv lock --check      # not `uv run …` — that relocks first and hides the answer
```

The `uv-lock-current` pre-commit hook runs the same command, so the usual failure
— the lock updated on disk by a local `uv run`, then never staged — is caught at
commit time by a real git hook. Run pre-commit as `uvx pre-commit` or through
the installed git hook: invoking it *through* `uv run` relocks before any hook
runs and so cannot catch it. CI's `UV_LOCKED=1` sync is the backstop, and it
fails every job in seconds.

`sync_product.py` rewrites `src/carrel/_product.py`, `pyproject.toml`
(version, description, `[project.urls]`), every plugin manifest under
`plugins/*/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and
`CITATION.cff`. Never edit those by hand — `tests/test_product_sync.py` and the
`lint` CI job fail when any copy drifts.

Then add a `## vX.Y.Z — YYYY-MM-DD` entry at the top of `CHANGELOG.md`
(the test suite checks the heading exists; the publish workflow checks it again).

Then regenerate `docs/REFERENCE.md` (its header names the version) and the doc
samples that print it — the `carrel --version` banner, the `carrel doctor`
header, the `pack` header, `catalog export` JSON, the `claude plugin list`
block and the SessionStart hook summary:

```sh
uv run python scripts/sync_reference.py
uv run pytest tests/test_docs_drift.py   # lists every stale file:line
```

For each reported site, re-run the command shown in that doc block and paste
its output; the `plugin.json` templates in PLUGIN_AUTHORING.md just take the
new version. Never hand-edit the numbers in real output — the samples are only
worth having because they are real.

## 2. Land it through a PR

`main` is protected: push a branch, open a PR, and wait for every required check
to go green — `lint`, `test (py3.12)`, `test (py3.13)`, `test (py3.14)`,
`test-minimal` and `test-minimal (macos)`; the list is `REQUIRED_CHECKS` in
`scripts/github-harden.sh`. `test-minimal (windows)` is advisory until it is
promoted, so a red one does not block — read it anyway. Per CLAUDE.md the PR's
`/code-review` must also have completed, with every confirmed finding fixed in
the PR or deferred in STATE.md. Then squash-merge.

## 3. Tag and publish the GitHub Release

```sh
git switch main && git pull --ff-only
sha=$(gh pr view N --json mergeCommit -q .mergeCommit.oid)   # N = the release PR
awk '/^## vX\.Y\.Z /{f=1;next} /^## /{f=0} f' CHANGELOG.md > /tmp/notes.md
gh release create vX.Y.Z --title "vX.Y.Z" --target "$sha" \
  --notes-file /tmp/notes.md --generate-notes
```

`--target` pins the tag to the commit you verified: without it the tag lands
on whatever `main` points at, so a PR merged in the meantime ships to PyPI as
this version, undescribed and unreviewable (PyPI versions are immutable).
Take the SHA from the release PR itself, not from `git rev-parse HEAD` after
the pull: if anything merged after the release PR, `HEAD` is that later commit
and `--target` would pin exactly the change it exists to keep out.
`--notes-file` puts the CHANGELOG entry first in the release body — that is
where a behaviour change and its escape hatch have to be visible — and
`--generate-notes` appends the PR list after it.

The tag **must** be `v` + the `product.json` version — the workflow refuses
anything else. Tags matching `v*` are protected by a ruleset (no deletion, no
force-move).

## 4. Watch the publish workflow

`.github/workflows/publish.yml` runs two jobs:

| job | what it does |
|---|---|
| `build` | verifies tag ↔ `product.json` ↔ CHANGELOG, regenerates and diffs the generated copies, `uv build`, installs the wheel in a clean venv and checks `carrel --version`, uploads `dist/` |
| `publish` | the only job with `id-token: write`; downloads `dist/`, publishes with `pypa/gh-action-pypi-publish` in the `pypi` environment with PEP 740 attestations |

```sh
gh run watch --exit-status
```

## PyPI side (one-time, after any repo move)

The trusted publisher on <https://pypi.org/manage/project/carrel/settings/publishing/>
must read exactly:

| field | value |
|---|---|
| Owner | `coltonbearden` |
| Repository name | `carrel` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

If the repository is transferred or renamed, PyPI rejects the OIDC token until
this entry is updated — that is the only manual step in the whole flow.

## If a release fails

- `build` red on the tag check → the tag is wrong; delete the release, fix
  `product.json`, land it, re-release.
- `publish` red with an OIDC error → the PyPI trusted-publisher entry above
  does not match; fix it and re-run the job (`gh run rerun <id> --failed`).
- Never re-upload an existing version: PyPI is immutable. Bump a patch version.
