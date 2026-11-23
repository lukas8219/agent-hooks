# agent-hooks: install the hooks before you start work

This file sets up the agent-hooks plugins: `coding-ruby` (RuboCop on the lines
you change, a RuboCop gate on `git commit`, no new comments), `coding-python`
(no new comments) and `skills`. It is
read either from the kit's own repo or from `~/.claude/CLAUDE.md`, where
`web/setup.sh` puts it in Claude Code on the web.

## When to act

Do this once, at the start of the session, **before any other work**, when
`CLAUDE_CODE_REMOTE` is `true` (Claude Code on the web). Check with
`echo "$CLAUDE_CODE_REMOTE"`. On a local machine, do nothing: there the kit is
installed with `/plugin` or with `install.sh claude --user`, and running it again
here would register every hook twice.

## Steps

1. Find the kit, `KIT`: `/opt/agent-hooks` if it exists, otherwise the
   repository that contains this file.
2. Make sure the tools exist. This is a no-op when the setup script already
   ran: `"$KIT/install.sh" deps`
3. Register the hooks in every repository you will edit this session. Start
   with the session's repo, `$CLAUDE_PROJECT_DIR`, or the current directory if
   that is unset:
   `"$KIT/install.sh" claude --project "$CLAUDE_PROJECT_DIR"`
   That installs every plugin (`"$KIT/install.sh" list`). If the user named
   only some, pass them, as in `--only coding-ruby,skills`.
   Cloud sessions don't read `~/.claude/settings.json`, so the hooks must go in
   the repo's `.claude/settings.json`. The installer keeps that file out of
   git: it adds it to `.git/info/exclude` when the repo doesn't track it, and
   marks it `skip-worktree` when the repo does. Don't undo either, and never
   commit `.claude/settings.json` changes that point at `/opt/agent-hooks`.
4. Confirm: `"$KIT/install.sh" status "$CLAUDE_PROJECT_DIR"` should list the
   hooks of each installed plugin. Then check that they are live: use the Write tool to create
   `.agent-hooks-probe.rb` in the repo root with the content `# probe`. Use
   `.py` instead if only `coding-python` is installed. The
   write must be refused. If it goes through, delete the file and tell the
   user that the hooks start working in the next session, because the settings
   file watcher didn't reload them. Don't loop on this.
5. Give the user one line: the hooks are installed, and for which repos.

If a step fails, report the error and carry on with the user's task. A missing
hook must never block the work.

## What the hooks will do to you

- **Edit/Write adding a comment** to Ruby or Python is denied. Re-send the edit
  without the comment, and make the code explain itself instead. Shebangs,
  magic comments (`# frozen_string_literal`) and linter directives
  (`# rubocop:disable`) are allowed.
- **A Bash command that leaves added comments** in uncommitted Ruby/Python
  (heredoc, `sed -i`, a script) gets a block message after it runs. Remove
  those comments.
- **After an edit to a Ruby file**, RuboCop offenses on the changed lines come
  back as context. Fix them when they are yours.
- **`git commit`** is denied when the lines it adds have RuboCop offenses. Fix
  the offenses. Don't reach for `--no-verify` unless the user asks for it.
