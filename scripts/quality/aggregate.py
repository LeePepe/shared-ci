"""Finite, pure receipt reconciliation; no authenticity or enforcement authority."""

import datetime as _datetime
import re as _re

from scripts.policy.validate import evaluate_policy as _evaluate_policy


_D = ("L1", "L2", "L3", "G1", "G2", "D1")
_METRICS = ("statements", "branches", "functions", "lines")
_MAX = 9223372036854775807
_DETAIL = {
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
_ENUMS = {
    "Phase": ("actions", "pre_commit", "pre_push"),
    "State": ("pass", "fail", "unknown"),
    "Status": ("pass", "failure", "cancelled", "skipped", "manual", "unmeasured",
               "planned", "not_run", "unavailable", "unknown"),
    "Level": ("required", "advisory"),
    "Impl": ("not_implemented", "partial", "implemented", "unknown"),
    "Enforce": ("local", "ci", "remote_required_verified", "unknown"),
    "Control": ("identity", "network", "ports", "state"),
    "Negative": ("abnormal_exit", "cleanup_refusal", "concurrent_run",
                 "port_collision", "unsafe_target"),
    "MappingKind": ("direct", "merge"),
    "Match": ("match", "mismatch", "unknown"),
    "Measured": ("measured", "unmeasured", "unknown"),
    "EventState": ("occurred", "not_occurred", "unknown"),
}


class _Invalid(Exception):
    def __init__(self, kind):
        self.kind = kind


def _require(ok, kind="quality_input_invalid"):
    if not ok:
        raise _Invalid(kind)


def _native(*roots):
    """Bound occurrences before any shape or policy work; never inspect objects."""
    active = set()
    nodes = 0
    string_bytes = 0

    def visit(value, depth):
        nonlocal nodes, string_bytes
        nodes += 1
        _require(nodes <= 100000 and depth <= 32, "quality_limit_exceeded")
        typ = type(value)
        _require(any(typ is allowed for allowed in (dict, list, str, int, type(None))))
        if typ is int:
            _require(0 <= value <= _MAX, "quality_limit_exceeded")
        elif typ is str:
            try:
                size = len(value.encode("utf-8", "strict"))
            except UnicodeEncodeError:
                raise _Invalid("quality_input_invalid") from None
            string_bytes += size
            _require(size <= 4096 and string_bytes <= 8388608,
                     "quality_limit_exceeded")
        elif typ is dict or typ is list:
            identity = id(value)
            _require(identity not in active)
            active.add(identity)
            if typ is dict:
                _require(all(type(key) is str for key in value))
                for key in sorted(value):
                    visit(key, depth + 1)
                    visit(value[key], depth + 1)
            else:
                for child in value:
                    visit(child, depth + 1)
            active.remove(identity)

    for root in roots:
        visit(root, 1)


# Private finite shape notation, not input-supplied expressions. U lists are
# bounded/sorted by identity; Q lists retain the embedded policy ordering rules.
_SHAPES = {
    "Pin": {"repository_id": "RepoID", "revision": "SHA"},
    "Subject": {"repository_id": "RepoID", "revision": "SHA", "path": "Path",
                "layer": "Text", "red_lines": "Seq:Text"},
    "Report": {"id": "ID", "ref": "Text", "digest": "Digest"},
    "Candidate": {"repository_id": "RepoID", "revision": "SHA", "tree": "SHA"},
    "Mapping": {"kind": "MappingKind", "tested_revision": "SHA", "tested_tree": "SHA",
                "source_revisions": "U+:SHA", "evidence": "?Report"},
    "Binding": {"candidate": "Candidate", "policy": "Pin", "phase": "Phase",
                "mapping": "Mapping"},
    "Item": {"id": "ID", "path": "Path"},
    "Exclusion": {"path": "Path", "reason": "Text"},
    "Scope": {"items": "U+:Item", "exclusions": "U:Exclusion", "basis": "Text"},
    "Tool": {"id": "ID", "version": "Text"},
    "Resource": {"id": "ID", "target": "Text", "owner": "ID", "marker": "Text"},
    "IsolationTarget": {"controls": "U+:Control", "resources": "U:Resource", "basis": "Text"},
    "Event": {"sequence": "Positive", "at": "Time"},
    "ControlResult": {"id": "Control", "state": "State"},
    "ResourceResult": {"id": "ID", "created_by_run": "ID", "ownership": "Match",
                       "marker": "Match", "cleanup": "State"},
    "Preflight": {"event": "Event", "controls": "U+:ControlResult"},
    "Cleanup": {"event": "Event", "state": "State", "resources": "U:ResourceResult"},
    "Isolation": {"run_id": "ID", "target": "IsolationTarget", "preflight": "Preflight",
                  "start": "Event", "finish": "Event", "cleanup": "Cleanup"},
    "MetricIDs": {metric: "ID" for metric in _METRICS},
    "Denominators": {metric: "Positive" for metric in _METRICS},
    "ScannerTarget": {"id": "ID", "items": "U+:ID"},
    "Measurement": {"state": "Measured", "numerator": "?Count", "denominator": "?Positive",
                    "report_id": "?ID"},
    "Measurements": {metric: "Measurement" for metric in _METRICS},
    "CaseResult": {"id": "ID", "status": "Status", "report_id": "ID"},
    "ScannerResult": {"id": "ID", "status": "Status", "verdict": "State",
                      "items": "U+:ID", "report_id": "ID"},
    "Condition": {"event": "ID", "condition": "Text"},
    "Waiver": {"policy": "Pin", "repository_id": "RepoID", "paths": "Q+:Path",
               "revisions": "Q+:SHA", "rule_id": "ID", "before": "Requirement",
               "after": "?Requirement", "reason": "Text", "expires_at": "?Time",
               "review_event": "?Condition", "alternative_verification": "Condition",
               "revocation_events": "Q+:Condition"},
    "Approval": {"schema": "Version", "approval_id": "ID", "evidence_ref": "Text",
                 "waiver": "Waiver"},
    "Baseline": {"schema": "Version", "policy": "Pin", "subject": "Subject", "rules": "Rules+"},
    "PolicyCandidate": {"schema": "Version", "policy": "Pin", "rules": "Rules",
                        "exceptions": "Seq:Approval"},
    "Observation": {"schema": "Version", "now": "Time", "events": "Events"},
    "PolicyInput": {"baseline": "Baseline", "candidate": "PolicyCandidate",
                    "approvals": "Seq:Approval", "observation": "Observation"},
    "PolicyCase": {"id": "ID", "input": "PolicyInput"},
    "Expectation": {"schema": "Version", "binding": "Binding", "policy_cases": "U+:PolicyCase",
                    "dimensions": "ExpectedDimensions"},
    "Evidence": {"schema": "Version", "binding": "Binding", "dimensions": "ObservedDimensions"},
    "ExpectedDimensions": {dim: "Expected" + dim for dim in _D},
    "ObservedDimensions": {dim: "Observed" + dim for dim in _D},
}
for _dim in _D:
    _bindings = {"obligation": "?ID", "scope": "ID"}
    if _dim == "L1":
        _bindings["metrics"] = "MetricIDs"
    if _dim == "G2":
        _bindings["scanners"] = "ID"
    _SHAPES["Bindings" + _dim] = _bindings
    _SHAPES["Target" + _dim] = {
        "L1": {"denominators": "Denominators"},
        "G2": {"scanners": "U+:ScannerTarget"},
        "D1": {"negative_cases": "U+:Negative"},
    }.get(_dim, {})
    _SHAPES["Payload" + _dim] = {
        "L1": {"metrics": "Measurements", "skipped": "Count", "focused": "Count",
               "integrity_report": "ID"},
        "L2": {"cases": "U+:CaseResult"}, "L3": {"cases": "U+:CaseResult"},
        "G1": {"errors": "Count", "warnings": "Count", "report_id": "ID"},
        "G2": {"scanners": "U+:ScannerResult"},
        "D1": {"runs": "U+:ID", "cases": "U+:CaseResult"},
    }[_dim]
    _SHAPES["Check" + _dim] = {
        "id": "ID", "subjects": "U+:Subject", "case_ids": "U+:ID", "level": "Level",
        "basis": "Text", "command": "Command:Text", "tools": "U+:Tool", "scope": "Scope",
        "reports": "U+:ID", "isolation": "IsolationTarget", "bindings": "Bindings" + _dim,
        "target": "Target" + _dim,
    }
    _SHAPES["Receipt" + _dim] = {
        "id": "ID", "binding": "Binding", "subjects": "U+:Subject", "command": "Command:Text",
        "tools": "U+:Tool", "scope": "Scope", "run_id": "?ID", "status": "Status",
        "reports": "U:Report", "isolation": "?Isolation", "payload": "?Payload" + _dim,
    }
    _SHAPES["Expected" + _dim] = {"owner": "ID", "checks": "U+:Check" + _dim}
    _SHAPES["Observed" + _dim] = {"implementation": "Impl", "enforcement": "Enforce",
                                "checks": "U:Receipt" + _dim}
del _dim, _bindings


def _key(value, name):
    if name == "Subject":
        return tuple(value[key] for key in ("repository_id", "revision", "path", "layer"))
    if name == "Exclusion":
        return value["path"]
    if name == "Condition":
        return value["event"]
    return value["id"] if type(value) is dict else value


def _shape(value, name):
    if name.startswith("?"):
        if value is not None:
            _shape(value, name[1:])
        return
    if ":" in name:
        mode, item_type = name.split(":")
        _require(type(value) is list)
        _require(not (mode.endswith("+") or mode == "Command") or bool(value))
        if mode.startswith("U") or mode == "Command":
            _require(len(value) <= 1024)
        for item in value:
            _shape(item, item_type)
        if mode.startswith(("U", "Q")):
            keys = [_key(item, item_type) for item in value]
            _require(all(left < right for left, right in zip(keys, keys[1:])))
        return
    if name in _SHAPES:
        fields = _SHAPES[name]
        _require(type(value) is dict and set(value) == set(fields))
        for key in sorted(fields):
            _shape(value[key], fields[key])
        if name == "Measurement":
            populated = [value[key] is not None for key in ("numerator", "denominator", "report_id")]
            _require(all(populated) if value["state"] == "measured" else not any(populated))
        if name.startswith("Receipt"):
            _require((value["run_id"] is None) == (value["isolation"] is None))
            if value["status"] == "pass":
                _require(value["run_id"] is not None and value["payload"] is not None)
        return
    if name in _ENUMS:
        _require(type(value) is str and value in _ENUMS[name])
    elif name == "Version":
        _require(type(value) is int)
        _require(value == 1, "quality_unsupported")
    elif name in ("Count", "Positive", "BP"):
        _require(type(value) is int and (1 if name == "Positive" else 0) <= value
                 <= (10000 if name == "BP" else _MAX))
    elif name in ("Rules", "Rules+", "Events"):
        _require(type(value) is dict and (name != "Rules+" or bool(value)))
        for key in sorted(value):
            _shape(key, "ID")
            _shape(value[key], "EventState" if name == "Events" else "Requirement")
    elif name == "Requirement":
        _require(type(value) is dict and "kind" in value)
        kind = value["kind"]
        _require(type(kind) is str)
        fields = {"required": {"kind": None},
                  "minimum_basis_points": {"kind": None, "value": "BP"},
                  "required_set": {"kind": None, "values": "Q:ID"}}.get(kind)
        _require(fields is not None)
        _require(set(value) == set(fields))
        for key in sorted(fields):
            if fields[key] is not None:
                _shape(value[key], fields[key])
    else:
        _require(type(value) is str)
        if name == "ID":
            _require(_re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value) is not None)
        elif name == "RepoID":
            _require(_re.fullmatch(r"[1-9][0-9]*", value) is not None)
        elif name in ("SHA", "Digest"):
            size = 40 if name == "SHA" else 64
            _require(_re.fullmatch(r"[0-9a-f]{%d}" % size, value) is not None
                     and value != "0" * size)
        elif name in ("Text", "Path"):
            _require(not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value))
            if name == "Text":
                _require(bool(value.strip()))
            else:
                _require(bool(value) and not value.startswith("/") and "\\" not in value
                         and all(part not in ("", ".", "..") for part in value.split("/")))
        elif name == "Time":
            _require(_re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
                                  value) is not None)
            try:
                _datetime.datetime(int(value[:4]), int(value[5:7]), int(value[8:10]),
                                   int(value[11:13]), int(value[14:16]), int(value[17:19]))
            except ValueError:
                raise _Invalid("quality_input_invalid") from None


