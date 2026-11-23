# Runs one check on a normalized event and prints the hook response.
# Sourced by hook.sh. Claude Code and Codex read the same response shape; a
# harness that differs gets its own renderer next to this one.
#
#   run_check <check-name> <normalized-event-json>

RUNTIME=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

run_check() {
  local check=$1 event=$2 phase report code event_name summary
  phase=$(printf '%s' "$event" | jq -r .phase)
  [ "$phase" = pre ] && event_name=PreToolUse || event_name=PostToolUse

  report=$(printf '%s' "$event" | "$RUNTIME/checks/$check.sh")
  code=$?
  summary=$(printf '%s\n' "$report" | head -1)

  case "$code" in
    0) ;;
    2)
      if [ "$phase" = pre ]; then
        jq -n --arg e "$event_name" --arg r "$report" '{
          hookSpecificOutput: {hookEventName: $e, permissionDecision: "deny", permissionDecisionReason: $r}}'
      else
        jq -n --arg r "$report" '{decision: "block", reason: $r}'
      fi
      ;;
    3)
      jq -n --arg e "$event_name" --arg r "$report" --arg s "$summary" '{
        systemMessage: $s,
        hookSpecificOutput: {hookEventName: $e, additionalContext: $r}}'
      ;;
    *)
      jq -n --arg s "$check: check failed (exit $code), allowed: $summary" '{systemMessage: $s}'
      ;;
  esac
  return 0
}
