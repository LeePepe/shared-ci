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

    def test_kimi_probe_dependency_preserves_required_fork_guard(self):
        text = (REPO / ".github/workflows/kimi-review.yml").read_text()
        self.assertEqual([], kinds(text))
        # Probe + execution now share one self-hosted job. The completion-only
        # job is hosted, with no checkout and no permissions.
        self.assertEqual(["self_hosted_unguarded"],
                         kinds(text.replace(GUARD, "needs.kimi-execute.outputs.completed == 'true'")))

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


class RunnerContextTests(unittest.TestCase):
    def workflow(self, fields):
        return "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n" + fields

    def test_job_env_fixture_reports_location(self):
        text = (REPO / "tests/lint/fixtures/runner-job-env.yml").read_text()
        found = lint.lint_text("w.yml", text)
        self.assertEqual(1, len(found))
        self.assertEqual("runner_context_unavailable", found[0]["kind"])
        self.assertEqual("w.yml#jobs.build.env.X", found[0]["path"])

    def test_step_env_fixture_is_legal(self):
        text = (REPO / "tests/lint/fixtures/runner-step-env.yml").read_text()
        self.assertEqual([], kinds(text))

    def test_other_unavailable_job_locations(self):
        fields = [
            "    name: ${{ runner.os }}\n",
            "    if: ${{ runner.os == 'Linux' }}\n",
            "    if: runner.os == 'Linux'\n",
            "    concurrency: ${{ runner.name }}\n",
            "    continue-on-error: ${{ runner.os == 'Linux' }}\n",
            "    timeout-minutes: ${{ runner.os == 'Linux' && 30 || 10 }}\n",
            "    strategy:\n      matrix:\n        os: ['${{ runner.os }}']\n",
            "    defaults:\n      run:\n        working-directory: ${{ runner.temp }}\n",
            "    container:\n      image: ${{ runner.os }}\n",
            "    container:\n      credentials:\n        username: ${{ runner.name }}\n",
            "    services:\n      db:\n        image: ${{ runner.os }}\n",
            "    services:\n      db:\n        credentials:\n          username: ${{ runner.name }}\n",
            "    environment:\n      name: ${{ runner.environment }}\n",
            "    uses: ./.github/workflows/callee.yml\n    with:\n      temp: ${{ runner.temp }}\n",
            "    uses: ./.github/workflows/callee.yml\n    secrets:\n      temp: ${{ runner.temp }}\n",
            "    env:\n      steps: ${{ runner.temp }}\n",
        ]
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(["runner_context_unavailable"], kinds(self.workflow(field)))
        text = self.workflow(f"    if: {GUARD}\n").replace(
            "runs-on: ubuntu-latest", "runs-on: ${{ runner.os }}")
        self.assertEqual(["runner_context_unavailable"], kinds(text))

    def test_unavailable_workflow_locations(self):
        for field in ("env:\n  X: ${{ runner.temp }}\n",
                      "run-name: ${{ runner.name }}\n",
                      "concurrency: ${{ runner.name }}\n"):
            with self.subTest(field=field):
                self.assertEqual(["runner_context_unavailable"], kinds(field + self.workflow("")))

    def test_legal_job_locations(self):
        fields = [
            "    outputs:\n      temp: ${{ runner.temp }}\n",
            "    environment:\n      name: preview\n      url: ${{ runner.temp }}\n",
            "    container:\n      image: alpine\n      env:\n        X: ${{ runner.temp }}\n",
            "    services:\n      db:\n        image: postgres\n        env:\n          X: ${{ runner.temp }}\n",
        ]
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual([], kinds(self.workflow(field)))

    def test_legal_step_locations(self):
        fields = [
            "        name: ${{ runner.name }}\n",
            "        if: ${{ runner.os == 'Linux' }}\n",
            "        env:\n          X: ${{ runner.temp }}\n",
            "        run: echo '${{ runner.temp }}'\n",
            "        with:\n          path: ${{ runner.temp }}\n",
            "        working-directory: ${{ runner.temp }}\n",
            "        continue-on-error: ${{ runner.os == 'Linux' }}\n",
            "        timeout-minutes: ${{ runner.os == 'Linux' && 30 || 10 }}\n",
        ]
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual([], kinds(self.workflow("    steps:\n      - id: check\n" + field)))

    def test_expression_references_and_yaml_shapes(self):
        values = [
            "${{runner.temp}}",
            "${{ runner['temp'] }}",
            "${{ toJSON(runner) }}",
            "${{ RUNNER.temp }}",
            "prefix/${{ format('{0}', runner.temp) }}/suffix",
            "${{ format('}} {0}', runner.temp) }}",
            "${{ format('it''s {0}', runner.temp) }}",
            "${{ vars.directory }}/${{ runner.temp }}",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(["runner_context_unavailable"],
                                 kinds(self.workflow("    env:\n      X: " + value + "\n")))
        for field in ("    env: {X: '${{ runner.temp }}'}\n",
                      "    env:\n      X: >-\n        ${{ format('{0}',\n            runner.temp) }}\n"):
            with self.subTest(field=field):
                self.assertEqual(["runner_context_unavailable"], kinds(self.workflow(field)))

    def test_literals_comments_and_other_context_properties_are_ignored(self):
        values = [
            "runner.temp",
            "literal # ${{ runner.temp }}",
            "${{ 'runner.temp' }}",
            "${{ format('runner.temp: {0}', vars.directory) }}",
            "${{ format('it''s runner.temp') }}",
            "${{ '}} runner.temp' }}",
            "${{ github.event.runner.temp }}",
            "${{ vars.runner }}",
            "${{ vars['runner'] }}",
            "${{ inputs.runner_temp }}",
            "${{ vars.directory }}/runner.temp",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual([], kinds(self.workflow("    env:\n      X: " + value + "\n")))


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

    def test_runner_context_fixtures(self):
        for name, expected_code in (("runner-job-env.yml", 1), ("runner-step-env.yml", 0)):
            with self.subTest(name=name):
                result = self.run_lint({name: (REPO / "tests/lint/fixtures" / name).read_text()})
                self.assertEqual(expected_code, result.returncode, result.stderr)
                self.assertEqual(expected_code == 0, json.loads(result.stdout)["ok"])
                if expected_code:
                    self.assertEqual("runner_context_unavailable", json.loads(result.stderr)["kind"])

    def test_no_workflows_fails_closed(self):
        self.assertEqual(1, self.run_lint({}).returncode)

    def test_shared_ci_own_workflows_are_clean(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--root", str(REPO)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
