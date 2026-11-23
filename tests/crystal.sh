CRYSTAL_HOOK=$KIT/plugins/coding-crystal/runtime/hook.sh
crystal_edit() {
  jq -nc --arg f "${3:-/tmp/a.cr}" --arg old "$1" --arg new "$2" \
    '{hook_event_name:"PreToolUse",tool_name:"Edit",tool_input:{file_path:$f,old_string:$old,new_string:$new}}' |
    "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict
}
crystal_post_edit() {
  jq -nc --arg f "$1" --arg d "$2" \
    '{hook_event_name:"PostToolUse",tool_name:"Edit",cwd:$d,tool_input:{file_path:$f}}' |
    "$CRYSTAL_HOOK" lint-changed --lang crystal
}
crystal_commit() {
  cc_pre_bash "$1" "$2" | "$CRYSTAL_HOOK" lint-changed --lang crystal | verdict
}

check "Crystal: new comment -> deny" "$(crystal_edit '' '# note')" deny
check "Crystal: inline comment -> deny" "$(crystal_edit 'x = 1' 'x = 2 # note')" deny
check "Crystal: existing comment -> allow" "$(crystal_edit $'# keep\nx = 1' $'# keep\nx = 2')" allow
check "Crystal: hash in string -> allow" "$(crystal_edit '' 'url = "http://x/#f"')" allow
check "Crystal: hash in regex -> allow" "$(crystal_edit '' 'pattern = /#foo/')" allow
check "Crystal: hash in percent literal -> allow" "$(crystal_edit '' 'text = %q(#foo)')" allow
check "Crystal: hash character -> allow" "$(crystal_edit '' "char = '#'")" allow
check "Crystal: hash in heredoc -> allow" "$(crystal_edit '' $'text = <<-TEXT\n# data\nTEXT\n')" allow
check "Crystal: comment after heredoc -> deny" "$(crystal_edit '' $'text = <<-TEXT\n# data\nTEXT\n# note\n')" deny
check "Crystal: interpolated string -> allow" "$(crystal_edit '' 'text = "#{1}# data"')" allow
check "Crystal: macro comment -> deny" "$(crystal_edit '' $'macro example\n  # note\n  {{ 1 }}\nend\n')" deny
check "Crystal: macro string -> allow" "$(crystal_edit '' $'macro example\n  puts "# data"\nend\n')" allow
check "Crystal: compiler directives -> allow" "$(crystal_edit '' $'#!/usr/bin/env crystal\n# ameba:disable Lint/UselessAssign\n# crystal: formatter off\nx = 1\n# crystal: formatter on\n')" allow
check "Crystal: Ruby magic comment is not a directive -> deny" "$(crystal_edit '' '# frozen_string_literal: true')" deny
check "Crystal: ignores Ruby comments" "$(crystal_edit '' '# note' /tmp/a.rb)" allow
check "Crystal: ignores Python comments" "$(crystal_edit '' '# note' /tmp/a.py)" allow
check "Ruby: ignores Crystal comments" "$(jq -nc '{hook_event_name:"PreToolUse",tool_name:"Edit",tool_input:{file_path:"/tmp/a.cr",new_string:"# note"}}' | "$HOOK" no-new-comments --lang ruby | verdict)" allow
check "Python: ignores Crystal comments" "$(jq -nc '{hook_event_name:"PreToolUse",tool_name:"Edit",tool_input:{file_path:"/tmp/a.cr",new_string:"# note"}}' | "$HOOK" no-new-comments --lang python | verdict)" allow
check "Crystal: apply_patch comment -> deny" "$(jq -nc --arg p $'*** Begin Patch\n*** Add File: a.cr\n+# note\n+x = 1\n*** End Patch' '{hook_event_name:"PreToolUse",tool_name:"apply_patch",cwd:"/tmp",tool_input:{command:$p}}' | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" deny
check "Crystal: MultiEdit comment -> deny" "$(jq -nc '{hook_event_name:"PreToolUse",tool_name:"MultiEdit",tool_input:{file_path:"/tmp/a.cr",edits:[{old_string:"x = 1",new_string:"# note\nx = 2"}]}}' | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" deny

