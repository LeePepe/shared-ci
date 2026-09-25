"""Actual caller templates against a published metadata-capable provider."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from fixture import AGENTS, ContractRepo, PIN, REPO, environment

# Published provider supporting the metadata/index contract and versioned AI docs.
PROVIDER = "d8fe8e3c68182e3d8435120814bae955ee327372"


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="provider space ")
        cls.provider = pathlib.Path(cls.temp.name) / "provider"
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(REPO), str(cls.provider)],
                       env=environment(), check=True, capture_output=True)
        subprocess.run(["git", "-C", str(cls.provider), "checkout", "-q", "--detach", PROVIDER],
                       env=environment(), check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        copies = {
            "AGENTS.md": "AGENTS.md", "CLAUDE.md": "CLAUDE.md",
            "CODEOWNERS": ".github/CODEOWNERS", "repo-contract.json": ".github/repo-contract.json",
            "repository-guide.md": "docs/repository-guide.md", "development.md": "docs/development.md",
            "ci.yml": ".github/workflows/ci.yml", "review.yml": ".github/workflows/review.yml",
            "scripts/verify": "scripts/verify", "githooks/pre-push": ".githooks/pre-push",
            "pull_request_template.md": ".github/pull_request_template.md",
        }
        for source, target in copies.items():
            text = (REPO / "templates" / source).read_text().replace("<40-char-sha>", PROVIDER)
            self.repo.write(target, text.replace("@OWNER", "@owner").replace("<Repository>", "Synthetic"))
        self.repo.write(".gitignore", ".shared-ci/\n")
        root = (REPO / "templates/tech-context.root.md").read_text()
        self.repo.write("docs/architecture/tech-context.md",
                        root.replace("Packages/Core", "src/core").replace("Packages/App", "src/app"))
        for layer, dependency in (("Core", "[]"), ("App", "[Core]")):
            leaf = (REPO / "templates/tech-context.leaf.md").read_text()
            leaf = leaf.replace("Core", layer).replace("Packages/" + layer, "src/" + layer.lower())
            leaf = leaf.replace("depends_on: []", "depends_on: " + dependency)
            start, end = leaf.index("gate:"), leaf.index("red_lines:")
            leaf = leaf[:start] + f'gate: {{test: "python3 -c \\\"print(\'gate-{layer}\')\\\""}}\n' + leaf[end:]
            self.repo.write(f"src/{layer.lower()}/tech-context.md", leaf)
        self.repo.add()

    def verify(self, *args, **updates):
        env = {k: v for k, v in self.repo.env.items()
               if k not in ("CI_SELECTION_FULL", "CI_SELECTED_LAYERS", "SHARED_CI")}
        env["SHARED_CI"] = str(self.provider)
        env.update(updates)
        return subprocess.run(["bash", "scripts/verify", *args], cwd=self.repo.root,
                              env=env, capture_output=True, text=True, timeout=120)

    def assert_pass(self, result):
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("gate-", result.stdout + result.stderr)

    def metadata(self, text):
        self.repo.write(".github/repo-contract.json", text)
        self.repo.add()

    def test_actual_kit_metadata_all_and_selected(self):
        self.assert_pass(self.verify("--all"))
        result = self.verify("--selected", CI_SELECTION_FULL="false", CI_SELECTED_LAYERS="App")
        self.assert_pass(result)
        self.assertNotIn("gate-Core", result.stdout)

    def test_legacy_mode(self):
        self.repo.remove(".github/repo-contract.json")
        text = (REPO / "templates/AGENTS.legacy.md").read_text()
        self.repo.write("AGENTS.md", text.replace("<40-char-sha>", PROVIDER))
        self.repo.add()
        self.assert_pass(self.verify("--all"))

    def test_invalid_metadata_never_falls_back(self):
        self.repo.write("AGENTS.md", AGENTS.replace(PIN, PROVIDER))
        baseline = json.loads((self.repo.root / ".github/repo-contract.json").read_text())
        invalid = ["{", "[]", "null"]
        for key, value in (("schema", True), ("schema", 2), ("shared_ci", "main"),
                           ("shared_ci", PROVIDER.upper()), ("shared_ci", "a" * 39),
                           ("shared_ci", "a" * 41), ("shared_ci", 1)):
            invalid.append(json.dumps(dict(baseline, **{key: value})))
        invalid.append(json.dumps(baseline).replace('"shared_ci":',
                       '"shared_ci": "' + PROVIDER + '", "shared_ci":'))
        for text in invalid:
            with self.subTest(text=text):
                self.metadata(text)
                self.assertNotEqual(0, self.verify("--all", SHARED_CI="").returncode)
                self.assertFalse((self.repo.root / ".shared-ci").exists())

    def test_untracked_metadata_and_symlink_metadata_fail(self):
        path = self.repo.root / ".github/repo-contract.json"
        original = path.read_text()
        self.repo.git("rm", "--cached", ".github/repo-contract.json")
        self.assertNotEqual(0, self.verify("--all").returncode)
        self.repo.write("metadata.json", original)
        path.unlink()
        path.symlink_to("../metadata.json")
        self.repo.add()
        self.assertNotEqual(0, self.verify("--all").returncode)
        path.unlink()
        path.symlink_to("../missing-metadata.json")
        self.repo.add()
        self.assertNotEqual(0, self.verify("--all").returncode)

    def test_git_hook_environment_is_not_used_for_provider(self):
        self.assert_pass(self.verify("--all", GIT_DIR=str(self.repo.root / ".git"),
                                    GIT_WORK_TREE=str(self.repo.root),
                                    GIT_INDEX_FILE=str(self.repo.root / ".git/index")))

    def test_wrong_supplied_checkout_preserved(self):
        before = self.repo.git("status", "--porcelain").stdout
        result = self.verify("--all", SHARED_CI=str(self.repo.root))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.repo.git("status", "--porcelain").stdout)

    def test_existing_default_paths_are_never_replaced(self):
        cache = self.repo.root / ".shared-ci"
        for shape in ("file", "directory", "symlink", "broken-symlink"):
            with self.subTest(shape=shape):
                if shape == "file":
                    cache.write_text("keep")
                elif shape == "directory":
                    cache.mkdir()
                    (cache / "keep").write_text("keep")
                else:
                    cache.symlink_to(self.provider if shape == "symlink" else "absent")
                self.assertNotEqual(0, self.verify("--all", SHARED_CI="").returncode)
                if cache.is_symlink():
                    cache.unlink()
                elif cache.is_file():
                    self.assertEqual("keep", cache.read_text())
                    cache.unlink()
                else:
                    self.assertEqual("keep", (cache / "keep").read_text())
                    shutil.rmtree(cache)

    def test_dirty_matching_provider_preserved_and_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "cache"
            subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(self.provider), str(cache)],
                           env=self.repo.env, check=True, capture_output=True)
            script = cache / "scripts/context/_context.py"
            original = script.read_text()
            script.write_text("raise SystemExit('MUST NOT EXECUTE')\n" + original)
            result = self.verify("--all", SHARED_CI=str(cache))
            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("MUST NOT EXECUTE", result.stderr)
            self.assertTrue(script.read_text().startswith("raise SystemExit"))

    def test_hidden_dirty_provider_index_flags_are_preserved(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as temp:
                cache = pathlib.Path(temp) / "cache"
                subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(self.provider), str(cache)],
                               env=self.repo.env, check=True, capture_output=True)
                path = "scripts/context/_context.py"
                script = cache / path
                script.write_text("raise SystemExit('HIDDEN CODE EXECUTED')\n")
                subprocess.run(["git", "-C", str(cache), "update-index", flag, path],
                               env=self.repo.env, check=True, capture_output=True)
                before = subprocess.check_output(["git", "-C", str(cache), "ls-files", "-v", path],
                                                 env=self.repo.env)
                result = self.verify("--all", SHARED_CI=str(cache))
                self.assertNotEqual(0, result.returncode)
                self.assertIn("provider index flags", result.stderr)
                self.assertNotIn("HIDDEN CODE EXECUTED", result.stderr)
                self.assertEqual(before, subprocess.check_output(
                    ["git", "-C", str(cache), "ls-files", "-v", path], env=self.repo.env))
                self.assertEqual("raise SystemExit('HIDDEN CODE EXECUTED')\n", script.read_text())

    def test_clean_linked_worktree_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            worktree = str(pathlib.Path(temp) / "linked provider")
            subprocess.run(["git", "-C", str(self.provider), "worktree", "add", "-q", "--detach", worktree, PROVIDER],
                           env=self.repo.env, check=True, capture_output=True)
            try:
                self.assert_pass(self.verify("--all", SHARED_CI=worktree))
            finally:
                subprocess.run(["git", "-C", str(self.provider), "worktree", "remove", worktree],
                               env=self.repo.env, check=True, capture_output=True)

    def test_untracked_and_ignored_provider_files_fail(self):
        for filename in ("untracked.txt", "__pycache__/ignored.pyc"):
            with self.subTest(filename=filename):
                path = self.provider / filename
                path.parent.mkdir(exist_ok=True)
                path.write_text("preserve me")
                try:
                    self.assertNotEqual(0, self.verify("--all").returncode)
                    self.assertEqual("preserve me", path.read_text())
                finally:
                    path.unlink()
                    if path.parent.name == "__pycache__":
                        path.parent.rmdir()

    def test_provider_status_error_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            git = pathlib.Path(temp) / "git"
            git.write_text('#!/bin/sh\ncase " $* " in *" status "*) exit 42 ;; esac\nexec "'
                           + shutil.which("git") + '" "$@"\n')
            git.chmod(0o755)
            result = self.verify("--all", PATH=temp + os.pathsep + self.repo.env["PATH"])
            self.assertNotEqual(0, result.returncode)
            self.assertIn("cannot inspect provider", result.stderr)

    def test_generated_hook_and_default_changed_selection(self):
        self.repo.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                      "commit", "-qm", "generated caller")
        self.repo.git("branch", "baseline")
        self.repo.write("src/core/model.py", "X = 2\n")
        self.repo.add()
        self.repo.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                      "commit", "-qm", "exercise hook")
        self.repo.git("config", "core.hooksPath", ".githooks")
        env = dict(self.repo.env, SHARED_CI=str(self.provider), VERIFY_BASE="baseline",
                   GIT_DIR=str(self.repo.root / ".git"))
        result = subprocess.run(["git", "hook", "run", "pre-push"], cwd=self.repo.root,
                                env=env, capture_output=True, text=True, timeout=120)
        self.assert_pass(result)

    def contract_url(self):
        return (f"https://github.com/LeePepe/shared-ci/blob/{PROVIDER}/ai/"
                "repo-contract.md#repository-development-contract")

    def test_relocated_protocol_links_resolve_at_selected_provider(self):
        guide = (self.repo.root / "docs/repository-guide.md").read_text()
        snapshot = guide.split("## Complete shared protocol snapshot\n", 1)[1]
        links = re.findall(r"\]\(([^)]+)\)", snapshot)
        # The selected protocol has exactly one Markdown link. No unresolved
        # relative links (nor floating provider versions) may survive relocation.
        self.assertEqual([self.contract_url()], links)
        contract = self.provider / "ai/repo-contract.md"
        self.assertTrue(contract.is_file())
        self.assertIn("\n## Repository development contract\n", contract.read_text())
        self.assertFalse((self.repo.root / "docs/repo-contract.md").exists())

    def test_complete_protected_reviewer_rules(self):
        guide = (self.repo.root / "docs/repository-guide.md").read_text()
        protocol = (self.provider / "ai/agent-protocol.md").read_text()
        # Only relocate the provider-relative contract link; every policy byte
        # outside that single URL must remain present in the generated guide.
        relative = "](repo-contract.md#repository-development-contract)"
        self.assertEqual(1, protocol.count(relative))
        protocol = protocol.replace(relative, "](" + self.contract_url() + ")")
        self.assertIn(protocol, guide)
        self.assertLess(len(guide.encode()), 24000)
        result = subprocess.run(["python3", "-I", "-B",
                                 str(self.provider / "scripts/review/render_prompt.py"),
                                 str(self.provider / "scripts/review/review-prompt.md")],
                                env=dict(self.repo.env, REPO_RULES=guide, ARCHITECTURE="Core -> App",
                                         CHANGED="src/core/model.py", DIFF="synthetic diff", TRUNCATED=""),
                                capture_output=True, text=True, check=True)
        self.assertIn(guide, result.stdout)
        self.assertIn("Ordinary test-code", result.stdout)
        self.assertIn("| Core | Core leaf", result.stdout)
        for job in ("codex-review", "kimi-review"):
            self.assertIn(job, (self.repo.root / ".github/workflows/review.yml").read_text())
        self.assertEqual(2, (self.repo.root / ".github/workflows/review.yml").read_text().count(
            "rules-file: docs/repository-guide.md"))
        self.repo.write(".github/workflows/review.yml", (self.repo.root / ".github/workflows/review.yml").read_text().replace(
            "rules-file: docs/repository-guide.md", "rules-file: AGENTS.md"))
        self.repo.add()
        self.assertNotEqual(0, self.verify("--all").returncode)


if __name__ == "__main__":
    unittest.main()
