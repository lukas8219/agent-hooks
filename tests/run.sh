#!/usr/bin/env bash
# End-to-end tests: real git repos, real rubocop/ruby/python3, driven through
# both harness adapters with the payloads each harness sends. Run anywhere:
#   tests/run.sh
set -uo pipefail
KIT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CC=$KIT/adapters/claude-code.sh
CX=$KIT/adapters/codex.sh

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else no "$1 (want $3, got ${2:-empty})"; fi; }

# The verdict a hook response carries: deny | block | context | allow.
verdict() {
  local out; out=$(cat)
  [ -n "$out" ] || { echo allow; return; }
  printf '%s' "$out" | jq -r '
    if .hookSpecificOutput.permissionDecision == "deny" then "deny"
    elif .decision == "block" then "block"
    elif .hookSpecificOutput.additionalContext then "context"
    else "allow" end'
}

GNARLY='\ndef gnarly(alpha, beta, gamma, delta)\n  t = 0\n  t += 1 if alpha\n  t += 2 if beta\n  t += 3 if gamma\n  t += 4 if delta\n  t += 5 if alpha && beta\n  t += 6 if gamma || delta\n  t += 7 if alpha && gamma\n  t\nend\n'

new_repo() {
  local d; d=$(mktemp -d)
  git init -q "$d"
  printf 'def ok(alpha)\n  alpha\nend\n' > "$d/a.rb"
  git -C "$d" add a.rb
  git -C "$d" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm base
  echo "$d"
}

