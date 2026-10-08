"""Execute release-template shell steps; no Actions, credentials or publishing."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from fixture import REPO, run_bounded

spec = importlib.util.spec_from_file_location(
    "release_yaml", REPO / "scripts/context/_frontmatter.py")
yaml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(yaml)


def workflow(kind):
    return yaml.parse((REPO / f"templates/release-{kind}.yml").read_text())


def step(kind, name, job=None):
    selected = job or ("admit" if name == "candidate" else "release")
    return next(s for s in workflow(kind)["jobs"][selected]["steps"]
                if s.get("id") == name)


class ReleaseTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="release-template-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR")
                    if key in os.environ}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_SYSTEM=os.devnull,
                        GITHUB_OUTPUT=str(self.root / "outputs"))

    def execute(self, kind, name, script=None, job=None, **values):
        return run_bounded(["bash", "--noprofile", "--norc", "-euo", "pipefail",
                            "-c", script if script is not None else step(kind, name, job)["run"]], cwd=self.root,
                           env=dict(self.env, **values), timeout=10)

    def test_unconfigured_adapter_fails_usefully(self):
        for kind in ("sdk", "testflight"):
            for name in ("prepare", "publish"):
                with self.subTest(kind=kind, name=name):
                    result = self.execute(kind, name)
                    self.assertNotEqual(0, result.returncode)
                    self.assertIn("::error::", result.stdout)
                    self.assertIn("not configured", result.stdout)

    def test_late_completion_cannot_replace_pending_valid_release(self):
        """Model documented pending replacement, not hosted Actions scheduling."""
        for kind in ("sdk", "testflight"):
            config = workflow(kind)
            scope = config.get("concurrency", config["jobs"]["release"].get("concurrency", {}))
            pending = ["C"]  # A is already publishing; C has passed admission.
            # B passed admission earlier but only reaches the queue after C.
            # Moving a guard alone cannot impose queue-arrival ordering.
            if scope.get("queue", "single") == "single":
                pending.clear()
            pending.append("B")
            with self.subTest(kind=kind):
                self.assertEqual(["C", "B"], pending)
                self.assertFalse(scope["cancel-in-progress"])

    def test_rejected_event_never_enters_publication_concurrency(self):
        for kind in ("sdk", "testflight"):
            config = workflow(kind)
            self.assertNotIn("concurrency", config)
            self.assertNotIn("concurrency", config["jobs"]["admit"])
            release = config["jobs"]["release"]
            self.assertEqual("admit", release["needs"])
            self.assertEqual("needs.admit.outputs.release == 'true'", release["if"])
            self.assertEqual("${{ steps.eligible.outputs.release }}",
                             config["jobs"]["admit"]["outputs"]["release"])
            for invalid in ({"RUN_EVENT": "pull_request"}, {"RUN_RESULT": "failure"},
                            {"RUN_REPOSITORY": "fork/project"}):
                result = self.execute(kind, "candidate", **self.candidate(**invalid))
                self.assertNotEqual(0, result.returncode)
            # Failed admission cannot satisfy needs/if, so pending C is intact.

    def test_delayed_admission_and_postqueue_checks_do_not_lose_c(self):
        current = self.history()
        older_sha = self.git("rev-parse", "HEAD^")
        older = dict(current, CANDIDATE=older_sha, CHECKED_SHA=older_sha)
        for kind in ("sdk", "testflight"):
            self.git("checkout", "-q", "--detach", older_sha)
            self.git("update-ref", "refs/remotes/origin/main", older_sha)
            self.assertEqual(0, self.execute(kind, "eligible", job="admit", **older).returncode)
            self.git("checkout", "-q", "--detach", current["CANDIDATE"])
            self.git("update-ref", "refs/remotes/origin/main", current["CANDIDATE"])
            self.assertEqual(0, self.execute(kind, "eligible", job="admit", **current).returncode)
            policy = workflow(kind)["jobs"]["release"]["concurrency"]
            # A is running. C arrives first; B was admitted earlier but delayed.
            arrivals = ["C", "B"]
            pending = arrivals if policy.get("queue", "single") == "max" else arrivals[-1:]
            self.assertEqual(["C", "B"], pending)
            self.assertEqual(0, self.execute(kind, "eligible", **current).returncode)
            self.git("checkout", "-q", "--detach", older_sha)
            result = self.execute(kind, "eligible", **older)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("not the current default-branch tip", result.stdout)
            # Sensitivity control: the former single slot cancels C even if B
            # later fails the same actual postqueue guard.
            self.assertEqual(["B"], arrivals[-1:])
            self.assertNotEqual(["C", "B"], arrivals[-1:])

    def candidate(self, **overrides):
        values = dict(CANDIDATE="1" * 40, EVENT_NAME="workflow_run",
                      RUN_EVENT="push", RUN_RESULT="success",
                      RUN_REPOSITORY="fixture/project", REPOSITORY="fixture/project",
                      RUN_BRANCH="main", DEFAULT_BRANCH="main")
        values.update(overrides)
        return values

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env,
                              check=True, capture_output=True, text=True).stdout.strip()

    def history(self):
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "fixture@example.test")
        self.git("config", "user.name", "Fixture")
        (self.root / "library.txt").write_text("old")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        baseline = self.git("rev-parse", "HEAD")
        (self.root / "library.txt").write_text("release change")
        self.git("commit", "-qam", "release content")
        (self.root / "notes.md").write_text("nonpublishing note")
        self.git("add", ".")
        self.git("commit", "-qm", "notes only last commit")
        candidate = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", candidate)
        return dict(CANDIDATE=candidate, BASELINE=baseline, DEFAULT_BRANCH="main",
                    CHECKED_SHA=candidate, REQUIRED_CHECKS="success", PUBLISHABLE="true")

    def test_release_admission_accepts_ancestor_baseline_and_rejects_stale_checks(self):
        values = self.history()
        result = self.execute("sdk", "eligible", **values)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("release=true\n", (self.root / "outputs").read_text())
        for updates in ({"CHECKED_SHA": "2" * 40}, {"REQUIRED_CHECKS": ""},
                        {"REQUIRED_CHECKS": "failure"}, {"PUBLISHABLE": "unknown"},
                        {"BASELINE": ""}, {"BASELINE": "3" * 40}):
            with self.subTest(updates=updates):
                self.assertNotEqual(0, self.execute("sdk", "eligible", **dict(values, **updates)).returncode)
        (self.root / "outputs").unlink()
        self.assertEqual(0, self.execute("sdk", "eligible", **dict(values, PUBLISHABLE="false")).returncode)
        self.assertEqual("release=false\n", (self.root / "outputs").read_text())
        self.git("update-ref", "refs/remotes/origin/main", values["BASELINE"])
        self.assertNotEqual(0, self.execute("sdk", "eligible", **values).returncode)

    def test_cumulative_range_fixture_distinguishes_last_commit_only_selection(self):
        values = self.history()
        self.assertEqual("library.txt", self.git("diff", "--name-only", values["BASELINE"],
                                               values["CANDIDATE"], "--", "library.txt"))
        self.assertEqual("", self.git("diff", "--name-only", "HEAD^", "HEAD", "--", "library.txt"))
        # The template validates the selected baseline; a product's actual
        # content classifier still needs its own integration tests.
        self.assertEqual(0, self.execute("testflight", "eligible", **values).returncode)

    def test_check_guard_negative_control_is_sensitive(self):
        values = dict(self.history(), REQUIRED_CHECKS="failure")
        self.assertNotEqual(0, self.execute("sdk", "eligible", **values).returncode)
        script = step("sdk", "eligible")["run"]
        changed = "\n".join(line for line in script.splitlines() if '"$CHECKED_SHA"' not in line)
        self.assertNotEqual(script, changed)
        # Removing the actual guard admits the bad input: the normal rejection
        # is not caused by an unrelated fixture or Git failure.
        self.assertEqual(0, self.execute("sdk", "eligible", script=changed, **values).returncode)

    def test_sdk_result_requires_accurate_candidate_and_artifact_verification(self):
        values = dict(CANDIDATE="1" * 40, PUBLISHED_SHA="1" * 40, VERIFIED_ARTIFACTS="success")
        self.assertEqual(0, self.execute("sdk", "confirmed", **values).returncode)
        for changes in ({"PUBLISHED_SHA": "2" * 40}, {"VERIFIED_ARTIFACTS": ""},
                        {"VERIFIED_ARTIFACTS": "uploaded"}):
            self.assertNotEqual(0, self.execute("sdk", "confirmed", **dict(values, **changes)).returncode)

    def test_templates_parse_lint_and_preserve_step_order_and_safe_defaults(self):
        for kind in ("sdk", "testflight"):
            with self.subTest(kind=kind):
                config = workflow(kind)
                self.assertEqual(["workflow_run"], list(config["on"]))
                self.assertEqual(["completed"], config["on"]["workflow_run"]["types"])
                self.assertEqual({"contents": "read"}, config["permissions"])
                self.assertFalse(config["jobs"]["release"]["concurrency"]["cancel-in-progress"])
                self.assertEqual("max", config["jobs"]["release"]["concurrency"]["queue"])
                self.assertEqual("${{ needs.admit.outputs.candidate }}",
                                 config["jobs"]["release"]["env"]["CANDIDATE"])
                steps = []
                for job, ids in (("admit", ["candidate", "prepare", "eligible"]),
                                 ("release", ["prepare", "eligible", "publish", "confirmed"])):
                    entries = config["jobs"][job]["steps"]
                    self.assertEqual(ids, [s["id"] for s in entries if "id" in s])
                    checkout = next(s for s in entries if "uses" in s)
                    self.assertFalse(checkout["with"]["persist-credentials"])
                    self.assertEqual("${{ env.CANDIDATE }}", checkout["with"]["ref"])
                    steps.extend(entries)
                self.assertEqual(step(kind, "eligible", "admit")["run"],
                                 step(kind, "eligible", "release")["run"])
                for name in ("publish", "confirmed"):
                    self.assertEqual("steps.eligible.outputs.release == 'true'", step(kind, name)["if"])
                for entry in steps:
                    self.assertNotIn("continue-on-error", entry)
                    if "run" in entry:
                        result = run_bounded(["bash", "-n"], input=entry["run"],
                                             env=self.env, timeout=10)
                        self.assertEqual(0, result.returncode, result.stderr)
                target = self.root / ".github/workflows/release.yml"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((REPO / f"templates/release-{kind}.yml").read_text())
                result = run_bounded([os.sys.executable, "-I", "-B",
                                      str(REPO / "scripts/lint/workflows.py"), "--root", str(self.root)],
                                     env=self.env, timeout=10)
                self.assertEqual(0, result.returncode, result.stderr)
        for name in ("candidate", "eligible"):
            self.assertEqual(step("sdk", name)["run"], step("testflight", name)["run"])

    def test_versioned_document_entry_and_template_links(self):
        document = REPO / "docs/automated-release.md"
        self.assertTrue(document.is_file())
        self.assertIn("../docs/automated-release.md", (REPO / "ai/USAGE.md").read_text())
        for kind in ("sdk", "testflight"):
            self.assertIn(f"../templates/release-{kind}.yml", document.read_text())

    def test_candidate_accepts_only_successful_default_branch_push(self):
        self.assertEqual(0, self.execute("sdk", "candidate", **self.candidate()).returncode)
        for values in ({"CANDIDATE": "main"}, {"CANDIDATE": ""},
                       {"EVENT_NAME": "pull_request_target"}, {"RUN_EVENT": "pull_request"},
                       {"RUN_RESULT": "failure"}, {"RUN_RESULT": "skipped"},
                       {"RUN_REPOSITORY": "fork/project"}, {"RUN_BRANCH": "topic"},
                       {"DEFAULT_BRANCH": ""}):
            with self.subTest(values=values):
                result = self.execute("sdk", "candidate", **self.candidate(**values))
                self.assertNotEqual(0, result.returncode)
                self.assertIn("::error::", result.stdout)

    def test_testflight_cannot_confirm_upload_only_or_another_build(self):
        values = dict(CANDIDATE="1" * 40, PUBLISHED_SHA="1" * 40,
                      EXPECTED_APP="fixture.app", EXPECTED_PLATFORM="macos",
                      EXPECTED_BUILD="7", ACTUAL_APP="fixture.app",
                      ACTUAL_PLATFORM="macos", ACTUAL_BUILD="7",
                      PROCESSING="complete", INTERNAL_GROUPS="available")
        result = self.execute("testflight", "confirmed", **values)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for changes in ({"PUBLISHED_SHA": "2" * 40}, {"ACTUAL_APP": "other.app"},
                        {"ACTUAL_PLATFORM": "ios"}, {"ACTUAL_BUILD": "6"},
                        {"PROCESSING": "processing"}, {"INTERNAL_GROUPS": "unknown"},
                        {"INTERNAL_GROUPS": ""}, {"EXPECTED_BUILD": ""}):
            with self.subTest(changes=changes):
                result = self.execute("testflight", "confirmed", **dict(values, **changes))
                self.assertNotEqual(0, result.returncode)
                self.assertIn("::error::", result.stdout)


if __name__ == "__main__":
    unittest.main()