def _ids(records):
    return [record["id"] for record in records]


def _identity_shapes(expectation, evidence):
    expected_ids, observed_ids, runs = [], [], []
    for dim in _D:
        expected_ids.extend(_ids(expectation["dimensions"][dim]["checks"]))
        receipts = evidence["dimensions"][dim]["checks"]
        observed_ids.extend(_ids(receipts))
        runs.extend(item["run_id"] for item in receipts if item["run_id"] is not None)
    for identities in (expected_ids, observed_ids, runs):
        _require(len(identities) == len(set(identities)))


def _contract(expectation):
    """Stage four examines baseline semantics only, never candidate rule values."""
    kind = "quality_contract_invalid"
    binding = expectation["binding"]
    candidate, mapping = binding["candidate"], binding["mapping"]
    if mapping["kind"] == "direct":
        _require(mapping["tested_revision"] == candidate["revision"]
                 and mapping["tested_tree"] == candidate["tree"]
                 and mapping["source_revisions"] == [candidate["revision"]]
                 and mapping["evidence"] is None, kind)
    else:
        _require(len(mapping["source_revisions"]) >= 2
                 and candidate["revision"] in mapping["source_revisions"]
                 and mapping["evidence"] is not None, kind)
    cases = {case["id"]: case["input"] for case in expectation["policy_cases"]}
    mapped = {case_id: [] for case_id in cases}
    used = set()
    negatives = {"abnormal_exit", "cleanup_refusal", "concurrent_run", "unsafe_target"}
    if any("ports" in check["isolation"]["controls"] for dim in _D
           for check in expectation["dimensions"][dim]["checks"]):
        negatives.add("port_collision")
    for dim in _D:
        checks = expectation["dimensions"][dim]["checks"]
        _require(any(check["level"] == "required" for check in checks), kind)
        for check in checks:
            slots = check["bindings"]
            _require((slots["obligation"] is None) == (check["level"] == "advisory"), kind)
            _require("state" in check["isolation"]["controls"], kind)
            subject_paths = {subject["path"] for subject in check["subjects"]}
            paths = {item["path"] for item in check["scope"]["items"]}
            exclusions = {item["path"] for item in check["scope"]["exclusions"]}
            _require(not paths & exclusions and subject_paths == paths | exclusions, kind)
            for subject in check["subjects"]:
                _require(subject["repository_id"] == candidate["repository_id"]
                         and subject["revision"] == candidate["revision"], kind)
            _require(all(case_id in cases for case_id in check["case_ids"]), kind)
            referenced = [cases[case_id]["baseline"]["subject"] for case_id in check["case_ids"]]
            _require(len(referenced) == len(check["subjects"])
                     and sorted(referenced, key=lambda item: _key(item, "Subject"))
                     == check["subjects"], kind)
            scope_ids = _ids(check["scope"]["items"])
            semantics = [(slots["scope"], {"kind": "required_set", "values": scope_ids})]
            if slots["obligation"] is not None:
                semantics.append((slots["obligation"], {"kind": "required"}))
            if dim == "L1":
                semantics.extend((slots["metrics"][metric], None) for metric in _METRICS)
            if dim == "G2":
                scanners = check["target"]["scanners"]
                _require(set(_ids(scanners)) <= set(_ids(check["tools"]))
                         and {item for scanner in scanners for item in scanner["items"]}
                         == set(scope_ids), kind)
                semantics.append((slots["scanners"], {"kind": "required_set", "values": _ids(scanners)}))
            if dim == "D1":
                _require(check["target"]["negative_cases"] == scope_ids
                         and negatives <= set(scope_ids), kind)
            for case_id in check["case_ids"]:
                used.add(case_id)
                case = cases[case_id]
                _require(case["baseline"]["policy"] == binding["policy"]
                         and case["candidate"]["policy"] == binding["policy"], kind)
                for rule_id, exact in semantics:
                    rule = case["baseline"]["rules"].get(rule_id)
                    if exact is None:
                        _require(rule is not None and rule["kind"] == "minimum_basis_points"
                                 and rule["value"] >= 9500, kind)
                    else:
                        _require(rule == exact, kind)
                    mapped[case_id].append(rule_id)
    _require(used == set(cases), kind)
    for case_id, case in cases.items():
        _require(len(mapped[case_id]) == len(set(mapped[case_id]))
                 and set(mapped[case_id]) == set(case["baseline"]["rules"]), kind)
    return cases


