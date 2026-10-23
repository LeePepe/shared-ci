"""Unit and integration tests for scripts/context/sync_contract.py."""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from fixture import REPO, isolated_environment

SCRIPT = REPO / "scripts" / "context" / "sync_contract.py"
CONTEXT = REPO / "scripts" / "context" / "_context.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_sync_contract", SCRIPT)
assert SPEC and SPEC.loader
sync_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_contract
SPEC.loader.exec_module(sync_contract)

OLD_PIN = "1" * 40
NEW_PIN = "2" * 40


class SyncContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-sync-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = isolated_environment()

    def _make_consumer_repo(self, name: str = "consumer") -> pathlib.Path:
        repo = self.root / name
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, env=self.env, check=True)
        subprocess.run(
            ["git", "config", "--local", "maintenance.auto", "false"],
            cwd=repo,
            env=self.env,
            check=True,
        )
        for source, target in (
            ("repository-guide.md", "docs/repository-guide.md"),
            ("development.md", "docs/development.md"),
            ("pull_request_template.md", ".github/pull_request_template.md"),
            ("scripts/verify", "scripts/verify"),
            ("githooks/pre-push", ".githooks/pre-push"),
        ):
            content = (REPO / "templates" / source).read_text(encoding="utf-8")
            content = content.replace("<40-char-sha>", OLD_PIN)
            dest = repo / target
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        for executable in ("scripts/verify", ".githooks/pre-push"):
            (repo / executable).chmod(0o755)
        root_ctx = (REPO / "templates" / "tech-context.root.md").read_text(encoding="utf-8")
        root_ctx = root_ctx.replace("Packages/Core", "src/core").replace("Packages/App", "src/app")
        (repo / "docs/architecture").mkdir(parents=True, exist_ok=True)
        (repo / "docs/architecture/tech-context.md").write_text(root_ctx, encoding="utf-8")
        for layer, dep in (("Core", "[]"), ("App", "[Core]")):
            leaf = (REPO / "templates" / "tech-context.leaf.md").read_text(encoding="utf-8")
            leaf = leaf.replace("Core", layer).replace("Packages/" + layer, "src/" + layer.lower())
            leaf = leaf.replace("depends_on: []", f"depends_on: {dep}")
            folder = repo / "src" / layer.lower()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "tech-context.md").write_text(leaf, encoding="utf-8")
            (folder / "mod.py").write_text("X = 1\n", encoding="utf-8")
        (repo / ".github/workflows").mkdir(parents=True, exist_ok=True)
        (repo / ".github/workflows/ci.yml").write_text(
            f"name: ci\non:\n  pull_request:\njobs:\n  quality:\n"
            f"    uses: LeePepe/shared-ci/.github/workflows/quality.yml@{OLD_PIN}\n"
            f"    with:\n      verify-command: scripts/verify --all\n",
            encoding="utf-8",
        )
        (repo / ".github/workflows/review.yml").write_text(
            f"name: review\non:\n  pull_request_target:\njobs:\n  codex-review:\n"
            f"    uses: LeePepe/shared-ci/.github/workflows/codex-review.yml@{OLD_PIN}\n"
            f"    with:\n      rules-file: AGENTS.md\n",
            encoding="utf-8",
        )
        return repo

    def _run_cli(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = sync_contract.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_check_is_dry_run_and_reports_drift(self) -> None:
        repo = self._make_consumer_repo()
        code, stdout, stderr = self._run_cli(str(repo), "--pin", NEW_PIN, "--check")
        self.assertEqual(1, code, stderr)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("check", report["mode"])
        self.assertEqual(1, report["drifted_count"])
        paths = {item["path"] for item in report["repos"][0]["changes"]}
        self.assertEqual(
            {
                ".github/repo-contract.json",
                "AGENTS.md",
                "CLAUDE.md",
                ".github/copilot-instructions.md",
                ".github/workflows/ci.yml",
                ".github/workflows/review.yml",
            },
            paths,
        )
        self.assertFalse((repo / ".github/repo-contract.json").exists())
        self.assertFalse((repo / "AGENTS.md").exists())

    def test_apply_synchronizes_consumer_and_passes_context_audit(self) -> None:
        repo = self._make_consumer_repo()
        code, stdout, stderr = self._run_cli(str(repo), "--pin", NEW_PIN, "--apply")
        self.assertEqual(0, code, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("apply", report["mode"])

        # Re-running --check after --apply reports zero drift.
        check_code, check_out, _ = self._run_cli(str(repo), "--pin", NEW_PIN, "--check")
        self.assertEqual(0, check_code, check_out)
        self.assertEqual(0, json.loads(check_out)["drifted_count"])

        # Stage all files and run the real context audit CLI against the synced repo.
        subprocess.run(["git", "add", "-A"], cwd=repo, env=self.env, check=True)
        for executable in ("scripts/verify", ".githooks/pre-push"):
            subprocess.run(
                ["git", "update-index", "--chmod=+x", executable],
                cwd=repo,
                env=self.env,
                check=True,
            )
        audit = subprocess.run(
            [sys.executable, "-I", "-B", str(CONTEXT), "audit"],
            cwd=repo,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, audit.returncode, audit.stdout + audit.stderr)
        self.assertTrue(json.loads(audit.stdout)["ok"])

    def test_preserves_metadata_dependencies_and_custom_index_routes(self) -> None:
        repo = self._make_consumer_repo()
        (repo / "docs/custom.md").write_text("# Custom doc\n", encoding="utf-8")
        (repo / ".github/repo-contract.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "guide": "docs/repository-guide.md",
                    "shared_ci": OLD_PIN,
                    "dependencies": {
                        "shared-telemetry": {
                            "version": "1.2.0",
                            "ai": "https://example.invalid/1.2.0/ai/",
                        },
                        "shared-ci": {
                            "version": OLD_PIN,
                            "ai": f"https://example.invalid/{OLD_PIN}/ai/",
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        custom_agents = (
            "# Document index\n\n"
            "## Read first\n\n"
            "- Before editing: [Repository guide](docs/repository-guide.md)\n"
            "- For custom context: [Custom](docs/custom.md)\n\n"
            "## Protocol\n\n"
            f"- For protocol: [Agent protocol](https://github.com/LeePepe/shared-ci/blob/{OLD_PIN}/ai/agent-protocol.md)\n"
        )
        (repo / "AGENTS.md").write_text(custom_agents, encoding="utf-8")
        self._run_cli(str(repo), "--pin", NEW_PIN, "--apply")

        metadata = json.loads((repo / ".github/repo-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(NEW_PIN, metadata["shared_ci"])
        self.assertEqual(
            {"shared-telemetry": {"version": "1.2.0", "ai": "https://example.invalid/1.2.0/ai/"}},
            metadata["dependencies"],
        )
        updated_agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("- For custom context: [Custom](docs/custom.md)", updated_agents)
        self.assertIn(NEW_PIN, updated_agents)
        self.assertNotIn(OLD_PIN, updated_agents)

    def test_repairs_invalid_tool_pointer_files_and_optional_pointers(self) -> None:
        repo = self._make_consumer_repo()
        (repo / "CLAUDE.md").write_text(
            f"Read AGENTS.md first.\nPinned to LeePepe/shared-ci@{OLD_PIN}/ai/agent-protocol.md\n",
            encoding="utf-8",
        )
        (repo / ".github/copilot-instructions.md").write_text(
            "Read AGENTS.md first.\nRequired check: `quality / aggregate`\n",
            encoding="utf-8",
        )
        (repo / "GEMINI.md").write_text("Custom instructions without index reference.\n", encoding="utf-8")

        self._run_cli(str(repo), "--pin", NEW_PIN, "--all-agent-files", "--apply")
        for rel in ("CLAUDE.md", ".github/copilot-instructions.md", "GEMINI.md", ".cursorrules"):
            content = (repo / rel).read_text(encoding="utf-8")
            self.assertIn("AGENTS.md", content)
            self.assertNotIn(OLD_PIN, content)
            self.assertNotIn("`quality / aggregate`", content)

    def test_multi_repo_batch_check_and_apply(self) -> None:
        repo_a = self._make_consumer_repo("repo_a")
        repo_b = self._make_consumer_repo("repo_b")
        self._run_cli(str(repo_a), "--pin", NEW_PIN, "--apply")

        code, stdout, _ = self._run_cli(str(repo_a), "--repo", str(repo_b), "--pin", NEW_PIN, "--check")
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertEqual(1, report["drifted_count"])
        self.assertFalse(report["repos"][0]["drifted"])
        self.assertTrue(report["repos"][1]["drifted"])

    def test_invalid_inputs_return_status_two(self) -> None:
        repo = self._make_consumer_repo()
        for bad_args in (
            (str(repo), "--pin", "not-a-sha"),
            (str(repo), "--pin", "A" * 40),
            (str(repo), "--pin", NEW_PIN, "--guide", "../escape.md"),
            (str(self.root / "missing"), "--pin", NEW_PIN),
        ):
            with self.subTest(bad_args=bad_args):
                code, _, stderr = self._run_cli(*bad_args)
                self.assertEqual(2, code)
                self.assertFalse(json.loads(stderr)["ok"])

    def test_symlinked_github_ancestor_rejected_in_check_and_apply_without_external_writes(self) -> None:
        repo = self._make_consumer_repo()
        external = self.root / "external-github"
        external.mkdir(parents=True, exist_ok=True)
        external_wf = external / "workflows"
        external_wf.mkdir(parents=True, exist_ok=True)
        sentinel_ci = external_wf / "ci.yml"
        sentinel_ci.write_text(
            f"name: ci\non:\n  pull_request:\njobs:\n  quality:\n"
            f"    uses: LeePepe/shared-ci/.github/workflows/quality.yml@{OLD_PIN}\n",
            encoding="utf-8",
        )
        # Replace consumer's .github directory with a symlink to external-github.
        for child in sorted((repo / ".github").rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        (repo / ".github").rmdir()
        (repo / ".github").symlink_to(external, target_is_directory=True)

        for mode_flag in ("--check", "--apply"):
            with self.subTest(mode=mode_flag):
                code, stdout, stderr = self._run_cli(str(repo), "--pin", NEW_PIN, mode_flag)
                self.assertEqual(2, code)
                self.assertEqual("", stdout)
                err_payload = json.loads(stderr)
                self.assertFalse(err_payload["ok"])
                self.assertIn(err_payload["code"], ("symlink_target", "unsafe_target"))
                self.assertFalse((external / "repo-contract.json").exists())
                self.assertFalse((external / "copilot-instructions.md").exists())
                self.assertFalse((repo / "AGENTS.md").exists())
                self.assertIn(OLD_PIN, sentinel_ci.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
