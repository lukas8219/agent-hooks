#!/usr/bin/env bash
# Setup script for a Claude Code on the web environment (claude.ai/code ->
# environment settings -> Setup script). It runs as root before Claude starts
# and its result is cached, so the slow part (apt, gem, npm) lives here.
#
# Default: provision dependencies, then enable the plugins on claude.ai.
# Set AGENT_HOOKS_INSTALL_MODE=manual here and in saved environment variables
# only for the alternative installer route, which appends CLAUDE.md instructions.
# Set AGENT_HOOKS_GIT_NAME and AGENT_HOOKS_GIT_EMAIL in the environment's
# variables to use your own Git identity at session startup. Setup runs before
# those variables are loaded; export them in this script too for global config.
set -euo pipefail

REPO=${AGENT_HOOKS_REPO:-https://github.com/lukas8219/agent-hooks.git}
DEST=/opt/agent-hooks   # CLAUDE.md looks here

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull -q --ff-only || true
else
  git clone -q --depth 1 "$REPO" "$DEST"
fi

"$DEST/install.sh" deps
case "${AGENT_HOOKS_INSTALL_MODE:-plugin}" in
  plugin)
    echo 'Dependencies ready. Enable git-account and any coding plugins at https://claude.ai/customize/plugins.'
    exit 0
    ;;
  manual) ;;
  *) echo 'AGENT_HOOKS_INSTALL_MODE must be plugin or manual.' >&2; exit 1 ;;
esac
"$DEST/install.sh" git-identity --user
"$DEST/install.sh" git-signing --user

mkdir -p "$HOME/.claude"
marker="<!-- agent-hooks -->"
if ! grep -qF "$marker" "$HOME/.claude/CLAUDE.md" 2>/dev/null; then
  { echo "$marker"; cat "$DEST/CLAUDE.md"; } >> "$HOME/.claude/CLAUDE.md"
fi
