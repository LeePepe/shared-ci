"""Fail-closed aggregate gate: positive and negative fixtures."""
import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quality_gate", REPO / "scripts/quality/gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
ACTIONS = REPO / "scripts/quality/gate_actions.py"
HEAD = "a" * 40
OLD = "b" * 40
LANES = ["verify", "lint", "build", "test", "contract", "workflow-lint"]
SECTIONS = ["Existing behaviour", "Intent", "Compatibility", "Removed or weakened tests or policy", "Test evidence"]
BODY = f"""## Existing behaviour
Parses config once at start-up.

## Intent
Reload config on SIGHUP.

## Compatibility
No API change; rollback by revert.

## Removed or weakened tests or policy
none

## Test evidence
- Command: scripts/verify --all
- Result: pass
- Tested SHA: {HEAD}
"""


def base(**overrides):
    lanes = {name: {"selected": name in ("verify", "contract", "workflow-lint"),
                    "result": "success" if name in ("verify", "contract", "workflow-lint") else "skipped",
                    "tested_sha": HEAD if name in ("verify", "contract", "workflow-lint") else ""}
             for name in LANES}
    data = {"lanes": lanes, "expected_lanes": LANES, "expected_sha": HEAD, "event": "pull_request",
            "check_pr_body": True, "pr_body": BODY, "required_sections": SECTIONS}
    data.update(overrides)
    return data


def with_lane(name, **fields):
    data = base()
    data["lanes"][name].update(fields)
    return data


class AggregatePositiveTests(unittest.TestCase):
    def test_all_green(self):
        result = gate.evaluate(base())
        self.assertEqual(("pass", HEAD, []), (result["verdict"], result["tested_sha"], result["problems"]))

    def test_every_lane_selected_and_green(self):
        data = base()
        for lane in data["lanes"].values():
            lane.update(selected=True, result="success", tested_sha=HEAD)
        self.assertEqual("pass", gate.evaluate(data)["verdict"])

    def test_not_selected_lane_skipped_passes(self):
        self.assertEqual("pass", gate.evaluate(with_lane("build", selected=False, result="skipped"))["verdict"])

    def test_not_selected_lane_success_passes(self):
        self.assertEqual("pass", gate.evaluate(with_lane("build", selected=False, result="success"))["verdict"])

    def test_push_event_skips_pr_body(self):
        self.assertEqual("pass", gate.evaluate(base(event="push", pr_body=None))["verdict"])

    def test_body_check_disabled(self):
        self.assertEqual("pass", gate.evaluate(base(check_pr_body=False, pr_body=""))["verdict"])


class AggregateNegativeTests(unittest.TestCase):
    def assertFails(self, data, fragment):
        result = gate.evaluate(data)
        self.assertEqual("fail", result["verdict"])
        self.assertEqual("", result["tested_sha"])
        self.assertTrue(any(fragment in p for p in result["problems"]), result["problems"])

    def test_selected_failure(self):
        self.assertFails(with_lane("verify", result="failure"), "'failure'")

    def test_selected_cancelled(self):
        self.assertFails(with_lane("verify", result="cancelled"), "'cancelled'")

    def test_selected_unexpected_skip(self):
        self.assertFails(with_lane("contract", result="skipped"), "'skipped'")

    def test_selected_unknown_or_empty_result(self):
        self.assertFails(with_lane("verify", result=""), "'unknown'")
        self.assertFails(with_lane("verify", result="neutral"), "'neutral'")

    def test_unselected_lane_failure(self):
        self.assertFails(with_lane("build", result="failure"), "unselected lane build")

    def test_unselected_lane_cancelled(self):
        self.assertFails(with_lane("build", result="cancelled"), "unselected lane build")

    def test_tested_sha_mismatch(self):
        self.assertFails(with_lane("verify", tested_sha=OLD), f"tested {OLD}")

    def test_tested_sha_missing(self):
        self.assertFails(with_lane("verify", tested_sha=""), "no SHA")

    def test_expected_sha_not_full(self):
        self.assertFails(base(expected_sha="abc123"), "not a full 40-char SHA")

    def test_missing_lane(self):
        data = base()
        del data["lanes"]["lint"]
        self.assertFails(data, "lane lint reported no result")

    def test_unexpected_lane(self):
        data = base()
        data["lanes"]["extra"] = {"selected": False, "result": "skipped"}
        self.assertFails(data, "unexpected lane extra")

    def test_nothing_selected(self):
        data = base()
        for lane in data["lanes"].values():
            lane.update(selected=False, result="skipped")
        self.assertFails(data, "no lane was selected")

    def test_malformed_input_raises(self):
        for bad in ({}, {"lanes": {}, "expected_lanes": [], "expected_sha": HEAD},
                    base(check_pr_body="yes")):
            with self.assertRaises(ValueError):
                gate.evaluate(bad)
        data = base()
        data["lanes"]["verify"]["selected"] = "true"
        with self.assertRaises(ValueError):
            gate.evaluate(data)


