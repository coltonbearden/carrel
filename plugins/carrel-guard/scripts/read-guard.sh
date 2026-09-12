#!/usr/bin/env bash
# PreToolUse hook (matcher: Read). Converts the documents Claude's Read cannot
# open — docx, odt, epub, rtf, xlsx, eml, mbox, mbx — to text with carrel into a
# per-file cache directory, and rewrites the Read's file_path to the text file.
# PDFs are converted too, for tokens rather than capability: Read handles them
# natively, but page images cost far more than the text. Images are left alone
# by default, because Read already shows Claude the picture.
#
# The source file is never touched. Every path out of this script is `exit 0`;
# when anything is off (not a handled extension, carrel missing, too big,
# conversion failed) it prints nothing and the normal Read proceeds. A
# conversion that *timed out* is the one exception: it says so, with no
# updatedInput, so the Read proceeds on the original and Claude knows why.
#
# Output shape (verified against https://code.claude.com/docs/en/hooks,
# 2026-09-12): hookSpecificOutput.{hookEventName, permissionDecision,
# updatedInput, additionalContext}; the decision fields are independent and an
# omitted permissionDecision means the normal permission flow applies.
# updatedInput must match the Read tool's input schema, so only file_path is
# rewritten and offset/limit pass through.
#
# Cache: ${XDG_CACHE_HOME:-$HOME/.cache}/carrel-guard/<sha256 of abs path>/<stem>.txt
# Tunables: CARREL_GUARD_TIMEOUT (s, convert; default 15),
#           CARREL_GUARD_OCR_TIMEOUT (s, images; default 30),
#           CARREL_GUARD_OCR_IMAGES (1 = OCR images instead of letting Read see them),
#           CARREL_GUARD_PDF_TEXT (0 = leave PDFs to the visual Read),
#           CARREL_GUARD_MAX_BYTES (default 67108864 = 64 MiB).
# Note: hooks/hooks.json caps this hook at 60 s, so a budget above that cannot
# be reached — Claude Code kills the hook first and nothing is printed.
set -u

