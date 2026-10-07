"""Provider completion gate: parse the workflow and execute its actual shell.

These are local configuration/shell checks, not hosted Actions scheduler evidence.
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

import test_review
from test_review import STUB_GH, run_bounded

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
            "types": ["opened", "synchronize", "reopened", "edited"], "branches": ["main"]}},
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
        return run_bounded([self.step()["shell"], "-eu", "-c", self.step()["run"]],
                           env=env, timeout=10)

    def test_actual_inline_shell_syntax(self):
        result = run_bounded([self.step()["shell"], "-n"], input=self.step()["run"],
                             timeout=10)
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
        self.assertEqual({"kimi-execute", "kimi-review"}, set(jobs))
        probe, review = jobs["kimi-execute"], jobs["kimi-review"]
        guard = ("github.event_name == 'pull_request_target' && "
                 "github.event.pull_request.head.repo.full_name == github.repository")
        self.assertEqual(guard, probe["if"])
        self.assertEqual(["kimi-execute"], review["needs"])
        self.assertEqual(guard + " && needs.kimi-execute.outputs.completed == 'true'", review["if"])
        self.assertEqual({"completed": "${{ steps.review.outputs.completed }}"}, probe["outputs"])
        self.assertEqual({"contents": "read", "pull-requests": "write"}, workflow["permissions"])
        self.assertEqual("${{ fromJSON(inputs.runs-on) }}", probe["runs-on"])
        self.assertEqual("ubuntu-latest", review["runs-on"])
        self.assertEqual({}, review["permissions"])
        self.assertEqual(2, review["timeout-minutes"])
        self.assertEqual(1, len(review["steps"]))
        self.assertEqual({"name", "run"}, set(review["steps"][0]))
        for job in (probe, review):
            self.assertIs(True, job["continue-on-error"])
            for step in job["steps"]:
                self.assertNotIn("${{", step.get("run", ""))
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertIn(step["with"]["ref"], (
                        "${{ github.event.pull_request.base.sha }}", "${{ job.workflow_sha }}"))
                if "kimi-review.sh" in step.get("run", ""):
                    self.assertEqual("bash .shared-ci/scripts/review/kimi-review.sh", step["run"])
                    self.assertEqual("review", step["id"])
                    self.assertEqual("steps.probe.outputs.available == 'true'", step["if"])
                    self.assertIs(probe, job, "Probe and execution must share the same runner job")
        check = next(step for step in probe["steps"] if step.get("id") == "probe")
        self.assertEqual("${{ inputs.kimi-bin }}", check["env"]["KIMI_BIN"])
        self.assertIn('command -v "$KIMI_BIN"', check["run"])
        checkouts = [step for step in probe["steps"] if "uses" in step]
        self.assertEqual(2, len(checkouts))
        base, shared = checkouts
        self.assertEqual({"ref": "${{ github.event.pull_request.base.sha }}", "fetch-depth": 0}, base["with"])
        self.assertEqual("steps.probe.outputs.available == 'true'", base["if"])
        self.assertEqual({"repository": "${{ job.workflow_repository }}",
                          "ref": "${{ job.workflow_sha }}", "path": ".shared-ci",
                          "persist-credentials": False}, shared["with"])
        self.assertNotIn("if", shared)
        confirm = next(step for step in probe["steps"] if step["name"] == "Confirm shared-ci revision")
        self.assertNotIn("if", confirm)
        execution = next(step for step in probe["steps"] if step.get("id") == "review")
        self.assertLess(probe["steps"].index(check), probe["steps"].index(execution))
        self.assertLess(probe["steps"].index(confirm), probe["steps"].index(execution))
        publish = next(step for step in probe["steps"] if "post_sticky" in step.get("run", ""))
        self.assertEqual("steps.probe.outputs.available == 'false'", publish["if"])
        inputs = workflow["on"]["workflow_call"]["inputs"]
        self.assertEqual({"runs-on", "kimi-bin", "kimi-model", "rules-file",
                          "max-diff-bytes", "timeout-minutes"}, set(inputs))
        self.assertTrue(all(not value.get("required", False) for value in inputs.values()))

    def test_actual_probe_shell_and_unavailable_sticky_comment(self):
        steps = self.workflow["jobs"]["kimi-execute"]["steps"]
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
                    result = run_bounded(["/bin/bash", "-e", "-o", "pipefail", "-c", check["run"]],
                                         cwd=root, env=env, timeout=10)
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
                    result = run_bounded(["/bin/bash", "-e", "-o", "pipefail", "-c", publish["run"]],
                                         cwd=root, env=env, timeout=10)
                    self.assertEqual(0, result.returncode, result.stderr)
                    comment = (root / "attempted-comment").read_text()
                    self.assertTrue(comment.startswith("<!-- shared-ci-kimi-review -->\n## kimi review unavailable\n"))
                    self.assertNotIn("review: pass", comment)
                    self.assertIn("does not block merge", comment)
                    self.assertEqual("PATCH\nPOST\n" if failure else "PATCH\n" if comment_id else "POST\n",
                                     (root / "publish-attempts").read_text())


class KimiExecutionCompletionTests(unittest.TestCase):
    """Run the real probe and wrapper, then resolve the final job's condition.

    Only this workflow's equality/conjunction subset is evaluated here. This
    locks its output wiring, not the hosted Actions scheduler's implementation.
    """

    def setUp(self):
        self.jobs = frontmatter.parse(
            (REPO / ".github/workflows/kimi-review.yml").read_text())["jobs"]
        self.fixture = test_review.ReviewScriptEndToEndTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def final_result(self, step_outputs, execution_result="success"):
        values = {"github.event_name": "pull_request_target",
                  "github.event.pull_request.head.repo.full_name": "o/r",
                  "github.repository": "o/r"}
        for job_id, job in self.jobs.items():
            values[f"needs.{job_id}.result"] = execution_result
            for name, expression in job.get("outputs", {}).items():
                self.assertTrue(expression.startswith("${{ steps."))
                self.assertTrue(expression.endswith(" }}"))
                _, step, _, output = expression[4:-3].split(".")
                values[f"needs.{job_id}.outputs.{name}"] = step_outputs.get(step, {}).get(output, "")

        def value(term):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            return values[term]  # Unknown/new expression syntax fails the test.

        enabled = all(value(left) == value(right) for left, right in (
            clause.split(" == ") for clause in self.jobs["kimi-review"]["if"].split(" && ")))
        return execution_result if enabled else "skipped"

    def run_execution(self, *, remove_cli=False, raw=None, **overrides):
        fixture = self.fixture
        probe = next(step for job in self.jobs.values() for step in job["steps"]
                     if step.get("id") == "probe")
        execution = next(step for job in self.jobs.values() for step in job["steps"]
                         if "kimi-review.sh" in step.get("run", ""))
        self.assertEqual("bash .shared-ci/scripts/review/kimi-review.sh", execution["run"])
        binary, output = fixture.tools / "kimi", fixture.out / "probe-output"
        for name in ("probe-output", "review-output", "prompt"):
            (fixture.out / name).unlink(missing_ok=True)
        result = run_bounded(["/bin/bash", "-e", "-o", "pipefail", "-c", probe["run"]],
                             env=dict(fixture.repo.env, KIMI_BIN=str(binary),
                                      GITHUB_OUTPUT=str(output)), timeout=10)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("available=true\n", output.read_text())
        self.assertFalse((fixture.out / "prompt").exists())
        if remove_cli:
            binary.unlink()  # Available at probe time, absent in the actual execution environment.
        completion = fixture.out / "review-output"
        result, comment = fixture.run_script(
            "kimi-review.sh", json.dumps(test_review.PASS) if raw is None else raw,
            KIMI_BIN=str(binary), GITHUB_OUTPUT=str(completion), **overrides)
        self.assertEqual(0, result.returncode, result.stderr)  # Still advisory.
        outputs = (dict(line.split("=", 1) for line in completion.read_text().splitlines())
                   if completion.exists() else {})
        final = self.final_result({"probe": {"available": "true"}, execution.get("id", ""): outputs})
        return final, result, comment

    def test_probe_available_but_execution_cli_missing_never_reports_success(self):
        final, result, comment = self.run_execution(remove_cli=True)
        self.fixture.assert_kimi_unavailable(result, comment, "kimi CLI is not installed on the runner")
        self.assertFalse((self.fixture.out / "prompt").exists())
        self.assertEqual("skipped", final, "An advisory exit 0 is not a completed model review")

    def test_unavailable_and_empty_diff_do_not_claim_model_completion(self):
        for overrides in ({"raw": "junk"}, {"fail": "1"},
                          {"REVIEW_RULES_FILE": "missing.md"}, {"HEAD_SHA": self.fixture.base},
                          {"raw": "junk", "STUB_PUBLISH_FAIL": "all"}):
            with self.subTest(overrides=overrides):
                final, _, _ = self.run_execution(**overrides)
                self.assertEqual("skipped", final)

    def test_valid_pass_and_findings_complete_even_if_comment_publication_fails(self):
        for verdict in (test_review.PASS, test_review.CHANGES):
            for failure in ("", "all"):
                with self.subTest(verdict=verdict["verdict"], publication=failure):
                    final, result, _ = self.run_execution(raw=json.dumps(verdict), STUB_PUBLISH_FAIL=failure)
                    self.assertEqual("success", final)
                    self.assertIn("advisory complete", result.stdout)

    def test_absent_or_nontrue_completion_never_enables_final_check(self):
        for completed in ("", "false", "unknown", "True"):
            with self.subTest(completed=completed):
                self.assertEqual("skipped", self.final_result(
                    {"probe": {"available": "true"}, "review": {"completed": completed}}))


class ReviewEditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflows = {
            path: frontmatter.parse((REPO / path).read_text())
            for path in (".github/workflows/review.yml", "templates/review.yml")
        }

    def test_review_events_include_all_input_edits(self):
        for path, workflow in self.workflows.items():
            with self.subTest(workflow=path):
                self.assertEqual(
                    ["opened", "synchronize", "reopened", "edited"],
                    workflow["on"]["pull_request_target"]["types"])

    def test_review_callers_and_gate_never_skip_based_on_event(self):
        for path, workflow in self.workflows.items():
            for job_id in ("codex-review-target", "codex-review-gate", "kimi-review"):
                with self.subTest(workflow=path, job=job_id):
                    self.assertIn(job_id, workflow["jobs"])
                    condition = workflow["jobs"][job_id].get("if", "")
                    self.assertNotRegex(
                        condition, r"\bgithub\s*\.\s*(?:event|event_name)\b",
                        "Title/body/base edits must not skip review or its required gate")

    def test_both_gates_always_wait_for_codex_and_use_same_fail_closed_gate(self):
        provider_gate = self.workflows[".github/workflows/review.yml"]["jobs"][
            "codex-review-gate"]
        for path, workflow in self.workflows.items():
            with self.subTest(workflow=path):
                self.assertIn("codex-review-gate", workflow["jobs"])
                gate = workflow["jobs"]["codex-review-gate"]
                self.assertEqual("${{ always() }}", gate["if"])
                self.assertEqual(["codex-review-target"], gate["needs"])
                # CompletionGateTests executes this exact gate's shell for
                # success and every non-success result, including cancellation.
                self.assertEqual(provider_gate, gate)

    def test_superseded_runs_are_cancelled_per_pull_request(self):
        for path, workflow in self.workflows.items():
            with self.subTest(workflow=path):
                self.assertEqual({
                    "group": "review-${{ github.event.pull_request.number }}",
                    "cancel-in-progress": True,
                }, workflow["concurrency"])


if __name__ == "__main__":
    unittest.main()