def _supported(expectation, cases):
    kind = "quality_unsupported"
    _require(expectation["binding"]["phase"] == "actions", kind)
    for case in cases.values():
        baseline, candidate = case["baseline"]["rules"], case["candidate"]["rules"]
        _require(set(candidate) == set(baseline), kind)
        for rule_id, before in baseline.items():
            after = candidate[rule_id]
            _require(after["kind"] == before["kind"], kind)
            if before["kind"] != "minimum_basis_points":
                _require(after == before, kind)


def _isolation_ok(receipt, check):
    run = receipt["run_id"]
    isolation = receipt["isolation"]
    if run is None or isolation is None:
        return False
    target = check["isolation"]
    if isolation["run_id"] != run or isolation["target"] != target:
        return False
    preflight, cleanup = isolation["preflight"], isolation["cleanup"]
    controls = preflight["controls"]
    if (_ids(controls) != target["controls"] or "state" not in target["controls"]
            or any(control["state"] != "pass" for control in controls)):
        return False
    events = [preflight["event"], isolation["start"], isolation["finish"], cleanup["event"]]
    if any(left["sequence"] >= right["sequence"] or left["at"] > right["at"]
           for left, right in zip(events, events[1:])):
        return False
    return (cleanup["state"] == "pass" and _ids(cleanup["resources"]) == _ids(target["resources"])
            and all(row["created_by_run"] == run and row["ownership"] == "match"
                    and row["marker"] == "match" and row["cleanup"] == "pass"
                    for row in cleanup["resources"]))


