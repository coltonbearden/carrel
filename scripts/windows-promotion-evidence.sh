#!/usr/bin/env bash
# windows-promotion-evidence.sh — what D-028 counts before `test-minimal (windows)`
# becomes a required check: that job's result in every attempt of every `main` run
# of `tests` and `tests (weekly)` since the count started.
#
# A run list cannot show it. `continue-on-error` keeps a run green when this job
# fails, and a re-run hides the first attempt behind the second.
#
# Usage: scripts/windows-promotion-evidence.sh [--since ISO-8601-UTC] [--repo owner/name]
# Needs: gh, jq. Read-only. Exit 0 when the window is at least 14 days old and no
# attempt failed; exit 1 otherwise, saying which.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

SINCE="2026-10-09T01:10:00Z"   # the first `main` run after the gap (D-028)
REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="${2:?}"; shift 2 ;;
    --repo)  REPO="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$REPO" ]; then
  REPO="$(python3 -c 'import json; print(json.load(open("product.json"))["repository"].removeprefix("https://github.com/"))')"
fi
command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

JOB="test-minimal (windows)"   # called through weekly.yml it is "tests / test-minimal (windows)"
failed=0
seen=0
for workflow in test.yml weekly.yml; do
  # A pull request from a fork's own `main` has head branch `main` too; it is a merge
  # simulation, not a run of this repository's `main`.
  runs="$(gh run list --repo "$REPO" --workflow "$workflow" --branch main --created ">=$SINCE" \
    --limit 500 --json databaseId,event,attempt,createdAt \
    --jq '.[] | select(.event != "pull_request") | [.databaseId, .attempt, .createdAt, .event] | @tsv' \
    2>/dev/null || true)"
  [ -n "$runs" ] || { echo "(no main runs of $workflow in the window)" >&2; continue; }
  while IFS=$'\t' read -r run attempts created event; do
    for attempt in $(seq 1 "$attempts"); do
      result="$(gh api "repos/$REPO/actions/runs/$run/attempts/$attempt/jobs?per_page=100" \
        | jq -r --arg job "$JOB" '[.jobs[] | select(.name | endswith($job)) | (.conclusion // .status)] | first // "absent"')"
      printf '%s\t%s\t%s\trun %s attempt %s\t%s\n' "$created" "$workflow" "$event" "$run" "$attempt" "$result"
      seen=$((seen + 1))
      [ "$result" = "failure" ] && failed=$((failed + 1))
    done
  done <<<"$runs"
done

age_days=$(( ( $(date -u +%s) - $(date -u -d "$SINCE" +%s) ) / 86400 ))
echo "---"
echo "$seen attempt(s) since $SINCE ($age_days day(s) ago); $failed with a failed Windows job"
if [ "$failed" -gt 0 ]; then
  echo "NOT YET: a failure restarts the count. Re-run with --since set to the next green run." >&2
  exit 1
fi
if [ "$age_days" -lt 14 ]; then
  echo "NOT YET: the window is $age_days day(s) old, 14 are needed." >&2
  exit 1
fi
echo "MET: two weeks of main runs with no failed Windows job (cancelled or absent is no evidence either way)."
