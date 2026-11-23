# agent-hooks

Plugins of guards and skills for coding agents. Install only the ones you
want. They work the same in Claude Code and Codex, because every check runs
on a neutral event and never sees the harness's own payload.

| Plugin | Hook | What it does |
|---|---|---|
| `coding-ruby` | after an edit | RuboCop on the changed lines only. Advisory. |
| | before `git commit` | Denies the commit when the lines it adds have offenses. Catches `git add -A && git commit` and `commit -a`. `--no-verify` bypasses. |
| | before an edit / after a shell command | No new comments in Ruby, found by Ripper rather than a regex. |
| `coding-python` | before an edit / after a shell command | No new comments in Python, found by `tokenize`. |
| `skills` | | Shared skills (`plugins/skills/skills/<name>/SKILL.md`). |

## Layout

```
runtime/                     the one source of the hook code
  hook.sh                    entry point: hook.sh <check> [--lang ruby,python]
  checks/                    the logic, harness-neutral: stdin = neutral event, exit 0/2/3
  lib/                       common.sh (the contract, git helpers), render.sh (-> hook JSON)
plugins/<name>/
  .claude-plugin/plugin.json Claude Code manifest
  plugin.json                Codex manifest
  hooks/hooks.json           the plugin's hooks, shared by both harnesses
  runtime/                   copy of runtime/, made by scripts/sync-runtime.sh
.claude-plugin/marketplace.json   Claude Code marketplace
.agents/plugins/marketplace.json  Codex marketplace
install.sh                   hooks without a plugin manager (and the web setup)
web/setup.sh                 setup script for Claude Code on the web
CLAUDE.md                    tells a Claude Code web session to install the hooks
tests/run.sh                 end-to-end tests
```

Each plugin carries its own copy of `runtime/`, because both harnesses copy
only the plugin directory into their cache, and Codex drops symlinks on the
way. Edit `runtime/` and run `scripts/sync-runtime.sh`. `tests/run.sh` fails
while any copy is stale.

## Install

Dependencies: `jq`, `git`, `ruby`, `python3`, `rubocop` (and `hunk`, optional).
`./install.sh deps` installs whatever is missing.

**Claude Code:**

```sh
/plugin marketplace add lukas8219/agent-hooks
/plugin install coding-ruby@agent-hooks     # and/or coding-python, skills
```

**Codex:**

```sh
codex plugin marketplace add lukas8219/agent-hooks
codex plugin add coding-ruby@agent-hooks    # or pick in /plugins
```

Then open `/hooks` in Codex once and trust the hooks. Installing a plugin
doesn't trust its hooks.

**Without a plugin manager:** `./install.sh claude|codex --user [--only
coding-ruby,skills]` writes the hooks into the harness settings. Use the
plugin manager or the script, not both, or every hook runs twice.
`./install.sh list` shows the plugins, and `./install.sh status [repo]` shows
what is registered where.

**Claude Code on the web:** cloud sessions don't read
`~/.claude/settings.json` or user plugins. Paste `web/setup.sh` into the
environment's setup script. It clones the kit to `/opt/agent-hooks`, installs
the dependencies, and appends `CLAUDE.md` to `~/.claude/CLAUDE.md`. At session
start, Claude follows those instructions and runs `install.sh claude --project
<repo>`. That writes the hooks into the repo's own `.claude/settings.json` and
keeps the file out of git.

## Extending

- **New check:** add `runtime/checks/<name>.sh`, which reads the neutral event
  (documented at the top of `runtime/lib/common.sh`) and exits 0, 2 or 3.
  Wire it into a plugin's `hooks/hooks.json`, run
  `scripts/sync-runtime.sh`, and add cases to `tests/run.sh`.
- **New language:** add it to `lang_for` (and to `extract` for comments), then
  add a `plugins/coding-<language>/` that passes `--lang <language>`.
- **New harness:** teach `normalize` in `runtime/hook.sh` its tool names. If
  its response JSON differs, add a renderer beside `runtime/lib/render.sh`.

## Notes

- Checks fail open. A missing linter, a crashed check or an unknown payload
  lets the action through.
- Codex reports edits as `apply_patch` with the raw patch. `hook.sh` turns each
  file section into a before/after pair. Some Codex builds have been reported
  to fire PreToolUse on `apply_patch` without enforcing the deny
  (openai/codex#27833). The post-shell check still catches comments on the
  next shell command.
- The post-shell comment check compares the work tree against HEAD. If
  uncommitted code already has comments, it keeps flagging them until they are
  removed or committed. Set `NO_NEW_COMMENTS_SCOPE=new-code` to flag only
  comments inside newly added code.