t=$(new_repo)
printf '# keep\nx = 1\n' > "$t/a.cr"
check "Crystal: Write preserves existing comments" "$(jq -nc --arg f "$t/a.cr" '{hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$f,content:"# keep\nx = 2\n"}}' | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" allow
check "Crystal: Write adds comment -> deny" "$(jq -nc --arg f "$t/a.cr" '{hook_event_name:"PreToolUse",tool_name:"Write",tool_input:{file_path:$f,content:"# keep\n# new\nx = 2\n"}}' | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" deny
check "Crystal: shell comment -> block" "$(cc_post_bash 'crystal run writer.cr' "$t" | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" block
check "Ruby: post-shell skips Crystal" "$(cc_post_bash 'cat > a.cr' "$t" | "$HOOK" no-new-comments --lang ruby | verdict)" allow
printf 'def old_issue\n  unused = 1\n  true\nend\n' > "$t/a.cr"
git -C "$t" add a.cr
git -C "$t" -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -qm crystal
printf '\ndef tidy\n  1\nend\n' >> "$t/a.cr"
check "Crystal: ignores unchanged offenses" "$(crystal_post_edit "$t/a.cr" "$t" | verdict)" allow
printf '\ndef new_issue\n  unused = 2\n  true\nend\n' >> "$t/a.cr"
out=$(crystal_post_edit "$t/a.cr" "$t")
check "Crystal: changed offense -> context" "$(printf '%s' "$out" | verdict)" context
printf '%s' "$out" | grep -q 'Lint/UselessAssign' && ok "Crystal: names the rule" || no "Crystal: missing rule name"
check "Crystal: report contains only new offense" "$(printf '%s' "$out" | jq -r .hookSpecificOutput.additionalContext | grep -c '\[Lint/UselessAssign\]')" 1
check "Ruby: lint skips Crystal" "$(jq -nc --arg f "$t/a.cr" --arg d "$t" '{hook_event_name:"PostToolUse",tool_name:"Edit",cwd:$d,tool_input:{file_path:$f}}' | "$HOOK" lint-changed --lang ruby | verdict)" allow
check "Crystal: unstaged plain commit -> allow" "$(crystal_commit 'git commit -m x' "$t")" allow
check "Crystal: add then commit -> deny" "$(crystal_commit 'git add -A && git commit -m x' "$t")" deny
check "Crystal: commit -am -> deny" "$(crystal_commit 'git commit -am x' "$t")" deny
git -C "$t" add a.cr
check "Crystal: staged offense -> deny" "$(crystal_commit 'git commit -m x' "$t")" deny
check "Crystal: no-verify bypasses" "$(crystal_commit 'git commit --no-verify -m x' "$t")" allow
check "Crystal: non-commit ignored" "$(crystal_commit 'git status' "$t")" allow
printf 'Lint/UselessAssign:\n  Enabled: false\n' > "$t/.ameba.yml"
check "Crystal: project config respected after edit" "$(crystal_post_edit "$t/a.cr" "$t" | verdict)" allow
check "Crystal: project config respected at commit" "$(crystal_commit 'git commit -m x' "$t")" allow
printf 'Excluded:\n  - a.cr\n' > "$t/.ameba.yml"
check "Crystal: excluded file skipped after edit" "$(crystal_post_edit "$t/a.cr" "$t" | verdict)" allow
check "Crystal: excluded staged file skipped" "$(crystal_commit 'git commit -m x' "$t")" allow
rm "$t/.ameba.yml"
git -C "$t" show HEAD:a.cr > "$t/a.cr"
check "Crystal: staged offense survives unstaged fix" "$(crystal_commit 'git commit -m x' "$t")" deny
rm "$t/a.cr"
check "Crystal: missing working file is skipped" "$(crystal_commit 'git commit -m x' "$t")" allow
git -C "$t" show HEAD:a.cr > "$t/a.cr"
printf '\ndef tidy\n  1\nend\n' >> "$t/a.cr"
git -C "$t" add a.cr
printf '\ndef new_issue\n  unused = 2\n  true\nend\n' >> "$t/a.cr"
check "Crystal: unstaged offense does not block clean index" "$(crystal_commit 'git commit -m x' "$t")" allow
git -C "$t" reset -q
git -C "$t" checkout -q a.cr
printf 'def new_issue\n  unused = 2\n  true\nend\n' > "$t/new file.cr"
check "Crystal: untracked path with spaces -> context" "$(crystal_post_edit "$t/new file.cr" "$t" | verdict)" context
check "Crystal: add then commit checks untracked files" "$(crystal_commit 'git add -A && git commit -m x' "$t")" deny
git -C "$t" add 'new file.cr'
check "Crystal: staged path with spaces -> deny" "$(crystal_commit 'git commit -m x' "$t")" deny
git -C "$t" reset -q
rm "$t/new file.cr"
printf '# annotation\n' > "$t/a.tmp"
cat "$t/a.cr" >> "$t/a.tmp"
mv "$t/a.tmp" "$t/a.cr"
check "Crystal: new-code scope spares annotation" "$(cc_post_bash 'sed -i x' "$t" | NO_NEW_COMMENTS_SCOPE=new-code "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" allow
check "Crystal: all scope blocks annotation" "$(cc_post_bash 'sed -i x' "$t" | "$CRYSTAL_HOOK" no-new-comments --lang crystal | verdict)" block
mkdir "$t/bin"
cat > "$t/bin/ameba" <<'SH'
#!/usr/bin/env bash
printf '%s\n' '{"sources":[{"issues":[{"rule_name":"Local/Rule","message":"local runner used","location":{"line":1,"column":1}}]}]}'
SH
chmod +x "$t/bin/ameba"
out=$(crystal_post_edit "$t/a.cr" "$t")
printf '%s' "$out" | grep -q 'Local/Rule' && ok "Crystal: project bin/ameba is preferred" || no "Crystal: project runner ignored"
printf '#!/usr/bin/env bash\nexit 1\n' > "$t/bin/ameba"
check "Crystal: broken linter fails open" "$(crystal_post_edit "$t/a.cr" "$t" | verdict)" allow
rm -rf "$t"

t=$(mktemp -d)
"$KIT/install.sh" codex --project "$t" --only coding-crystal >/dev/null
check "Crystal: installer registers four scoped hooks" "$(count "$t/.codex/hooks.json" 'coding-crystal/.*--lang crystal')" 4
rm -rf "$t"
