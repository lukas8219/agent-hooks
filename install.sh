#!/usr/bin/env bash
# Registers this kit's plugins with an agent harness without a plugin manager.
#
#   ./install.sh deps                                install jq/ruby/rubocop/hunk where missing
#   ./install.sh claude --user          [--only ...] ~/.claude/settings.json
#   ./install.sh claude --project <dir> [--only ...] <dir>/.claude/settings.json (cloud sessions)
#   ./install.sh codex  --user          [--only ...] ${CODEX_HOME:-~/.codex}/hooks.json
#   ./install.sh codex  --project <dir> [--only ...] <dir>/.codex/hooks.json
#   ./install.sh status [dir]                        show what is registered where
#   ./install.sh list                                list the plugins
#
# --only takes a comma-separated list of plugins (see `list`); default is all.
#
# Each plugins/<name>/hooks/hooks.json is the plugin's own hook file, used
# as-is by /plugin (Claude Code) and /plugins (Codex). Here those files are
# merged into the harness settings with ${CLAUDE_PLUGIN_ROOT} made absolute.
# Re-running is idempotent: every entry pointing at runtime/hook.sh is
# replaced, so moving the kit or narrowing --only is fine.
#
# Pick one route per harness, the plugin manager or this script, not both, or
# every hook runs twice.
set -euo pipefail
KIT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

die() { echo "install.sh: $*" >&2; exit 1; }
say() { printf '  %s\n' "$*"; }

need_jq() { command -v jq >/dev/null || die "jq is required (./install.sh deps)"; }

all_plugins() { for p in "$KIT"/plugins/*/; do basename "$p"; done; }

SCOPE="" DIR="" ONLY=""
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --user) SCOPE=user ;;
      --project) SCOPE=project; DIR=${2:-}; shift
                 [ -d "$DIR" ] || die "--project needs an existing directory"
                 DIR=$(cd "$DIR" && pwd) ;;
      --only) ONLY=${2:-}; shift ;;
      *) die "unknown argument: $1" ;;
    esac
    shift
  done
  [ -n "$SCOPE" ] || die "expected --user or --project <dir>"
  [ -n "$ONLY" ] || ONLY=$(all_plugins | paste -sd, -)
  local p
  for p in ${ONLY//,/ }; do [ -d "$KIT/plugins/$p" ] || die "no such plugin: $p (./install.sh list)"; done
}

# The selected plugins' hooks, one {Event: [groups]} object.
selected_hooks() {
  local p f
  for p in ${ONLY//,/ }; do
    f=$KIT/plugins/$p/hooks/hooks.json
    [ -f "$f" ] || continue
    jq --arg root "$KIT/plugins/$p" \
      '.hooks | walk(if type == "object" and has("command")
                     then .command |= gsub("\\$\\{CLAUDE_PLUGIN_ROOT\\}"; $root) else . end)' "$f"
  done | jq -s 'reduce .[] as $h ({}; reduce ($h | keys[]) as $e (.; .[$e] += $h[$e]))'
}

# Merges our hooks into a settings/hooks file, dropping earlier copies of ours.
merge_hooks() {
  local file=$1 extra=${2:-'{}'} ours tmp
  mkdir -p "$(dirname "$file")"
  [ -s "$file" ] || echo '{}' > "$file"
  ours=$(selected_hooks)
  tmp=$(mktemp)
  jq --argjson ours "$ours" --argjson extra "$extra" '
    def mine: (.command? // "") | test("/runtime/hook\\.sh|/adapters/(claude-code|codex)\\.sh");
    . * $extra
    | .hooks //= {}
    | .hooks |= with_entries(.value |= [ .[] | .hooks |= map(select(mine | not)) | select(.hooks | length > 0) ])
    | reduce ($ours | keys[]) as $ev (.; .hooks[$ev] += $ours[$ev])
    | .hooks |= with_entries(select(.value | length > 0))' "$file" > "$tmp"
  mv "$tmp" "$file"
  say "plugins ${ONLY//,/, } -> $file"
}

link_skills() {
  local dest=$1 p s name linked=false
  for s in "$dest"/*; do
    [ -L "$s" ] || continue
    case "$(readlink "$s")" in
      "$KIT"/plugins/*/skills/*) rm "$s" ;;
    esac
  done
  for p in ${ONLY//,/ }; do
    for s in "$KIT/plugins/$p/skills"/*/; do
      [ -f "$s/SKILL.md" ] || continue
      mkdir -p "$dest"
      name=$(basename "$s")
      ln -sfn "${s%/}" "$dest/$name"
      say "skill $name -> $dest/$name"
      linked=true
    done
  done
  if [ "$linked" = true ] && command -v hunk >/dev/null && [ ! -e "$dest/hunk-review/SKILL.md" ]; then
    mkdir -p "$dest/hunk-review"
    ln -sfn "$(hunk skill path)" "$dest/hunk-review/SKILL.md" && say "skill hunk-review -> $dest/hunk-review"
  fi
}

# A cloud session's work repo gets our settings in its own .claude/ - keep
# that out of the agent's commits.
keep_out_of_git() {
  local repo=$1 rel=$2
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || return 0
  [ -e "$repo/$rel" ] || return 0
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

install_claude() {
  need_jq; parse_args "$@"
  local prefs
  prefs=$(cat "$KIT/config/claude-settings.json")
  if [ "$SCOPE" = user ]; then
    merge_hooks "$HOME/.claude/settings.json" "$prefs"
    link_skills "$HOME/.claude/skills"
  else
    merge_hooks "$DIR/.claude/settings.json" "$prefs"
    keep_out_of_git "$DIR" .claude/settings.json
    link_skills "$DIR/.claude/skills"
    keep_out_of_git "$DIR" .claude/skills
  fi
}

install_codex() {
  need_jq; parse_args "$@"
  if [ "$SCOPE" = user ]; then
    merge_hooks "${CODEX_HOME:-$HOME/.codex}/hooks.json"
    link_skills "${CODEX_HOME:-$HOME/.codex}/skills"
  else
    merge_hooks "$DIR/.codex/hooks.json"
    keep_out_of_git "$DIR" .codex/hooks.json
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
           | .hooks[] | select(.command | test("/runtime/hook\\.sh"))
           | "  \($e) \($m) -> \(.command | sub(".*/plugins/"; ""))"' "$f"
  done
}

list() {
  local p
  for p in $(all_plugins); do
    printf '  %-14s %s\n' "$p" "$(jq -r .description "$KIT/plugins/$p/.claude-plugin/plugin.json")"
  done
}

cmd=${1:-}; shift || true
case "$cmd" in
  deps)   install_deps ;;
  claude) install_claude "$@" ;;
  codex)  install_codex "$@" ;;
  status) status "$@" ;;
  list)   list ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
