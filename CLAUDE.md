# agent-hooks: prefer installed plugins

The preferred setup enables the `git-account` plugin and the selected coding
plugins. Its `SessionStart` hook configures Git identity and optional signing
automatically. Do not run the manual installer when using installed plugins.
The instructions below apply only when the user explicitly chose the alternative
installer route by setting `AGENT_HOOKS_INSTALL_MODE=manual`.

This file sets up the agent-hooks plugins: `coding-ruby` (RuboCop on the lines
you change, a RuboCop gate on `git commit`, no new comments), `coding-python`
(no new comments), `coding-crystal` (Ameba on changed lines, an Ameba commit
gate, no new comments) and `feature-graph` (the `/feature-graph` and `/verify-changed`
skills). It is
read either from the kit's own repo or from `~/.claude/CLAUDE.md`, where
`web/setup.sh` puts it in Claude Code on the web.

## When to act

Do this once, at the start of the session, **before any other work**, when
`CLAUDE_CODE_REMOTE` is `true` and `AGENT_HOOKS_INSTALL_MODE` is `manual`
(the alternative Claude Code web installer route). Check with
`echo "$CLAUDE_CODE_REMOTE"`. On a local machine, do nothing: there the kit is
installed with `/plugin` or with `install.sh claude --user`, and running it again
here would register every hook twice.

## Steps

1. Find the kit, `KIT`: `/opt/agent-hooks` if it exists, otherwise the
   repository that contains this file.
2. Make sure the tools exist. This is a no-op when the setup script already
   ran: `"$KIT/install.sh" deps`. Crystal hooks additionally need `crystal`
   and `ameba` (or a project's `bin/ameba`); see `README.md` for installation.
3. Register the hooks in every repository you will edit this session. Start
   with the session's repo, `$CLAUDE_PROJECT_DIR`, or the current directory if
   that is unset:
   `"$KIT/install.sh" claude --project "$CLAUDE_PROJECT_DIR"`
   That installs every plugin (`"$KIT/install.sh" list`). If the user named
   only some, pass them, as in `--only coding-ruby,feature-graph`.
   Cloud sessions don't read `~/.claude/settings.json`, so the hooks must go in
   the repo's `.claude/settings.json`. The installer keeps that file out of
   git: it adds it to `.git/info/exclude` when the repo doesn't track it, and
   marks it `skip-worktree` when the repo does. Don't undo either, and never
   commit `.claude/settings.json` changes that point at `/opt/agent-hooks`.
   When `AGENT_HOOKS_GIT_NAME` and `AGENT_HOOKS_GIT_EMAIL` are set, this also
   configures the repo's Git author and committer and the four `GIT_AUTHOR_*`
   / `GIT_COMMITTER_*` variables in Claude's settings. Never infer an identity
   from the repository owner or its last commit.
   When the `AGENT_HOOKS_SIGN_*` variables are supplied, this also configures
   remote commit signing. It needs the provisioned bridge client, public key,
   HTTPS origin, and a protected token file or explicit proxy authorization.
   See `README.md` for the complete variables. Do not print tokens or put them
   in settings, command arguments, or commits.
4. Confirm: `"$KIT/install.sh" status "$CLAUDE_PROJECT_DIR"` should list the
   hooks of each installed plugin and the effective Git author and committer.
   Run it in a new Bash tool call so updated settings can take effect. If
   an identity was requested, verify both match it. If they do not, report
   the mismatch and have the user set the four `GIT_AUTHOR_*` / `GIT_COMMITTER_*`
   environment variables to their name and email in the web environment and
   restart. If neither `AGENT_HOOKS_GIT_*` variable is set, report that Git
   identity was not configured and name the two variables needed to opt in.
   If signing was requested, confirm that status reports it enabled with the
   remote bridge. Status checks configuration only; it does not prove the
   service is reachable or authorization is still valid.
   Then check that the hooks are live: use the Write tool to create
   `.agent-hooks-probe.rb` in the repo root with the content `# probe`. Use
   `.py` instead if only `coding-python` is installed, or `.cr` for
   `coding-crystal`. The
   write must be refused. If it goes through, delete the file and tell the
   user that the hooks start working in the next session, because the settings
   file watcher didn't reload them. Don't loop on this.
5. Give the user one line: the hooks are installed, and for which repos.

If a step fails, report the error and carry on with the user's task. A missing
hook must never block the work. If requested signing could not be configured,
continue other work but do not commit until signing is configured. If a commit
fails because authorization expired, ask the user to create a new session on
their trusted host and update the protected token or proxy secret. Rerun setup
when the hostname or paths change. Never disable signing, use `--no-gpg-sign`,
export the private key, or silently retry unsigned to work around a failure.

## What the hooks will do to you

- **Edit/Write adding a comment** to Ruby, Python or Crystal is denied. Re-send the edit
  without the comment, and make the code explain itself instead. Shebangs,
  magic comments (`# frozen_string_literal`) and linter directives
  (`# rubocop:disable`, `# ameba:disable`) are allowed, as are Crystal formatter directives.
- **A Bash command that leaves added comments** in uncommitted Ruby/Python/Crystal
  (heredoc, `sed -i`, a script) gets a block message after it runs. Remove
  those comments.
- **After an edit to a Ruby file**, RuboCop offenses on the changed lines come
  back as context. Fix them when they are yours.
- **After an edit to a Crystal file**, Ameba issues on the changed lines come
  back as context. Fix them when they are yours.
- **`git commit`** is denied when the lines it adds have RuboCop or Ameba offenses. Fix
  the offenses. Don't reach for `--no-verify` unless the user asks for it.