def _references(dim, payload):
    if payload is None:
        return []
    if dim == "L1":
        return [payload["integrity_report"]] + [value["report_id"]
                for value in payload["metrics"].values() if value["report_id"] is not None]
    if dim == "G1":
        return [payload["report_id"]]
    return [row["report_id"] for row in payload["scanners" if dim == "G2" else "cases"]]


def _predicate(dim, check, receipt, cases, runs):
    payload = receipt["payload"]
    if payload is None:
        return "quality_measurement" if dim == "L1" else "quality_coverage"
    scope_ids = _ids(check["scope"]["items"])
    if dim == "L1":
        if payload["skipped"] or payload["focused"]:
            return "quality_measurement"
        for metric in _METRICS:
            value = payload["metrics"][metric]
            if value["state"] != "measured" or any(value[key] is None
                    for key in ("numerator", "denominator", "report_id")):
                return "quality_measurement"
            rule_id = check["bindings"]["metrics"][metric]
            threshold = max(cases[case_id]["candidate"]["rules"][rule_id]["value"]
                            for case_id in check["case_ids"])
            if (value["denominator"] != check["target"]["denominators"][metric]
                    or value["numerator"] > value["denominator"]
                    or value["numerator"] * 10000 < threshold * value["denominator"]):
                return "quality_measurement"
    elif dim in ("L2", "L3", "D1"):
        if (_ids(payload["cases"]) != scope_ids
                or any(row["status"] != "pass" for row in payload["cases"])):
            return "quality_coverage"
        if dim == "D1" and payload["runs"] != sorted(runs):
            return "quality_coverage"
    elif dim == "G1":
        if payload["errors"] or payload["warnings"]:
            return "quality_measurement"
    elif dim == "G2":
        expected = check["target"]["scanners"]
        observed = payload["scanners"]
        if (_ids(observed) != _ids(expected)
                or any(row["items"] != target["items"] or row["status"] != "pass"
                       or row["verdict"] != "pass" for row, target in zip(observed, expected))):
            return "quality_coverage"
    return None


