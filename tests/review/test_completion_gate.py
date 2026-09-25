"""Provider completion gate: parse the workflow and execute its actual shell.

These are local configuration/shell checks, not hosted Actions scheduler evidence.
"""
import importlib.util
import os
import pathlib
import subprocess
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gate_frontmatter", REPO / "scripts" / "context" / "_frontmatter.py")
frontmatter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontmatter)
PIN = "9ff304e317a5ff924a4c488515ead5a607d28236"


class CompletionGateTests(unittest.TestCase):
    def setUp(self):
        self.workflow = frontmatter.parse(
            (REPO / ".github" / "workflows" / "review.yml").read_text())
        self.jobs = self.workflow["jobs"]

    def gate(self):
        self.assertIn("codex-review-gate", self.jobs,
                      "A skipped Codex caller needs an always-running completion gate")
        return self.jobs["codex-review-gate"]

    def step(self):
        steps = self.gate()["steps"]
        self.assertEqual(1, len(steps))
        step = steps[0]
        self.assertEqual({"name", "shell", "env", "run"}, set(step))
        self.assertEqual("sh", step["shell"])
        self.assertEqual(
            {"CODEX_RESULT": "${{ needs.codex-review-target.result }}"}, step["env"])
        self.assertNotIn("${{", step["run"], "Result must be data, not interpolated shell")
        return step

    def test_gate_runs_always_and_waits_only_for_codex(self):
        gate = self.gate()
        self.assertEqual(
            {"if", "needs", "runs-on", "permissions", "timeout-minutes", "steps"},
            set(gate))  # No renamed check, continue-on-error, matrix or extra dependency.
        self.assertEqual("${{ always() }}", gate["if"])
        self.assertEqual(["codex-review-target"], gate["needs"])
        self.assertEqual("ubuntu-latest", gate["runs-on"])
        self.assertEqual({}, gate["permissions"])
        self.assertEqual(2, gate["timeout-minutes"])
        self.step()  # No checkout, action, secrets, model, or conditional step.

    def test_review_trigger_and_conditional_pinned_callers_are_preserved(self):
        self.assertEqual({"pull_request_target": {
            "types": ["opened", "synchronize", "reopened"], "branches": ["main"]}},
            self.workflow["on"])
        self.assertEqual({"codex-review-target", "codex-review-gate", "kimi-review"},
                         set(self.jobs))
        for job_id, filename in (("codex-review-target", "codex-review.yml"),
                                 ("kimi-review", "kimi-review.yml")):
            with self.subTest(job=job_id):
                job = self.jobs[job_id]
                self.assertEqual({"if", "uses"}, set(job))
                self.assertEqual("vars.SHARED_CI_REVIEW_RUNNER == 'true'", job["if"])
                self.assertTrue(job["uses"].endswith(
                    "/.github/workflows/" + filename + "@" + PIN))
                self.assertEqual(
                    self.jobs["codex-review-target"]["uses"].split("/.github/")[0],
                    job["uses"].split("/.github/")[0])

    def test_reusable_codex_retains_trusted_base_and_fork_boundary(self):
        workflow = frontmatter.parse(
            (REPO / ".github" / "workflows" / "codex-review.yml").read_text())
        codex = workflow["jobs"]["codex-review"]
        self.assertEqual(
            "github.event_name == 'pull_request_target' && "
            "github.event.pull_request.head.repo.full_name == github.repository",
            codex["if"])
        self.assertEqual("${{ fromJSON(inputs.runs-on) }}", codex["runs-on"])
        self.assertEqual('["self-hosted", "macOS", "ARM64"]',
                         workflow["on"]["workflow_call"]["inputs"]["runs-on"]["default"])
        checkouts = [step["with"] for step in codex["steps"]
                     if step.get("uses", "").startswith("actions/checkout@")]
        self.assertEqual(2, len(checkouts))
        self.assertEqual("${{ github.event.pull_request.base.sha }}", checkouts[0]["ref"])
        self.assertEqual("${{ job.workflow_sha }}", checkouts[1]["ref"])
        self.assertEqual("${{ job.workflow_repository }}", checkouts[1]["repository"])

    def run_gate(self, result):
        env = dict(os.environ)
        env.pop("CODEX_RESULT", None)
        if result is not None:
            env["CODEX_RESULT"] = result
        return subprocess.run([self.step()["shell"], "-eu", "-c", self.step()["run"]],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_actual_inline_shell_syntax(self):
        result = subprocess.run([self.step()["shell"], "-n"], input=self.step()["run"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_explicit_success_passes(self):
        result = self.run_gate("success")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Codex review completed successfully", result.stdout)

    def test_disabled_runner_or_any_non_success_fails_closed(self):
        for value in ("skipped", "failure", "cancelled", "", None, "unknown", "neutral",
                      "timed_out", "action_required", "Success", "success ", " success",
                      "success\nfailure", "$(exit 0)", "success; exit 0"):
            with self.subTest(result=value):
                result = self.run_gate(value)
                self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                self.assertIn("::error::", result.stdout)
                self.assertIn("SHARED_CI_REVIEW_RUNNER", result.stdout)
                self.assertIn("re-run", result.stdout)
                self.assertIn("Owner approval and Kimi", result.stdout)


if __name__ == "__main__":
    unittest.main()
