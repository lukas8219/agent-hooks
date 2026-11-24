# git-account

Configures Git identity and optional remote commit signing automatically on
`SessionStart`, including resumed sessions. Requires Python 3, Git, and OpenSSH
with SSH signing support when signing is enabled.

Enable the plugin before starting your session. For Claude Code Web, add the
marketplace or upload this plugin at <https://claude.ai/customize/plugins>.
For local Claude Code, install `git-account@agent-hooks`. For Codex, also review
and trust the hooks with `/hooks` where plugin hook execution is supported.

Save both `AGENT_HOOKS_GIT_NAME` and `AGENT_HOOKS_GIT_EMAIL` to configure identity.
To enable signing, also supply:

| Variable | Value |
|---|---|
| `AGENT_HOOKS_SIGN_URL` | HTTPS origin of the running signing bridge |
| `AGENT_HOOKS_SIGN_PROGRAM` | Absolute path to the provisioned executable bridge client |
| `AGENT_HOOKS_SIGN_KEY_FILE` | Absolute path to your public Ed25519 key |
| `AGENT_HOOKS_SIGN_AUTH` | `proxy` when a network-secret proxy injects authorization |
| `AGENT_HOOKS_SIGN_TOKEN_FILE` | Alternative to proxy mode: owner-only token file outside repositories |

The bridge client, key, and authorization must be provisioned separately.
For Claude's Network secrets, use the exact bridge hostname, header
`Authorization`, prefix `Bearer`, and the token as its value. Leave the token
file variable unset in proxy mode. The Mac bridge and tunnel must be running.

The hook updates only the session repository (or its worktree config). In
Claude it appends identity exports to `CLAUDE_ENV_FILE`; it never writes tokens
there. With no opt-in variables it leaves Git unchanged. There is no network
request during startup. Git checks authorization when a commit is signed.

Invalid requested signing setup records a failed configuration and requires
Git signing, so commits fail until the configuration is repaired. The hook
adds instructions for the agent; it cannot itself block session startup.
Expired authorization also aborts commits. Renew access on the trusted host
and update the protected token or proxy secret. If paths or the hostname
change, update saved variables and start a new session. Never bypass signing
to work around an error. Explicit Git overrides remain possible; this is
configuration automation, not a sandbox policy.

Use the plugin route on its own. Do not also register this hook with the manual
installer. For other repositories opened after startup, configure Git in each
one using the Git-only installer. See the repository README for full setup.
