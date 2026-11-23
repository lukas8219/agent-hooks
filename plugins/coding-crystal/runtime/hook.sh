#!/usr/bin/env bash
# The one hook entry point, for every harness:
#
#   hook.sh <check> [--lang ruby,python,crystal]
#
# Turns the harness's hook payload into the neutral event of lib/common.sh,
# runs checks/<check>.sh on it, and prints the hook response. --lang limits the
# check to those languages, so each coding-<language> plugin guards only its
# own files.
#
# The tool shapes this understands, and who sends them:
#   Bash                    Claude Code, Codex   tool_input.command
#   Write, Edit, MultiEdit  Claude Code          tool_input.file_path + text
#   apply_patch             Codex                tool_input.command holds the raw
#                                                patch (*** Begin Patch ...)
# A new harness with other tool names gets a branch in normalize below.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/lib/render.sh"

check=${1:?usage: hook.sh <check> [--lang ruby,python,crystal]}
shift
[ "${1:-}" = --lang ] && export AGENT_HOOKS_LANGS=${2:-}

payload=$(cat)
case "$(printf '%s' "$payload" | jq -r '.hook_event_name // ""' 2>/dev/null)" in
  PreToolUse)  phase=pre ;;
  PostToolUse) phase=post ;;
  *) exit 0 ;;
esac

tool=$(printf '%s' "$payload" | jq -r '.tool_name // ""')
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // ""')
current=/dev/null
[ "$tool" = Write ] && [ "$phase" = pre ] && [ -f "$file" ] && current=$file

event=$(printf '%s' "$payload" | jq -c --arg phase "$phase" --rawfile current "$current" '
  def text: if type == "array" then join(" ") else (. // "") end;
  def last_set(f; v): .files[(.files | length) - 1] |= (f = v);
  # Each file section of a patch becomes one edit whose before/after hold its
  # hunks old and new sides - the same shape an Edit gives.
  def parse_patch($cwd):
    reduce (split("\n")[]) as $l ({files: []};
      if   ($l | startswith("*** Add File: "))    then .files += [{path: $l[14:], before: "", after: ""}]
      elif ($l | startswith("*** Update File: ")) then .files += [{path: $l[17:], before: "", after: ""}]
      elif ($l | startswith("*** Delete File: ")) then .files += [{path: $l[17:], deleted: true}]
      elif ($l | startswith("*** Move to: "))     then last_set(.path; $l[13:])
      elif ($l | startswith("***")) or ($l | startswith("@@")) or (.files | length) == 0 then .
      elif ($l | startswith("+")) then last_set(.after;  .after  + $l[1:] + "\n")
      elif ($l | startswith("-")) then last_set(.before; .before + $l[1:] + "\n")
      elif ($l | startswith(" ")) then last_set(.before; .before + $l[1:] + "\n")
                                     | last_set(.after;  .after  + $l[1:] + "\n")
      else . end)
    | [.files[] | select(.deleted | not)
       | .path |= (if startswith("/") then . else $cwd + "/" + . end)];

  (.cwd // env.PWD) as $cwd
  | .tool_input as $in
  | {phase: $phase, cwd: $cwd} + (
      if .tool_name == "Bash" then
        {kind: "shell", command: ($in.command | text)}
      elif .tool_name == "apply_patch" then
        {kind: "edit", edits: ($in.command | text | parse_patch($cwd))}
      elif .tool_name == "Write" then
        {kind: "edit", edits: [{path: $in.file_path, before: $current, after: ($in.content // "")}]}
      elif .tool_name == "Edit" then
        {kind: "edit", edits: [{path: $in.file_path, before: ($in.old_string // ""), after: ($in.new_string // "")}]}
      elif .tool_name == "MultiEdit" then
        {kind: "edit", edits: [{path: $in.file_path,
                                before: ([$in.edits[]?.old_string] | join("\n")),
                                after:  ([$in.edits[]?.new_string] | join("\n"))}]}
      else error("unhandled tool") end)' 2>/dev/null) || exit 0
[ -n "$event" ] || exit 0

run_check "$check" "$event"
