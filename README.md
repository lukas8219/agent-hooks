# agent-hooks

Guards for coding agents. They work the same in any harness, because each
check runs on a neutral event and never sees the harness's own payload.

| Check | When | What it does |
|---|---|---|
| `lint-changed` | after an edit | Runs RuboCop and reports offenses on the changed lines only. Advisory. |
| `lint-changed` | before `git commit` | Denies the commit when the lines it adds have offenses. Catches `git add -A && git commit` and `commit -a`. `--no-verify` bypasses. |
| `no-new-comments` | before an edit | Denies edits that add Ruby/Python comments. Uses each language's real lexer (Ripper, tokenize). |
| `no-new-comments` | after a shell command | Blocks when uncommitted code gained comments by other means: heredoc, `sed -i`, scripts. |

## Layout

```
checks/      the logic, harness-neutral: stdin = neutral event, exit 0/2/3
lib/         common.sh (the contract, git helpers) and run.sh (event -> hook JSON)
adapters/    one per harness: payload -> neutral event -> run_check
hooks/       hooks.json: the Claude Code plugin hook file and the single source
             of truth that install.sh rewrites for each harness
skills/      skills/<name>/SKILL.md, linked into each harness's skills dir
config/      harness preferences merged on install (Claude: no commit attribution)
web/         setup.sh for Claude Code on the web environments
tests/       run.sh: end-to-end tests through both adapters
CLAUDE.md    tells a Claude Code web session to install the hooks
```

The neutral event and the exit codes are documented at the top of
`lib/common.sh`.

## Install

Dependencies: `jq`, `git`, `ruby`, `python3`, `rubocop` (and `hunk`, optional).
`./install.sh deps` installs whatever is missing.

**Claude Code, local:** pick one of these. Using both runs every hook twice.

```sh
/plugin marketplace add /path/to/agent-hooks   # then: /plugin install agent-hooks@agent-hooks
./install.sh claude --user                     # or write ~/.claude/settings.json directly
```

**Codex:**

```sh
./install.sh codex --user        # ${CODEX_HOME:-~/.codex}/hooks.json
```

Then run `/hooks` in Codex once and trust the hooks. Codex skips new or changed
hooks until you do.

**Claude Code on the web:** cloud sessions don't read `~/.claude/settings.json`.
Paste `web/setup.sh` into the environment's setup script, and set
`AGENT_HOOKS_REPO` if this repo lives somewhere other than the default. The
script clones the kit to `/opt/agent-hooks`, installs the dependencies, and
appends `CLAUDE.md` to `~/.claude/CLAUDE.md`. At session start, Claude follows
those instructions and runs `install.sh claude --project <repo>`. That writes
the hooks into the repo's own `.claude/settings.json` and keeps the file out
of git.

`./install.sh status [repo]` shows what is registered where.

## Extending

- **New check:** add `checks/<name>.sh`, which reads the neutral event and
  exits 0, 2 or 3. Then register it in `hooks/hooks.json` and add cases to
  `tests/run.sh`.
- **New harness:** add `adapters/<harness>.sh`, which maps the payload to the
  neutral event and calls `run_check`. If the harness's response JSON differs,
  give it a renderer beside `lib/run.sh`. Then add a `hooks_for` rewrite and an
  `install_<harness>` function in `install.sh`.

## Notes

- Checks fail open. A missing linter, a crashed check or a payload the adapter
  doesn't understand lets the action through.
- Codex reports edits as `apply_patch` with the raw patch in
  `tool_input.command`. The adapter turns each file section into a
  before/after pair. Some Codex builds have been reported to fire PreToolUse on
  `apply_patch` without enforcing the deny (openai/codex#27833). The post-shell
  check still catches comments on the next shell command.
- The post-shell comment check compares the whole work tree against HEAD. If
  uncommitted code already has comments, it keeps flagging them until they are
  removed or committed. Set `NO_NEW_COMMENTS_SCOPE=new-code` to flag only
  comments inside newly added code.
