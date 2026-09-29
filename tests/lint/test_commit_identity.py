"""Commit identity CLI and its quality-workflow step, using isolated Git repos."""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/lint/commit_identity.py"
NOREPLY = "123+contributor@users.noreply.github.com"
BOT = "456+automation[bot]@users.noreply.github.com"


class Repo:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-identity-")
        self.root = pathlib.Path(self.temp.name).resolve()
        home = self.root / "home"
        home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
        self.env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                         "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C.UTF-8",
                         "GIT_AUTHOR_NAME": 'Odd "quoted"\t雪\x1fname',
                         "GIT_COMMITTER_NAME": 'Another "quoted"\t雪\x1fname'})
        self.git("init", "-q", "-b", "main")
        self.git("config", "maintenance.auto", "false")
        # The excluded base deliberately has invalid emails.
        self.base = self.commit("base@example.invalid", "base@example.invalid")

    def close(self):
        self.temp.cleanup()

    def git(self, *args, env=None):
        return subprocess.run(["git", *args], cwd=self.root, env=env or self.env,
                              check=True, capture_output=True, text=True, timeout=20).stdout.strip()

    def commit(self, author=NOREPLY, committer=NOREPLY):
        env = dict(self.env, GIT_AUTHOR_EMAIL=author, GIT_COMMITTER_EMAIL=committer)
        self.git("commit", "-q", "--allow-empty", "-m", "subject\n\nOdd body\x1f", env=env)
        return self.git("rev-parse", "HEAD")

    def cli(self, head, *args, base=None):
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                               "--base", self.base if base is None else base, "--head", head,
                               "--root", str(self.root), *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=20)


class CommitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_noreply_author_and_committer_with_odd_names_pass(self):
        result = self.repo.cli(self.repo.commit())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ok (1 commits)", result.stdout)
        self.assertEqual("", result.stderr)

    def test_bot_noreply_passes(self):
        result = self.repo.cli(self.repo.commit(BOT, BOT))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_noreply_matching_is_case_insensitive(self):
        result = self.repo.cli(self.repo.commit(NOREPLY.upper(), BOT.upper()))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_local_author_fails_with_fix_hint_without_names(self):
        head = self.repo.commit("contributor@MacBook-Pro.local")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn(f'{head[:12]} author "contributor@MacBook-Pro.local"', result.stderr)
        self.assertNotIn(f"{head[:12]} committer ", result.stderr)
        self.assertNotIn("quoted", result.stderr)
        self.assertEqual(1, result.stderr.count("Fix:"))
        self.assertIn("user.email", result.stderr)
        self.assertIn("rewrite the branch commits", result.stderr)

    def test_non_noreply_committer_fails(self):
        head = self.repo.commit(committer="committer@example.invalid")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn(f'{head[:12]} committer "committer@example.invalid"', result.stderr)
        self.assertNotIn(f"{head[:12]} author ", result.stderr)

    def test_allowlist_pattern_passes_for_both_roles_case_insensitively(self):
        head = self.repo.commit("author@EXAMPLE.invalid", "committer@example.INVALID")
        result = self.repo.cli(head, "--allow", "*@Example.Invalid")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_comma_newline_and_repeated_allow_values(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        for args in (("--allow", " , *@ONE.invalid ,\n *@two.invalid\r\n,"),
                     ("--allow", "*@one.invalid", "--allow", "*@TWO.invalid")):
            with self.subTest(args=args):
                result = self.repo.cli(head, *args)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_allowlist_is_not_a_substring_match_or_blanket_exception(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        result = self.repo.cli(head, "--allow", "one.invalid")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author ", result.stderr)
        self.assertIn(f"{head[:12]} committer ", result.stderr)
        result = self.repo.cli(head, "--allow", "one.invalid, ,\n, *@ONE.invalid")
        self.assertEqual(1, result.returncode)
        self.assertNotIn(f"{head[:12]} author ", result.stderr)
        self.assertIn(f"{head[:12]} committer ", result.stderr)

    def test_noreply_domain_suffix_spoof_fails(self):
        head = self.repo.commit(NOREPLY + ".invalid")
        self.assertEqual(1, self.repo.cli(head).returncode)

    def test_web_flow_committer_passes_but_author_requires_allowlist(self):
        result = self.repo.cli(self.repo.commit(committer="NOREPLY@GITHUB.COM"))
        self.assertEqual(0, result.returncode, result.stderr)
        head = self.repo.commit("noreply@github.com", "noreply@github.com")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author ", result.stderr)
        self.assertNotIn(f"{head[:12]} committer ", result.stderr)
        self.assertEqual(0, self.repo.cli(head, "--allow", "noreply@github.com").returncode)

    def test_empty_range_ok(self):
        result = self.repo.cli(self.repo.base)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ok (0 commits)", result.stdout)

    def test_root_defaults_to_current_repository(self):
        head = self.repo.commit()
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                                 "--base", self.repo.base, "--head", head],
                                cwd=self.repo.root, env=self.repo.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_both_bad_roles_and_escaped_diagnostics(self):
        head = self.repo.commit("author\x1b@host.local", "committer@host.local")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn(f'{head[:12]} author "author\\u001b@host.local"', result.stderr)
        self.assertIn(f'{head[:12]} committer "committer@host.local"', result.stderr)
        self.assertNotIn("\x1b", result.stderr)
        self.assertEqual(1, result.stderr.count("Fix:"))

    def test_replacement_objects_cannot_hide_offenders(self):
        bad = self.repo.commit("author@host.local")
        good = self.repo.commit()
        self.repo.git("replace", bad, good)
        result = self.repo.cli(bad)
        self.assertEqual(1, result.returncode)
        self.assertIn(f'{bad[:12]} author "author@host.local"', result.stderr)

    def test_bad_revisions_and_empty_endpoints_exit_two(self):
        for base, head in (("unknown", self.repo.base), (self.repo.base, "unknown"),
                           ("", self.repo.base), (self.repo.base, ""),
                           (" ", self.repo.base), ("--all", self.repo.base),
                           (self.repo.base, "HEAD^{tree}")):
            with self.subTest(base=base, head=head):
                result = self.repo.cli(head, base=base)
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("", result.stdout)

    def test_missing_argument_or_non_repository_exit_two(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                                env=self.repo.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(2, result.returncode)
        # A nonexistent root cannot inherit the surrounding test repository.
        result = self.repo.cli(self.repo.base, "--root", str(self.repo.root / "absent"))
        self.assertEqual(2, result.returncode)

    def test_mixed_commits_report_only_offenders_not_just_head(self):
        good = self.repo.commit()
        bad_author = self.repo.commit("author@host.local")
        bad_committer = self.repo.commit(committer="committer@example.invalid")
        head = self.repo.commit()
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        findings = [line for line in result.stderr.splitlines() if line.startswith("commit-identity:")]
        self.assertCountEqual([
            f'commit-identity: {bad_author[:12]} author "author@host.local"',
            f'commit-identity: {bad_committer[:12]} committer "committer@example.invalid"',
        ], findings)
        for sha in (self.repo.base, good, head):
            self.assertNotIn(sha[:12], result.stderr)

    def test_mailmap_and_log_settings_cannot_hide_raw_emails(self):
        head = self.repo.commit("author@host.local")
        (self.repo.root / ".mailmap").write_text(f"<{NOREPLY}> <author@host.local>\n")
        self.repo.git("config", "log.mailmap", "true")
        self.repo.git("config", "log.showSignature", "true")
        self.repo.git("config", "format.pretty", "fuller")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn("author@host.local", result.stderr)
        self.assertNotIn("quoted", result.stderr)

    def test_merge_commits_and_side_branch_commits_are_checked(self):
        self.repo.git("checkout", "-q", "-b", "side")
        side = self.repo.commit("side@host.local")
        self.repo.git("checkout", "-q", "main")
        self.repo.commit()
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge", "side",
                      env=dict(self.repo.env, GIT_AUTHOR_EMAIL=NOREPLY,
                               GIT_COMMITTER_EMAIL="merge@host.local"))
        head = self.repo.git("rev-parse", "HEAD")
        result = self.repo.cli(head)
        self.assertEqual(1, result.returncode)
        self.assertIn(f'{side[:12]} author "side@host.local"', result.stderr)
        self.assertIn(f'{head[:12]} committer "merge@host.local"', result.stderr)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("identity_frontmatter", REPO / "scripts/context/_frontmatter.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.workflow = module.parse((REPO / ".github/workflows/quality.yml").read_text())
        cls.job = cls.workflow["jobs"]["select"]
        cls.step = next(step for step in cls.job["steps"]
                        if step.get("name") == "Check commit author and committer emails")

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        provider = self.repo.root / ".shared-ci/scripts/lint"
        provider.mkdir(parents=True)
        shutil.copyfile(SCRIPT, provider / SCRIPT.name)

    def run_step(self, head="", **env):
        environment = dict(self.repo.env, EVENT="pull_request", ENABLED="true", ALLOW="",
                           BASE_SHA=self.repo.base, HEAD_SHA=head)
        environment.update(env)
        return subprocess.run(["bash", "-euo", "pipefail", "-c", self.step["run"]],
                              cwd=self.repo.root, env=environment,
                              capture_output=True, text=True, timeout=20)

    def test_step_contract_preserves_jobs_and_aggregate(self):
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        for name, kind, default in (("commit-identity", "boolean", True),
                                     ("commit-identity-allow", "string", "")):
            self.assertEqual(kind, inputs[name]["type"])
            self.assertEqual(default, inputs[name]["default"])
        self.assertNotIn("if", self.job)
        self.assertNotIn("if", self.step)
        self.assertNotIn("continue-on-error", self.step)
        self.assertEqual("${{ inputs.commit-identity }}", self.step["env"]["ENABLED"])
        self.assertEqual("${{ inputs.commit-identity-allow }}", self.step["env"]["ALLOW"])
        self.assertEqual("${{ github.event.pull_request.base.sha || '' }}", self.step["env"]["BASE_SHA"])
        self.assertEqual("${{ github.event.pull_request.head.sha || github.sha }}", self.step["env"]["HEAD_SHA"])
        self.assertNotIn("${{", self.step["run"])
        checkout = self.job["steps"][0]
        self.assertEqual("inputs.changed-only || (inputs.commit-identity && github.event_name == 'pull_request')",
                         checkout["if"])
        self.assertEqual(0, checkout["with"]["fetch-depth"])
        self.assertEqual(self.step["env"]["HEAD_SHA"], checkout["with"]["ref"])
        self.assertFalse(checkout["with"]["persist-credentials"])
        provider = next(step for step in self.job["steps"] if step.get("with", {}).get("path") == ".shared-ci")
        self.assertEqual("${{ job.workflow_sha }}", provider["with"]["ref"])
        jobs = {"select", "verify", "lint", "build", "test", "contract", "workflow-lint", "test-integrity"}
        self.assertEqual(jobs | {"aggregate"}, set(self.workflow["jobs"]))
        self.assertEqual(jobs, set(self.workflow["jobs"]["aggregate"]["needs"]))
        self.assertEqual("always()", self.workflow["jobs"]["aggregate"]["if"])

    def test_workflow_step_propagates_pass_failure_and_git_error(self):
        self.assertEqual(0, self.run_step(self.repo.commit()).returncode)
        self.assertEqual(1, self.run_step(self.repo.commit("author@host.local")).returncode)
        self.assertEqual(2, self.run_step("unknown").returncode)

    def test_non_pr_events_and_disabled_input_explicitly_skip(self):
        for event in ("push", "schedule", "workflow_dispatch", "merge_group", "pull_request_target"):
            with self.subTest(event=event):
                result = self.run_step(EVENT=event)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("skipped (not a pull_request event:", result.stdout)
        result = self.run_step(ENABLED="false")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("skipped (disabled by input)", result.stdout)

    def test_workflow_allowlist_is_data_not_shell_code(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        result = self.run_step(head, ALLOW="$(touch injected), *@ONE.invalid\n*@two.invalid")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.repo.root / "injected").exists())


if __name__ == "__main__":
    unittest.main()
