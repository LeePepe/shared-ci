"""workflow-lint positive and negative fixtures."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "lint" / "workflows.py"
SPEC = importlib.util.spec_from_file_location("workflow_lint", SCRIPT)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)
SHA = "0123456789abcdef0123456789abcdef01234567"
GUARD = "github.event.pull_request.head.repo.full_name == github.repository"


def caller(ref):
    return f"""on: pull_request
jobs:
  quality:
    uses: LeePepe/shared-ci/.github/workflows/quality.yml@{ref}
"""


def self_hosted(condition=None, runs_on="[self-hosted, macOS, ARM64]", on="pull_request_target"):
    line = f"    if: {condition}\n" if condition is not None else ""
    return f"""on:
  {on}:
jobs:
  review:
{line}    runs-on: {runs_on}
    steps:
      - uses: actions/checkout@{SHA}
        with:
          ref: ${{{{ github.event.pull_request.base.sha }}}}
"""


def kinds(text):
    return [finding["kind"] for finding in lint.lint_text("w.yml", text)]


class SharedCiRefTests(unittest.TestCase):
    def test_full_sha_accepted(self):
        self.assertEqual([], kinds(caller(SHA)))

    def test_tag_rejected(self):
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(caller("v1.2.0")))

    def test_branch_rejected(self):
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(caller("main")))

    def test_short_sha_rejected(self):
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(caller(SHA[:7])))

    def test_uppercase_sha_rejected(self):
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(caller(SHA.upper())))

    def test_missing_ref_rejected(self):
        self.assertEqual(["shared_ci_ref_not_sha"],
                         kinds("jobs:\n  q:\n    uses: LeePepe/shared-ci/.github/workflows/quality.yml\n"))

    def test_step_level_action_ref_checked(self):
        text = f"on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: leepepe/shared-ci/actions/x@main\n"
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(text))

    def test_quoted_ref_checked(self):
        text = 'jobs:\n  q:\n    uses: "LeePepe/shared-ci/.github/workflows/quality.yml@main"\n'
        self.assertEqual(["shared_ci_ref_not_sha"], kinds(text))

    def test_other_repositories_ignored(self):
        text = "on: push\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/setup-python@v5\n"
        self.assertEqual([], kinds(text))

    def test_local_reusable_workflow_ignored(self):
        self.assertEqual([], kinds("on: workflow_call\njobs:\n  l:\n    uses: ./.github/workflows/workflow-lint.yml\n"))


class ForkGuardTests(unittest.TestCase):
    def test_guarded_self_hosted_accepted(self):
        self.assertEqual([], kinds(self_hosted(GUARD)))

    def test_guard_with_extra_conjunct_accepted(self):
        self.assertEqual([], kinds(self_hosted(f"github.event_name == 'pull_request_target' && {GUARD}")))

    def test_guard_in_expression_syntax_accepted(self):
        self.assertEqual([], kinds(self_hosted("${{ " + GUARD + " }}")))

    def test_missing_guard_rejected(self):
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted()))

    def test_unrelated_condition_rejected(self):
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted("github.actor == 'owner'")))

    def test_disjunction_does_not_count(self):
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted(f"{GUARD} || always()")))

    def test_negated_guard_rejected(self):
        self.assertEqual(["self_hosted_unguarded"],
                         kinds(self_hosted("github.event.pull_request.head.repo.full_name != github.repository")))

    def test_string_label_and_group_forms(self):
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted(runs_on="self-hosted")))
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted(runs_on="{group: mac-runners}")))

    def test_expression_runs_on_treated_as_self_hosted(self):
        self.assertEqual(["self_hosted_unguarded"], kinds(self_hosted(runs_on="${{ fromJSON(inputs.runs-on) }}")))
        self.assertEqual([], kinds(self_hosted(GUARD, runs_on="${{ fromJSON(inputs.runs-on) }}")))

    def test_hosted_runner_needs_no_guard(self):
        self.assertEqual([], kinds(self_hosted(runs_on="ubuntu-latest", on="pull_request")))

    def test_push_trusted_alternative_accepted(self):
        self.assertEqual([], kinds(self_hosted(f"github.event.pull_request == null || {GUARD}", on="push")))


class PullRequestTargetTests(unittest.TestCase):
    def test_head_checkout_rejected(self):
        text = self_hosted(GUARD).replace("pull_request.base.sha", "pull_request.head.sha")
        self.assertEqual(["prt_checks_out_pr_code"], kinds(text))

    def test_head_ref_rejected(self):
        text = self_hosted(GUARD).replace("${{ github.event.pull_request.base.sha }}", "${{ github.head_ref }}")
        self.assertEqual(["prt_checks_out_pr_code"], kinds(text))


class CliTests(unittest.TestCase):
    def run_lint(self, files):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / ".github/workflows").mkdir(parents=True)
            for name, text in files.items():
                (root / ".github/workflows" / name).write_text(text)
            return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--root", str(root)],
                                  capture_output=True, text=True, timeout=20)

    def test_cli_clean_and_failing(self):
        result = self.run_lint({"ci.yml": caller(SHA)})
        self.assertEqual((0, True), (result.returncode, json.loads(result.stdout)["ok"]))
        result = self.run_lint({"ci.yml": caller("main"), "r.yml": self_hosted()})
        self.assertEqual(1, result.returncode)
        found = sorted(json.loads(line)["kind"] for line in result.stderr.splitlines())
        self.assertEqual(["self_hosted_unguarded", "shared_ci_ref_not_sha"], found)

    def test_unparseable_workflow_fails_closed(self):
        result = self.run_lint({"bad.yml": "jobs: [unterminated\n"})
        self.assertEqual(1, result.returncode)
        self.assertIn("workflow_unparseable", result.stderr)

    def test_no_workflows_fails_closed(self):
        self.assertEqual(1, self.run_lint({}).returncode)

    def test_shared_ci_own_workflows_are_clean(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--root", str(REPO)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