# One convention for every toggle in this script: 0/false/no/off (any case) is
# off, anything else is on. Two knobs with opposite rules meant
# `CARREL_GUARD_OCR_IMAGES=true` silently did nothing while
# `CARREL_GUARD_PDF_TEXT=true` worked.
truthy() {
    case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        ''|0|false|no|off) return 1 ;;
        *) return 0 ;;
    esac
}

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
    /*|[A-Za-z]:*) ;;    # POSIX absolute, or a Windows drive path (Claude Code on Windows)
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
    # Claude's Read cannot open these at all, so converting is pure gain.
    docx|odt|epub|rtf|xlsx|eml|mbox|mbx) mode="convert" ;;
    # Read shows a PDF to Claude as page images. Converting to text is much
    # cheaper in tokens and is still the default, but it loses the layout, so
    # CARREL_GUARD_PDF_TEXT=0 hands the file back to the visual Read.
    pdf) truthy "${CARREL_GUARD_PDF_TEXT:-1}" && mode="convert" || exit 0 ;;
    # Read shows Claude a png/jpg/jpeg itself, and OCR would throw that away
    # for a worse transcription — so it is opt-in. `.ico` is grouped here for
    # the toggle, not for the reason: Read cannot render an ICO container
    # either, so OCR is the only text carrel can offer for one, and it stays
    # behind the same switch rather than running on every icon.
    png|jpg|jpeg|ico) truthy "${CARREL_GUARD_OCR_IMAGES:-0}" && mode="ocr" || exit 0 ;;
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
# Under Git Bash / MSYS, pwd -P gives /c/Users/...; key the cache and report
# paths in the native form Claude Code and carrel use there.
native() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w -- "$1" 2>/dev/null || printf '%s' "$1"
    else
        printf '%s' "$1"
    fi
}
abs="$(native "$abs")"
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
txt="$(native "$cache/${name%.*}.txt")"

# ---- convert unless a fresh cached copy exists (source newer => redo)
run_bounded() {
    # run_bounded SECONDS cmd args... — `timeout` when available, plain otherwise
    # `local`: this used to assign the caller's `secs`, which the timeout note
    # reads back. Correct only while the two happened to hold the same value.
    local secs="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$secs" "$@"
    else
        "$@"
    fi
}

# One JSON emitter. The shape was written out three times, so a change to the
# python3 fallback had to be made in each. Prints nothing and returns non-zero
# if neither jq nor python3 is present, which every caller treats as "be quiet".
emit_hook_json() {
    # emit_hook_json CONTEXT [REWRITTEN_PATH OFFSET LIMIT]
    if [ "$#" -eq 1 ]; then
        if command -v jq >/dev/null 2>&1; then
            jq -cn --arg ctx "$1" \
                '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}'
        elif command -v python3 >/dev/null 2>&1; then
            python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": sys.argv[1]}}))' "$1"
        else
            return 1
        fi
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -cn --arg ctx "$1" --arg fp "$2" --arg off "$3" --arg lim "$4" '
            {hookSpecificOutput: {
                hookEventName: "PreToolUse",
                permissionDecision: "allow",
                updatedInput: ({file_path: $fp}
                    + (if $off != "" then {offset: ($off | tonumber)} else {} end)
                    + (if $lim != "" then {limit: ($lim | tonumber)} else {} end)),
                additionalContext: $ctx}}'
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json, sys
ctx, txt, off, lim = sys.argv[1:5]
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
    "additionalContext": ctx}}))' "$1" "$2" "$3" "$4"
    else
        return 1
    fi
}
timed_out=0
rc=0
budget=""
if [ ! -s "$txt" ] || [ "$abs" -nt "$txt" ]; then
    rm -f -- "$txt" 2>/dev/null
    if [ "$mode" = "convert" ]; then
        # 15 s, not 5: `carrel convert --to txt` takes 6.7 s on a 68 KB
        # pandoc-written docx and 13.9 s on a 127 KB one, so the old budget
        # killed ordinary documents silently. pdftotext is far faster (0.3 s
        # for 600 pages); this bound exists for the pandoc formats.
        budget="${CARREL_GUARD_TIMEOUT:-15}"
        knob="CARREL_GUARD_TIMEOUT"
        run_bounded "$budget" carrel convert "$abs" --to txt --out-dir "$cache" --force >/dev/null 2>&1 || rc=$?
    else
        # OCR is optional: without tesseract carrel exits 3 and we stay silent.
        budget="${CARREL_GUARD_OCR_TIMEOUT:-30}"
        knob="CARREL_GUARD_OCR_TIMEOUT"
        run_bounded "$budget" carrel ocr "$abs" --to txt -o "$txt" --force >/dev/null 2>&1 || rc=$?
    fi
    # coreutils `timeout` exits 124 when it had to kill the command
    if [ "$rc" = "124" ]; then
        timed_out=1
        # A killed conversion can leave a *partial* file — `carrel convert`
        # writes the text in one call, and SIGTERM mid-write truncates it.
        # Serving that would hand Claude half a document as if it were whole,
        # and cache it forever: the partial is newer than the source, so the
        # freshness check never re-converts.
        rm -f -- "$txt" 2>/dev/null
    fi
fi
if [ ! -s "$txt" ]; then
    [ "$timed_out" = "1" ] || exit 0
    # "Read the original instead" is only true where Read can open it. For the
    # zip/XML and mailbox formats it cannot, so saying so there would promise a
    # fallback that errors.
    case "$ext" in
        pdf|png|jpg|jpeg)
            fallback="Reading the original instead — Read handles it natively." ;;
        *)
            fallback="Read cannot open this format, so the Read that follows will fail: run \`carrel convert '$abs' --to txt\` by hand, or raise the budget." ;;
    esac
    note="carrel-guard: converting $abs to text timed out after ${budget}s. $fallback Raise $knob to allow longer (hooks.json caps this hook at 60s)."
    emit_hook_json "$note" 2>/dev/null || exit 0
    exit 0
fi

chars="$(wc -m < "$txt" 2>/dev/null | tr -d '[:space:]')"
case "$chars" in
    ''|*[!0-9]*) chars="$size" ;;
esac
ctx="carrel-guard: $abs was converted to text at $txt ($chars chars). The original is untouched — Read $abs directly when layout, diagrams or images matter."

# ---- emit the PreToolUse decision; silence on any failure
emit_hook_json "$ctx" "$txt" "$offset" "$limit" 2>/dev/null || exit 0
