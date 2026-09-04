# Releasing

carrel ships to PyPI from GitHub Actions through
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no API
token exists anywhere. A release is four steps; only the last one touches PyPI.

## 1. Bump the version (one file)

```sh
# edit product.json → "version": "X.Y.Z"
uv run python scripts/sync_product.py   # regenerates every derived copy
```

`sync_product.py` rewrites `src/carrel/_product.py`, `pyproject.toml`
(version, description, `[project.urls]`), every plugin manifest under
`plugins/*/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, and
`CITATION.cff`. Never edit those by hand — `tests/test_product_sync.py` and the
`lint` CI job fail when any copy drifts.

Then add a `## vX.Y.Z — YYYY-MM-DD` entry at the top of `CHANGELOG.md`
(the test suite checks the heading exists; the publish workflow checks it again).

## 2. Land it through a PR

`main` is protected: push a branch, open a PR, wait for `lint`, `test (py3.12 /
3.13 / 3.14)` and `test-minimal` to go green, squash-merge.

## 3. Tag and publish the GitHub Release

```sh
git switch main && git pull --ff-only
gh release create vX.Y.Z --title "vX.Y.Z" --generate-notes
```

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
