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
        self.assertEqual({"workflow_call", "workflow_dispatch"}, set(workflow["on"]))
        self.assertEqual(PERMISSIONS, workflow["permissions"])
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        for event in ("workflow_call", "workflow_dispatch"):
            inputs = workflow["on"][event]["inputs"]
            self.assertEqual({"failure-hours", "open-hours", "stale-days", "draft-days", "auto-merge-grace-minutes", "thread-hours", "mention-allowlist", "summary-assignee", "exclude-prs", "auto-merge-exempt-prs"}, set(inputs))
            for key, default in (("failure-hours", 2), ("open-hours", 24), ("stale-days", 14), ("draft-days", 7), ("auto-merge-grace-minutes", 30), ("thread-hours", 24), ("mention-allowlist", ""), ("summary-assignee", ""), ("exclude-prs", ""), ("auto-merge-exempt-prs", "")):
                self.assertEqual("string" if isinstance(default, str) else "number", inputs[key]["type"])
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
        expected_env = {"FAILURE_HOURS": "${{ inputs.failure-hours }}", "OPEN_HOURS": "${{ inputs.open-hours }}",
                        "STALE_DAYS": "${{ inputs.stale-days }}", "DRAFT_DAYS": "${{ inputs.draft-days }}",
                        "AUTO_MERGE_GRACE_MINUTES": "${{ inputs.auto-merge-grace-minutes }}", "THREAD_HOURS": "${{ inputs.thread-hours }}",
                        "MENTION_ALLOWLIST": "${{ inputs.mention-allowlist }}", "SUMMARY_ASSIGNEE": "${{ inputs.summary-assignee }}",
                        "EXCLUDE_PRS": "${{ inputs.exclude-prs }}", "AUTO_MERGE_EXEMPT_PRS": "${{ inputs.auto-merge-exempt-prs }}",
                        "GITHUB_TOKEN": "${{ github.token }}"}
        self.assertEqual(expected_env, report["env"])

    def test_caller_owns_manual_trigger_and_uses_full_sha_placeholder(self):
        text = (REPO / "templates/stuck-pr-bot.yml").read_text()
        caller = yaml.parse(text.replace("<40-char-sha>", "1" * 40))
        self.assertEqual({"workflow_dispatch"}, set(caller["on"]))
        self.assertIn("cron: '7,37 * * * *'", text)
        self.assertIn("unique pair of minutes", text)
        self.assertEqual(PERMISSIONS, caller["permissions"])
        job = caller["jobs"]["report"]
        self.assertEqual("LeePepe/shared-ci/.github/workflows/stuck-pr-bot.yml@" + "1" * 40, job["uses"])
        self.assertEqual({"failure-hours": 2, "open-hours": 24, "stale-days": 14, "draft-days": 7,
                          "auto-merge-grace-minutes": 30, "thread-hours": 24, "mention-allowlist": "",
                          "summary-assignee": "", "exclude-prs": "", "auto-merge-exempt-prs": ""}, job["with"])
        self.assertNotIn("secrets", job)
