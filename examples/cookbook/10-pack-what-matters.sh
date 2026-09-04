#!/usr/bin/env bash
# 10 — Pack what matters: index a docs tree, then pack by relevance
#
# `carrel pack DIR` bundles everything under DIR. `carrel pack DIR --query TEXT`
# bundles only the files the desk index ranks for TEXT, in relevance order —
# so an agent gets the five files about "release" instead of the whole tree.
# Runs entirely offline against a synthetic docs tree built in a temp dir, so
# the output is deterministic. Requires: nothing beyond carrel (index and pack
# are pure python; the index is stdlib SQLite FTS5).
#
# Honest limitation shown at the end: --query can only rank files the index
# knows about, and `carrel index` skips unsupported types such as .py/.toml, so
# query-driven packing fits document trees, not source trees (see docs/FEATURES.md).
#
# Expected: an index summary of 6 files, a --stats table with a `score` column
# listing only the 5 files that mention "release", a written ctx.md whose header
# names the query, exit 5 for a query with no hits, then RECIPE OK.
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ -z "${CARREL:-}" ] && ! command -v carrel >/dev/null 2>&1; then CARREL="uv run carrel"; fi
CARREL="${CARREL:-carrel}"   # intentionally unquoted below: may hold "uv run carrel"
export COLUMNS="${COLUMNS:-110}"   # rich tables truncate long paths when piped at 80 columns

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
docs="$work/docs"

echo "==> build a synthetic docs tree (deterministic input)"
mkdir -p "$docs/guides" "$docs/reference" "$docs/notes"
cat > "$docs/guides/onboarding.md" <<'EOF'
# Onboarding guide

Welcome. Start by reading the release checklist, then set up your desk.
The first week is about learning the catalog and the index.
EOF
cat > "$docs/guides/release-checklist.md" <<'EOF'
# Release checklist

1. Bump the version in product.json.
2. Run the release checklist tests.
3. Tag the release and push the tag.
4. Publish to PyPI — the release is done when the badge turns green.
EOF
cat > "$docs/reference/exit-codes.md" <<'EOF'
# Exit codes

0 success, 1 error, 2 usage, 3 missing dependency, 4 bad input, 5 empty result.
EOF
cat > "$docs/reference/glossary.md" <<'EOF'
# Glossary

**Desk** — the root directory carrel indexes. **Release** — a tagged, published version.
EOF
cat > "$docs/notes/meeting-2026-09-01.txt" <<'EOF'
Meeting notes, 2026-09-01. Agreed: the release goes out Friday after the checklist passes.
Action items: update the glossary, draft the onboarding guide.
EOF
printf 'id,topic,owner\n1,release,ada\n2,onboarding,grace\n' > "$docs/notes/topics.csv"
printf 'def release():\n    return "release"  # source files are not indexed\n' > "$docs/notes/scratch.py"

echo "==> step 1: build the desk index under --root (creates docs/.carrel/carrel.db)"
$CARREL --root "$docs" index
# 6 indexed: the .py is an unsupported type and is skipped silently

echo "==> step 2: size the relevant subset first (--stats adds a score column)"
$CARREL --root "$docs" pack "$docs" --query release --stats
# assert on the data, not the table: --json lists the same selection under "files"
$CARREL --root "$docs" --json pack "$docs" --query release \
  | python3 -c 'import json,sys; print("\n".join(f["path"] for f in json.load(sys.stdin)["files"]))' > "$work/selected.txt"
grep -qx 'guides/release-checklist.md' "$work/selected.txt"
if grep -q 'exit-codes.md' "$work/selected.txt"; then
  echo "exit-codes.md does not mention 'release' and should not be packed" >&2; exit 1
fi
if grep -q 'scratch.py' "$work/selected.txt"; then
  echo "scratch.py is not indexed and cannot be ranked" >&2; exit 1
fi

echo "==> step 3: write the pack (relevance order, header names the query)"
$CARREL --root "$docs" pack "$docs" --query release --top 5 -o "$work/ctx.md"
grep -q "^- query: 'release'" "$work/ctx.md"
grep -q 'Publish to PyPI' "$work/ctx.md"        # contents really inlined
echo "  header of the pack:"
sed -n '1,8p' "$work/ctx.md"

echo "==> step 4: the same thing as data (--json carries meta.query/hits and per-file score)"
$CARREL --root "$docs" --json pack "$docs" --query release --top 3 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  query:", d["meta"]["query"], "| hits:", d["meta"]["hits"], "| files:", [f["path"] for f in d["files"]])'

echo "==> step 5: no hits + --fail-empty exits 5, so pipelines can branch on it"
set +e
$CARREL --root "$docs" pack "$docs" --query xyzzyplugh --fail-empty --tree-only >/dev/null
rc=$?
set -e
[ "$rc" -eq 5 ] || { echo "expected exit 5, got $rc" >&2; exit 1; }
echo "  exit code: $rc"

echo "==> limitation: 'release' also appears in notes/scratch.py, but .py is not an indexed type"
$CARREL --root "$docs" --json search release \
  | python3 -c 'import json,sys; print("  index hits:", [h["path"] for h in json.load(sys.stdin)])'
echo "  (for source trees use --include/--exclude, --since REF, or --outline instead)"

echo "RECIPE OK"