cc_pre_bash()  { jq -nc --arg c "$1" --arg d "$2" '{hook_event_name:"PreToolUse",tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
cc_post_bash() { jq -nc --arg c "$1" --arg d "$2" '{hook_event_name:"PostToolUse",tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
cx_pre_bash()  { jq -nc --arg c "$1" --arg d "$2" '{hook_event_name:"PreToolUse",tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }

echo "0. prerequisites"
for c in jq git ruby python3 rubocop; do
  command -v "$c" >/dev/null && ok "$c" || no "$c missing (./install.sh deps)"
done

echo "1. lint-changed: advisory after an edit (Claude Code)"
d=$(new_repo); printf "$GNARLY" >> "$d/a.rb"
out=$(jq -nc --arg f "$d/a.rb" --arg d "$d" '{hook_event_name:"PostToolUse",tool_name:"Edit",cwd:$d,tool_input:{file_path:$f}}' | "$CC" lint-changed)
check "changed complex method -> context" "$(printf '%s' "$out" | verdict)" context
printf '%s' "$out" | grep -q CyclomaticComplexity && ok "names the cop" || no "CyclomaticComplexity not reported"
printf '%s' "$out" | grep -q 'def ok' && no "reported unchanged code" || ok "unchanged code is not reported"

echo "2. lint-changed: commit gate"
git -C "$d" add a.rb
check "staged complexity -> deny"            "$(cc_pre_bash 'git commit -m x' "$d" | "$CC" lint-changed | verdict)" deny
check "--no-verify bypasses, as in git"      "$(cc_pre_bash 'git commit --no-verify -m x' "$d" | "$CC" lint-changed | verdict)" allow
check "non-commit command is ignored"        "$(cc_pre_bash 'git status' "$d" | "$CC" lint-changed | verdict)" allow
check "Codex Bash payload -> deny"           "$(cx_pre_bash 'git commit -m x' "$d" | "$CX" lint-changed | verdict)" deny
git -C "$d" reset -q
check "unstaged + plain commit -> allow"     "$(cc_pre_bash 'git commit -m x' "$d" | "$CC" lint-changed | verdict)" allow
check "'git add -A && git commit' -> deny"   "$(cc_pre_bash 'git add -A && git commit -m x' "$d" | "$CC" lint-changed | verdict)" deny
check "'git commit -am' -> deny"             "$(cc_pre_bash 'git commit -am x' "$d" | "$CC" lint-changed | verdict)" deny
git -C "$d" checkout -q a.rb
printf '\ndef tidy(alpha)\n  alpha + 1\nend\n' >> "$d/a.rb"; git -C "$d" add a.rb
check "clean staged change -> allow"         "$(cc_pre_bash 'git commit -m x' "$d" | "$CC" lint-changed | verdict)" allow
rm -rf "$d"

echo "3. no-new-comments: edits (Claude Code)"
cc_edit() { jq -nc --arg f "$1" --arg o "$2" --arg n "$3" '{hook_event_name:"PreToolUse",tool_name:"Edit",cwd:"/tmp",tool_input:{file_path:$f,old_string:$o,new_string:$n}}' | "$CC" no-new-comments | verdict; }
check "adding a comment -> deny"              "$(cc_edit /tmp/v.rb '  1' $'  # note\n  2')" deny
check "untouched existing comment -> allow"   "$(cc_edit /tmp/v.rb $'  # keep\n  1' $'  # keep\n  2')" allow
check "# inside a string -> allow"            "$(cc_edit /tmp/v.rb '  1' '  u = "http://x/#f"')" allow
check "magic comment -> allow"                "$(cc_edit /tmp/v.rb '' '# frozen_string_literal: true')" allow
check "python comment -> deny"                "$(cc_edit /tmp/v.py '    return 1' $'    # note\n    return 2')" deny
check "unsupported language -> allow"         "$(cc_edit /tmp/v.go 'x' $'// note\nx')" allow
w=$(mktemp -d)/w.rb; printf '# old\nx = 1\n' > "$w"
check "Write keeping existing comment -> allow" "$(jq -nc --arg f "$w" '{hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$f,content:"# old\nx = 2\n"}}' | "$CC" no-new-comments | verdict)" allow
check "Write adding a comment -> deny"          "$(jq -nc --arg f "$w" '{hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$f,content:"# old\n# new\nx = 2\n"}}' | "$CC" no-new-comments | verdict)" deny

echo "4. no-new-comments: apply_patch (Codex)"
cx_patch() { jq -nc --arg p "$1" '{hook_event_name:"PreToolUse",tool_name:"apply_patch",cwd:"/tmp",tool_input:{command:$p}}' | "$CX" no-new-comments | verdict; }
check "update adding a comment -> deny" \
  "$(cx_patch $'*** Begin Patch\n*** Update File: lib/a.rb\n@@ def ok\n-  1\n+  # note\n+  2\n*** End Patch')" deny
check "update keeping context comment -> allow" \
  "$(cx_patch $'*** Begin Patch\n*** Update File: lib/a.rb\n@@\n   # keep\n-  1\n+  2\n*** End Patch')" allow
check "added file with a comment -> deny" \
  "$(cx_patch $'*** Begin Patch\n*** Add File: b.py\n+# hello\n+x = 1\n*** End Patch')" deny
check "second file in patch is checked -> deny" \
  "$(cx_patch $'*** Begin Patch\n*** Update File: a.rb\n@@\n-x\n+y\n*** Update File: c.rb\n@@\n-x\n+# z\n+x\n*** End Patch')" deny
check "deleted file -> allow" \
  "$(cx_patch $'*** Begin Patch\n*** Delete File: a.rb\n*** End Patch')" allow

echo "5. no-new-comments: written via the shell"
t=$(new_repo)
printf '\n# added by heredoc\ndef n(alpha)\n  alpha\nend\n' >> "$t/a.rb"
check "heredoc comment -> block"           "$(cc_post_bash 'cat >> a.rb <<EOF' "$t" | "$CC" no-new-comments | verdict)" block
check "Codex Bash payload -> block"        "$(jq -nc --arg d "$t" '{hook_event_name:"PostToolUse",tool_name:"Bash",cwd:$d,tool_input:{command:"cat >> a.rb"}}' | "$CX" no-new-comments | verdict)" block
git -C "$t" checkout -q a.rb
{ printf '# explains old code\n'; cat "$t/a.rb"; } > "$t/a.tmp" && mv "$t/a.tmp" "$t/a.rb"
check "scope=new-code spares old code"     "$(cc_post_bash 'sed -i x' "$t" | NO_NEW_COMMENTS_SCOPE=new-code "$CC" no-new-comments | verdict)" allow
check "scope=all catches the annotation"   "$(cc_post_bash 'sed -i x' "$t" | "$CC" no-new-comments | verdict)" block
rm -rf "$t"

echo "6. adapters stay quiet on what they don't handle"
check "SessionStart ignored"  "$(echo '{"hook_event_name":"SessionStart"}' | "$CC" lint-changed | verdict)" allow
check "Read tool ignored"     "$(echo '{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{}}' | "$CC" no-new-comments | verdict)" allow
check "garbage stdin ignored" "$(echo 'not json' | "$CX" no-new-comments | verdict)" allow

echo "7. installer"
h=$(mktemp -d); r=$(new_repo)
HOME=$h "$KIT/install.sh" claude --user >/dev/null && HOME=$h "$KIT/install.sh" claude --user >/dev/null
check "claude --user registers 4 hooks, idempotent" \
  "$(jq '[.hooks[][] .hooks[] | select(.command|test("adapters/claude-code.sh"))] | length' "$h/.claude/settings.json")" 4
check "attribution cleared" "$(jq -c .attribution "$h/.claude/settings.json")" '{"commit":"","pr":""}'
HOME=$h "$KIT/install.sh" claude --project "$r" >/dev/null
check "claude --project writes repo settings" \
  "$(jq '[.hooks[][] .hooks[]] | length' "$r/.claude/settings.json")" 4
check "repo settings stay out of git status" "$(git -C "$r" status --porcelain)" ""
HOME=$h CODEX_HOME=$h/.codex "$KIT/install.sh" codex --user >/dev/null
check "codex uses apply_patch matcher" \
  "$(jq -r '.hooks.PreToolUse[] | select(.hooks[0].command|test("no-new-comments")) | .matcher' "$h/.codex/hooks.json")" apply_patch
check "codex commands point at codex.sh" \
  "$(jq '[.hooks[][] .hooks[] | select(.command|test("adapters/codex.sh"))] | length' "$h/.codex/hooks.json")" 4
rm -rf "$h" "$r"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