class PrBodyTests(unittest.TestCase):
    def assertBodyFails(self, body, fragment):
        result = gate.evaluate(base(pr_body=body))
        self.assertEqual("fail", result["verdict"])
        self.assertTrue(any(fragment in p for p in result["problems"]), result["problems"])

    def test_empty_body(self):
        self.assertBodyFails("", "PR body is empty")
        self.assertBodyFails(None, "PR body is empty")

    def test_missing_section(self):
        self.assertBodyFails(BODY.replace("## Compatibility", "## Notes"), "missing section '## Compatibility'")

    def test_untouched_template_fails(self):
        template = (REPO / "templates/pull_request_template.md").read_text()
        result = gate.evaluate(base(pr_body=template))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(5, sum("placeholder-only" in p for p in result["problems"]), result["problems"])

    def test_comment_only_section_fails(self):
        self.assertBodyFails(BODY.replace("Reload config on SIGHUP.", "<!-- fill me -->"), "'## Intent'")

    def test_placeholder_tokens_fail(self):
        for token in ("TBD", "TODO", "...", "- [ ]", "<describe>"):
            self.assertBodyFails(BODY.replace("Reload config on SIGHUP.", token), "'## Intent'")

    def test_bare_labels_fail(self):
        body = BODY.split("## Test evidence")[0] + "## Test evidence\n- Command:\n- Result:\n- Tested SHA:\n"
        self.assertBodyFails(body, "'## Test evidence'")

    def test_stale_tested_sha_fails(self):
        self.assertBodyFails(BODY.replace(HEAD, OLD), "not the PR head")

    def test_none_is_a_valid_answer(self):
        self.assertEqual("pass", gate.evaluate(base())["verdict"])

    def test_crlf_and_heading_suffix(self):
        body = BODY.replace("## Intent", "## Intent (why)").replace("\n", "\r\n")
        self.assertEqual("pass", gate.evaluate(base(pr_body=body))["verdict"])


LAYER_LANES = ["verify", "lint", "build", "test"]


def selective(any_layer=False, full=False, ran=None, select_result="success", **overrides):
    """v0.2.0 gate input: verify/contract/workflow-lint selected; verify short-circuits unless any_layer."""
    data = base(**overrides)
    for name, lane in data["lanes"].items():
        lane["ran"] = lane["selected"] and (name not in LAYER_LANES or any_layer)
    if ran:
        for name, value in ran.items():
            data["lanes"][name]["ran"] = value
    data["layer_lanes"] = LAYER_LANES
    data["selection"] = {"mode": "changed-only", "result": select_result, "full": full,
                         "any_layer": any_layer, "layers": ["Core"] if any_layer else [],
                         "reason": "only support paths changed; no layer selected", "head": HEAD}
    return data


