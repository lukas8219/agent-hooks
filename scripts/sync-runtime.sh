#!/usr/bin/env bash
# Copies runtime/ into every plugin that has hooks. Plugins must be
# self-contained: Claude Code and Codex each copy only the plugin directory
# into their cache, and Codex drops symlinks on the way. Edit runtime/, never a
# plugin's copy, then run this. tests/run.sh fails while a copy is stale.
set -euo pipefail
KIT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
for p in "$KIT"/plugins/*/; do
  [ -f "$p/hooks/hooks.json" ] || continue
  rm -rf "$p/runtime"
  cp -R "$KIT/runtime" "$p/runtime"
  echo "synced $(basename "$p")/runtime"
done
