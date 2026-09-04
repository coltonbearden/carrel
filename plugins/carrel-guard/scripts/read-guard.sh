#!/usr/bin/env bash
# PreToolUse hook (matcher: Read). When Claude is about to Read a document it
# cannot parse natively (pdf, docx, odt, epub, rtf, xlsx) or an image (png,
# jpg, ico), convert it to text with carrel into a per-file cache directory and
# rewrite the Read's file_path to the text file. The source file is never
# touched. Every path out of this script is `exit 0`; when anything is off
# (not a binary, carrel missing, too big, conversion failed) it prints nothing
# and the normal Read proceeds.
#
# Output shape (verified against https://code.claude.com/docs/en/hooks,
# 2026-09-04): hookSpecificOutput.{hookEventName, permissionDecision,
# updatedInput, additionalContext}; updatedInput must match the Read tool's
# input schema, so only file_path is rewritten and offset/limit pass through.
#
# Cache: ${XDG_CACHE_HOME:-$HOME/.cache}/carrel-guard/<sha256 of abs path>/<stem>.txt
# Tunables: CARREL_GUARD_TIMEOUT (s, convert; default 5),
#           CARREL_GUARD_OCR_TIMEOUT (s, images; default 30),
#           CARREL_GUARD_MAX_BYTES (default 67108864 = 64 MiB).
set -u

# Drain stdin first (Claude Code pipes the event JSON). Keep it for parsing.
payload="$(cat 2>/dev/null || true)"

command -v carrel >/dev/null 2>&1 || exit 0

# ---- parse tool_input.file_path / offset / limit and cwd (jq, else python3)
file_path=""
offset=""
limit=""
hook_cwd=""
if command -v jq >/dev/null 2>&1; then
    file_path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty | strings' 2>/dev/null || true)"
    offset="$(printf '%s' "$payload" | jq -r '.tool_input.offset | numbers' 2>/dev/null || true)"
    limit="$(printf '%s' "$payload" | jq -r '.tool_input.limit | numbers' 2>/dev/null || true)"
    hook_cwd="$(printf '%s' "$payload" | jq -r '.cwd // empty | strings' 2>/dev/null || true)"
elif command -v python3 >/dev/null 2>&1; then
    parsed="$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input") if isinstance(d, dict) else None
    ti = ti if isinstance(ti, dict) else {}
    def num(v):
        return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else ""
    fp = ti.get("file_path")
    cwd = d.get("cwd") if isinstance(d, dict) else None
    print(fp if isinstance(fp, str) else "")
    print(num(ti.get("offset")))
    print(num(ti.get("limit")))
    print(cwd if isinstance(cwd, str) else "")
except Exception:
    pass
' 2>/dev/null || true)"
    file_path="$(printf '%s\n' "$parsed" | sed -n 1p)"
    offset="$(printf '%s\n' "$parsed" | sed -n 2p)"
    limit="$(printf '%s\n' "$parsed" | sed -n 3p)"
    hook_cwd="$(printf '%s\n' "$parsed" | sed -n 4p)"
else
    exit 0
fi

[ -n "$file_path" ] || exit 0
case "$file_path" in
    /*) ;;
    *) file_path="${hook_cwd:-$PWD}/$file_path" ;;
esac
[ -f "$file_path" ] && [ -r "$file_path" ] || exit 0

# ---- decide by extension (cheap and sufficient; carrel re-sniffs magic bytes)
name="$(basename -- "$file_path")"
case "$name" in
    *.*) ;;
    *) exit 0 ;;
esac
ext="$(printf '%s' "${name##*.}" | tr '[:upper:]' '[:lower:]')"
mode=""
case "$ext" in
    pdf|docx|odt|epub|rtf|xlsx) mode="convert" ;;
    png|jpg|jpeg|ico) mode="ocr" ;;
    *) exit 0 ;;
esac

# ---- size guard
size="$(wc -c < "$file_path" 2>/dev/null | tr -d '[:space:]')" || exit 0
case "$size" in
    ''|*[!0-9]*) exit 0 ;;
esac
[ "$size" -gt 0 ] || exit 0
[ "$size" -le "${CARREL_GUARD_MAX_BYTES:-67108864}" ] || exit 0

# ---- cache dir keyed by sha256 of the absolute (symlink-resolved dir) path
dir="$(cd -- "$(dirname -- "$file_path")" 2>/dev/null && pwd -P)" || exit 0
abs="$dir/$name"
hash=""
if command -v sha256sum >/dev/null 2>&1; then
    hash="$(printf '%s' "$abs" | sha256sum 2>/dev/null | cut -d' ' -f1)"
elif command -v shasum >/dev/null 2>&1; then
    hash="$(printf '%s' "$abs" | shasum -a 256 2>/dev/null | cut -d' ' -f1)"
elif command -v python3 >/dev/null 2>&1; then
    hash="$(printf '%s' "$abs" | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' 2>/dev/null)"
fi
case "$hash" in
    *[!0-9a-f]*|'') exit 0 ;;
esac
cache="${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/carrel-guard/$hash"
mkdir -p -- "$cache" 2>/dev/null || exit 0
txt="$cache/${name%.*}.txt"

# ---- convert unless a fresh cached copy exists (source newer => redo)
run_bounded() {
    # run_bounded SECONDS cmd args... — `timeout` when available, plain otherwise
    secs="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$secs" "$@"
    else
        "$@"
    fi
}
if [ ! -s "$txt" ] || [ "$abs" -nt "$txt" ]; then
    rm -f -- "$txt" 2>/dev/null
    if [ "$mode" = "convert" ]; then
        run_bounded "${CARREL_GUARD_TIMEOUT:-5}" carrel convert "$abs" --to txt --out-dir "$cache" --force >/dev/null 2>&1 || true
    else
        # OCR is optional: without tesseract carrel exits 3 and we stay silent.
        run_bounded "${CARREL_GUARD_OCR_TIMEOUT:-30}" carrel ocr "$abs" --to txt -o "$txt" --force >/dev/null 2>&1 || true
    fi
fi
[ -s "$txt" ] || exit 0

chars="$(wc -m < "$txt" 2>/dev/null | tr -d '[:space:]')"
case "$chars" in
    ''|*[!0-9]*) chars="$size" ;;
esac
ctx="carrel-guard: $abs was converted to text at $txt ($chars chars). Original left untouched."

# ---- emit the PreToolUse decision (jq, else python3); silence on any failure
if command -v jq >/dev/null 2>&1; then
    jq -cn --arg fp "$txt" --arg off "$offset" --arg lim "$limit" --arg ctx "$ctx" '
        {hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "allow",
            updatedInput: ({file_path: $fp}
                + (if $off != "" then {offset: ($off | tonumber)} else {} end)
                + (if $lim != "" then {limit: ($lim | tonumber)} else {} end)),
            additionalContext: $ctx}}' 2>/dev/null || exit 0
else
    python3 - "$txt" "$offset" "$limit" "$ctx" <<'PY' 2>/dev/null || exit 0
import json, sys
txt, off, lim, ctx = sys.argv[1:5]
updated = {"file_path": txt}
for key, raw in (("offset", off), ("limit", lim)):
    if raw:
        try:
            value = float(raw)
        except ValueError:
            continue
        updated[key] = int(value) if value.is_integer() else value
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "updatedInput": updated,
    "additionalContext": ctx}}))
PY
fi
exit 0
