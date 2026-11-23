#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import urllib.parse


SETTING = "agentHooks.signing"
VARIABLES = ("URL", "PROGRAM", "KEY_FILE", "TOKEN_FILE", "AUTH")
RENEWAL = (
    "Restore access to the signing bridge. If authorization expired, ask the user "
    "to create a new session on their trusted host and update the protected token "
    "or proxy secret. Rerun the installer if the URL or paths changed. "
    "Keep signing enabled; do not retry with an unsigned commit."
)


def git(directory, *args, missing=False):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
    if result.returncode and not (missing and result.returncode == 1):
        raise ValueError("Git configuration could not be read or written")
    return result.stdout.strip()


def validate(config):
    endpoint = config["url"]
    if not isinstance(endpoint, str) or any(char.isspace() or ord(char) < 32 for char in endpoint):
        raise ValueError("AGENT_HOOKS_SIGN_URL must be an HTTPS origin")
    url = urllib.parse.urlsplit(endpoint)
    if (url.scheme != "https" or not url.hostname or url.username is not None
            or url.password is not None or url.path not in ("", "/")
            or url.query or url.fragment or "?" in endpoint or "#" in endpoint):
        raise ValueError("AGENT_HOOKS_SIGN_URL must be an HTTPS origin without credentials, path, query, or fragment")
    try:
        url.port
    except ValueError:
        raise ValueError("AGENT_HOOKS_SIGN_URL has an invalid port") from None
    config["url"] = endpoint.rstrip("/")
    for field, variable in (("program", "PROGRAM"), ("key_file", "KEY_FILE")):
        path = Path(config[field]).expanduser()
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.R_OK):
            raise ValueError(f"AGENT_HOOKS_SIGN_{variable} must name an existing readable absolute file")
        config[field] = str(path.resolve())
    program = Path(config["program"])
    if not os.access(program, os.X_OK) or program == Path(__file__).resolve():
        raise ValueError("AGENT_HOOKS_SIGN_PROGRAM must be the executable bridge client")
    key = Path(config["key_file"])
    with key.open("rb") as stream:
        public = stream.read(16385).strip()
    if len(public) > 16384 or not public.startswith(b"ssh-ed25519 ") or b"\n" in public:
        raise ValueError("AGENT_HOOKS_SIGN_KEY_FILE must contain one Ed25519 public key")
    result = subprocess.run(["ssh-keygen", "-l", "-f", str(key)], capture_output=True)
    if result.returncode:
        raise ValueError("AGENT_HOOKS_SIGN_KEY_FILE is not a valid public key")
    if config["auth"] == "proxy":
        if config["token_file"]:
            raise ValueError("proxy authorization requires AGENT_HOOKS_SIGN_TOKEN_FILE to be unset")
    elif config["auth"] == "token-file":
        token = Path(config["token_file"]).expanduser()
        if not token.is_absolute() or not token.is_file() or not os.access(token, os.R_OK):
            raise ValueError("AGENT_HOOKS_SIGN_TOKEN_FILE must name an existing readable absolute file")
        token = token.resolve()
        mode = token.stat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("AGENT_HOOKS_SIGN_TOKEN_FILE must be owner-only (chmod 600 or 400)")
        if subprocess.run(
            ["git", "-C", str(token.parent), "rev-parse", "--git-dir"],
            capture_output=True,
            env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        ).returncode == 0:
            raise ValueError("keep AGENT_HOOKS_SIGN_TOKEN_FILE outside Git repositories")
        config["token_file"] = str(token)
    else:
        raise ValueError("set AGENT_HOOKS_SIGN_TOKEN_FILE or explicitly set AGENT_HOOKS_SIGN_AUTH=proxy")
    return config


def requested():
    values = {name: os.environ.get("AGENT_HOOKS_SIGN_" + name, "") for name in VARIABLES}
    if not any(values.values()):
        return None
    if not all(values[name] for name in ("URL", "PROGRAM", "KEY_FILE")):
        raise ValueError("set AGENT_HOOKS_SIGN_URL, AGENT_HOOKS_SIGN_PROGRAM, and AGENT_HOOKS_SIGN_KEY_FILE together")
    return validate({
        "url": values["URL"], "program": values["PROGRAM"], "key_file": values["KEY_FILE"],
        "auth": values["AUTH"] or ("token-file" if values["TOKEN_FILE"] else ""),
        "token_file": values["TOKEN_FILE"],
    })


def signing_command():
    return str(Path(__file__).resolve())


def configure(config, directory, scope):
    for key, value in (
        (SETTING, json.dumps(config)),
        ("user.signingkey", config["key_file"]),
        ("gpg.format", "ssh"),
        ("gpg.ssh.program", signing_command()),
        ("commit.gpgsign", "true"),
    ):
        git(directory, "config", "--" + scope, "--replace-all", key, value)
    print(f"  Git --{scope} remote signing configured ({config['auth']}); access is checked when signing.")


def sign(args):
    operation = args[args.index("-Y") + 1] if "-Y" in args and args.index("-Y") + 1 < len(args) else ""
    if operation in {"verify", "find-principals", "check-novalidate"}:
        return subprocess.run(["ssh-keygen", *args]).returncode
    if operation != "sign":
        raise ValueError("unsupported SSH signing operation")
    saved = git(Path.cwd(), "config", "--get", SETTING, missing=True)
    if not saved:
        raise ValueError("remote signing is not configured; rerun install.sh git-signing")
    config = validate(json.loads(saved))
    env = os.environ.copy()
    env["AGENT_HOOKS_SIGN_URL"] = config["url"]
    env.pop("AGENT_HOOKS_SIGN_TOKEN_FILE", None)
    if config["auth"] == "token-file":
        env["AGENT_HOOKS_SIGN_TOKEN_FILE"] = config["token_file"]
    result = subprocess.run([config["program"], *args], env=env)
    if result.returncode:
        print(RENEWAL, file=sys.stderr)
    return result.returncode if result.returncode >= 0 else 1


def status(directory):
    enabled = git(directory, "config", "--bool", "--get", "commit.gpgsign", missing=True) == "true"
    saved = git(directory, "config", "--get", SETTING, missing=True)
    print("Git commit signing: " + ("enabled" if enabled else "disabled"))
    if saved:
        config = validate(json.loads(saved))
        program = git(directory, "config", "--get", "gpg.ssh.program", missing=True)
        if program != signing_command() or git(directory, "config", "--get", "gpg.format", missing=True) != "ssh":
            print("  Remote bridge settings are present, but Git's signing program has been overridden.")
        else:
            print(f"  Remote bridge: {config['url']} ({config['auth']})")
            print("  Authorization validity is checked when signing; no signing request was made.")


def main():
    if sys.argv[1:2] == ["-Y"]:
        return sign(sys.argv[1:])
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "configure", "status"])
    parser.add_argument("--directory", default=".")
    parser.add_argument("--scope", choices=["global", "local", "worktree"], default="local")
    args = parser.parse_args()
    if args.command == "status":
        status(args.directory)
    else:
        config = requested()
        if config and args.command == "configure":
            configure(config, args.directory, args.scope)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"remote signing: {error}", file=sys.stderr)
        if sys.argv[1:2] == ["-Y"]:
            print(RENEWAL, file=sys.stderr)
        sys.exit(1)
