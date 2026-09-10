#!/usr/bin/env bash
# Verifies what the sbx-dev kit is supposed to have set up. Run inside a sandbox.
pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }
skip() { printf '  \033[33mSKIP\033[0m %s\n' "$1"; }

echo "1. hunk CLI"
if command -v hunk >/dev/null; then ok "hunk $(hunk --version) at $(command -v hunk)"
else no "hunk not on PATH"; fi

echo "2. allowedSignersFile"
sf=$(git config --get gpg.ssh.allowedSignersFile)
sfx=${sf/#\~/$HOME}
if [ -n "$sf" ] && [ -r "$sfx" ]; then ok "$sf -> $(wc -l < "$sfx") signer(s)"
else no "unset or unreadable (value: '${sf:-none}')"; fi

echo "3. signature round-trip"
if ! ssh-add -l >/dev/null 2>&1; then skip "no ssh-agent keys; cannot sign"
else
  d=$(mktemp -d); git init -q "$d"; : > "$d/f"
  if git -C "$d" add f && git -C "$d" -c commit.gpgsign=true commit -qm t 2>/dev/null &&
     git -C "$d" log --show-signature -1 2>&1 | grep -q '^Good "git" signature'
  then ok "signed and verified locally"
  else no "sign or verify failed"; fi
  rm -rf "$d"
fi

echo "4. github.com host key"
want=SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
if [ -r "$HOME/.ssh/known_hosts" ] && ssh-keygen -lf "$HOME/.ssh/known_hosts" 2>/dev/null | grep -q "$want"
then ok "pinned ed25519 key matches GitHub's published fingerprint"
else no "expected $want in ~/.ssh/known_hosts"; fi

echo "5. attribution cleared"
s=$HOME/.claude/settings.json
if [ -r "$s" ] && [ "$(jq -c '.attribution' "$s" 2>/dev/null)" = '{"commit":"","pr":""}' ]
then ok "attribution = $(jq -c .attribution "$s")"
else no "got $(jq -c '.attribution // "absent"' "$s" 2>/dev/null || echo 'unreadable')"; fi

echo "6. hunk-review skill"
sk=$HOME/.claude/skills/hunk-review/SKILL.md
if mountpoint -q "$HOME/.claude/skills" 2>/dev/null; then
  skip "skills dir is the shared host mount; kit correctly leaves it alone"
  [ -r "$sk" ] && echo "       (host provides it: $(head -2 "$sk" | tail -1 | cut -c1-40)...)"
elif [ -L "$sk" ] && [ -r "$sk" ]; then ok "symlink -> $(readlink "$sk")"
elif [ -r "$sk" ]; then ok "present (regular file)"
else no "missing"; fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
