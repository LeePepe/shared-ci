"""Synthetic public-interface tests. Execution requires separate Main clearance.

Proposed command, only after static review and explicit runtime authorization:
python3 -I -S -B tests/quality/test_aggregation.py
"""

import ast
import builtins
import copy
import datetime
import json
from pathlib import Path
import re
import types
import unittest


DIMS = ("L1", "L2", "L3", "G1", "G2", "D1")
METRICS = ("statements", "branches", "functions", "lines")
ROOT = Path(__file__).resolve().parents[2]
DETAILS = {
    "quality_input_invalid": "Input structure is invalid.",
    "quality_limit_exceeded": "Input exceeds transport limits.",
    "quality_unsupported": "Evaluation requires unsupported semantics.",
    "quality_policy_rejected": "Existing policy evaluation rejected the case.",
    "quality_contract_invalid": "Expected obligation mapping is invalid.",
    "quality_binding_mismatch": "Observed identity or scope differs.",
    "quality_missing": "Expected receipt is missing.",
    "quality_nonpass": "Observed execution is not a pass.",
    "quality_measurement": "Required measurements do not satisfy the obligation.",
    "quality_coverage": "Required evidence coverage is incomplete or unsuccessful.",
    "quality_isolation": "Isolation evidence does not satisfy the obligation.",
}


def load_reviewed_sources():
    """Private imports only; no sys.path/sys.modules/global-builtins edits.

    This is not an adversarial Python sandbox. Review these pinned source files
    before executing. The actual policy function, not a fake, fills the import.
    """
    sources = {name: (ROOT / path).read_text(encoding="utf-8") for name, path in (
        ("policy", "scripts/policy/validate.py"),
        ("aggregate", "scripts/quality/aggregate.py"),
    )}
    standard = {"datetime": datetime, "re": re}

    def denied(*args, **kwargs):
        raise AssertionError("Prohibited side effect or dynamic execution")

    def standard_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name in standard and not fromlist:
            return standard[name]
        raise ImportError("Import not in reviewed allowlist")

    def private_builtins(importer):
        private = dict(vars(builtins))
        private["__import__"] = importer
        for name in ("open", "input", "print", "eval", "exec", "compile", "breakpoint"):
            private[name] = denied
        return private

    policy = {"__name__": "_quality_test_policy", "__builtins__": private_builtins(standard_import)}
    exec(compile(sources["policy"], "scripts/policy/validate.py", "exec"), policy)
    carrier = types.ModuleType("_quality_test_policy_export")
    carrier.evaluate_policy = policy["evaluate_policy"]

    def aggregate_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (level == 0 and name == "scripts.policy.validate"
                and tuple(fromlist) == ("evaluate_policy",)):
            return carrier
        return standard_import(name, globals, locals, fromlist, level)

    namespace = {"__name__": "_quality_test_aggregate",
                 "__builtins__": private_builtins(aggregate_import)}
    exec(compile(sources["aggregate"], "scripts/quality/aggregate.py", "exec"), namespace)
    return namespace["aggregate_6dq"], sources


def fixture():
    pin = {"repository_id": "101", "revision": "a" * 40}
    subject = {"repository_id": "202", "revision": "b" * 40, "path": "src/a.py",
               "layer": "Synthetic", "red_lines": []}
    binding = {"candidate": {"repository_id": "202", "revision": "b" * 40, "tree": "c" * 40},
               "policy": pin, "phase": "actions",
               "mapping": {"kind": "direct", "tested_revision": "b" * 40,
                           "tested_tree": "c" * 40, "source_revisions": ["b" * 40], "evidence": None}}
    isolation = {"controls": ["state"], "resources": [], "basis": "Synthetic no-I/O"}
    scope_ids = {
        "L1": ["Logic"], "L2": ["Interface"], "L3": ["Journey"], "G1": ["Static"],
        "G2": ["Dependency", "History"],
        "D1": ["abnormal_exit", "cleanup_refusal", "concurrent_run", "unsafe_target"],
    }
    expectation = {"schema": 1, "binding": copy.deepcopy(binding), "policy_cases": [], "dimensions": {}}
    evidence = {"schema": 1, "binding": copy.deepcopy(binding), "dimensions": {}}
    rules = {}
    for index, dim in enumerate(DIMS, 1):
        ids = scope_ids[dim]
        slots = {"obligation": dim + ".required", "scope": dim + ".scope"}
        rules[slots["obligation"]] = {"kind": "required"}
        rules[slots["scope"]] = {"kind": "required_set", "values": list(ids)}
        target = {}
        if dim == "L1":
            slots["metrics"] = {metric: "L1." + metric for metric in METRICS}
            target = {"denominators": {metric: 100 for metric in METRICS}}
            for metric in METRICS:
                rules[slots["metrics"][metric]] = {"kind": "minimum_basis_points", "value": 9500}
            payload = {"metrics": {metric: {"state": "measured", "numerator": 95, "denominator": 100,
                                          "report_id": "Report"} for metric in METRICS},
                       "skipped": 0, "focused": 0, "integrity_report": "Report"}
        elif dim == "G1":
            payload = {"errors": 0, "warnings": 0, "report_id": "Report"}
        elif dim == "G2":
            slots["scanners"] = "G2.scanners"
            rules["G2.scanners"] = {"kind": "required_set", "values": ["Tool"]}
            target = {"scanners": [{"id": "Tool", "items": list(ids)}]}
            payload = {"scanners": [{"id": "Tool", "items": list(ids), "status": "pass",
                                     "verdict": "pass", "report_id": "Report"}]}
        else:
            payload = {"cases": [{"id": item, "status": "pass", "report_id": "Report"} for item in ids]}
            if dim == "D1":
                target = {"negative_cases": list(ids)}
                payload["runs"] = ["Run" + str(number) for number in range(1, 7)]
        check = {"id": dim, "subjects": [copy.deepcopy(subject)], "case_ids": ["Case"],
                 "level": "required", "basis": "Synthetic", "command": ["synthetic", dim],
                 "tools": [{"id": "Tool", "version": "1.0"}],
                 "scope": {"items": [{"id": item, "path": "src/a.py"} for item in ids],
                           "exclusions": [], "basis": "Synthetic"},
                 "reports": ["Report"], "isolation": copy.deepcopy(isolation),
                 "bindings": slots, "target": target}
        expectation["dimensions"][dim] = {"owner": "Owner", "checks": [check]}
        run = "Run" + str(index)

        def event(number):
            return {"sequence": number, "at": "2030-01-01T00:00:0%dZ" % (number - 1)}

        observed_isolation = {
            "run_id": run, "target": copy.deepcopy(isolation),
            "preflight": {"event": event(1), "controls": [{"id": "state", "state": "pass"}]},
            "start": event(2), "finish": event(3),
            "cleanup": {"event": event(4), "state": "pass", "resources": []},
        }
        receipt = {key: copy.deepcopy(check[key]) for key in ("id", "subjects", "command", "tools", "scope")}
        receipt.update(binding=copy.deepcopy(binding), run_id=run, status="pass",
                       reports=[{"id": "Report", "ref": "synthetic-report", "digest": "d" * 64}],
                       isolation=observed_isolation, payload=payload)
        evidence["dimensions"][dim] = {"implementation": "implemented", "enforcement": "unknown",
                                        "checks": [receipt]}
    policy = {"baseline": {"schema": 1, "policy": copy.deepcopy(pin), "subject": copy.deepcopy(subject),
                            "rules": copy.deepcopy(rules)},
              "candidate": {"schema": 1, "policy": copy.deepcopy(pin), "rules": copy.deepcopy(rules),
                            "exceptions": []}, "approvals": [],
              "observation": {"schema": 1, "now": "2030-01-01T00:00:10Z", "events": {}}}
    expectation["policy_cases"] = [{"id": "Case", "input": policy}]
    return expectation, evidence


