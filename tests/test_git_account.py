import json
from pathlib import Path
import shutil
import shlex
import subprocess
import unittest

import test_git_signing as signing_tests


class GitAccountTests(unittest.TestCase):
    run_command = signing_tests.GitSigningTests.run_command
    git = signing_tests.GitSigningTests.git
    assert_signed_commit = signing_tests.GitSigningTests.assert_signed_commit

    def setUp(self):
        signing_tests.GitSigningTests.setUp(self)
        self.plugin = self.root / "cached plugin's $directory"
        shutil.copytree(signing_tests.KIT / "plugins/git-account", self.plugin)
        self.command = json.loads((self.plugin / "hooks/hooks.json").read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.env_file = self.root / "session environment"
        self.env_file.write_text("export KEEP_ME=retained\n")
        self.account = {"AGENT_HOOKS_GIT_NAME": "Account Owner", "AGENT_HOOKS_GIT_EMAIL": "test@example.com"}

    def hook(self, source="startup", extra=None, event="SessionStart", cwd=None):
        env = self.env | {"CLAUDE_PLUGIN_ROOT": str(self.plugin), "CLAUDE_ENV_FILE": str(self.env_file)} | (extra or {})
        return subprocess.run(
            ["bash", "-c", self.command], cwd=self.home, env=env,
            input=json.dumps({"hook_event_name": event, "source": source, "cwd": str(cwd or self.repo)}),
            text=True, capture_output=True, check=True,
        )

    def test_cached_plugin_configures_startup_and_resume_without_installer(self):
        for source in ("startup", "resume", "clear", "compact"):
            result = self.hook(source, extra=self.options | self.account)
            message = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("configured Git identity and remote signing", message)
            self.assertNotIn("test-authorization", result.stdout)
        self.assert_signed_commit()
        self.assertEqual(self.git("log", "-1", "--format=%an%n%ae%n%cn%n%ce").stdout.splitlines(), ["Account Owner", "test@example.com"] * 2)
        self.assertEqual(self.git("config", "gpg.ssh.program").stdout.strip(), str((self.plugin / "scripts/git_signing.py").resolve()))
        self.assertFalse((self.repo / ".claude").exists())
        self.assertFalse((self.repo / ".codex").exists())
        self.assertFalse((self.home / ".gitconfig").exists())
        self.assertFalse((self.plugin / "scripts/__pycache__").exists())
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_no_opt_in_or_wrong_event_leaves_configuration_unchanged(self):
        before = self.git("config", "--local", "--list").stdout
        self.assertEqual(self.hook().stdout, "")
        self.assertEqual(self.hook(event="PostToolUse", extra=self.options | self.account).stdout, "")
        self.assertEqual(self.git("config", "--local", "--list").stdout, before)
        self.assertEqual(self.env_file.read_text(), "export KEEP_ME=retained\n")

    def test_identity_exports_override_inherited_defaults_without_shell_expansion(self):
        sentinel = self.root / "must-not-exist"
        name = f"O'Connor $(touch {sentinel})"
        requested = self.account | {"AGENT_HOOKS_GIT_NAME": name}
        self.hook(extra=requested | {"GIT_AUTHOR_NAME": "Claude", "GIT_COMMITTER_EMAIL": "claude@example.com"})
        result = self.run_command(
            "bash", "-c", '. "$1"; git -C "$2" -c commit.gpgsign=false commit --allow-empty -qm "identity"; test "$KEEP_ME" = retained',
            "test", str(self.env_file), str(self.repo),
            extra={"GIT_AUTHOR_NAME": "Claude", "GIT_COMMITTER_EMAIL": "claude@example.com"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertEqual(self.git("log", "-1", "--format=%an%n%ae%n%cn%n%ce").stdout.splitlines(), [name, "test@example.com"] * 2)
        self.assertNotIn("TOKEN", self.env_file.read_text())
        self.assertNotIn("AGENT_HOOKS_SIGN", self.env_file.read_text())

    def test_invalid_startup_requires_signing_and_resume_recovers(self):
        self.git("config", "user.signingkey", str(self.key) + ".pub")
        result = self.hook(extra=self.options | {"AGENT_HOOKS_SIGN_URL": "https://secret:do-not-print@host.test"})
        self.assertIn("setup failed", result.stdout)
        self.assertNotIn("do-not-print", result.stdout + result.stderr)
        self.assertEqual(self.git("config", "commit.gpgsign").stdout.strip(), "true")
        self.assertTrue(json.loads(self.git("config", "agentHooks.signing").stdout)["setup_error"])
        commit = self.git("commit", "--allow-empty", "-qm", "must fail", check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn("setup failed", commit.stderr)
        self.hook("resume", extra=self.options | self.account)
        self.assert_signed_commit()
        self.assertEqual(self.git("rev-list", "--count", "HEAD").stdout.strip(), "1")

    def test_expiry_still_blocks_commits_after_successful_startup(self):
        self.hook(extra=self.options)
        self.assert_signed_commit()
        self.token.write_text("expired-authorization")
        commit = self.git("commit", "--allow-empty", "-qm", "must fail", check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn("ask the user", commit.stderr)
        self.assertNotIn("expired-authorization", commit.stderr)
        self.token.write_text("test-authorization")
        self.assert_signed_commit()

    def test_worktree_and_payload_cwd_take_precedence_over_launcher_repository(self):
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "base")
        self.git("config", "extensions.worktreeConfig", "true")
        before = self.git("config", "--local", "--list").stdout
        original = self.repo
        linked = self.root / "linked"
        self.git("worktree", "add", "-q", "-b", "linked", str(linked))
        self.repo = linked
        self.hook(extra=self.options | self.account | {"GIT_DIR": str(original / ".git"), "GIT_WORK_TREE": str(original)})
        self.assert_signed_commit()
        self.assertEqual(self.git("config", "--worktree", "user.name").stdout.strip(), "Account Owner")
        self.repo = original
        self.assertEqual(self.git("config", "--local", "--list").stdout, before)

    def test_proxy_mode_does_not_save_or_export_credentials(self):
        self.hook(extra=self.options | {"AGENT_HOOKS_SIGN_AUTH": "proxy", "AGENT_HOOKS_SIGN_TOKEN_FILE": ""})
        self.token.unlink()
        self.assert_signed_commit(extra={"AGENT_HOOKS_SIGN_TOKEN_FILE": "/stale-token"})
        self.assertNotIn(str(self.token), self.git("config", "agentHooks.signing").stdout)
        self.assertEqual(self.env_file.read_text(), "export KEEP_ME=retained\n")

    def test_non_repository_and_partial_identity_report_without_global_changes(self):
        before = self.git("config", "--local", "--list").stdout
        result = self.hook(extra=self.account, cwd=self.home)
        self.assertIn("no working Git repository", result.stdout)
        result = self.hook(extra={"AGENT_HOOKS_GIT_NAME": "Only name"})
        self.assertIn("set both", result.stdout)
        self.assertEqual(self.git("config", "--local", "--list").stdout, before)
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_web_setup_defaults_to_provisioning_without_manual_hook_instructions(self):
        checkout = self.root / "setup kit"
        self.run_command("git", "init", "-q", str(checkout))
        calls = self.root / "installer calls"
        installer = checkout / "install.sh"
        installer.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> " + shlex.quote(str(calls)) + "\n")
        installer.chmod(0o700)
        shutil.copy2(signing_tests.KIT / "CLAUDE.md", checkout / "CLAUDE.md")
        setup = self.root / "setup.sh"
        setup.write_text((signing_tests.KIT / "web/setup.sh").read_text().replace("DEST=/opt/agent-hooks", "DEST=" + shlex.quote(str(checkout))))
        self.run_command("bash", str(setup), extra={"AGENT_HOOKS_INSTALL_MODE": "plugin"})
        self.assertEqual(calls.read_text().splitlines(), ["deps"])
        self.assertFalse((self.home / ".claude").exists())
        calls.write_text("")
        self.run_command("bash", str(setup), extra={"AGENT_HOOKS_INSTALL_MODE": "manual"})
        self.assertEqual(calls.read_text().splitlines(), ["deps", "git-identity --user", "git-signing --user"])
        self.assertIn("<!-- agent-hooks -->", (self.home / ".claude/CLAUDE.md").read_text())


if __name__ == "__main__":
    unittest.main()
