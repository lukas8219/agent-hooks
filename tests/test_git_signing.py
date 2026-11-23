import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


KIT = Path(__file__).resolve().parents[1]
CLIENT = '''import os
from pathlib import Path
import subprocess
import sys

if os.environ["AGENT_HOOKS_SIGN_URL"] != "https://signer.example.test":
    sys.exit("unexpected signing origin")
token_file = os.environ.get("AGENT_HOOKS_SIGN_TOKEN_FILE")
if token_file and Path(token_file).read_text().strip() != "test-authorization":
    sys.exit("signing access expired; ask the user to renew it on the trusted host")
args = sys.argv[1:]
args[args.index("-f") + 1] = str(Path(__file__).with_name("disposable-key"))
sys.exit(subprocess.run(["ssh-keygen", *args]).returncode)
'''


class GitSigningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="installer-signing-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo with spaces"
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("GIT_", "AGENT_HOOKS_SIGN_", "AGENT_HOOKS_GIT_"))
            and key not in {"CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"}
        }
        self.env.update(
            HOME=str(self.home), CODEX_HOME=str(self.home / ".codex"),
            GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"), GIT_CONFIG_NOSYSTEM="1",
        )
        self.run_command("git", "init", "-q", str(self.repo))
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.credentials = self.root / "protected files"
        self.credentials.mkdir(mode=0o700)
        self.key = self.credentials / "disposable-key"
        self.run_command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key))
        self.program = self.credentials / "signing client.py"
        self.program.write_text("#!" + sys.executable + "\n" + CLIENT)
        self.program.chmod(0o700)
        self.token = self.credentials / "token"
        self.token.write_text("test-authorization\n")
        self.token.chmod(0o600)
        self.options = {
            "AGENT_HOOKS_SIGN_URL": "https://signer.example.test/",
            "AGENT_HOOKS_SIGN_PROGRAM": str(self.program),
            "AGENT_HOOKS_SIGN_KEY_FILE": str(self.key) + ".pub",
            "AGENT_HOOKS_SIGN_TOKEN_FILE": str(self.token),
        }
        self.allowed = self.credentials / "allowed-signers"
        self.allowed.write_text("test@example.com " + Path(str(self.key) + ".pub").read_text())

    def run_command(self, *args, extra=None, check=True):
        return subprocess.run(args, env=self.env | (extra or {}), text=True, capture_output=True, check=check)

    def git(self, *args, extra=None, check=True):
        return self.run_command("git", "-C", str(self.repo), *args, extra=extra, check=check)

    def install(self, harness="git-signing", scope="--project", extra=None, check=True, kit=KIT):
        args = [str(kit / "install.sh"), harness, scope]
        if scope == "--project":
            args.append(str(self.repo))
        args += ["--only", "coding-python"]
        return self.run_command(*args, extra=extra, check=check)

    def assert_signed_commit(self, extra=None):
        commit = self.git("commit", "--allow-empty", "-qm", "Signed by installed adapter", extra=extra, check=False)
        self.assertEqual(commit.returncode, 0, commit.stderr)
        result = self.git("-c", f"gpg.ssh.allowedSignersFile={self.allowed}", "verify-commit", "HEAD")
        self.assertIn('Good "git" signature', result.stderr)

    def test_no_opt_in_preserves_existing_signing_configuration(self):
        self.git("config", "gpg.format", "openpgp")
        self.git("config", "user.signingkey", "existing-key")
        self.git("config", "commit.gpgsign", "false")
        before = self.git("config", "--local", "--list").stdout
        for harness in ("claude", "codex", "git-signing"):
            self.install(harness)
            self.assertEqual(self.git("config", "--local", "--list").stdout, before)

    def test_each_harness_signs_without_install_environment_or_secret_in_settings(self):
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                for _ in range(2):
                    output = self.install(harness, extra=self.options).stdout
                    self.assertNotIn("test-authorization", output)
                self.assert_signed_commit(extra={
                    "AGENT_HOOKS_SIGN_URL": "https://stale.example.test",
                    "AGENT_HOOKS_SIGN_TOKEN_FILE": "/missing-stale-token",
                })
                self.assertEqual(self.git("config", "--get-all", "agentHooks.signing").stdout.count("signer.example.test"), 1)
                self.assertNotIn("test-authorization", self.git("config", "--local", "--list").stdout)
                folder = self.repo / (".claude" if harness == "claude" else ".codex")
                settings = next(folder.glob("*.json")).read_text()
                self.assertNotIn("AGENT_HOOKS_SIGN", settings)
                self.assertNotIn("test-authorization", settings)
                self.assertEqual(self.git("status", "--porcelain").stdout, "")
                self.assertFalse((self.home / ".gitconfig").exists())

    def test_invalid_requests_do_not_change_identity_signing_or_hooks(self):
        before = self.git("config", "--local", "--list").stdout
        invalid = [
            {"AGENT_HOOKS_SIGN_URL": "https://signer.example.test"},
            self.options | {"AGENT_HOOKS_SIGN_URL": "http://signer.example.test"},
            self.options | {"AGENT_HOOKS_SIGN_URL": "https://secret-user:secret-password@signer.example.test"},
            self.options | {"AGENT_HOOKS_SIGN_URL": "https://signer.example.test/?token=secret-password"},
            self.options | {"AGENT_HOOKS_SIGN_PROGRAM": "/missing-client"},
            self.options | {"AGENT_HOOKS_SIGN_KEY_FILE": str(self.key)},
            self.options | {"AGENT_HOOKS_SIGN_TOKEN_FILE": ""},
            self.options | {"AGENT_HOOKS_SIGN_AUTH": "proxy"},
        ]
        for options in invalid:
            with self.subTest(options=list(options)):
                result = self.install("claude", extra=options | {
                    "AGENT_HOOKS_GIT_NAME": "Changed", "AGENT_HOOKS_GIT_EMAIL": "changed@example.com",
                }, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("secret-password", result.stdout + result.stderr)
                self.assertNotIn("PRIVATE KEY", result.stdout + result.stderr)
                self.assertEqual(self.git("config", "--local", "--list").stdout, before)
                self.assertFalse((self.repo / ".claude").exists())

    def test_token_permissions_and_repository_location_are_checked(self):
        self.token.chmod(0o644)
        result = self.install(extra=self.options, check=False)
        self.assertIn("owner-only", result.stderr)
        self.token.chmod(0o600)
        in_repo = self.repo / "token"
        in_repo.write_text("test-authorization")
        in_repo.chmod(0o600)
        result = self.install(extra=self.options | {"AGENT_HOOKS_SIGN_TOKEN_FILE": str(in_repo)}, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside Git repositories", result.stderr)
        self.assertEqual(self.git("config", "--get", "agentHooks.signing", check=False).returncode, 1)

    def test_global_install_works_in_a_fresh_repository(self):
        self.install(scope="--user", extra=self.options)
        self.assert_signed_commit()
        self.assertNotIn("signing", self.git("config", "--local", "--list").stdout)
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_worktree_configuration_overrides_stale_signer_without_changing_primary(self):
        self.git("-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "base")
        self.git("config", "extensions.worktreeConfig", "true")
        self.git("config", "gpg.ssh.program", "/previous-signer")
        self.git("config", "commit.gpgsign", "false")
        original = self.repo
        linked = self.root / "linked worktree"
        self.git("worktree", "add", "-q", "-b", "linked", str(linked))
        self.repo = linked
        self.git("config", "--worktree", "gpg.ssh.program", "/stale-worktree-signer")
        self.install("codex", extra=self.options)
        self.assert_signed_commit()
        self.repo = original
        self.assertEqual(self.git("config", "gpg.ssh.program").stdout.strip(), "/previous-signer")
        self.assertEqual(self.git("config", "commit.gpgsign").stdout.strip(), "false")

    def test_expired_or_missing_token_blocks_commit_and_explains_renewal(self):
        self.install(extra=self.options)
        self.assert_signed_commit()
        self.token.write_text("expired-test-authorization")
        for missing in (False, True):
            if missing:
                self.token.unlink()
            result = self.git("commit", "--no-verify", "--allow-empty", "-qm", "Must not commit", check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ask the user", result.stderr)
            self.assertIn("do not retry with an unsigned commit", result.stderr)
            self.assertNotIn("expired-test-authorization", result.stderr)
            self.assertEqual(self.git("rev-list", "--count", "HEAD").stdout.strip(), "1")

    def test_renewal_and_proxy_migration_replace_saved_authorization(self):
        self.install(extra=self.options)
        renewed = self.credentials / "renewed-token"
        self.token.rename(renewed)
        self.install(extra=self.options | {"AGENT_HOOKS_SIGN_TOKEN_FILE": str(renewed)})
        self.assert_signed_commit()
        self.install(extra=self.options | {"AGENT_HOOKS_SIGN_TOKEN_FILE": "", "AGENT_HOOKS_SIGN_AUTH": "proxy"})
        renewed.unlink()
        self.assert_signed_commit(extra={"AGENT_HOOKS_SIGN_TOKEN_FILE": "/stale-token"})
        config = json.loads(self.git("config", "agentHooks.signing").stdout)
        self.assertEqual(config["token_file"], "")
        self.assertEqual(config["auth"], "proxy")

    def test_installer_checkout_path_is_used_literally(self):
        kit = self.root / "kit with 'quote' $PATH; space"
        kit.mkdir()
        shutil.copy2(KIT / "install.sh", kit / "install.sh")
        shutil.copytree(KIT / "scripts", kit / "scripts")
        (kit / "plugins/coding-python").mkdir(parents=True)
        self.install(extra=self.options, kit=kit)
        self.assert_signed_commit()

    def test_status_reports_signer_without_reading_token_or_contacting_service(self):
        self.install(extra=self.options)
        status = self.run_command(str(KIT / "install.sh"), "status", str(self.repo)).stdout
        self.assertIn("Git commit signing: enabled", status)
        self.assertIn("https://signer.example.test (token-file)", status)
        self.assertNotIn("test-authorization", status)
        self.git("config", "gpg.ssh.program", "/other-signer")
        status = self.run_command(str(KIT / "install.sh"), "status", str(self.repo)).stdout
        self.assertIn("overridden", status)


if __name__ == "__main__":
    unittest.main()
