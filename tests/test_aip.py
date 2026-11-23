import copy
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


KIT = Path(__file__).resolve().parents[1]
SKILLS = KIT / "plugins/feature-graph/skills"
VALIDATOR = runpy.run_path(str(KIT / "scripts/validate-aip.py"))
validate_skill = VALIDATOR["validate_skill"]
validate_graph = VALIDATOR["validate_graph"]
ValidationError = VALIDATOR["ValidationError"]
VERIFY = SKILLS / "verify-changed"
COLLECTOR = VERIFY / "scripts/changed_files.py"
ADAPTER = VERIFY / "scripts/graph.py"


class AipContractTests(unittest.TestCase):
    def setUp(self):
        self.root = SKILLS / "feature-graph"
        self.body = validate_skill(self.root)

    def reject_graph(self, body, message):
        with self.assertRaisesRegex(ValidationError, message):
            validate_graph(body, self.root)

    def test_both_skills_validate_in_an_isolated_plugin_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = Path(directory) / "feature-graph"
            shutil.copytree(SKILLS.parent, plugin)
            for name in ("feature-graph", "verify-changed"):
                validate_skill(plugin / "skills" / name)
            result = subprocess.run([sys.executable, "-I", str(plugin / "skills/verify-changed/scripts/graph.py"),
                                     "uri", "neo4j://localhost:7687"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["base"], "http://localhost:7474")

    def test_all_writes_depend_on_user_approval_and_validation(self):
        ancestors = validate_graph(self.body, self.root)
        for name in ("initialize-graph", "write-graph"):
            self.assertIn("confirm-mapping", ancestors[name])
            self.assertIn("validate-payload", ancestors[name])
            step = next(s for s in self.body["steps"] if s["name"] == name)
            self.assertIn({"name": "approval", "type": "boolean"}, step["inputs"])

    def test_rejects_unknown_dependency(self):
        self.body["steps"][1]["depends_on"] = ["missing-step"]
        self.reject_graph(self.body, "unknown dependency")

    def test_rejects_cycle(self):
        self.body["steps"][0]["depends_on"] = ["write-graph"]
        self.reject_graph(self.body, "dependency cycle")

    def test_rejects_missing_data_dependency(self):
        self.body["steps"][1]["depends_on"] = []
        self.reject_graph(self.body, "must depend on its producer")

    def test_rejects_type_mismatch(self):
        self.body["steps"][1]["inputs"][0]["type"] = "string"
        self.reject_graph(self.body, "type mismatch")

    def test_rejects_unbound_input(self):
        self.body["steps"][1]["inputs"][0]["name"] = "typo"
        self.reject_graph(self.body, "unknown input")

    def test_rejects_nullable_value_without_fallback_contract(self):
        body = validate_skill(VERIFY)
        body["steps"][2]["inputs"][1].pop("nullable")
        with self.assertRaisesRegex(ValidationError, "nullable output"):
            validate_graph(body, VERIFY)

    def test_rejects_duplicate_step_names(self):
        self.body["steps"].append(copy.deepcopy(self.body["steps"][0]))
        self.reject_graph(self.body, "step names must be unique")

    def test_rejects_missing_script(self):
        self.body["steps"][0]["script"] = "scripts/missing.py"
        self.reject_graph(self.body, "missing or external script")

    def test_rejects_schema_drift_and_frontmatter_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "feature-graph"
            shutil.copytree(self.root, root)
            schema = root / "source/procedure.schema.json"
            schema.write_text(schema.read_text().replace('"additionalProperties": false', '"additionalProperties": true'))
            with self.assertRaisesRegex(ValidationError, "schema differs"):
                validate_skill(root)
            shutil.copyfile(self.root / "source/procedure.schema.json", schema)
            skill = root / "SKILL.md"
            skill.write_text(skill.read_text().replace("aip/tree/v0.3a3", "aip/tree/main"))
            with self.assertRaisesRegex(ValidationError, "pinned to v0.3a3"):
                validate_skill(root)

    def test_rejects_extra_prose_and_duplicate_yaml_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "feature-graph"
            shutil.copytree(self.root, root)
            skill = root / "SKILL.md"
            original = skill.read_text()
            skill.write_text(original + "\nextra prose\n")
            with self.assertRaisesRegex(ValidationError, "one fenced YAML block"):
                validate_skill(root)
            skill.write_text(original.replace("purpose: >-", "purpose: duplicate\npurpose: >-"))
            with self.assertRaisesRegex(ValidationError, "duplicate YAML key"):
                validate_skill(root)


class ChangeCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("remote", "add", "origin", "https://example.invalid/team/repo.git")
        for name in ("app.py", "delete.py", "rename.py"):
            (self.repo / name).write_text("value = 1\n")
        (self.repo / ".gitignore").write_text("ignored*\n")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("update-ref", "refs/remotes/origin/main", self.base)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def collect(self, *args):
        return subprocess.run([sys.executable, "-I", str(COLLECTOR), *args], cwd=self.repo,
                              capture_output=True, text=True)

    def test_empty_diff(self):
        result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["files"], [])
        self.assertEqual(data["base_sha"], self.base)
        self.assertEqual(data["repo"]["name"], "team/repo")

    def test_union_includes_deletions_renames_and_unusual_filenames(self):
        (self.repo / "app.py").write_text("value = 2\n")
        self.git("mv", "rename.py", "renamed.py")
        self.git("add", ".")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "branch changes")
        (self.repo / "app.py").write_text("value = 3\n")
        (self.repo / "delete.py").unlink()
        (self.repo / "staged.py").write_text("value = 1\n")
        self.git("add", "staged.py")
        (self.repo / "odd\nname.py").write_text("value = 1\n")
        (self.repo / "ignored.py").write_text("value = 1\n")
        result = self.collect("--base-ref", self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(set(data["files"]), {"app.py", "delete.py", "rename.py", "renamed.py", "staged.py", "odd\nname.py"})
        self.assertEqual(set(data["deleted_files"]), {"delete.py", "rename.py"})

    def test_missing_default_base_fails_with_fetch_guidance(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        result = self.collect()
        self.assertEqual(result.returncode, 1)
        self.assertIn("fetch origin main", result.stderr)

    def test_nested_working_directory_keeps_repository_relative_paths(self):
        nested = self.repo / "nested"
        nested.mkdir()
        (nested / "new.py").write_text("value = 1\n")
        (self.repo / "root_new.py").write_text("value = 1\n")
        result = subprocess.run([sys.executable, "-I", str(COLLECTOR)], cwd=nested,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(json.loads(result.stdout)["files"]), {"nested/new.py", "root_new.py"})

    def test_invalid_explicit_base_does_not_fall_back(self):
        result = self.collect("--base-ref", "missing-ref")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")


class ReadOnlyAdapterTests(unittest.TestCase):
    def test_write_commands_are_rejected_without_connecting(self):
        for command in ("init", "upsert", "write"):
            with self.subTest(command=command):
                result = subprocess.run([sys.executable, "-I", str(ADAPTER), command], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("only read-only commands", result.stderr)

    def test_missing_credentials_are_reported_for_fallback(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("NEO4J_")}
        result = subprocess.run([sys.executable, "-I", str(ADAPTER), "status"], env=environment,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("NEO4J_URI is not set", result.stderr)

    def test_impact_json_preserves_path_boundaries(self):
        adapter = runpy.run_path(str(ADAPTER))["main"]
        paths = ["a b.py", "odd\nname.py", "--help"]
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "changes.json"
            payload.write_text(json.dumps({"repo": {"name": "team/repo"}, "files": paths}))
            calls = []
            with patch("runpy.run_path", return_value={"main": lambda args: calls.append(args) or 0}):
                self.assertEqual(adapter(["impact", "--changes-json", str(payload)]), 0)
            self.assertEqual(calls, [["impact", "--repo", "team/repo", "--", *paths]])


if __name__ == "__main__":
    unittest.main()