class SelectionGateTests(unittest.TestCase):
    """Short-circuited lanes: success that did not run is allowed only when the selection says so."""

    def assertFails(self, data, fragment):
        result = gate.evaluate(data)
        self.assertEqual("fail", result["verdict"], result)
        self.assertTrue(any(fragment in p for p in result["problems"]), result["problems"])

    def test_short_circuited_layer_lane_passes_and_is_recorded(self):
        result = gate.evaluate(selective())
        self.assertEqual("pass", result["verdict"], result["problems"])
        self.assertEqual(["verify"], result["short_circuited"])
        self.assertEqual((False, []), (result["selection"]["any_layer"], result["selection"]["layers"]))
        verify = next(row for row in result["lanes"] if row["lane"] == "verify")
        self.assertEqual((False, False), (verify["ran"], verify["required_by_selection"]))

    def test_selected_layers_run_in_full(self):
        result = gate.evaluate(selective(any_layer=True))
        self.assertEqual(("pass", []), (result["verdict"], result["short_circuited"]))

    def test_lane_that_short_circuits_while_layers_are_selected_fails(self):
        self.assertFails(selective(any_layer=True, ran={"verify": False}), "short-circuited but the selection requires it")

    def test_full_run_lane_that_short_circuits_fails(self):
        self.assertFails(selective(any_layer=True, full=True, ran={"verify": False}), "selection requires it")

    def test_contract_lane_can_never_short_circuit(self):
        self.assertFails(selective(ran={"contract": False}), "selected lane contract short-circuited")

    def test_short_circuited_lane_must_still_succeed(self):
        for result in ("failure", "cancelled", "skipped", ""):
            with self.subTest(result=result):
                data = selective()
                data["lanes"]["verify"]["result"] = result
                self.assertFails(data, "selected lane verify result")

    def test_short_circuited_lane_must_report_head_sha(self):
        data = selective()
        data["lanes"]["verify"]["tested_sha"] = OLD
        self.assertFails(data, f"tested {OLD}")

    def test_unselected_lane_rules_unchanged(self):
        data = selective()
        data["lanes"]["build"]["result"] = "failure"
        self.assertFails(data, "unselected lane build")

    def test_select_job_failure_fails(self):
        for result in ("failure", "cancelled", "skipped", "unknown"):
            with self.subTest(result=result):
                self.assertFails(selective(select_result=result), "select job result")

    def test_selection_for_another_sha_fails(self):
        data = selective()
        data["selection"]["head"] = OLD
        self.assertFails(data, "selection was computed for")

    def test_full_without_layers_is_inconsistent(self):
        self.assertFails(selective(full=True, any_layer=False), "full but selects no layer")

    def test_disabled_selection_must_be_full(self):
        data = selective(any_layer=True, full=True)
        data["selection"]["mode"] = "disabled"
        self.assertEqual("pass", gate.evaluate(data)["verdict"])
        data["selection"]["full"] = False
        self.assertFails(data, "disabled selection must be a full run")

    def test_malformed_selection_raises(self):
        for mutate in (lambda d: d.update(selection="x"),
                       lambda d: d["selection"].update(mode="fast"),
                       lambda d: d["selection"].update(full="false"),
                       lambda d: d["selection"].update(layers="Core"),
                       lambda d: d.pop("layer_lanes"),
                       lambda d: d["lanes"]["verify"].pop("ran")):
            data = selective()
            mutate(data)
            with self.assertRaises(ValueError):
                gate.evaluate(data)

    def test_without_selection_v010_rules_apply(self):
        result = gate.evaluate(base())
        self.assertEqual("pass", result["verdict"])
        self.assertNotIn("selection", result)


