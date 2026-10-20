"""Source trust and privilege contract for the report-only reusable workflow."""
import importlib.util
import unittest

from fixture import REPO

SPEC = importlib.util.spec_from_file_location("stuck_workflow_yaml", REPO / "scripts/context/_frontmatter.py")
yaml = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(yaml)
PERMISSIONS = {"contents": "read", "checks": "read", "pull-requests": "write", "issues": "write"}


class StuckWorkflowTests(unittest.TestCase):
    def test_reusable_schedule_inputs_permissions_and_provider_only_checkout(self):
        workflow = yaml.parse((REPO / ".github/workflows/stuck-pr-bot.yml").read_text())
        self.assertEqual({"workflow_call", "workflow_dispatch", "schedule"}, set(workflow["on"]))
        self.assertEqual([{"cron": "17 * * * *"}], workflow["on"]["schedule"])
        self.assertEqual(PERMISSIONS, workflow["permissions"])
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        for event in ("workflow_call", "workflow_dispatch"):
            inputs = workflow["on"][event]["inputs"]
            self.assertEqual({"failure-hours", "open-hours"}, set(inputs))
            for key, default in (("failure-hours", 2), ("open-hours", 24)):
                self.assertEqual("number", inputs[key]["type"])
                self.assertEqual(default, inputs[key]["default"])
        self.assertEqual({"report"}, set(workflow["jobs"]))
        job = workflow["jobs"]["report"]
        self.assertEqual("ubuntu-latest", job["runs-on"])
        checkout, confirm, report = job["steps"]
        self.assertEqual({"repository": "${{ job.workflow_repository }}", "ref": "${{ job.workflow_sha }}",
                          "path": ".shared-ci", "persist-credentials": False}, checkout["with"])
        self.assertRegex(checkout["uses"], r"^actions/checkout@[0-9a-f]{40}$")
        self.assertEqual({"WORKFLOW_REPOSITORY": "${{ job.workflow_repository }}",
                          "WORKFLOW_SHA": "${{ job.workflow_sha }}"}, confirm["env"])
        self.assertIn('git -C .shared-ci rev-parse HEAD', confirm["run"])
        self.assertIn('"${#WORKFLOW_SHA}" -eq 40', confirm["run"])
        self.assertIn('exit 1', confirm["run"])
        self.assertEqual("python3 -I -B .shared-ci/scripts/stuck_pr/bot.py", report["run"])
        self.assertEqual({"GITHUB_TOKEN": "${{ github.token }}", "FAILURE_HOURS": "${{ inputs.failure-hours }}",
                          "OPEN_HOURS": "${{ inputs.open-hours }}"}, report["env"])

    def test_caller_preserves_hourly_manual_schedule_and_uses_full_sha_placeholder(self):
        text = (REPO / "templates/stuck-pr-bot.yml").read_text()
        caller = yaml.parse(text.replace("<40-char-sha>", "1" * 40))
        self.assertEqual({"schedule", "workflow_dispatch"}, set(caller["on"]))
        self.assertEqual([{"cron": "17 * * * *"}], caller["on"]["schedule"])
        self.assertEqual(PERMISSIONS, caller["permissions"])
        job = caller["jobs"]["report"]
        self.assertEqual("LeePepe/shared-ci/.github/workflows/stuck-pr-bot.yml@" + "1" * 40, job["uses"])
        self.assertEqual({"failure-hours": 2, "open-hours": 24}, job["with"])
        self.assertNotIn("secrets", job)
