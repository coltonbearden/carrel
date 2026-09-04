#!/usr/bin/env bash
# github-harden.sh — assert the GitHub repository configuration documented in
# docs/REPO_SETTINGS.md. Idempotent: every call is a PUT/PATCH or a
# create-or-update by name, so re-running only re-asserts state.
#
# Usage: scripts/github-harden.sh [--repo owner/name] [--verify-only]
# Needs: gh (authenticated as a repo admin), jq. Read-only with --verify-only.
set -euo pipefail

REPO=""
VERIFY_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)        REPO="${2:?}"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    -h|--help)     sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$REPO" ]; then
  REPO="$(python3 -c 'import json; print(json.load(open("product.json"))["repository"].removeprefix("https://github.com/"))')"
fi
command -v gh >/dev/null || { echo "gh is required" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '   \033[1;32m✔\033[0m %s\n' "$*"; }
bad()  { printf '   \033[1;31m✘\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0
api()  { gh api -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$@"; }
apply(){ [ "$VERIFY_ONLY" -eq 1 ] && return 0; api "$@" >/dev/null; }

REQUIRED_CHECKS='["lint","test (py3.12)","test (py3.13)","test (py3.14)","test-minimal"]'
ADMIN_BYPASS='[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}]'

# ---------------------------------------------------------------- repository
say "repository settings ($REPO)"
apply -X PATCH "repos/$REPO" --input - <<JSON
{
  "has_wiki": false,
  "allow_merge_commit": false,
  "allow_squash_merge": true,
  "allow_rebase_merge": true,
  "allow_auto_merge": true,
  "allow_update_branch": true,
  "delete_branch_on_merge": true,
  "squash_merge_commit_title": "PR_TITLE",
  "squash_merge_commit_message": "PR_BODY",
  "security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"},
    "secret_scanning_non_provider_patterns": {"status": "enabled"}
  }
}
JSON
apply -X PUT "repos/$REPO/vulnerability-alerts"
apply -X PUT "repos/$REPO/automated-security-fixes"
apply -X PUT "repos/$REPO/private-vulnerability-reporting"

# -------------------------------------------------------------- code scanning
say "CodeQL default setup"
apply -X PATCH "repos/$REPO/code-scanning/default-setup" --input - <<'JSON'
{"state": "configured", "query_suite": "extended", "languages": ["python", "actions"]}
JSON

# ------------------------------------------------------------------- actions
say "Actions policy"
apply -X PUT "repos/$REPO/actions/permissions" --input - <<'JSON'
{"enabled": true, "allowed_actions": "selected", "sha_pinning_required": true}
JSON
apply -X PUT "repos/$REPO/actions/permissions/selected-actions" --input - <<'JSON'
{"github_owned_allowed": true, "verified_allowed": true,
 "patterns_allowed": ["astral-sh/setup-uv@*", "pypa/gh-action-pypi-publish@*"]}
JSON
apply -X PUT "repos/$REPO/actions/permissions/workflow" --input - <<'JSON'
{"default_workflow_permissions": "read", "can_approve_pull_request_reviews": false}
JSON

# ------------------------------------------------------------------ rulesets
upsert_ruleset() {  # name, json-body
  local name="$1" body="$2" id
  id="$(api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$name\") | .id" | head -1)"
  if [ "$VERIFY_ONLY" -eq 1 ]; then return 0; fi
  if [ -n "$id" ]; then
    printf '%s' "$body" | api -X PUT "repos/$REPO/rulesets/$id" --input - >/dev/null
  else
    printf '%s' "$body" | api -X POST "repos/$REPO/rulesets" --input - >/dev/null
  fi
}
say "ruleset: main"
upsert_ruleset "main" "$(cat <<JSON
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": $ADMIN_BYPASS,
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": true,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": true,
      "allowed_merge_methods": ["squash", "rebase"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "do_not_enforce_on_create": true,
      "required_status_checks": $(echo "$REQUIRED_CHECKS" | jq -c '[.[] | {context: ., integration_id: 15368}]')
    }}
  ]
}
JSON
)"
say "ruleset: release tags"
upsert_ruleset "release tags" "$(cat <<JSON
{
  "name": "release tags",
  "target": "tag",
  "enforcement": "active",
  "bypass_actors": $ADMIN_BYPASS,
  "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "update"}
  ]
}
JSON
)"