def expected_pass(expectation, evidence):
    return {"schema": 1, "binding": copy.deepcopy(expectation["binding"]), "required_acceptable": True,
            "dimensions": {dim: {"owner": expectation["dimensions"][dim]["owner"],
                                  "implementation": evidence["dimensions"][dim]["implementation"],
                                  "enforcement": evidence["dimensions"][dim]["enforcement"],
                                  "latest": "pass", "checks": [
                                      {"id": check["id"], "requirement": check["level"], "observed": "pass",
                                       "result": "pass", "findings": []}
                                      for check in expectation["dimensions"][dim]["checks"]], "gaps": []}
                           for dim in DIMS}, "findings": [], "applied_exceptions": [],
            "assurance": {"authenticity": "not_verified", "enforcement": "not_verified", "ship": "not_assessed"}}


def finding(kind, subject=None):
    return {"layer": "quality" if subject is None else subject["layer"],
            "path": "" if subject is None else subject["path"], "kind": kind, "detail": DETAILS[kind],
            "red_lines": [] if subject is None else list(subject["red_lines"])}


def fallback(kind):
    return {"schema": 1, "binding": None, "required_acceptable": False,
            "dimensions": {dim: {"owner": None, "implementation": "unknown", "enforcement": "unknown",
                                  "latest": "unsupported" if kind == "quality_unsupported" else "unknown",
                                  "checks": [], "gaps": []} for dim in DIMS},
            "findings": [finding(kind)], "applied_exceptions": [],
            "assurance": {"authenticity": "not_verified", "enforcement": "not_verified", "ship": "not_assessed"}}


def fail_check(output, expectation, dim, kind, *, check_id=None, observed="pass", result="fail"):
    check_id = check_id or dim
    dimension = output["dimensions"][dim]
    expected = next(check for check in expectation["dimensions"][dim]["checks"] if check["id"] == check_id)
    row = next(check for check in dimension["checks"] if check["id"] == check_id)
    row.update(observed=observed, result=result, findings=[finding(kind, expected["subjects"][0])])
    dimension["gaps"].append({"check_id": check_id, "kind": kind})
    dimension["gaps"].sort(key=lambda gap: gap["check_id"])
    priority = ("fail", "unsupported", "unknown", "unavailable", "not_run", "pass")
    dimension["latest"] = min((check["result"] for check in dimension["checks"]), key=priority.index)
    output["findings"] = [item for d in DIMS for check in output["dimensions"][d]["checks"]
                          for item in check["findings"]]
    if expected["level"] == "required":
        output["required_acceptable"] = False
        output["applied_exceptions"] = []


def check(expectation, dim):
    return expectation["dimensions"][dim]["checks"][0]


def receipt(evidence, dim):
    return evidence["dimensions"][dim]["checks"][0]


def policy(expectation):
    return expectation["policy_cases"][0]["input"]


def approve(expectation, rule_id, after):
    case = policy(expectation)
    before = copy.deepcopy(case["baseline"]["rules"][rule_id])
    if after is None:
        del case["candidate"]["rules"][rule_id]
    else:
        case["candidate"]["rules"][rule_id] = copy.deepcopy(after)
    approval = {"schema": 1, "approval_id": "Approval", "evidence_ref": "synthetic-approval",
                "waiver": {"policy": copy.deepcopy(case["baseline"]["policy"]), "repository_id": "202",
                           "paths": ["src/a.py"], "revisions": ["b" * 40], "rule_id": rule_id,
                           "before": before, "after": copy.deepcopy(after), "reason": "Synthetic",
                           "expires_at": "2031-01-01T00:00:00Z", "review_event": None,
                           "alternative_verification": {"event": "Alternative", "condition": "Synthetic"},
                           "revocation_events": [{"event": "Revocation", "condition": "Synthetic"}]}}
    case["candidate"]["exceptions"] = [copy.deepcopy(approval)]
    case["approvals"] = [copy.deepcopy(approval)]
    case["observation"]["events"] = {"Alternative": "occurred", "Revocation": "not_occurred"}


def add_advisory(expectation, evidence):
    advisory = copy.deepcopy(check(expectation, "L2"))
    advisory.update(id="L2.advisory", level="advisory")
    advisory["bindings"] = {"obligation": None, "scope": "L2.advisory.scope"}
    check_list = expectation["dimensions"]["L2"]["checks"]
    check_list.append(advisory)
    for side in ("baseline", "candidate"):
        policy(expectation)[side]["rules"]["L2.advisory.scope"] = {"kind": "required_set", "values": ["Interface"]}
    observed = copy.deepcopy(receipt(evidence, "L2"))
    observed.update(id="L2.advisory", run_id="Run7")
    observed["isolation"]["run_id"] = "Run7"
    evidence["dimensions"]["L2"]["checks"].append(observed)
    receipt(evidence, "D1")["payload"]["runs"].append("Run7")
    return advisory, observed


class AggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        function, cls.sources = load_reviewed_sources()
        cls.aggregate = staticmethod(function)

    def assert_output(self, expectation, evidence, output):
        before = copy.deepcopy((expectation, evidence))
        actual = self.aggregate(expectation=expectation, evidence=evidence)
        self.assertEqual(actual, output)
        self.assertEqual((expectation, evidence), before)
        self.assertEqual(self.aggregate(expectation=expectation, evidence=evidence), output)

    def test_canonical_pass_and_reported_states_are_not_assurance(self):
        e, v = fixture()
        self.assert_output(e, v, expected_pass(e, v))
        for dim in DIMS:
            v["dimensions"][dim]["implementation"] = "not_implemented"
            v["dimensions"][dim]["enforcement"] = "remote_required_verified"
        self.assert_output(e, v, expected_pass(e, v))

    def test_exact_merge_and_each_binding_field(self):
        e, v = fixture()
        e["binding"]["mapping"] = {"kind": "merge", "tested_revision": "e" * 40,
                                    "tested_tree": "f" * 40, "source_revisions": ["b" * 40, "d" * 40],
                                    "evidence": {"id": "Merge", "ref": "synthetic-merge", "digest": "e" * 64}}
        v["binding"] = copy.deepcopy(e["binding"])
        for dim in DIMS:
            receipt(v, dim)["binding"] = copy.deepcopy(e["binding"])
        self.assert_output(e, v, expected_pass(e, v))
        mutations = [(('candidate', 'repository_id'), '203'), (('candidate', 'revision'), '1' * 40),
                     (('candidate', 'tree'), '1' * 40), (('policy', 'repository_id'), '102'),
                     (('policy', 'revision'), '1' * 40), (('phase',), 'pre_push'),
                     (('mapping', 'kind'), 'direct'), (('mapping', 'tested_revision'), '1' * 40),
                     (('mapping', 'tested_tree'), '1' * 40),
                     (('mapping', 'source_revisions'), ['b' * 40, 'c' * 40]),
                     (('mapping', 'evidence', 'id'), 'Other'), (('mapping', 'evidence', 'ref'), 'other'),
                     (('mapping', 'evidence', 'digest'), '1' * 64), (('mapping', 'evidence'), None)]
        for path, value in mutations:
            for top in (True, False):
                with self.subTest(path=path, top=top):
                    ev = copy.deepcopy(v)
                    node = ev['binding'] if top else receipt(ev, 'L2')['binding']
                    for key in path[:-1]:
                        node = node[key]
                    node[path[-1]] = value
                    output = fallback('quality_binding_mismatch') if top else expected_pass(e, ev)
                    if not top:
                        fail_check(output, e, 'L2', 'quality_binding_mismatch')
                    self.assert_output(e, ev, output)

    def test_receipt_binding_before_status_reports_predicate_and_isolation(self):
        for field, value in [('repository_id', '203'), ('revision', 'e' * 40), ('path', 'src/b.py'),
                             ('layer', 'Other'), ('red_lines', ['Do not change'])]:
            e, v = fixture()
            r = receipt(v, 'L2')
            r['subjects'][0][field] = value
            r['status'] = 'failure'
            r['reports'] = []
            r['isolation']['preflight']['controls'][0]['state'] = 'fail'
            output = expected_pass(e, v)
            fail_check(output, e, 'L2', 'quality_binding_mismatch', observed='failure')
            fail_check(output, e, 'D1', 'quality_isolation')
            self.assert_output(e, v, output)
        for field, value in [('command', ['other']), ('tools', [{'id': 'Tool', 'version': '2.0'}]),
                             ('scope', {'items': [{'id': 'Other', 'path': 'src/a.py'}],
                                        'exclusions': [], 'basis': 'Synthetic'})]:
            e, v = fixture()
            receipt(v, 'L2')[field] = value
            output = expected_pass(e, v)
            fail_check(output, e, 'L2', 'quality_binding_mismatch')
            self.assert_output(e, v, output)

    def test_global_stage_precedence_and_structural_fallback(self):
        e, v = fixture()
        del v['dimensions']['G1']
        policy(e)['candidate']['rules'].pop('L1.required')
        self.assert_output(e, v, fallback('quality_input_invalid'))
        for root in ('expectation', 'evidence'):
            e, v = fixture()
            (e if root == 'expectation' else v)['schema'] = 2
            self.assert_output(e, v, fallback('quality_unsupported'))
        e, v = fixture()
        e['schema'] = 2
        e['binding']['candidate']['repository_id'] = '0'
        self.assert_output(e, v, fallback('quality_input_invalid'))  # sorted keys: binding first
        e, v = fixture()
        check(e, 'L1')['bindings']['scope'] = 'Absent'
        policy(e)['candidate']['rules'].pop('L1.required')
        self.assert_output(e, v, fallback('quality_policy_rejected'))
        e, v = fixture()
        e['binding']['phase'] = 'pre_commit'
        check(e, 'L1')['bindings']['scope'] = 'Absent'
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        e['binding']['phase'] = 'pre_push'
        v['binding']['candidate']['repository_id'] = '203'
        self.assert_output(e, v, fallback('quality_unsupported'))
        e, v = fixture()
        receipt(v, 'L2')['id'] = 'Unexpected'
        self.assert_output(e, v, fallback('quality_binding_mismatch'))

    def test_baseline_mapping_contract(self):
        mutations = [
            lambda e: check(e, 'L2').update(level='advisory'),
            lambda e: check(e, 'L2')['bindings'].update(obligation=None),
            lambda e: check(e, 'L2')['bindings'].update(scope='Missing'),
            lambda e: check(e, 'L2')['bindings'].update(scope='L3.scope'),
            lambda e: check(e, 'L2')['subjects'][0].update(layer='Other'),
            lambda e: check(e, 'L2')['subjects'][0].update(red_lines=['New']),
            lambda e: check(e, 'L2')['subjects'][0].update(repository_id='203'),
            lambda e: check(e, 'L2')['scope']['items'][0].update(path='src/b.py'),
            lambda e: check(e, 'L2')['scope']['exclusions'].append({'path': 'src/a.py', 'reason': 'Synthetic'}),
            lambda e: check(e, 'G2')['target']['scanners'][0].update(id='MissingTool'),
            lambda e: check(e, 'G2')['target']['scanners'][0].update(items=['Dependency']),
            lambda e: check(e, 'L1')['isolation'].update(controls=['network']),
            lambda e: e['binding']['mapping'].update(tested_tree='f' * 40),
        ]
        for mutate in mutations:
            e, v = fixture()
            mutate(e)
            self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        e['dimensions']['L2']['checks'] = []
        self.assert_output(e, v, fallback('quality_input_invalid'))
        e, v = fixture()
        check(e, 'L2')['level'] = 'advisory'
        check(e, 'L2')['bindings']['obligation'] = None
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        for side in ('baseline', 'candidate'):
            policy(e)[side]['rules']['Unmapped'] = {'kind': 'required'}
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        check(e, 'L2')['subjects'].append({**copy.deepcopy(check(e, 'L2')['subjects'][0]), 'path': 'src/b.py'})
        check(e, 'L2')['scope']['items'].append({'id': 'Other', 'path': 'src/b.py'})
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        for side in ('baseline', 'candidate'):
            policy(e)[side]['rules']['L1.lines']['value'] = 9499
        self.assert_output(e, v, fallback('quality_contract_invalid'))

    def test_approved_numeric_exception_and_actual_policy_failures(self):
        e, v = fixture()
        approve(e, 'L1.lines', {'kind': 'minimum_basis_points', 'value': 9000})
        receipt(v, 'L1')['payload']['metrics']['lines']['numerator'] = 90
        output = expected_pass(e, v)
        output['applied_exceptions'] = ['Approval']
        self.assert_output(e, v, output)
        for failure in ('expired', 'forged', 'revoked', 'unknown', 'alternative', 'review'):
            ex = copy.deepcopy(e)
            case = policy(ex)
            if failure == 'forged':
                case['candidate']['exceptions'][0]['evidence_ref'] = 'forged'
            elif failure == 'expired':
                case['observation']['now'] = '2031-01-01T00:00:00Z'
            elif failure == 'revoked':
                case['observation']['events']['Revocation'] = 'occurred'
            elif failure == 'unknown':
                case['observation']['events'].pop('Revocation')
            elif failure == 'alternative':
                case['observation']['events']['Alternative'] = 'not_occurred'
            else:
                for records in (case['approvals'], case['candidate']['exceptions']):
                    records[0]['waiver']['review_event'] = {'event': 'Review', 'condition': 'Synthetic'}
                case['observation']['events']['Review'] = 'occurred'
            self.assert_output(ex, v, fallback('quality_policy_rejected'))
        receipt(v, 'L1')['payload']['focused'] = 1
        fail_check(output, e, 'L1', 'quality_measurement')
        self.assert_output(e, v, output)

    def test_supported_vs_approved_unsupported_and_baseline_precedence(self):
        alternatives = [('L2.required', None), ('L2.scope', None),
                        ('L2.scope', {'kind': 'required_set', 'values': []}),
                        ('G2.scanners', {'kind': 'required_set', 'values': []})]
        for rule_id, after in alternatives:
            e, v = fixture()
            approve(e, rule_id, after)
            self.assert_output(e, v, fallback('quality_unsupported'))
            check(e, 'L1')['bindings']['scope'] = 'Absent'
            self.assert_output(e, v, fallback('quality_contract_invalid'))
            policy(e)['candidate']['exceptions'][0]['evidence_ref'] = 'forged'
            self.assert_output(e, v, fallback('quality_policy_rejected'))
        e, v = fixture()
        policy(e)['candidate']['rules']['L2.scope']['values'].append('Other')
        self.assert_output(e, v, fallback('quality_unsupported'))
        e, v = fixture()
        policy(e)['candidate']['rules']['New'] = {'kind': 'required'}
        self.assert_output(e, v, fallback('quality_unsupported'))

    def test_coverage_metrics_exact_arithmetic(self):
        for metric in METRICS:
            e, v = fixture()
            measurement = receipt(v, 'L1')['payload']['metrics'][metric]
            measurement.update(numerator=9499, denominator=10000)
            check(e, 'L1')['target']['denominators'][metric] = 10000
            output = expected_pass(e, v)
            fail_check(output, e, 'L1', 'quality_measurement')
            self.assert_output(e, v, output)
            measurement['numerator'] = 9500
            self.assert_output(e, v, expected_pass(e, v))
        for field in ('skipped', 'focused'):
            e, v = fixture()
            receipt(v, 'L1')['payload'][field] = 1
            output = expected_pass(e, v)
            fail_check(output, e, 'L1', 'quality_measurement')
            self.assert_output(e, v, output)
        for change in ('denominator', 'excess', 'unmeasured', 'strict'):
            e, v = fixture()
            m = receipt(v, 'L1')['payload']['metrics']['lines']
            if change == 'denominator':
                m['denominator'] = 101
            elif change == 'excess':
                m['numerator'] = 101
            elif change == 'unmeasured':
                m.update(state='unmeasured', numerator=None, denominator=None, report_id=None)
            else:
                for side in ('baseline', 'candidate'):
                    policy(e)[side]['rules']['L1.lines']['value'] = 9600
            output = expected_pass(e, v)
            fail_check(output, e, 'L1', 'quality_measurement')
            self.assert_output(e, v, output)
        for change in ('line_only', 'zero', 'mixed_null'):
            e, v = fixture()
            metrics = receipt(v, 'L1')['payload']['metrics']
            if change == 'line_only':
                receipt(v, 'L1')['payload']['metrics'] = {'lines': metrics['lines']}
            elif change == 'zero':
                metrics['lines']['denominator'] = 0
            else:
                metrics['lines']['numerator'] = None
            self.assert_output(e, v, fallback('quality_input_invalid'))

    def test_reports_before_predicates_and_predicates_before_isolation(self):
        e, v = fixture()
        r = receipt(v, 'L1')
        r['reports'] = []
        r['payload']['skipped'] = 1
        r['isolation']['cleanup']['state'] = 'fail'
        output = expected_pass(e, v)
        fail_check(output, e, 'L1', 'quality_coverage')
        fail_check(output, e, 'D1', 'quality_isolation')
        self.assert_output(e, v, output)
        r['reports'] = [{'id': 'Report', 'ref': 'synthetic', 'digest': 'd' * 64}]
        output = expected_pass(e, v)
        fail_check(output, e, 'L1', 'quality_measurement')
        fail_check(output, e, 'D1', 'quality_isolation')
        self.assert_output(e, v, output)
        for dim in DIMS:
            e, v = fixture()
            receipt(v, dim)['reports'][0]['id'] = 'Other'
            output = expected_pass(e, v)
            fail_check(output, e, dim, 'quality_coverage')
            self.assert_output(e, v, output)

    def test_gates_and_missing_case_scanner_coverage(self):
        e, v = fixture()
        receipt(v, 'G1')['payload']['warnings'] = 1
        output = expected_pass(e, v)
        fail_check(output, e, 'G1', 'quality_measurement')
        self.assert_output(e, v, output)
        for dim in ('L2', 'L3', 'D1'):
            e, v = fixture()
            receipt(v, dim)['payload']['cases'][0]['status'] = 'failure'
            output = expected_pass(e, v)
            fail_check(output, e, dim, 'quality_coverage')
            self.assert_output(e, v, output)
        for key, value in [('id', 'Other'), ('items', ['Dependency']), ('status', 'skipped'), ('verdict', 'unknown')]:
            e, v = fixture()
            receipt(v, 'G2')['payload']['scanners'][0][key] = value
            output = expected_pass(e, v)
            fail_check(output, e, 'G2', 'quality_coverage')
            self.assert_output(e, v, output)
        for location in ('scanner', 'version'):
            e, v = fixture()
            if location == 'scanner':
                receipt(v, 'G2')['payload']['scanners'] = []
            else:
                receipt(v, 'G2')['tools'][0].pop('version')
            self.assert_output(e, v, fallback('quality_input_invalid'))

    def test_all_nonpass_statuses_and_missing(self):
        for status in ('failure', 'cancelled', 'skipped', 'manual', 'unmeasured', 'planned',
                       'not_run', 'unavailable', 'unknown'):
            e, v = fixture()
            receipt(v, 'L2')['status'] = status
            receipt(v, 'L2')['reports'] = []
            output = expected_pass(e, v)
            result = status if status in ('not_run', 'unavailable', 'unknown') else 'fail'
            fail_check(output, e, 'L2', 'quality_nonpass', observed=status, result=result)
            self.assert_output(e, v, output)
        e, v = fixture()
        v['dimensions']['L2']['checks'] = []
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_missing', observed=None, result='not_run')
        fail_check(output, e, 'D1', 'quality_coverage')
        self.assert_output(e, v, output)
        receipt(v, 'D1')['payload']['runs'].remove('Run2')
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_missing', observed=None, result='not_run')
        self.assert_output(e, v, output)

    def test_isolation_and_all_run_closure(self):
        mutations = [lambda iso: iso['preflight']['event'].update(sequence=3),
                     lambda iso: iso['preflight']['event'].update(at='2030-01-01T00:00:02Z'),
                     lambda iso: iso.update(run_id='Wrong'),
                     lambda iso: iso['preflight']['controls'][0].update(state='unknown'),
                     lambda iso: iso['preflight']['controls'][0].update(id='network'),
                     lambda iso: iso['cleanup'].update(state='fail'),
                     lambda iso: iso['target'].update(basis='Other')]
        for mutate in mutations:
            e, v = fixture()
            mutate(receipt(v, 'L2')['isolation'])
            output = expected_pass(e, v)
            fail_check(output, e, 'L2', 'quality_isolation')
            fail_check(output, e, 'D1', 'quality_isolation')
            self.assert_output(e, v, output)
        e, v = fixture()
        receipt(v, 'D1')['payload']['runs'].remove('Run6')
        output = expected_pass(e, v)
        fail_check(output, e, 'D1', 'quality_coverage')
        self.assert_output(e, v, output)
        e, v = fixture()
        receipt(v, 'D1')['payload']['cases'].pop()
        output = expected_pass(e, v)
        fail_check(output, e, 'D1', 'quality_coverage')
        self.assert_output(e, v, output)
        e, v = fixture()
        receipt(v, 'L2')['isolation']['preflight']['state'] = 'pass'
        self.assert_output(e, v, fallback('quality_input_invalid'))

    def test_resource_ownership_marker_cleanup(self):
        e, v = fixture()
        resources = [{'id': 'Resource', 'target': 'synthetic-target', 'owner': 'Owner', 'marker': 'synthetic-marker'}]
        check(e, 'L2')['isolation']['resources'] = copy.deepcopy(resources)
        iso = receipt(v, 'L2')['isolation']
        iso['target']['resources'] = copy.deepcopy(resources)
        iso['cleanup']['resources'] = [{'id': 'Resource', 'created_by_run': 'Run2', 'ownership': 'match',
                                       'marker': 'match', 'cleanup': 'pass'}]
        self.assert_output(e, v, expected_pass(e, v))
        for key, value in [('created_by_run', 'Wrong'), ('ownership', 'mismatch'),
                           ('marker', 'unknown'), ('cleanup', 'fail'), ('id', 'Other')]:
            ev = copy.deepcopy(v)
            receipt(ev, 'L2')['isolation']['cleanup']['resources'][0][key] = value
            output = expected_pass(e, ev)
            fail_check(output, e, 'L2', 'quality_isolation')
            fail_check(output, e, 'D1', 'quality_isolation')
            self.assert_output(e, ev, output)

    def test_advisory_visibility_and_unsafe_advisory_blocks_d1(self):
        e, v = fixture()
        advisory, observed = add_advisory(e, v)
        observed['status'] = 'failure'
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_nonpass', check_id='L2.advisory', observed='failure')
        self.assertTrue(output['required_acceptable'])
        self.assert_output(e, v, output)
        observed['isolation']['cleanup']['state'] = 'fail'
        fail_check(output, e, 'D1', 'quality_isolation')
        self.assert_output(e, v, output)
        advisory['isolation']['controls'] = ['ports', 'state']
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        _, observed = add_advisory(e, v)
        observed['status'] = 'cancelled'
        receipt(v, 'D1')['payload']['runs'].remove('Run7')
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_nonpass', check_id='L2.advisory', observed='cancelled')
        fail_check(output, e, 'D1', 'quality_coverage')
        self.assert_output(e, v, output)

    def test_native_limits_ordering_and_lexical_edges(self):
        class Foreign(dict):
            pass

        for value, kind in [(True, 'quality_input_invalid'), (1.0, 'quality_input_invalid'),
                            (Foreign(), 'quality_input_invalid'), (-1, 'quality_limit_exceeded'),
                            (9223372036854775808, 'quality_limit_exceeded'),
                            ('a' * 4097, 'quality_limit_exceeded'), ('\ud800', 'quality_input_invalid')]:
            e, v = fixture()
            e['bad'] = value
            self.assertEqual(self.aggregate(expectation=e, evidence=v), fallback(kind))
        e, v = fixture()
        e['bad'] = e
        self.assertEqual(self.aggregate(expectation=e, evidence=v), fallback('quality_input_invalid'))
        e, v = fixture()
        nested = None
        for _ in range(32):
            nested = [nested]
        e['bad'] = nested
        self.assertEqual(self.aggregate(expectation=e, evidence=v), fallback('quality_limit_exceeded'))
        for value in ([None] * 100000, ['a' * 4096] * 2049):
            e, v = fixture()
            e['bad'] = value
            self.assertEqual(self.aggregate(expectation=e, evidence=v), fallback('quality_limit_exceeded'))
        e, v = fixture()
        # The same acyclic subtree is counted twice, not mistaken for a cycle.
        check(e, 'L2')['subjects'] = check(e, 'L1')['subjects']
        self.assert_output(e, v, expected_pass(e, v))
        for change in ('reverse', 'duplicate_subject', 'duplicate_run', 'command_empty', 'command_limit',
                       'bad_time', 'zero_sha', 'control_text', 'blank', 'path', 'null_run'):
            e, v = fixture()
            if change == 'reverse':
                check(e, 'G2')['scope']['items'].reverse()
            elif change == 'duplicate_subject':
                check(e, 'L1')['subjects'].append({**check(e, 'L1')['subjects'][0], 'red_lines': ['Other']})
            elif change == 'duplicate_run':
                receipt(v, 'L2')['run_id'] = 'Run1'
            elif change == 'command_empty':
                check(e, 'L1')['command'] = []
            elif change == 'command_limit':
                check(e, 'L1')['command'] = ['token'] * 1025
            elif change == 'bad_time':
                receipt(v, 'L1')['isolation']['start']['at'] = '2030-02-30T00:00:00Z'
            elif change == 'zero_sha':
                e['binding']['candidate']['tree'] = '0' * 40
            elif change == 'control_text':
                check(e, 'L1')['basis'] = 'bad\x7f'
            elif change == 'blank':
                check(e, 'L1')['basis'] = '\u3000'
            elif change == 'path':
                check(e, 'L1')['subjects'][0]['path'] = 'src/../a.py'
            else:
                receipt(v, 'L1')['run_id'] = None
            self.assert_output(e, v, fallback('quality_input_invalid'))

    def test_detached_output_and_key_order(self):
        e, v = fixture()
        output = expected_pass(e, v)
        actual = self.aggregate(expectation=e, evidence=v)
        actual['binding']['candidate']['revision'] = 'f' * 40
        self.assert_output(e, v, output)

        def reverse_keys(value):
            if type(value) is dict:
                return {key: reverse_keys(value[key]) for key in reversed(value)}
            if type(value) is list:
                return [reverse_keys(item) for item in value]
            return value

        self.assert_output(reverse_keys(e), reverse_keys(v), output)

    def test_multiple_subject_cases_bijection_and_maximum_effective_minimum(self):
        e, v = fixture()
        second = copy.deepcopy(e['policy_cases'][0])
        second['id'] = 'Case2'
        second['input']['baseline']['subject']['path'] = 'src/b.py'
        for side in ('baseline', 'candidate'):
            second['input'][side]['rules'] = {
                key: value for key, value in second['input'][side]['rules'].items()
                if key.startswith('L1.')}
            second['input'][side]['rules']['L1.lines']['value'] = 9600
        e['policy_cases'].append(second)
        subject = copy.deepcopy(second['input']['baseline']['subject'])
        check(e, 'L1')['subjects'].append(subject)
        check(e, 'L1')['case_ids'].append('Case2')
        # Complete scope can explicitly exclude this subject path with a reason.
        check(e, 'L1')['scope']['exclusions'] = [{'path': 'src/b.py', 'reason': 'Synthetic exclusion'}]
        receipt(v, 'L1')['subjects'] = copy.deepcopy(check(e, 'L1')['subjects'])
        receipt(v, 'L1')['scope'] = copy.deepcopy(check(e, 'L1')['scope'])
        output = expected_pass(e, v)
        fail_check(output, e, 'L1', 'quality_measurement')
        self.assert_output(e, v, output)
        receipt(v, 'L1')['payload']['metrics']['lines']['numerator'] = 96
        self.assert_output(e, v, expected_pass(e, v))
        check(e, 'L1')['case_ids'].remove('Case2')
        self.assert_output(e, v, fallback('quality_contract_invalid'))

    def test_advisory_ports_requires_negative_even_when_failed(self):
        e, v = fixture()
        advisory, observed = add_advisory(e, v)
        advisory['isolation']['controls'] = ['ports', 'state']
        observed['isolation']['target'] = copy.deepcopy(advisory['isolation'])
        observed['isolation']['preflight']['controls'].insert(0, {'id': 'ports', 'state': 'pass'})
        observed['status'] = 'failure'
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        d1 = check(e, 'D1')
        d1['scope']['items'].append({'id': 'port_collision', 'path': 'src/a.py'})
        d1['scope']['items'].sort(key=lambda item: item['id'])
        d1['target']['negative_cases'] = [item['id'] for item in d1['scope']['items']]
        for side in ('baseline', 'candidate'):
            policy(e)[side]['rules']['D1.scope']['values'] = list(d1['target']['negative_cases'])
        receipt(v, 'D1')['scope'] = copy.deepcopy(d1['scope'])
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_nonpass', check_id='L2.advisory', observed='failure')
        fail_check(output, e, 'D1', 'quality_coverage')
        self.assert_output(e, v, output)
        receipt(v, 'D1')['payload']['cases'].append({'id': 'port_collision', 'status': 'pass', 'report_id': 'Report'})
        receipt(v, 'D1')['payload']['cases'].sort(key=lambda item: item['id'])
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_nonpass', check_id='L2.advisory', observed='failure')
        self.assert_output(e, v, output)

    def test_dimension_latest_and_nonrun_without_isolation(self):
        for required, advisory, latest in [('unknown', 'unavailable', 'unknown'),
                                            ('unavailable', 'not_run', 'unavailable'),
                                            ('not_run', 'pass', 'not_run'),
                                            ('unknown', 'failure', 'fail')]:
            e, v = fixture()
            _, observed = add_advisory(e, v)
            receipt(v, 'L2')['status'] = required
            observed['status'] = advisory
            output = expected_pass(e, v)
            fail_check(output, e, 'L2', 'quality_nonpass', observed=required, result=required)
            if advisory != 'pass':
                fail_check(output, e, 'L2', 'quality_nonpass', check_id='L2.advisory', observed=advisory,
                           result='fail' if advisory == 'failure' else advisory)
            self.assertEqual(output['dimensions']['L2']['latest'], latest)
            self.assert_output(e, v, output)
        e, v = fixture()
        receipt(v, 'L2').update(status='not_run', run_id=None, isolation=None, payload=None, reports=[])
        receipt(v, 'D1')['payload']['runs'].remove('Run2')
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_nonpass', observed='not_run', result='not_run')
        self.assert_output(e, v, output)

    def test_resource_boundaries_and_no_findings_leak(self):
        e, v = fixture()
        check(e, 'L1')['basis'] = 'a' * 4096
        check(e, 'L1')['command'] = ['token'] * 1024
        receipt(v, 'L1')['command'] = ['token'] * 1024
        self.assert_output(e, v, expected_pass(e, v))
        check(e, 'L1')['basis'] = 'é' * 2049  # bytes, not character count
        self.assert_output(e, v, fallback('quality_limit_exceeded'))
        e, v = fixture()
        for metric in METRICS:
            check(e, 'L1')['target']['denominators'][metric] = 9223372036854775807
            receipt(v, 'L1')['payload']['metrics'][metric].update(
                numerator=9223372036854775807, denominator=9223372036854775807)
        self.assert_output(e, v, expected_pass(e, v))
        e, v = fixture()
        receipt(v, 'L2')['command'] = ['DO_NOT_LEAK_COMMAND']
        receipt(v, 'L2')['reports'][0]['ref'] = 'DO_NOT_LEAK_REF'
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_binding_mismatch')
        self.assert_output(e, v, output)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(output))

    def test_exact_native_occurrence_depth_and_aggregate_byte_boundaries(self):
        for size, kind in [(99998, 'quality_input_invalid'), (99999, 'quality_limit_exceeded')]:
            # List root + size elements + evidence root: 100000/100001 nodes.
            self.assertEqual(self.aggregate(expectation=[None] * size, evidence=None), fallback(kind))
        for size, kind in [(31, 'quality_input_invalid'), (32, 'quality_limit_exceeded')]:
            value = None
            for _ in range(size):
                value = [value]
            self.assertEqual(self.aggregate(expectation=value, evidence=None), fallback(kind))
        value = ['a' * 4096] * 2048
        self.assertEqual(self.aggregate(expectation=value, evidence=None), fallback('quality_input_invalid'))
        self.assertEqual(self.aggregate(expectation=value, evidence='a'), fallback('quality_limit_exceeded'))
        # Native/resource pass precedes all shape work and visits roots in order.
        self.assertEqual(self.aggregate(expectation=True, evidence='a' * 4097), fallback('quality_input_invalid'))
        self.assertEqual(self.aggregate(expectation='a' * 4097, evidence=True), fallback('quality_limit_exceeded'))

    def test_exact_policy_pins_unused_cases_and_subject_redline_order(self):
        e, v = fixture()
        policy(e)['candidate']['policy']['repository_id'] = '102'
        self.assert_output(e, v, fallback('quality_policy_rejected'))
        policy(e)['baseline']['policy']['repository_id'] = '102'
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        unused = copy.deepcopy(e['policy_cases'][0])
        unused['id'] = 'Unused'
        e['policy_cases'].append(unused)
        self.assert_output(e, v, fallback('quality_contract_invalid'))
        e, v = fixture()
        policy(e)['baseline']['subject']['red_lines'] = ['First', 'Second']
        for dim in DIMS:
            check(e, dim)['subjects'][0]['red_lines'] = ['First', 'Second']
            receipt(v, dim)['subjects'][0]['red_lines'] = ['First', 'Second']
        self.assert_output(e, v, expected_pass(e, v))
        receipt(v, 'L2')['subjects'][0]['red_lines'].reverse()
        output = expected_pass(e, v)
        fail_check(output, e, 'L2', 'quality_binding_mismatch')
        self.assert_output(e, v, output)
        check(e, 'L3')['subjects'][0]['red_lines'].reverse()
        self.assert_output(e, v, fallback('quality_contract_invalid'))

    def test_local_payload_references_and_complete_missing_dimension(self):
        for dim, path in [('L1', ('integrity_report',)), ('L1', ('metrics', 'lines', 'report_id')),
                          ('L2', ('cases', 0, 'report_id')), ('G1', ('report_id',)),
                          ('G2', ('scanners', 0, 'report_id')), ('D1', ('cases', 0, 'report_id'))]:
            e, v = fixture()
            node = receipt(v, dim)['payload']
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = 'Unresolved'
            output = expected_pass(e, v)
            fail_check(output, e, dim, 'quality_coverage')
            self.assert_output(e, v, output)
        for extra in (True, False):
            for root in ('expectation', 'evidence'):
                e, v = fixture()
                dimensions = (e if root == 'expectation' else v)['dimensions']
                if extra:
                    dimensions['Other'] = {}
                else:
                    del dimensions['G2']
                self.assert_output(e, v, fallback('quality_input_invalid'))

    def test_source_imports_and_side_effect_surface(self):
        tree = ast.parse(self.sources['aggregate'])
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual(len(imports), 3)
        self.assertEqual([(node.names[0].name, node.names[0].asname) for node in imports[:2]],
                         [('datetime', '_datetime'), ('re', '_re')])
        self.assertEqual(imports[2].module, 'scripts.policy.validate')
        self.assertEqual([(name.name, name.asname) for name in imports[2].names],
                         [('evaluate_policy', '_evaluate_policy')])
        prohibited = {'open', 'print', 'input', 'eval', 'exec', 'compile', '__import__'}
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                             and node.func.id in prohibited for node in ast.walk(tree)))
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr in ('now', 'today', 'utcnow')
                             for node in ast.walk(tree)))

    def test_schema_references_closed_shapes_and_shared_definitions(self):
        schemas = [json.loads((ROOT / 'schemas' / name).read_text(encoding='utf-8'))
                   for name in ('quality-input-v1.schema.json', 'quality-result-v1.schema.json')]
        for schema in schemas:
            def walk(value):
                if isinstance(value, dict):
                    if '$ref' in value:
                        self.assertTrue(value['$ref'].startswith('#/$defs/'))
                        self.assertIn(value['$ref'][8:], schema['$defs'])
                    if value.get('type') == 'object' and 'properties' in value:
                        self.assertIs(value['additionalProperties'], False)
                        self.assertEqual(set(value['required']), set(value['properties']))
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
            walk(schema)
        for name in set(schemas[0]['$defs']) & set(schemas[1]['$defs']):
            self.assertEqual(schemas[0]['$defs'][name], schemas[1]['$defs'][name])
        self.assertEqual(schemas[0]['$defs']['Count']['maximum'], 9223372036854775807)
        self.assertEqual(schemas[0]['$defs']['Preflight']['required'], ['event', 'controls'])
        self.assertEqual({branch['properties']['kind']['const']: branch['properties']['detail']['const']
                          for branch in schemas[1]['$defs']['Finding']['oneOf']}, DETAILS)


