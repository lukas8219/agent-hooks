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
| `feature-graph` | | Includes `/feature-graph` to build the cross-repo graph in Neo4j and `/verify-changed` to plan verification and run local tests for a diff. |

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
  skills/<skill>/SKILL.md     related skills and their supporting files
.claude-plugin/marketplace.json   Claude Code marketplace
.agents/plugins/marketplace.json  Codex marketplace
install.sh                   hooks without a plugin manager (and the web setup)
web/setup.sh                 setup script for Claude Code on the web
CLAUDE.md                    tells a Claude Code web session to install the hooks
tests/run.sh                 end-to-end tests
```

Each hook plugin carries its own copy of `runtime/`, because both harnesses copy
only the plugin directory into their cache, and Codex drops symlinks on the
way. Edit `runtime/` and run `scripts/sync-runtime.sh`. `tests/run.sh` fails
while any copy is stale.

## Install

Dependencies: `jq`, `git`, `ruby`, `python3`, `rubocop` (and `hunk`, optional).
`./install.sh deps` installs whatever is missing.

**Claude Code:**

```sh
/plugin marketplace add lukas8219/agent-hooks
/plugin install coding-ruby@agent-hooks     # and/or coding-python
/plugin install feature-graph@agent-hooks
```

**Codex:**

```sh
codex plugin marketplace add lukas8219/agent-hooks
codex plugin add coding-ruby@agent-hooks    # or pick in /plugins
codex plugin add feature-graph@agent-hooks
```

For hook plugins, open `/hooks` in Codex once and trust the hooks. Installing
a plugin doesn't trust its hooks. Installing `feature-graph` includes both skills.

The former `skills` plugin is now named `feature-graph`. If you installed it
through a plugin manager, uninstall `skills` and install `feature-graph`.

**Without a plugin manager:** `./install.sh claude|codex --user [--only
coding-ruby,feature-graph]` writes the hooks into the harness
settings and links the selected skills. Rerunning updates existing skill links
and removes this checkout's links for unselected plugins. Use the
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
- **New skill:** add `plugins/<plugin>/skills/<skill>/SKILL.md` to the plugin
  that owns its workflow. For a new plugin, add both manifests and an entry
  in each marketplace. Keep supporting files inside the plugin.
- **New harness:** teach `normalize` in `runtime/hook.sh` its tool names. If
  its response JSON differs, add a renderer beside `runtime/lib/render.sh`.

## Feature graph skills

`/feature-graph` maps the repo it runs in into a Neo4j knowledge graph:
features, the files they touch, how to verify them, and the interfaces (HTTP
routes, AMQP exchanges, shared tables, gems) the repo exposes or consumes. Run
it once in each repo. Repos link up through shared interfaces: a route that
account-console exposes and customer-console calls becomes one `Interface`
node with an edge from each side. `/verify-changed` reads that graph for the
branch's diff, prints a verification plan that includes other repos to test
or change, and runs the local tests. It never writes to the graph.

Both skills belong to the `feature-graph` plugin and share
`plugins/feature-graph/skills/feature-graph/scripts/graph.py`, a stdlib-only
client for the Neo4j Query API. The model and payload are in
`plugins/feature-graph/skills/feature-graph/references/schema.md`.

| Env var | |
|---|---|
| `NEO4J_URI` | `neo4j+s://…` (Aura), `neo4j://host:7687` or `http(s)://host:port` |
| `NEO4J_USERNAME`, `NEO4J_PASSWORD` | used by `/feature-graph` |
| `NEO4J_READ_USERNAME`, `NEO4J_READ_PASSWORD` | optional read-only user for `/verify-changed` |
| `NEO4J_DATABASE` | default `neo4j` |

In Claude Code on the web, set these in the environment's variables. With
`NEO4J_URI` set, `tests/run.sh` also runs a round trip against the database
(it creates and then deletes `test-fg/*` nodes).

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
