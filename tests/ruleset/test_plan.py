"""Ruleset plan/verify: synthetic fixtures only; never calls the live API."""
import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ruleset" / "plan.py"
SPEC = importlib.util.spec_from_file_location("ruleset_plan", SCRIPT)
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)
TEMPLATE = json.loads((REPO / "templates" / "ruleset.json").read_text())
AGGREGATE, CODEX = "quality / aggregate", "codex-review-target / codex-review"
LEGACY = ["SPM Core", "App target", "Lint & policy", "codex-review-target"]


def existing_ruleset(checks=LEGACY, ruleset_id=101, **pr):
    parameters = {"required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
                  "required_reviewers": [], "require_code_owner_review": False,
                  "require_last_push_approval": False, "required_review_thread_resolution": False,
                  "require_extra_approval_for_unattributed_changes": True,
                  "allowed_merge_methods": ["squash", "merge", "rebase"]}
    parameters.update(pr)
    return {"id": ruleset_id, "name": "main protection", "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
            "bypass_actors": [], "rules": [
                {"type": "deletion"}, {"type": "non_fast_forward"},
                {"type": "pull_request", "parameters": parameters},
                {"type": "required_status_checks", "parameters": {
                    "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": c} for c in checks]}}]}


def effective(ruleset):
    return [dict(rule, ruleset_id=ruleset["id"], ruleset_source_type="Repository",
                 ruleset_source="o/r") for rule in ruleset["rules"]]


def run_plan(current, rulesets, detail, **options):
    return planner.plan(TEMPLATE, current, rulesets, detail, extra=options.get("extra", []),
                        maps=options.get("maps", {}), strict=options.get("strict", False),
                        code_owner=options.get("code_owner", True))


class CreateTests(unittest.TestCase):
    def test_empty_repository_creates_template(self):
        result = run_plan([], [], None)
        self.assertEqual(("create", None), (result["action"], result["ruleset_id"]))
        self.assertEqual([AGGREGATE, CODEX], result["diff"]["checks_new"])
        rules = {r["type"]: r for r in result["payload"]["rules"]}
        self.assertEqual({"deletion", "non_fast_forward", "pull_request", "required_status_checks"}, set(rules))
        self.assertTrue(rules["pull_request"]["parameters"]["require_code_owner_review"])
        self.assertFalse(rules["required_status_checks"]["parameters"]["strict_required_status_checks_policy"])
        self.assertEqual([], result["payload"]["bypass_actors"])


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.ruleset = existing_ruleset()
        self.current = effective(self.ruleset)
        self.list = [{"id": 101, "name": "main protection"}]

    def test_existing_checks_preserved(self):
        result = run_plan(self.current, self.list, self.ruleset)
        self.assertEqual("update", result["action"])
        self.assertEqual([AGGREGATE, CODEX] + LEGACY, result["diff"]["checks_new"])
        self.assertEqual([], result["diff"]["checks_removed"])
        self.assertEqual([AGGREGATE, CODEX], result["diff"]["checks_added"])

    def test_explicit_map_replaces_and_removes(self):
        result = run_plan(self.current, self.list, self.ruleset,
                          maps={"codex-review-target": CODEX, "Lint & policy": ""})
        self.assertEqual([AGGREGATE, CODEX, "SPM Core", "App target"], result["diff"]["checks_new"])
        self.assertEqual(["Lint & policy", "codex-review-target"], result["diff"]["checks_removed"])

    def test_map_of_unknown_check_is_rejected(self):
        with self.assertRaises(planner.PlanError):
            run_plan(self.current, self.list, self.ruleset, maps={"not-required": "x"})

    def test_extra_checks_strict_and_code_owner_opt_out(self):
        result = run_plan(self.current, self.list, self.ruleset, extra=["iOS build"], strict=True, code_owner=False)
        self.assertIn("iOS build", result["diff"]["checks_new"])
        rules = {r["type"]: r for r in result["payload"]["rules"]}
        self.assertTrue(rules["required_status_checks"]["parameters"]["strict_required_status_checks_policy"])
        self.assertFalse(rules["pull_request"]["parameters"]["require_code_owner_review"])

    def test_rule_parameter_diff_is_reported(self):
        changes = run_plan(self.current, self.list, self.ruleset)["diff"]["rules"]
        self.assertIn("~ pull_request.require_code_owner_review: false -> true", changes)
        self.assertIn("~ required_status_checks.strict_required_status_checks_policy: true -> false", changes)

    def test_unmanaged_parameters_and_rules_are_kept(self):
        self.ruleset["rules"].append({"type": "required_signatures"})
        result = run_plan(effective(self.ruleset), self.list, self.ruleset)
        rules = {r["type"]: r for r in result["payload"]["rules"]}
        self.assertIn("required_signatures", rules)
        self.assertTrue(rules["pull_request"]["parameters"]["require_extra_approval_for_unattributed_changes"])

    def test_applied_state_is_noop(self):
        first = run_plan(self.current, self.list, self.ruleset)
        applied = dict(copy.deepcopy(first["payload"]), id=101)
        second = run_plan(effective(applied), self.list, applied)
        self.assertEqual("noop", second["action"])
        self.assertEqual([], second["diff"]["checks_added"] + second["diff"]["checks_removed"])

    def test_checks_from_other_rulesets_preserved_and_reported(self):
        other = existing_ruleset(checks=["org check"], ruleset_id=202)
        other["name"] = "org rules"
        result = run_plan(self.current + effective(other), self.list + [{"id": 202, "name": "org rules"}], self.ruleset)
        self.assertIn("org check", result["diff"]["checks_new"])
        self.assertEqual([202], result["other_rulesets"])

    def test_inconsistent_inputs_rejected(self):
        with self.assertRaises(planner.PlanError):
            run_plan(self.current, self.list, None)                      # detail missing
        with self.assertRaises(planner.PlanError):
            run_plan(self.current, self.list + [{"id": 303, "name": "main protection"}], self.ruleset)
        with self.assertRaises(planner.PlanError):
            run_plan({"not": "a list"}, self.list, self.ruleset)


