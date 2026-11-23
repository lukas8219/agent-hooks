#!/usr/bin/env bash
# Registers this kit's hooks (and skills) with an agent harness.
#
#   ./install.sh deps                         install jq/ruby/rubocop/hunk where missing
#   ./install.sh claude --user                ~/.claude/settings.json
#   ./install.sh claude --project <repo>      <repo>/.claude/settings.json (cloud sessions)
#   ./install.sh codex  --user                ${CODEX_HOME:-~/.codex}/hooks.json
#   ./install.sh codex  --project <repo>      <repo>/.codex/hooks.json
#   ./install.sh status                       show what is registered where
#
# hooks/hooks.json is the one source of truth: it is the Claude Code plugin's
# hook file as-is, and is rewritten here with absolute paths for settings
# files and with Codex's tool names for Codex. Re-running is idempotent: every
# entry pointing at an adapters/ script is replaced, so moving the kit is fine.
#
# Pick one route per harness: either the Claude Code plugin or `claude --user`,
# not both, or every hook runs twice.
set -euo pipefail
KIT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

die() { echo "install.sh: $*" >&2; exit 1; }
say() { printf '  %s\n' "$*"; }

need_jq() { command -v jq >/dev/null || die "jq is required (./install.sh deps)"; }

# hooks/hooks.json, re-targeted at one harness.
hooks_for() {
  local harness=$1
  jq --arg kit "$KIT" --arg harness "$harness" '
    .hooks | walk(
      if type == "object" and has("command") then
        .command |= (gsub("\\$\\{CLAUDE_PLUGIN_ROOT\\}"; $kit)
                     | if $harness == "codex" then sub("claude-code.sh"; "codex.sh") else . end)
      elif type == "object" and has("matcher") and $harness == "codex" then
        .matcher |= (if . == "Write|Edit|MultiEdit" then "apply_patch" else . end)
      else . end)' "$KIT/hooks/hooks.json"
}

