#!/usr/bin/env python3
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True
import git_signing as signing


def context(message):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}))


def identity():
    name = os.environ.get("AGENT_HOOKS_GIT_NAME", "")
    email = os.environ.get("AGENT_HOOKS_GIT_EMAIL", "")
    if not name and not email:
        return None
    if not name or not email:
        raise ValueError("set both AGENT_HOOKS_GIT_NAME and AGENT_HOOKS_GIT_EMAIL")
    if any(char in name + email for char in "\r\n\x00"):
        raise ValueError("Git identity must not contain line breaks or NUL characters")
    return name, email


def configure_identity(value, directory, scope):
    name, email = value
    for role in ("user", "author", "committer"):
        for field, text in (("name", name), ("email", email)):
            signing.git(directory, "config", "--" + scope, "--replace-all", f"{role}.{field}", text)
    overrides = {
        "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email,
    }
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if env_file:
        with Path(env_file).open("a") as stream:
            stream.write("\n" + "".join(f"export {key}={shlex.quote(text)}\n" for key, text in overrides.items()))
    elif any(key in os.environ and os.environ[key] != text for key, text in overrides.items()):
        return " Inherited GIT_AUTHOR_* or GIT_COMMITTER_* values still override Git config; correct them before committing."
    return ""


def main():
    payload = json.loads(sys.stdin.read(65537))
    if payload.get("hook_event_name") != "SessionStart":
        return
    wants_signing = any(os.environ.get("AGENT_HOOKS_SIGN_" + key) for key in signing.VARIABLES)
    wants_identity = bool(os.environ.get("AGENT_HOOKS_GIT_NAME") or os.environ.get("AGENT_HOOKS_GIT_EMAIL"))
    if not wants_signing and not wants_identity:
        return
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_PREFIX"):
        os.environ.pop(key, None)
    directory = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    result = subprocess.run(
        ["git", "-C", directory, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if result.returncode:
        context("git-account: no working Git repository at session startup; run Git setup in each repository before committing.")
        return
    directory = result.stdout.strip()
    scope = "worktree" if signing.git(directory, "config", "--bool", "--get", "extensions.worktreeConfig", missing=True) == "true" else "local"
    try:
        account = identity()
        config = signing.requested()
        warning = configure_identity(account, directory, scope) if account else ""
        if config:
            with contextlib.redirect_stdout(io.StringIO()):
                signing.configure(config, directory, scope)
    except (ValueError, OSError, KeyError, TypeError) as error:
        guard = ""
        if wants_signing:
            try:
                signing.configure({"setup_error": True}, directory, scope)
                guard = " Git now requires signing but has no usable signer until setup succeeds."
            except (ValueError, OSError):
                guard = " Git configuration could not be updated; this hook cannot enforce signing."
        context(f"git-account setup failed: {error}.{guard} Fix the configuration before committing; do not bypass signing.")
        return
    configured = " and ".join(part for part, active in (("identity", account), ("remote signing", config)) if active)
    message = f"git-account configured Git {configured} for {directory}.{warning}"
    if config:
        message += " Authorization is checked when signing. If signing later fails: " + signing.RENEWAL
    context(message)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        context(f"git-account could not configure this session: {error}. Do not commit until requested Git setup succeeds.")
