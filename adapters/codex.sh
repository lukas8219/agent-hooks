#!/usr/bin/env bash
# Codex adapter: translates a Codex hook payload into the neutral event of
# lib/common.sh, runs a check on it, and answers in Codex's hook JSON.
# Usage, as a hook command:  codex.sh <check-name>
#
# Codex reports file edits as tool_name "apply_patch" with the raw patch in
# tool_input.command (*** Begin Patch / *** Update File: ... / *** End Patch);
# each file section becomes one edit whose before/after hold the hunks' old
# and new sides, the same shape Claude Code's Edit gives.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib/run.sh"

check=${1:?usage: codex.sh <check-name>}
payload=$(cat)

case "$(printf '%s' "$payload" | jq -r '.hook_event_name // ""' 2>/dev/null)" in
  PreToolUse)  phase=pre ;;
  PostToolUse) phase=post ;;
  *) exit 0 ;;
esac

event=$(printf '%s' "$payload" | jq -c --arg phase "$phase" '
  def text: if type == "array" then join(" ") else (. // "") end;
  def last_set(f; v): .files[(.files | length) - 1] |= (f = v);
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
  | (.tool_input.command | text) as $cmd
  | if .tool_name == "Bash" then
      {phase: $phase, kind: "shell", cwd: $cwd, command: $cmd}
    elif .tool_name == "apply_patch" then
      {phase: $phase, kind: "edit", cwd: $cwd, edits: ($cmd | parse_patch($cwd))}
    else empty end') || exit 0
[ -n "$event" ] || exit 0

run_check "$check" "$event"
