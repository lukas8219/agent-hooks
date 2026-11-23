# Shared by the checks. Sourced, never executed.
#
# The neutral contract every check speaks, so no check ever sees a harness's
# own payload:
#
#   stdin   one normalized event (built by hook.sh from the harness payload):
#             {
#               "phase":   "pre" | "post",
#               "kind":    "shell" | "edit",
#               "cwd":     "/abs/dir",
#               "command": "git commit -m x",                       (shell)
#               "edits":   [{"path": "/abs/f.rb",                    (edit)
#                            "before": "old text", "after": "new text"}]
#             }
#   stdout  a report; its first line is a one-line summary
#   exit    0  nothing to say
#           2  violation: denied (pre) or blocked (post)
#           3  advisory: the report goes to the agent as context
#           *  the check itself failed: the action is let through

EXIT_OK=0
EXIT_VIOLATION=2
EXIT_ADVISORY=3

ev() { printf '%s' "$EVENT" | jq -r "$1 // empty"; }

# The file's language, or nothing when the file is not ours to check: an
# unknown language, or one left out of AGENT_HOOKS_LANGS (comma-separated,
# set by hook.sh --lang; unset means every language).
lang_for() {
  local lang
  case "$1" in
    *.rb|*.rake|*.gemspec|*/Gemfile|*/Rakefile) lang=ruby ;;
    *.py) lang=python ;;
    *.cr) lang=crystal ;;
    *) return 0 ;;
  esac
  case ",${AGENT_HOOKS_LANGS:-$lang}," in *",$lang,"*) echo "$lang" ;; esac
}

is_ruby() { [ "$(lang_for "$1")" = ruby ]; }

# A `git commit` anywhere in a shell line, including `git add -A && git commit`
# and `git -C dir commit`.
is_commit_command() {
  printf '%s' "$1" | grep -Eq '(^|[;&|(]|[[:space:]])git[[:space:]][^;&|]*commit([[:space:]]|$|[;&|)])'
}

# Whether that commit also stages work the index doesn't hold yet: an earlier
# `git add` in the same line, or `commit -a`. At PreToolUse time neither has
# run, so the index alone would miss those changes.
commit_stages_worktree() {
  printf '%s' "$1" | grep -Eq 'git[^;&|]*[[:space:]]add([[:space:]]|$)|commit[^;&|]*[[:space:]](-[a-zA-Z]*a[a-zA-Z]*|--all)([[:space:]]|$)'
}

# stdin: unified diff with -U0. stdout: "start end" per added range.
added_ranges() {
  awk '/^@@/ {
         s = $3; sub(/^\+/, "", s)
         if (index(s, ",")) { split(s, a, ","); st = a[1]; n = a[2] } else { st = s; n = 1 }
         if (n > 0) print st, st + n - 1
       }'
}

# Lines of FILE that differ from BASE ("head", "index" or "worktree", which
# means HEAD plus whatever is unstaged). Untracked files count as all-new.
changed_ranges() {
  local root=$1 file=$2 base=$3
  if ! git -C "$root" ls-files --error-unmatch "$file" >/dev/null 2>&1 && [ "$base" != index ]; then
    echo "1 $(wc -l < "$file" | tr -d ' ')"
    return
  fi
  case "$base" in
    index) git -C "$root" diff --no-color --no-ext-diff --cached -U0 -- "$file" ;;
    *)     git -C "$root" diff --no-color --no-ext-diff -U0 HEAD -- "$file" ;;
  esac | added_ranges
}

# "start end" ranges -> one line number per line.
expand_ranges() { awk '{ for (i = $1; i <= $2; i++) print i }'; }