def _check(dim, check, receipt, binding, cases, runs):
    if receipt is None:
        return "not_run", "quality_missing"
    if (receipt["binding"] != binding or any(receipt[key] != check[key]
            for key in ("subjects", "command", "tools", "scope"))):
        return "fail", "quality_binding_mismatch"
    if receipt["status"] != "pass":
        status = receipt["status"]
        return (status if status in ("not_run", "unavailable", "unknown") else "fail",
                "quality_nonpass")
    report_ids = _ids(receipt["reports"])
    if (report_ids != check["reports"]
            or not set(_references(dim, receipt["payload"])) <= set(report_ids)):
        return "fail", "quality_coverage"
    failure = _predicate(dim, check, receipt, cases, runs)
    if failure:
        return "fail", failure
    if not _isolation_ok(receipt, check):
        return "fail", "quality_isolation"
    if dim == "D1" and any(not _isolation_ok(row, owner) for row, owner in runs.values()):
        return "fail", "quality_isolation"
    return "pass", None


def _copy(value):
    if type(value) is dict:
        return {key: _copy(item) for key, item in value.items()}
    if type(value) is list:
        return [_copy(item) for item in value]
    return value


def _finding(kind, subject=None):
    return {"layer": "quality" if subject is None else subject["layer"],
            "path": "" if subject is None else subject["path"], "kind": kind,
            "detail": _DETAIL[kind],
            "red_lines": [] if subject is None else list(subject["red_lines"])}


