#!/usr/bin/env bash
# Setup script for a Claude Code on the web environment (claude.ai/code ->
# environment settings -> Setup script). It runs as root before Claude starts
# and its result is cached, so the slow part (apt, gem, npm) lives here.
#
# Cloud sessions don't read ~/.claude/settings.json, so hooks can't be
# installed user-wide. Instead this clones the kit and appends its CLAUDE.md
# to ~/.claude/CLAUDE.md, which tells Claude to register the hooks in the
# working repo's .claude/settings.json at the start of every session.
set -euo pipefail

REPO=${AGENT_HOOKS_REPO:-https://github.com/lukas8219/agent-hooks.git}
DEST=/opt/agent-hooks   # CLAUDE.md looks here

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull -q --ff-only || true
else
  git clone -q --depth 1 "$REPO" "$DEST"
fi

"$DEST/install.sh" deps

mkdir -p "$HOME/.claude"
marker="<!-- agent-hooks -->"
if ! grep -qF "$marker" "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
  { echo "$marker"; cat "$DEST/CLAUDE.md"; } >> "$HOME/.claude/CLAUDE.md"
fi
