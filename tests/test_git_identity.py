import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]
NAME = "Test O'Connor"
EMAIL = "123+test@users.noreply.github.com"


class GitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo with spaces"
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("GIT_", "AGENT_HOOKS_GIT_"))
            and key not in {"CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"}
        }
        self.env.update(
            HOME=str(self.home),
            CODEX_HOME=str(self.home / ".codex"),
            GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"),
            GIT_CONFIG_NOSYSTEM="1",
        )
        self.run_command("git", "init", "-q", str(self.repo))
        self.git("config", "commit.gpgsign", "false")
        self.identity = {"AGENT_HOOKS_GIT_NAME": NAME, "AGENT_HOOKS_GIT_EMAIL": EMAIL}

    def run_command(self, *args, extra=None, check=True):
        return subprocess.run(
            args, env=self.env | (extra or {}), text=True,
            capture_output=True, check=check,
        )

    def git(self, *args, extra=None, check=True):
        return self.run_command("git", "-C", str(self.repo), *args, extra=extra, check=check)

    def install(self, *args, extra=None, check=True):
        return self.run_command(str(KIT / "install.sh"), *args, extra=extra, check=check)

    def seed_identity(self, scope, name="Claude", email="claude@example.com"):
        for role in ("user", "author", "committer"):
            self.git("config", scope, f"{role}.name", name)
            self.git("config", scope, f"{role}.email", email)

    def assert_commit_identity(self, extra=None):
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "identity test", extra=extra)
        actual = self.git("log", "-1", "--format=%an%n%ae%n%cn%n%ce").stdout.splitlines()
        self.assertEqual(actual, [NAME, EMAIL, NAME, EMAIL])

    def test_missing_identity_preserves_existing_configuration(self):
        self.seed_identity("--local", "Existing User", "existing@example.com")
        before = self.git("config", "--local", "--list").stdout
        self.install("claude", "--project", str(self.repo), "--only", "coding-python")
        self.assertEqual(self.git("config", "--local", "--list").stdout, before)
        settings = json.loads((self.repo / ".claude/settings.json").read_text())
        self.assertNotIn("env", settings)
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_partial_identity_fails_before_changes(self):
        self.seed_identity("--local")
        before = self.git("config", "--local", "--list").stdout
        for key, value in self.identity.items():
            with self.subTest(key=key):
                result = self.install("claude", "--project", str(self.repo), extra={key: value}, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("set both AGENT_HOOKS_GIT_NAME and AGENT_HOOKS_GIT_EMAIL", result.stderr)
                self.assertEqual(self.git("config", "--local", "--list").stdout, before)
                self.assertFalse((self.repo / ".claude/settings.json").exists())

    def test_project_install_overrides_defaults_and_preserves_other_settings(self):
        self.seed_identity("--global")
        self.seed_identity("--local")
        self.git("config", "--add", "user.name", "Another default")
        settings_file = self.repo / ".claude/settings.json"
        settings_file.parent.mkdir()
        settings_file.write_text(json.dumps({"env": {"KEEP_ME": "yes", "GIT_AUTHOR_NAME": "Claude"}}))
        for _ in range(2):
            self.install("claude", "--project", str(self.repo), "--only", "coding-python", extra=self.identity)
        self.assert_commit_identity()
        self.assertEqual(self.git("config", "--global", "user.name").stdout.strip(), "Claude")
        self.assertEqual(self.git("config", "--get-all", "user.name").stdout.splitlines(), ["Claude", NAME])
        settings = json.loads(settings_file.read_text())
        self.assertEqual(settings["env"], {
            "KEEP_ME": "yes", "GIT_AUTHOR_NAME": NAME, "GIT_AUTHOR_EMAIL": EMAIL,
            "GIT_COMMITTER_NAME": NAME, "GIT_COMMITTER_EMAIL": EMAIL,
        })
        inherited = {key: "Claude" for key in settings["env"] if key.startswith("GIT_")}
        self.assert_commit_identity(extra=inherited | settings["env"])
        self.assertEqual(settings["attribution"], {"commit": "", "pr": ""})
        self.assertEqual(self.git("status", "--porcelain").stdout, "")
        status = self.install("status", str(self.repo)).stdout
        self.assertEqual(status.count(f"{NAME} <{EMAIL}>"), 2)

    def test_git_only_setup_configures_global_identity_without_installing_hooks(self):
        self.seed_identity("--global")
        for _ in range(2):
            self.install("git-identity", "--user", extra=self.identity)
        self.assert_commit_identity()
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_codex_project_install_configures_git(self):
        self.seed_identity("--local")
        self.install("codex", "--project", str(self.repo), "--only", "coding-python", extra=self.identity)
        self.assert_commit_identity()
        self.assertTrue((self.repo / ".codex/hooks.json").exists())
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_worktree_identity_overrides_stale_worktree_config(self):
        self.seed_identity("--local")
        self.git("commit", "--allow-empty", "-qm", "base")
        self.git("config", "extensions.worktreeConfig", "1")
        original = self.repo
        linked = self.root / "linked worktree"
        self.git("worktree", "add", "-q", "-b", "linked", str(linked))
        self.repo = linked
        self.seed_identity("--worktree")
        self.install("git-identity", "--project", str(self.repo), extra=self.identity)
        self.assert_commit_identity()
        self.assertEqual(self.git("config", "--worktree", "user.name").stdout.strip(), NAME)
        self.repo = original
        self.assertEqual(self.git("config", "user.name").stdout.strip(), "Claude")


if __name__ == "__main__":
    unittest.main()
