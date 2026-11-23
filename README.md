# agent-hooks

Plugins of guards and skills for coding agents. Install only the ones you
want. They work the same in Claude Code and Codex, because every check runs
on a neutral event and never sees the harness's own payload.

| Plugin | Hook | What it does |
|---|---|---|
| `coding-ruby` | after an edit | RuboCop on the changed lines only. Advisory. |
| | before `git commit` | Denies the commit when the lines it adds have offenses. Catches `git add -A && git commit` and `commit -a`. `--no-verify` bypasses. |
| | before an edit / after a shell command | No new comments in Ruby, found by Ripper rather than a regex. |
| `coding-crystal` | after an edit | Ameba on the changed lines only. Advisory. |
| | before `git commit` | Denies the commit when the lines it adds have Ameba issues. Catches `git add -A && git commit` and `commit -a`. `--no-verify` bypasses. |
| | before an edit / after a shell command | No new comments in Crystal, found by Crystal's parser. |
| `coding-python` | before an edit / after a shell command | No new comments in Python, found by `tokenize`. |
| `feature-graph` | | Includes `/feature-graph` to build the cross-repo graph in Neo4j and `/verify-changed` to plan verification and run local tests for a diff. |

## Layout

```
runtime/                     the one source of the hook code
  hook.sh                    entry point: hook.sh <check> [--lang ruby,python,crystal]
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

Crystal hooks additionally require `crystal` for comment checks and `ameba`
for linting. On macOS, install them with `brew install crystal ameba`.
For other platforms, follow the [Crystal installation instructions](https://crystal-lang.org/install/)
and [Ameba installation instructions](https://github.com/crystal-ameba/ameba#installation).
The hooks prefer a project's executable `bin/ameba` over `ameba` on PATH and
respect its `.ameba.yml`. The comment parser is compiled on first use and
cached under `${XDG_CACHE_HOME:-$HOME/.cache}/agent-hooks`; changes to the
helper or Crystal version rebuild it. Syntax errors stop comment extraction
at the point the parser cannot continue. Comment extraction parses source
without executing it.

Commit linting checks staged Crystal content; files missing from the working
tree are skipped, as with the Ruby hooks.

**Claude Code:**

```sh
/plugin marketplace add lukas8219/agent-hooks
/plugin install coding-ruby@agent-hooks     # and/or coding-python
/plugin install coding-crystal@agent-hooks
/plugin install feature-graph@agent-hooks
```

**Codex:**

```sh
codex plugin marketplace add lukas8219/agent-hooks
codex plugin add coding-ruby@agent-hooks    # or pick in /plugins
codex plugin add coding-crystal@agent-hooks
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

### Git commit identity

To use your account for web commits, add both variables to the web
environment's saved variables before rerunning setup and starting a new session:

```sh
AGENT_HOOKS_GIT_NAME="Your Name"
AGENT_HOOKS_GIT_EMAIL="your-verified-email@example.com"
```