def _output():
    return {"schema": 1, "binding": None, "required_acceptable": False, "dimensions": {},
            "findings": [], "applied_exceptions": [],
            "assurance": {"authenticity": "not_verified", "enforcement": "not_verified",
                          "ship": "not_assessed"}}


def aggregate_6dq(*, expectation: dict, evidence: dict) -> dict:
    """Reconcile caller-supplied native data. No I/O, execution or trust claims.

    The caller owns decoding, trusted import resolution and input stability.
    All returned containers are new. See the contract for exact precedence.
    """
    result = _output()
    try:
        _native(expectation, evidence)
        _shape(expectation, "Expectation")
        _shape(evidence, "Evidence")
        _identity_shapes(expectation, evidence)
        applied = set()
        for case in expectation["policy_cases"]:
            evaluated = _evaluate_policy(**case["input"])
            _require(evaluated["eligible"], "quality_policy_rejected")
            applied.update(evaluated["applied_exceptions"])
        cases = _contract(expectation)
        _supported(expectation, cases)
        _require(evidence["binding"] == expectation["binding"], "quality_binding_mismatch")
        runs = {}
        receipts = {}
        for dim in _D:
            expected = {check["id"]: check for check in expectation["dimensions"][dim]["checks"]}
            observed = {row["id"]: row for row in evidence["dimensions"][dim]["checks"]}
            _require(set(observed) <= set(expected), "quality_binding_mismatch")
            receipts[dim] = observed
            for check_id, row in observed.items():
                if row["run_id"] is not None:
                    runs[row["run_id"]] = (row, expected[check_id])
    except _Invalid as error:
        result["findings"] = [_finding(error.kind)]
        for dim in _D:
            result["dimensions"][dim] = {
                "owner": None, "implementation": "unknown", "enforcement": "unknown",
                "latest": "unsupported" if error.kind == "quality_unsupported" else "unknown",
                "checks": [], "gaps": [],
            }
        return result
    result["binding"] = _copy(expectation["binding"])
    result["required_acceptable"] = True
    priority = ("fail", "unsupported", "unknown", "unavailable", "not_run", "pass")
    for dim in _D:
        observed = evidence["dimensions"][dim]
        dimension = {"owner": expectation["dimensions"][dim]["owner"],
                     "implementation": observed["implementation"], "enforcement": observed["enforcement"],
                     "latest": "pass", "checks": [], "gaps": []}
        for check in expectation["dimensions"][dim]["checks"]:
            receipt = receipts[dim].get(check["id"])
            outcome, kind = _check(dim, check, receipt, expectation["binding"], cases, runs)
            findings = [] if kind is None else [_finding(kind, check["subjects"][0])]
            dimension["checks"].append({"id": check["id"], "requirement": check["level"],
                                        "observed": None if receipt is None else receipt["status"],
                                        "result": outcome, "findings": findings})
            if kind is not None:
                dimension["gaps"].append({"check_id": check["id"], "kind": kind})
                result["findings"].extend(_copy(findings))
            if check["level"] == "required" and outcome != "pass":
                result["required_acceptable"] = False
        dimension["latest"] = min((row["result"] for row in dimension["checks"]), key=priority.index)
        result["dimensions"][dim] = dimension
    if result["required_acceptable"]:
        result["applied_exceptions"] = sorted(applied)
    return result