class ActionsAdapterTests(unittest.TestCase):
    """The workflow adapter maps `needs` + flags to gate input and fails closed."""

    def run_adapter(self, needs, **env):
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "EVENT": "push",
                       "EXPECTED_SHA": HEAD, "CHECK_PR_BODY": "true",
                       "NEEDS_JSON": json.dumps(needs)}
        for lane in LANES:
            environment[lane.upper().replace("-", "_") + "_SELECTED"] = "true" if lane in ("verify", "contract", "workflow-lint") else "false"
        environment.update(env)
        return subprocess.run([sys.executable, "-I", "-B", str(ACTIONS)], env=environment,
                              capture_output=True, text=True, timeout=20)

    def needs(self, **overrides):
        result = {lane: {"result": "success" if lane in ("verify", "contract", "workflow-lint") else "skipped",
                         "outputs": {"tested-sha": HEAD} if lane in ("verify", "contract", "workflow-lint") else {}}
                  for lane in LANES}
        for lane, value in overrides.items():
            result[lane.replace("_", "-")] = value
        return result

    def test_green_needs_pass(self):
        result = self.run_adapter(self.needs())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("pass", json.loads(result.stdout)["verdict"])

    def test_cancelled_need_fails(self):
        result = self.run_adapter(self.needs(verify={"result": "cancelled", "outputs": {}}))
        self.assertEqual(1, result.returncode)

    def test_absent_need_fails(self):
        needs = self.needs()
        del needs["contract"]
        self.assertEqual(1, self.run_adapter(needs).returncode)

    def test_bad_flag_fails_closed(self):
        self.assertEqual(1, self.run_adapter(self.needs(), VERIFY_SELECTED="").returncode)

    def test_missing_needs_fails_closed(self):
        self.assertEqual(1, self.run_adapter(self.needs(), NEEDS_JSON="").returncode)

    def selection_needs(self, any_layer, ran_verify, select_result="success", selection=None):
        needs = self.needs()
        for lane in LANES:
            needs[lane]["outputs"]["ran"] = "true" if lane != "verify" or ran_verify else "false"
        record = {"mode": "changed-only", "full": False, "any_layer": any_layer,
                  "layers": ["Core"] if any_layer else [], "reason": "docs only", "head": HEAD}
        needs["select"] = {"result": select_result,
                           "outputs": {"selection": json.dumps(record) if selection is None else selection}}
        return needs

    def test_select_job_short_circuit_passes(self):
        result = self.run_adapter(self.selection_needs(any_layer=False, ran_verify=False))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["verify"], json.loads(result.stdout)["short_circuited"])

    def test_select_job_short_circuit_while_layers_selected_fails(self):
        self.assertEqual(1, self.run_adapter(self.selection_needs(any_layer=True, ran_verify=False)).returncode)

    def test_select_job_failed_fails(self):
        self.assertEqual(1, self.run_adapter(self.selection_needs(False, False, select_result="failure")).returncode)

    def test_select_job_without_output_fails_closed(self):
        # A successful select job always writes its record; a missing one is never trusted.
        for ran in (False, True):
            result = self.run_adapter(self.selection_needs(False, ran, selection=""))
            self.assertEqual(1, result.returncode)
            self.assertIn("selection was computed for no SHA", result.stderr)

    def test_select_job_garbage_output_fails_closed(self):
        self.assertEqual(1, self.run_adapter(self.selection_needs(False, True, selection="[1]")).returncode)
        self.assertEqual(1, self.run_adapter(self.selection_needs(False, True, selection="{bad")).returncode)

    def test_pull_request_without_api_context_fails_closed(self):
        result = self.run_adapter(self.needs(), EVENT="pull_request")
        self.assertEqual(1, result.returncode)
        self.assertIn("PR body is empty", result.stderr)


class CliTests(unittest.TestCase):
    def run_cli(self, data):
        return subprocess.run([sys.executable, "-I", "-B", str(REPO / "scripts/quality/gate.py")],
                              input=data, capture_output=True, text=True, timeout=20)

    def test_exit_codes(self):
        self.assertEqual(0, self.run_cli(json.dumps(base())).returncode)
        self.assertEqual(1, self.run_cli(json.dumps(with_lane("verify", result="cancelled"))).returncode)
        self.assertEqual(2, self.run_cli("not json").returncode)


if __name__ == "__main__":
    unittest.main()