class SchemaLexicalTests(unittest.TestCase):
    """Decoded primitive patterns only, not a JSON Schema validator.

    Search semantics exercise the schemas' own anchors/end assertions. Do not
    add fullmatch, extra anchors, flags or display-string unescaping here.
    Python re checks this shared regex subset, not complete ECMA-262 conformance.
    Calendar validity, byte budgets, native types and other schema keywords are
    outside these tests. This class does not load or invoke either source module.
    """

    @classmethod
    def setUpClass(cls):
        cls.schemas = {
            name: json.loads((ROOT / 'schemas' / name).read_text(encoding='utf-8'))
            for name in ('quality-input-v1.schema.json', 'quality-result-v1.schema.json')
        }

    def assert_lexical(self, schema_name, primitive, value, accepted):
        pattern = self.schemas[schema_name]['$defs'][primitive]['pattern']
        with self.subTest(schema=schema_name, primitive=primitive, value=repr(value), accepted=accepted):
            match = re.search(pattern, value)
            if accepted:
                self.assertIsNotNone(match)
            else:
                self.assertIsNone(match)

    def assert_examples(self, primitive, valid, invalid):
        for schema_name, schema in self.schemas.items():
            if primitive not in schema['$defs']:
                continue  # Time belongs only to the input schema; inventory is checked below.
            for value in valid:
                self.assert_lexical(schema_name, primitive, value, True)
            for value in invalid:
                self.assert_lexical(schema_name, primitive, value, False)

    def test_pattern_inventory_and_shared_definitions(self):
        expected = {
            'quality-input-v1.schema.json': {'ID', 'Text', 'Path', 'SHA', 'Digest', 'RepoID', 'Time'},
            'quality-result-v1.schema.json': {'ID', 'Text', 'Path', 'SHA', 'Digest', 'RepoID'},
        }
        for schema_name, schema in self.schemas.items():
            actual = {name for name, definition in schema['$defs'].items() if 'pattern' in definition}
            self.assertEqual(actual, expected[schema_name])
        input_defs = self.schemas['quality-input-v1.schema.json']['$defs']
        result_defs = self.schemas['quality-result-v1.schema.json']['$defs']
        for name in expected['quality-result-v1.schema.json']:
            self.assertEqual(input_defs[name], result_defs[name])

    def test_id_and_repository_boundaries_reject_prefix_acceptance(self):
        self.assert_examples('ID', ['A', 'quality', 'L1.lines', 'abnormal_exit', 'Z_.-09', 'A' * 128],
                             ['', '1A', '_A', 'é', 'A' * 129, 'A!', 'A/', 'A ', 'A\n', 'A\r\n',
                              '\nA', ' A', 'A\x00', 'A\\s', 'Aé', 'A😀'])
        self.assert_examples('RepoID', ['1', '9', '101', '202', '12345678901234567890'],
                             ['', '0', '01', '+1', '-1', '1.0', '1e2', '１２', '١', '1!', '1a',
                              '1/', '1 ', '1\n', '1\r\n', '1\x00', ' 1', '\n1', '1é', '1\\s'])

    def test_text_and_every_c0_c1_control(self):
        self.assert_examples('Text', ['quality', 'Synthetic', ' quality ', '示例模块', 'café',
                                     'cafe\u0301', '😀', '100% complete', '\\s', 'line\u2028separator',
                                     '\u200b'] + list(DETAILS.values()),
                             ['', ' ', '   ', '\u00a0', '\u1680', '\u2000\u200a', '\u2028\u2029',
                              '\u202f', '\u205f', '\u3000'])
        controls = [chr(code) for code in list(range(32)) + list(range(127, 160))]
        for control in controls:
            self.assert_examples('Text', [], [control, control + 'quality', 'qua' + control + 'lity',
                                             'quality' + control])
            self.assert_examples('Path', [], [control + 'src/a.py', 'src/' + control + 'a.py',
                                             'src/a.py' + control])

    def test_literal_paths_and_invalid_segments(self):
        self.assert_examples('Path', [
            'src/a.py', '.gitignore', 'src/.hidden', 'src/.../a', '...', 'a.b/c..d', 'src/..name',
            ' ', ' /file ', 'SampleWatch Watch App/Sources/App.swift', 'assets/100% complete.txt',
            'src/%61.py', 'src/%2e%2e/%2F.py', 'src/*?[x].py', '示例模块/消费者 测试.swift',
            'café.py', 'cafe\u0301.py', 'emoji/😀.txt',
        ], [
            '', '/', '/src/a.py', 'src/', 'src//a.py', '.', '..', './a', '../a', 'a/.', 'a/..',
            'a/./b', 'a/../b', 'src/a.py/.', 'src/a.py/..', 'src/a.py//b',
            'src\\a.py', '\\\\host\\share', 'src/a.py\\', 'src/a.py\n', 'src/a.py\r\n',
        ])

    def test_sha_digest_and_timestamp_spellings(self):
        for primitive, size in [('SHA', 40), ('Digest', 64)]:
            valid = ['a' * size, '1' * size, '0' * (size - 1) + '1', '1' + '0' * (size - 1)]
            invalid = ['', '0' * size, 'a' * (size - 1), 'a' * (size + 1), 'A' * size,
                       'g' * size, 'é' * size, ' ' + 'a' * size, '\n' + 'a' * size]
            invalid.extend('a' * size + suffix for suffix in ('!', '/', ' ', '\n', '\r\n', '\x00', 'é', '\\s'))
            self.assert_examples(primitive, valid, invalid)
        self.assert_examples('Time', [
            '0001-01-01T00:00:00Z', '9999-12-31T23:59:59Z', '2000-02-29T12:34:56Z',
            '2030-01-01T00:00:10Z',
        ], [
            '', '0000-01-01T00:00:00Z', '10000-01-01T00:00:00Z', '2030-00-01T00:00:00Z',
            '2030-13-01T00:00:00Z', '2030-01-00T00:00:00Z', '2030-01-32T00:00:00Z',
            '2030-01-01T24:00:00Z', '2030-01-01T00:60:00Z', '2030-01-01T00:00:60Z',
            '2030-1-01T00:00:00Z', '2030-01-01t00:00:00Z', '2030-01-01 00:00:00Z',
            '2030-01-01T00:00:00z', '2030-01-01T00:00:00.0Z', '2030-01-01T00:00:00+00:00',
            ' 2030-01-01T00:00:00Z', '\n2030-01-01T00:00:00Z',
        ] + ['2030-01-01T00:00:00Z' + suffix for suffix in ('!', ' ', '\n', '\r\n', '\x00', 'é', '\\s')])

    def test_documented_non_regex_checks_remain_separate(self):
        # These satisfy spelling only. Runtime still rejects invalid Gregorian
        # dates and over-budget UTF-8; pattern acceptance is not input acceptance.
        self.assert_examples('Time', ['2030-02-30T00:00:00Z'], [])
        self.assert_examples('Text', ['é' * 2049], [])
        self.assert_examples('Path', ['é' * 2049], [])

    def test_canonical_and_fixed_fallback_primitive_values(self):
        expectation, evidence = fixture()
        canonical = expected_pass(expectation, evidence)
        global_kinds = ('quality_input_invalid', 'quality_limit_exceeded', 'quality_unsupported',
                        'quality_policy_rejected', 'quality_contract_invalid', 'quality_binding_mismatch')
        outputs = [canonical] + [fallback(kind) for kind in global_kinds]
        # Include nonempty finding paths/red lines as well as global empty paths.
        check(expectation, 'L2')['subjects'][0]['red_lines'] = ['Preserve shared code.']
        per_check = copy.deepcopy(canonical)
        fail_check(per_check, expectation, 'L2', 'quality_binding_mismatch')
        outputs.append(per_check)
        for output in outputs:
            values = {'ID': [], 'Text': [], 'Path': [], 'RepoID': [], 'SHA': []}
            binding = output['binding']
            if binding is not None:
                for pin in (binding['candidate'], binding['policy']):
                    values['RepoID'].append(pin['repository_id'])
                    values['SHA'].append(pin['revision'])
                values['SHA'].extend([binding['candidate']['tree'], binding['mapping']['tested_revision'],
                                      binding['mapping']['tested_tree']] + binding['mapping']['source_revisions'])
            values['ID'].extend(output['applied_exceptions'])
            findings = list(output['findings'])
            for dimension in output['dimensions'].values():
                if dimension['owner'] is not None:
                    values['ID'].append(dimension['owner'])
                for row in dimension['checks']:
                    values['ID'].append(row['id'])
                    findings.extend(row['findings'])
                values['ID'].extend(gap['check_id'] for gap in dimension['gaps'])
            for item in findings:
                values['Text'].extend([item['layer'], item['detail']] + item['red_lines'])
                if item['path']:
                    values['Path'].append(item['path'])
                else:
                    # Finding.path explicitly permits "" outside the Path primitive.
                    finding_schema = self.schemas['quality-result-v1.schema.json']['$defs']['Finding']
                    alternatives = finding_schema['properties']['path']['anyOf']
                    self.assertIn({'const': ''}, alternatives)
            for primitive, valid in values.items():
                self.assert_examples(primitive, valid, [])
        # Digest and Time do not occur in canonical/fallback output bindings;
        # cover their actual canonical receipt values using applicable definitions.
        for dim in DIMS:
            row = receipt(evidence, dim)
            for report in row['reports']:
                self.assert_examples('ID', [report['id']], [])
                self.assert_examples('Text', [report['ref']], [])
                self.assert_examples('Digest', [report['digest']], [])
            isolation = row['isolation']
            for event in (isolation['preflight']['event'], isolation['start'], isolation['finish'],
                          isolation['cleanup']['event']):
                self.assert_examples('Time', [event['at']], [])


if __name__ == '__main__':
    unittest.main()
