#!/usr/bin/env bash
# SessionStart hook: if carrel is on PATH, hand Claude one paragraph of
# additionalContext — version, how many commands are ok/degraded/unavailable
# per `carrel doctor --json`, and the three most useful missing optional
# binaries with their install hints. Without carrel (or on any failure) it
# prints nothing and exits 0. Never blocks a session.
#
# Output shape (https://code.claude.com/docs/en/hooks, 2026-09-04):
# {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
set -u

# Drain stdin (the SessionStart payload); nothing in it changes what we do.
cat >/dev/null 2>&1 || true

command -v carrel >/dev/null 2>&1 || exit 0

report=""
if command -v timeout >/dev/null 2>&1; then
    report="$(timeout "${CARREL_GUARD_DOCTOR_TIMEOUT:-20}" carrel --json doctor 2>/dev/null)" || exit 0
else
    report="$(carrel --json doctor 2>/dev/null)" || exit 0
fi
[ -n "$report" ] || exit 0

if command -v jq >/dev/null 2>&1; then
    printf '%s' "$report" | jq -c '
        def count(s): [.commands[] | select(.status == s)] | length;
        ([.commands[] | ((.requires // [])[]), ((.optional // [])[])]) as $wanted
        | (.adapters
           | map(select(.found == false))
           | map(. as $a | {name: .name,
                            hint: (.install_hint // "no install hint recorded"),
                            score: ([$wanted[] | select(. == $a.name)] | length)})
           | sort_by(-.score, .name)
           | .[:3]) as $missing
        | ("carrel " + (.product.version // "?") + " is on PATH: "
           + (count("ok") | tostring) + " of " + (.commands | length | tostring) + " commands ok, "
           + (count("degraded") | tostring) + " degraded, "
           + (count("unavailable") | tostring) + " unavailable. "
           + "Run `carrel doctor --json` for the full table and `carrel <cmd> --help` before composing flags. "
           + (if ($missing | length) == 0 then "No optional binaries are missing."
              else "Most useful missing binaries: "
                   + ($missing | map(.name + " (" + .hint + ")") | join(", ")) + "." end))
        | {hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: .}}
    ' 2>/dev/null || exit 0
elif command -v python3 >/dev/null 2>&1; then
    printf '%s' "$report" | python3 -c '
import json, sys
from collections import Counter
try:
    d = json.load(sys.stdin)
    commands = d.get("commands") or []
    adapters = d.get("adapters") or []
    status = Counter(c.get("status") for c in commands)
    wanted = Counter()
    for c in commands:
        wanted.update(c.get("requires") or [])
        wanted.update(c.get("optional") or [])
    missing = sorted(
        (a for a in adapters if not a.get("found")),
        key=lambda a: (-wanted.get(a.get("name"), 0), a.get("name") or ""),
    )[:3]
    version = (d.get("product") or {}).get("version", "?")
    text = (
        "carrel " + str(version) + " is on PATH: "
        + str(status.get("ok", 0)) + " of " + str(len(commands)) + " commands ok, "
        + str(status.get("degraded", 0)) + " degraded, "
        + str(status.get("unavailable", 0)) + " unavailable. "
        "Run `carrel doctor --json` for the full table and `carrel <cmd> --help` before composing flags. "
    )
    if missing:
        text += "Most useful missing binaries: " + ", ".join(
            str(a.get("name")) + " (" + str(a.get("install_hint") or "no install hint recorded") + ")"
            for a in missing
        ) + "."
    else:
        text += "No optional binaries are missing."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
except Exception:
    pass
' 2>/dev/null || exit 0
fi
exit 0