# -------------------------------------------------------------- environments
say "environment: pypi (deploy only from v* tags)"
apply -X PUT "repos/$REPO/environments/pypi" --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
if [ "$VERIFY_ONLY" -eq 0 ]; then
  existing="$(api "repos/$REPO/environments/pypi/deployment-branch-policies" --jq '.branch_policies[] | select(.name == "v*" and .type == "tag") | .id' | head -1)"
  if [ -z "$existing" ]; then
    api -X POST "repos/$REPO/environments/pypi/deployment-branch-policies" --input - >/dev/null <<'JSON'
{"name": "v*", "type": "tag"}
JSON
  fi
fi

# ------------------------------------------------------------------- verify
say "verify"
r="$(api "repos/$REPO")"
check() { local label="$1" expr="$2" want="$3" got; got="$(echo "$r" | jq -r "$expr")"; [ "$got" = "$want" ] && ok "$label = $got" || bad "$label = $got (want $want)"; }
check "wiki disabled"            '.has_wiki'                false
check "merge commits off"        '.allow_merge_commit'      false
check "auto-merge"               '.allow_auto_merge'        true
check "delete branch on merge"   '.delete_branch_on_merge'  true
check "update-branch button"     '.allow_update_branch'     true
check "secret scanning"          '.security_and_analysis.secret_scanning.status' enabled
check "push protection"          '.security_and_analysis.secret_scanning_push_protection.status' enabled
npp="$(echo "$r" | jq -r '.security_and_analysis.secret_scanning_non_provider_patterns.status')"
[ "$npp" = "enabled" ] && ok "non-provider patterns" || printf '   \033[1;33m•\033[0m %s\n' "non-provider patterns = $npp (GitHub ignores this via the API on user-owned repos; toggle it under Settings → Advanced Security if wanted)"
[ "$(api "repos/$REPO/private-vulnerability-reporting" --jq .enabled)" = "true" ] && ok "private vulnerability reporting" || bad "private vulnerability reporting"
[ "$(api "repos/$REPO/vulnerability-alerts" -i 2>/dev/null | head -1 | grep -c 204)" = "1" ] && ok "dependabot alerts" || bad "dependabot alerts"
[ "$(api "repos/$REPO/automated-security-fixes" --jq .enabled)" = "true" ] && ok "dependabot security updates" || bad "dependabot security updates"
cs="$(api "repos/$REPO/code-scanning/default-setup")"
[ "$(echo "$cs" | jq -r .state)" = "configured" ] && ok "CodeQL default setup ($(echo "$cs" | jq -r '.query_suite + ", " + (.languages|join("+"))'))" || bad "CodeQL default setup: $(echo "$cs" | jq -c .)"
ap="$(api "repos/$REPO/actions/permissions")"
[ "$(echo "$ap" | jq -r .allowed_actions)" = "selected" ] && ok "actions: selected only" || bad "actions allowed = $(echo "$ap" | jq -r .allowed_actions)"
[ "$(echo "$ap" | jq -r .sha_pinning_required)" = "true" ] && ok "actions: SHA pinning required" || bad "actions: SHA pinning not required"
wp="$(api "repos/$REPO/actions/permissions/workflow")"
[ "$(echo "$wp" | jq -r .default_workflow_permissions)" = "read" ] && ok "GITHUB_TOKEN default read" || bad "GITHUB_TOKEN default = $(echo "$wp" | jq -r .default_workflow_permissions)"
rs="$(api "repos/$REPO/rulesets")"
for name in "main" "release tags"; do
  rid="$(echo "$rs" | jq -r ".[] | select(.name == \"$name\") | .id")"
  if [ -n "$rid" ]; then
    detail="$(api "repos/$REPO/rulesets/$rid")"
    [ "$(echo "$detail" | jq -r .enforcement)" = "active" ] && ok "ruleset '$name' active: $(echo "$detail" | jq -r '[.rules[].type] | join(", ")')" || bad "ruleset '$name' not active"
  else
    bad "ruleset '$name' missing"
  fi
done
pol="$(api "repos/$REPO/environments/pypi/deployment-branch-policies" 2>/dev/null | jq -r 'try ([.branch_policies[] | .type + ":" + .name] | join(",")) catch ""' || true)"
[ "$pol" = "tag:v*" ] && ok "pypi environment deploys only from tag v*" || bad "pypi deployment policy = '$pol'"

if [ "$FAILED" -ne 0 ]; then echo "some checks failed" >&2; exit 1; fi
say "all settings verified"
