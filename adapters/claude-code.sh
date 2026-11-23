#!/usr/bin/env bash
# Claude Code adapter: translates a Claude Code hook payload into the neutral
# event of lib/common.sh, runs a check on it, and answers in Claude Code's
# hook JSON. Usage, as a hook command:  claude-code.sh <check-name>
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib/run.sh"

check=${1:?usage: claude-code.sh <check-name>}
payload=$(cat)

case "$(printf '%s' "$payload" | jq -r '.hook_event_name // ""' 2>/dev/null)" in
  PreToolUse)  phase=pre ;;
  PostToolUse) phase=post ;;
  *) exit 0 ;;
esac

tool=$(printf '%s' "$payload" | jq -r '.tool_name // ""')
file=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // ""')
before_file=/dev/null
[ "$tool" = Write ] && [ "$phase" = pre ] && [ -f "$file" ] && before_file=$file

event=$(printf '%s' "$payload" | jq -c --arg phase "$phase" --rawfile current "$before_file" '
  (.cwd // env.PWD) as $cwd
  | .tool_input as $in
  | if .tool_name == "Bash" then
      {phase: $phase, kind: "shell", cwd: $cwd, command: ($in.command // "")}
    elif .tool_name == "Write" then
      {phase: $phase, kind: "edit", cwd: $cwd,
       edits: [{path: $in.file_path, before: $current, after: ($in.content // "")}]}
    elif .tool_name == "Edit" then
      {phase: $phase, kind: "edit", cwd: $cwd,
       edits: [{path: $in.file_path, before: ($in.old_string // ""), after: ($in.new_string // "")}]}
    elif .tool_name == "MultiEdit" then
      {phase: $phase, kind: "edit", cwd: $cwd,
       edits: [{path: $in.file_path,
                before: ([$in.edits[]?.old_string] | join("\n")),
                after:  ([$in.edits[]?.new_string] | join("\n"))}]}
    else empty end') || exit 0
[ -n "$event" ] || exit 0

run_check "$check" "$event"