# Merges our hooks into a settings/hooks file, dropping earlier copies of ours.
merge_hooks() {
  local file=$1 harness=$2 extra=${3:-'{}'} ours tmp
  mkdir -p "$(dirname "$file")"
  [ -s "$file" ] || echo '{}' > "$file"
  ours=$(hooks_for "$harness")
  tmp=$(mktemp)
  jq --argjson ours "$ours" --argjson extra "$extra" '
    def mine: (.command? // "") | test("/adapters/(claude-code|codex)\\.sh");
    . * $extra
    | .hooks //= {}
    | reduce ($ours | keys[]) as $ev (.;
        .hooks[$ev] = (
          [ (.hooks[$ev] // [])[] | .hooks |= map(select(mine | not)) | select(.hooks | length > 0) ]
          + $ours[$ev]))' "$file" > "$tmp"
  mv "$tmp" "$file"
  say "hooks -> $file"
}

link_skills() {
  local dest=$1 s name
  mkdir -p "$dest"
  for s in "$KIT"/skills/*/; do
    [ -f "$s/SKILL.md" ] || continue
    name=$(basename "$s")
    ln -sfn "${s%/}" "$dest/$name"
    say "skill $name -> $dest/$name"
  done
  if command -v hunk >/dev/null && [ ! -e "$dest/hunk-review/SKILL.md" ]; then
    mkdir -p "$dest/hunk-review"
    ln -sfn "$(hunk skill path)" "$dest/hunk-review/SKILL.md" && say "skill hunk-review -> $dest/hunk-review"
  fi
}

# A cloud session's work repo gets our settings in its own .claude/ - keep
# that out of the agent's commits.
keep_out_of_git() {
  local repo=$1 rel=$2
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  if git -C "$repo" ls-files --error-unmatch "$rel" >/dev/null 2>&1; then
    git -C "$repo" update-index --skip-worktree "$rel"
    say "$rel is tracked: marked skip-worktree so our edits stay out of commits"
    say "  undo with: git -C $repo update-index --no-skip-worktree $rel && git -C $repo checkout $rel"
  else
    local ex
    ex="$(git -C "$repo" rev-parse --git-path info/exclude)"
    case "$ex" in /*) ;; *) ex="$repo/$ex" ;; esac
    mkdir -p "$(dirname "$ex")"
    grep -qxF "/$rel" "$ex" 2>/dev/null || echo "/$rel" >> "$ex"
    say "$rel added to $(basename "$ex") (untracked, ignored locally)"
  fi
}

target() {
  case "${1:-}" in
    --user) echo user ;;
    --project) [ -d "${2:-}" ] || die "--project needs an existing directory"; echo project ;;
    *) die "expected --user or --project <dir>" ;;
  esac
}

install_claude() {
  need_jq
  local scope repo file prefs
  scope=$(target "$@")
  prefs=$(cat "$KIT/config/claude-settings.json")
  if [ "$scope" = user ]; then
    merge_hooks "$HOME/.claude/settings.json" claude "$prefs"
    link_skills "$HOME/.claude/skills"
  else
    repo=$(cd "$2" && pwd)
    file=$repo/.claude/settings.json
    merge_hooks "$file" claude "$prefs"
    keep_out_of_git "$repo" .claude/settings.json
    link_skills "$repo/.claude/skills"
    keep_out_of_git "$repo" .claude/skills
  fi
}

install_codex() {
  need_jq
  local scope repo
  scope=$(target "$@")
  if [ "$scope" = user ]; then
    merge_hooks "${CODEX_HOME:-$HOME/.codex}/hooks.json" codex
    link_skills "${CODEX_HOME:-$HOME/.codex}/skills"
  else
    repo=$(cd "$2" && pwd)
    merge_hooks "$repo/.codex/hooks.json" codex
    keep_out_of_git "$repo" .codex/hooks.json
  fi
  say "Codex skips new or changed hooks until you trust them: run /hooks in Codex once."
}

install_deps() {
  local sudo=""
  [ "$(id -u)" = 0 ] || { command -v sudo >/dev/null && sudo="sudo"; }
  local missing=()
  for c in jq git ruby python3; do command -v "$c" >/dev/null || missing+=("$c"); done
  if [ ${#missing[@]} -gt 0 ]; then
    if command -v apt-get >/dev/null; then
      local pkgs=()
      for c in "${missing[@]}"; do
        case "$c" in ruby) pkgs+=(ruby-full build-essential) ;; *) pkgs+=("$c") ;; esac
      done
      $sudo apt-get update -qq && DEBIAN_FRONTEND=noninteractive $sudo apt-get install -y -q --no-install-recommends "${pkgs[@]}"
    elif command -v brew >/dev/null; then
      brew install "${missing[@]}"
    else
      die "install these yourself: ${missing[*]}"
    fi
  fi
  command -v rubocop >/dev/null || gem install rubocop --no-document || $sudo gem install rubocop --no-document
  if ! command -v hunk >/dev/null && command -v npm >/dev/null; then
    npm install -g hunkdiff || $sudo npm install -g hunkdiff || say "hunk not installed (optional)"
  fi
  for c in jq git ruby python3 rubocop hunk; do
    command -v "$c" >/dev/null && say "ok   $c" || say "MISSING $c"
  done
}

status() {
  local f
  for f in "$HOME/.claude/settings.json" "${CODEX_HOME:-$HOME/.codex}/hooks.json" "${1:-.}/.claude/settings.json" "${1:-.}/.codex/hooks.json"; do
    [ -r "$f" ] || continue
    echo "$f"
    jq -r '.hooks // {} | to_entries[] | .key as $e | .value[] | .matcher as $m
           | .hooks[] | select(.command | test("/adapters/")) | "  \($e) \($m) -> \(.command)"' "$f"
  done
}

cmd=${1:-}; shift || true
case "$cmd" in
  deps)   install_deps ;;
  claude) install_claude "$@" ;;
  codex)  install_codex "$@" ;;
  status) status "$@" ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