Use an email associated with your GitHub account, or your GitHub-provided
`noreply` address. GitHub identifies commit authors by email, independently of
the credentials used to push. The existing `attribution.commit: ""` setting
only removes Claude's co-author trailer; it does not change Git's author or
committer. See [Git's identity settings](https://git-scm.com/docs/git-config#Documentation/git-config.txt-username),
[GitHub's commit email instructions](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address),
and [Claude's attribution setting](https://code.claude.com/docs/en/settings-reference#attributioncommit).

At session start, the installer applies the identity in each working
repository, including explicit author
and committer settings that could otherwise override `user.name` / `user.email`.
It uses worktree config when enabled. The Claude installer also sets
`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, and
`GIT_COMMITTER_EMAIL` in Claude settings so inherited defaults do not take
precedence. Other environment settings are preserved. Verify from a fresh
Bash tool call with `./install.sh status .`; it prints the effective author
and committer. If the launcher still overrides them, set those four variables
in the saved web environment too and restart the session.

Saved environment variables are loaded after the web setup script runs. To
also configure global Git identity during setup, export the two
`AGENT_HOOKS_GIT_*` values in the setup script itself. Otherwise setup leaves
global identity unchanged and the session installer configures each repo.

The same opt-in works with `install.sh claude|codex --user|--project <repo>`.
To configure only Git, including when using the plugin manager:

```sh
AGENT_HOOKS_GIT_NAME="Your Name" \
AGENT_HOOKS_GIT_EMAIL="your-verified-email@example.com" \
  ./install.sh git-identity --project /path/to/repo
```

Use `--user` for global Git config. Neither variable set leaves identity
unchanged; supplying only one is an error. The Git-only and Codex installers
do not alter the calling shell: any existing `GIT_AUTHOR_*` / `GIT_COMMITTER_*`
exports must match your intended identity. Installation through a plugin
manager alone does not run this setup. These settings affect future commits;
existing commits and GitHub authentication are unchanged.

### Remote Git commit signing

The Claude and Codex installers can also configure the remote signing client.
First run the signing bridge and Lima tunnel on your trusted Mac, and provision
the bridge's executable `signing/git-sign.py` and your **public** Ed25519 key in
the cloud environment. The bridge and its deployment remain in the separate
private repository. This installer does not start the Mac, create a signing
session, download the private repository, or export a private key.

Set the following variables in the environment where the installer runs:

```sh
export AGENT_HOOKS_SIGN_URL="https://your-signing-tunnel.example.com"
export AGENT_HOOKS_SIGN_PROGRAM="/opt/git-signing-bridge/signing/git-sign.py"
export AGENT_HOOKS_SIGN_KEY_FILE="/run/git-signing/key.pub"
export AGENT_HOOKS_SIGN_TOKEN_FILE="/run/secrets/git-signing-token"
./install.sh claude --project "$PWD"
```

Use `codex` instead of `claude` for Codex, or `git-signing` to configure signing
without registering hooks (including installations through a plugin manager).
Use `--user` for global Git configuration. Project installation uses worktree
configuration when enabled. Set the Git identity variables above to the name
and email authorized by the bridge; signing setup does not infer an identity
from the public key.

The token file must already exist, be readable only by its owner (mode 600 or
400), and live outside Git repositories. Provision its contents through a
protected secret mechanism. Never put a token in the URL, command arguments,
settings JSON, or chat. The installer validates an HTTPS origin, executable
client, public key, and authorization configuration before changing Git or
installing hooks. It does not contact the service or request a signature during
installation.

If an HTTP secret proxy injects `Authorization: Bearer <session-token>` for the
exact signing hostname, use this instead of a local token file:

```sh
unset AGENT_HOOKS_SIGN_TOKEN_FILE
export AGENT_HOOKS_SIGN_AUTH=proxy
```

Proxy configuration and the network allowlist must be provisioned separately.
The installer cannot verify that the proxy injects the header. To switch back
to a token file, unset `AGENT_HOOKS_SIGN_AUTH` (or set it to `token-file`) and
provide `AGENT_HOOKS_SIGN_TOKEN_FILE` again.

All three of `URL`, `PROGRAM`, and `KEY_FILE` are required when opting in, plus
either a token file or explicit proxy mode. With no signing variables set,
installation leaves existing signing settings unchanged, including previously
enabled remote signing. Partial or invalid settings fail installation.

The installer enables `commit.gpgsign`, selects SSH signing, and points Git at
this kit's adapter. It persists the URL, client/public-key paths, authorization
mode, and token **path** in Git config; it never reads or saves the token's
contents. Keep both checkouts and the configured files at their installed
paths. Later commits use the saved configuration even if setup variables are
absent or stale. Ordinary local signature verification still uses `ssh-keygen`.
`./install.sh status .` reports signing configuration without contacting the
bridge; an actual signed commit is needed to verify connectivity and access.

When the bridge is unavailable, access expires, or the token file disappears,
signing fails and Git aborts the commit. The error tells the agent to ask the
user to renew authorization on the trusted Mac. The adapter does not renew its
own authorization or silently retry unsigned. It does not prevent an explicit
`--no-gpg-sign` or a Git configuration change; agents must not use those to
bypass a requested signature.

For renewal, create a fresh bridge session and replace the protected token
file or proxy secret. Replacing a token at the same path needs no reinstall.
If the tunnel hostname, public key, client path, or token path changed, rerun
the installer with the complete updated variables. Quick Tunnel hostnames can
change on restart. Keep the Mac, 1Password, bridge, and tunnel available while
the cloud agent signs commits.

For Claude Code web setup, provide these variables at session startup alongside
the identity variables; the existing session instructions run the installer in
each work repo. `web/setup.sh` also applies global signing if the variables and
files are already present during setup. For a Codex cloud environment, run the
`codex --project` or `git-signing --project` installation step after provisioning
the client, public key, and authorization. Harness-specific proxy delivery and
network policy still need testing inside the actual cloud environment.

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

Both skills use [AIP v0.3a3](https://github.com/zach-blumenfeld/aip/tree/v0.3a3),
the version evaluated in the [AIP paper](https://arxiv.org/html/2606.04781v1).
Their `SKILL.md` bodies are YAML procedures with typed inputs/outputs, named steps,
and explicit dependencies. Each bundles the unchanged upstream procedure schema
and original instructions in `source/`. AIP describes these execution procedures;
the repository feature graph's Neo4j data model is unchanged. Mapping confirmation
precedes all graph writes, including index initialization. Verification uses a
read-only command adapter and deterministic Git change collection.

Validate the skills offline with:

```sh
python3 -m pip install -r tests/requirements.txt
python3 scripts/validate-aip.py
python3 -B -m unittest discover -s tests -p 'test_aip.py'
```

The test dependencies are only needed for development; the installed graph
clients still use Python's standard library. `tests/run.sh` includes these AIP
checks. They verify the pinned schema, dependencies, typed data flow, bundled
paths, approval ordering, and read-only commands. The upstream AIP validator can
also be run against either skill directory from a checkout of tag `v0.3a3`.
This is conformance to that specification, not a claim of runtime-enforced graph
traversal, certification, or improved task success without behavioral evaluation.

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