class VerifyTests(unittest.TestCase):
    def test_readback_matches_and_mismatches(self):
        result = run_plan([], [], None)
        applied = dict(result["payload"], id=404)
        self.assertEqual([], planner.verify(result, effective(applied)))
        broken = copy.deepcopy(applied)
        broken["rules"][-1]["parameters"]["required_status_checks"] = [{"context": AGGREGATE}]
        self.assertEqual([f"required check missing after apply: {CODEX}"], planner.verify(result, effective(broken)))
        self.assertIn("rule missing after apply: deletion", planner.verify(result, effective(broken)[1:]))


class CliTests(unittest.TestCase):
    def test_cli_plan_and_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            ruleset = existing_ruleset()
            for name, data in (("current", effective(ruleset)), ("rulesets", [{"id": 101, "name": "main protection"}]),
                               ("detail", ruleset)):
                (root / f"{name}.json").write_text(json.dumps(data))
            argv = [sys.executable, "-I", "-B", str(SCRIPT), "--current", str(root / "current.json"),
                    "--rulesets", str(root / "rulesets.json"), "--detail", str(root / "detail.json")]
            result = subprocess.run(argv + ["--summary", "--map", "codex-review-target=" + CODEX],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("- codex-review-target", result.stderr)
            (root / "plan.json").write_text(result.stdout)
            verify = subprocess.run(argv + ["--verify", str(root / "current.json"), "--plan", str(root / "plan.json")],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(1, verify.returncode)  # old state lacks the new checks
            bad = subprocess.run(argv + ["--map", "nope"], capture_output=True, text=True, timeout=20)
            self.assertEqual(2, bad.returncode)

    def test_apply_script_is_dry_run_by_default(self):
        text = (REPO / "scripts/ruleset/apply.sh").read_text()
        self.assertIn('if [ "$apply" -ne 1 ]; then', text)
        dry_run_end = text.index('if [ "$apply" -ne 1 ]; then')
        self.assertNotIn("-X POST", text[:dry_run_end])
        self.assertNotIn("-X PUT", text[:dry_run_end])


if __name__ == "__main__":
    unittest.main()
