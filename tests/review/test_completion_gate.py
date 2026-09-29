"""Provider completion gate: parse the workflow and execute its actual shell.

These are local configuration/shell checks, not hosted Actions scheduler evidence.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from test_review import STUB_GH

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "gate_frontmatter", REPO / "scripts" / "context" / "_frontmatter.py")
frontmatter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontmatter)
PIN = "6e354f476bc53d68f0f09fc231d5cd938466af9c"


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
        codex_inputs = {"codex-bin": "/opt/homebrew/bin/codex",
                        "rules-file": "docs/repository-guide.md", "owner-user-id": "13819054"}
        for job_id, filename, inputs in (
                ("codex-review-target", "codex-review.yml", codex_inputs),
                ("kimi-review", "kimi-review.yml", {"rules-file": "docs/repository-guide.md"})):
            with self.subTest(job=job_id):
                job = self.jobs[job_id]
                self.assertEqual({"if", "uses", "with"}, set(job))
                self.assertEqual(inputs, job["with"])
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


class KimiAvailabilityWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = frontmatter.parse(
            (REPO / ".github" / "workflows" / "kimi-review.yml").read_text())

    def test_missing_cli_skips_review_without_changing_trust_or_permissions(self):
        workflow = self.workflow
        jobs = workflow["jobs"]
        self.assertIn("kimi-probe", jobs)
        probe, review = jobs["kimi-probe"], jobs["kimi-review"]
        guard = ("github.event_name == 'pull_request_target' && "
                 "github.event.pull_request.head.repo.full_name == github.repository")
        self.assertEqual(guard, probe["if"])
        self.assertEqual(["kimi-probe"], review["needs"])
        self.assertEqual(guard + " && needs.kimi-probe.outputs.available == 'true'", review["if"])
        self.assertEqual({"available": "${{ steps.probe.outputs.available }}"}, probe["outputs"])
        self.assertEqual({"contents": "read", "pull-requests": "write"}, workflow["permissions"])
        for job in (probe, review):
            self.assertIs(True, job["continue-on-error"])
            self.assertEqual("${{ fromJSON(inputs.runs-on) }}", job["runs-on"])
            for step in job["steps"]:
                self.assertNotIn("${{", step.get("run", ""))
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertIn(step["with"]["ref"], (
                        "${{ github.event.pull_request.base.sha }}", "${{ job.workflow_sha }}"))
                if "kimi-review.sh" in step.get("run", ""):
                    self.assertEqual("bash .shared-ci/scripts/review/kimi-review.sh", step["run"])
        check = next(step for step in probe["steps"] if step.get("id") == "probe")
        self.assertEqual("${{ inputs.kimi-bin }}", check["env"]["KIMI_BIN"])
        self.assertIn('command -v "$KIMI_BIN"', check["run"])
        shared = next(step for step in probe["steps"] if "uses" in step)
        self.assertEqual({"repository": "${{ job.workflow_repository }}",
                          "ref": "${{ job.workflow_sha }}", "path": ".shared-ci",
                          "persist-credentials": False}, shared["with"])
        for step in probe["steps"][1:]:
            self.assertEqual("steps.probe.outputs.available == 'false'", step["if"])
        inputs = workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual({"runs-on", "kimi-bin", "kimi-model", "rules-file",
                          "max-diff-bytes", "timeout-minutes"}, set(inputs))
        self.assertTrue(all(not value.get("required", False) for value in inputs.values()))

    def test_actual_probe_shell_and_unavailable_sticky_comment(self):
        steps = self.workflow["jobs"]["kimi-probe"]["steps"]
        check = next(step for step in steps if step.get("id") == "probe")
        publish = next(step for step in steps if "post_sticky" in step.get("run", ""))
        with tempfile.TemporaryDirectory(prefix="kimi-probe-") as temp:
            root = pathlib.Path(temp)
            tools = root / "tools"
            tools.mkdir()
            (root / ".shared-ci").symlink_to(REPO, target_is_directory=True)
            (tools / "python3").symlink_to(sys.executable)
            (tools / "gh").write_text(STUB_GH)
            (tools / "gh").chmod(0o755)
            available = tools / "installed kimi"
            available.write_text("#!/bin/sh\nexit 99\n")  # Probe must not execute the CLI.
            available.chmod(0o755)
            env = dict(os.environ, PATH=str(tools), PR_NUMBER="7", BASE_REPO="o/r",
                       HEAD_SHA="a" * 40, STUB_OUT=str(root), STUB_PUBLISH_FAIL="",
                       GITHUB_OUTPUT=str(root / "output"), GITHUB_STEP_SUMMARY=str(root / "summary"))
            for binary, expected in (("kimi", "false"), ("", "false"),
                                     (str(available), "true"), ("$(printf unsafe > injected); kimi", "false")):
                with self.subTest(binary=binary):
                    for name in ("output", "summary"):
                        (root / name).unlink(missing_ok=True)
                    env["KIMI_BIN"] = binary
                    result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", check["run"]],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual("available=" + expected + "\n", (root / "output").read_text())
                    self.assertFalse((root / "injected").exists())
                    if expected == "true":
                        self.assertNotIn("unavailable", result.stdout)
                        self.assertFalse((root / "summary").exists())
                    else:
                        reason = "kimi review unavailable: kimi CLI is not installed on the runner"
                        self.assertIn("::warning::" + reason, result.stdout)
                        self.assertEqual(reason + "\n", (root / "summary").read_text())
            for comment_id, failure in (("", ""), ("123", ""), ("123", "all")):
                with self.subTest(comment_id=comment_id, failure=failure):
                    (root / "publish-attempts").unlink(missing_ok=True)
                    env.update(STUB_COMMENT_ID=comment_id, STUB_PUBLISH_FAIL=failure)
                    result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", publish["run"]],
                                            cwd=root, env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(0, result.returncode, result.stderr)
                    comment = (root / "attempted-comment").read_text()
                    self.assertTrue(comment.startswith("<!-- shared-ci-kimi-review -->\n## kimi review unavailable\n"))
                    self.assertNotIn("review: pass", comment)
                    self.assertIn("does not block merge", comment)
                    self.assertEqual("PATCH\nPOST\n" if failure else "PATCH\n" if comment_id else "POST\n",
                                     (root / "publish-attempts").read_text())


if __name__ == "__main__":
    unittest.main()
