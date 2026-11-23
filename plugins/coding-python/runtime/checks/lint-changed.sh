#!/usr/bin/env bash
# lint-changed: RuboCop, reported only for lines the agent changed.
#
#   post + edit    lints each edited Ruby file against HEAD. Advisory.
#   pre  + shell   when the line runs `git commit`, lints what the commit will
#                  contain and refuses it on offenses. `--no-verify` bypasses,
#                  as in git.
#
# A project .rubocop.yml is inherited as-is; Metrics/CyclomaticComplexity and
# Metrics/PerceivedComplexity are switched on over it.
#
# Speaks the neutral contract in lib/common.sh.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib/common.sh"

EVENT=$(cat)
phase=$(ev .phase); kind=$(ev .kind); cwd=$(ev .cwd)
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null

build_config() {
  local root=$1 file=$2 cfg=$3 d project_cfg=""
  d=$(dirname "$file")
  while [ "$d" != "/" ]; do
    [ -f "$d/.rubocop.yml" ] && { project_cfg=$d/.rubocop.yml; break; }
    [ "$d" = "$root" ] && break
    d=$(dirname "$d")
  done
  {
    [ -n "$project_cfg" ] && printf 'inherit_from: %s\n' "$project_cfg"
    cat <<'YAML'
Metrics/CyclomaticComplexity:
  Enabled: true
Metrics/PerceivedComplexity:
  Enabled: true
YAML
  } > "$cfg"
}

# "  line:col [Cop] message" for each offense touching a changed range.
offenses_on() {
  local root=$1 file=$2 ranges=$3 tmp out runner
  ranges=$(printf '%s\n' "$ranges" |
    jq -Rn '[inputs | select(length > 0) | split(" ") | {s: (.[0]|tonumber), e: (.[1]|tonumber)}]')

  tmp=$(mktemp -d)
  build_config "$root" "$file" "$tmp/rubocop.yml"
  runner=(rubocop)
  [ -f "$root/Gemfile" ] && grep -q rubocop "$root/Gemfile" 2>/dev/null && runner=(bundle exec rubocop)
  out=$(cd "$root" && "${runner[@]}" --config "$tmp/rubocop.yml" --format json --force-exclusion "$file" 2>/dev/null)
  rm -rf "$tmp"

  printf '%s' "$out" | jq -e . >/dev/null 2>&1 || return 0
  # `. as $o` matters: inside any(), `.` is the range, not the offense.
  printf '%s' "$out" | jq -r --argjson r "$ranges" '
    [ .files[].offenses[] | . as $o
      | select(any($r[]; .s <= $o.location.last_line and .e >= $o.location.start_line)) ]
    | .[] | "  \(.location.line):\(.location.column) [\(.cop_name)] \(.message)"'
}

# stdin: absolute or root-relative paths. stdout: "rel:\n  offenses" blocks.
report_for() {
  local root=$1 base=$2 path file ranges hits
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in /*) file=$path ;; *) file=$root/$path ;; esac
    is_ruby "$file" && [ -f "$file" ] || continue
    ranges=$(changed_ranges "$root" "$file" "$base")
    [ -n "$ranges" ] || continue
    hits=$(offenses_on "$root" "$file" "$ranges")
    [ -n "$hits" ] && printf '%s:\n%s\n' "${file#"$root"/}" "$hits"
  done
}

NOTE="Only changed lines are reported. The project .rubocop.yml is inherited; Metrics/CyclomaticComplexity and Metrics/PerceivedComplexity are added on top."

if [ "$phase" = pre ] && [ "$kind" = shell ]; then
  cmd=$(ev .command)
  is_commit_command "$cmd" || exit $EXIT_OK
  printf '%s' "$cmd" | grep -q -- '--no-verify' && exit $EXIT_OK
  command -v rubocop >/dev/null || exit $EXIT_OK   # never block a commit over a missing linter
  root=$(git rev-parse --show-toplevel 2>/dev/null) || exit $EXIT_OK

  if commit_stages_worktree "$cmd"; then
    base=worktree
    files=$({ git diff --name-only HEAD; git ls-files --others --exclude-standard; } | sort -u)
  else
    base=index
    files=$(git diff --cached --name-only --diff-filter=ACM)
  fi
  report=$(printf '%s\n' "$files" | report_for "$root" "$base")
  [ -n "$report" ] || exit $EXIT_OK
  printf 'RuboCop offenses on lines this commit adds - fix them before committing:\n\n%s\n\n%s\n' "$report" "$NOTE"
  exit $EXIT_VIOLATION
fi

if [ "$phase" = post ] && [ "$kind" = edit ]; then
  command -v rubocop >/dev/null || exit $EXIT_OK
  report=""
  while IFS= read -r file; do
    [ -f "$file" ] && is_ruby "$file" || continue
    root=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) || continue
    r=$(printf '%s\n' "$file" | report_for "$root" head)
    [ -n "$r" ] && report+="$r"$'\n'
  done < <(printf '%s' "$EVENT" | jq -r '[.edits[]?.path] | unique | .[]')
  [ -n "$report" ] || exit $EXIT_OK
  printf 'lint-changed: RuboCop offenses on lines you changed:\n%s\n(%s)\n' "$report" "$NOTE"
  exit $EXIT_ADVISORY
fi

exit $EXIT_OK
