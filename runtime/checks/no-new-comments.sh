#!/usr/bin/env bash
# no-new-comments: refuses comments the agent adds to code.
#
#   pre  + edit    compares comments in each edit's before/after text and
#                  refuses the edit if it adds any.
#   post + shell   catches comments written any other way (heredoc, sed -i, a
#                  script) by diffing the work tree against HEAD.
#
# Comments come from each language's own lexer (Ruby's Ripper, Python's
# tokenize), never a regex, so a `#` in a string, URL or heredoc is not one.
# Languages without an exact lexer are skipped rather than guessed at.
#
# NO_NEW_COMMENTS_SCOPE:
#   all       (default) any comment the change adds
#   new-code  only comments inside a run of newly added code, so annotating
#             pre-existing code is left alone (post + shell only)
#
# Speaks the neutral contract in lib/common.sh.
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$here/../lib/common.sh"

SCOPE=${NO_NEW_COMMENTS_SCOPE:-all}
ALLOWED="Shebangs, magic/encoding comments and linter directives are allowed."

EVENT=$(cat)
phase=$(ev .phase); kind=$(ev .kind); cwd=$(ev .cwd)
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null

# stdin: source. stdout: "LINE<TAB>TEXT" per comment, functional ones dropped.
extract() {
  case "$1" in
    ruby)
      command -v ruby >/dev/null || return 0
      ruby -rripper -e '
        begin
          Ripper.lex(STDIN.read).each do |(line, _col), type, tok|
            next unless %i[on_comment on_embdoc].include?(type)
            t = tok.strip
            next if t.empty? || t.start_with?("#!")
            next if t =~ /\A#\s*(frozen_string_literal|encoding|coding|warn_indent|shareable_constant_value)\b/
            next if t =~ /\A#\s*-\*-/ || t =~ /\A#\s*rubocop:/
            puts "#{line}\t#{t}"
          end
        rescue StandardError
        end' 2>/dev/null
      ;;
    python)
      command -v python3 >/dev/null || return 0
      python3 -I -c '
import io, re, sys, tokenize
src = sys.stdin.buffer.read()
skip = re.compile(r"^#\s*(!|-\*-|coding[:=]|type:|noqa|pylint:|mypy:|fmt:\s*(on|off)|pragma:)")
try:
    for tok in tokenize.tokenize(io.BytesIO(src).readline):
        if tok.type == tokenize.COMMENT:
            t = tok.string.strip()
            if t and not skip.match(t):
                print(f"{tok.start[0]}\t{t}")
except Exception:
    pass' 2>/dev/null
      ;;
  esac
}

if [ "$phase" = pre ] && [ "$kind" = edit ]; then
  report=""
  a=$(mktemp); b=$(mktemp); trap 'rm -f "$a" "$b"' EXIT
  n=$(printf '%s' "$EVENT" | jq '.edits | length')
  for ((i = 0; i < n; i++)); do
    path=$(ev ".edits[$i].path")
    lang=$(lang_for "$path"); [ -n "$lang" ] || continue
    ev ".edits[$i].after"  | extract "$lang" | cut -f2- | sort > "$a"
    ev ".edits[$i].before" | extract "$lang" | cut -f2- | sort > "$b"
    added=$(comm -23 "$a" "$b")
    [ -n "$added" ] && report+="$(basename "$path"):"$'\n'"$(printf '%s\n' "$added" | sed 's/^/  /')"$'\n'
  done
  [ -n "$report" ] || exit $EXIT_OK
  printf 'This edit adds new comments:\n%s\nWrite the code so it explains itself instead - clearer names, smaller methods. Re-send the edit without these comments. (%s)\n' "$report" "$ALLOWED"
  exit $EXIT_VIOLATION
fi

if [ "$phase" = post ] && [ "$kind" = shell ]; then
  cmd=$(ev .command)
  printf '%s' "$cmd" | grep -Eq '>|tee|sed|awk|perl|python|ruby|cat|printf|echo|patch|tr|cp|mv|git' || exit $EXIT_OK
  root=$(git rev-parse --show-toplevel 2>/dev/null) || exit $EXIT_OK

  report=""
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    file=$root/$rel
    [ -f "$file" ] || continue
    lang=$(lang_for "$file"); [ -n "$lang" ] || continue
    added=$(changed_ranges "$root" "$file" head | expand_ranges)
    [ -n "$added" ] || continue
    cmts=$(extract "$lang" < "$file")
    [ -n "$cmts" ] || continue

    hits=$(awk -v scope="$SCOPE" -v rel="$rel" '
      NR == FNR { add[$1] = 1; next }
      { split($0, p, "\t"); iscmt[p[1]] = 1; text[p[1]] = p[2] }
      END {
        for (l in text) {
          if (!(l in add)) continue
          if (scope == "new-code") {
            # keep it only if its run of added lines also holds added code
            has_code = 0
            for (i = l; (i in add); i--) if (!(i in iscmt)) { has_code = 1; break }
            for (i = l; (i in add); i++) if (!(i in iscmt)) { has_code = 1; break }
            if (!has_code) continue
          }
          printf "  %s:%s  %s\n", rel, l, text[l]
        }
      }' <(printf '%s\n' "$added") <(printf '%s\n' "$cmts") | sort -t: -k2 -n)
    [ -n "$hits" ] && report+="$hits"$'\n'
  done < <({ git -C "$root" diff --name-only HEAD; git -C "$root" ls-files --others --exclude-standard; } | sort -u)

  [ -n "$report" ] || exit $EXIT_OK
  printf 'Uncommitted code now contains added comments:\n\n%s\nRemove them - the code should read clearly without them. (%s)\n' "$report" "$ALLOWED"
  exit $EXIT_VIOLATION
fi

exit $EXIT_OK
