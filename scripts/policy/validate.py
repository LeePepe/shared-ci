"""Pure, caller-trusted policy eligibility; no approval or enforcement authority."""

import datetime as _datetime
import re as _re


class _Invalid(Exception):
    def __init__(self, kind, detail):
        self.kind = kind
        self.detail = detail


def _reject(detail, kind="policy_input_invalid"):
    raise _Invalid(kind, detail)


def _native_tree(*roots):
    """Count occurrences (including keys); reject cycles, not shared subtrees."""
    active = set()
    nodes = 0

    def visit(value, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 100000:
            _reject("Input exceeds the 100000-node limit.")
        if depth > 32:
            _reject("Input exceeds the 32-level depth limit.")
        value_type = type(value)
        if not any(value_type is native for native in (dict, list, str, int, type(None))):
            _reject("Input contains a non-native or forbidden value type.")
        if value_type is not dict and value_type is not list:
            return
        identity = id(value)
        if identity in active:
            _reject("Input contains a cycle.")
        active.add(identity)
        if value_type is dict:
            if any(type(key) is not str for key in value):
                _reject("Object keys must be native strings.")
            for key in sorted(value):
                visit(key, depth + 1)
                visit(value[key], depth + 1)
        else:
            for child in value:
                visit(child, depth + 1)
        active.remove(identity)

    for root in roots:
        visit(root, 1)


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _reject("Object must contain exactly its v1 required fields.")


def _version(value):
    if type(value) is not int:
        _reject("Schema must be a native integer.")
    if value != 1:
        _reject("Only schema 1 is supported.", "policy_schema_unsupported")


def _utf8(value):
    if type(value) is not str:
        _reject("String field must be a native string.")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError:
        _reject("String field must encode as strict UTF-8.")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        _reject("String field contains a forbidden control character.")


def _text(value):
    _utf8(value)
    if not value.strip():
        _reject("Text field must be nonblank.")


def _id(value):
    if type(value) is not str or not _re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", value):
        _reject("Identifier must match the v1 identifier grammar.")


def _repo(value):
    if type(value) is not str or not _re.fullmatch(r"[1-9][0-9]*", value):
        _reject("Repository ID must be a positive decimal string without leading zero.")


def _sha(value):
    if (type(value) is not str or not _re.fullmatch(r"[0-9a-f]{40}", value)
            or value == "0" * 40):
        _reject("Revision must be a nonzero lowercase 40-hex SHA.")


def _path(value):
    _utf8(value)
    if (not value or value.startswith("/") or "\\" in value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        _reject("Path must be a literal UTF-8 Git-relative name with valid segments.")


def _timestamp(value):
    if type(value) is not str or not _re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        _reject("Timestamp must use YYYY-MM-DDTHH:MM:SSZ.")
    try:
        _datetime.datetime(int(value[:4]), int(value[5:7]), int(value[8:10]),
                           int(value[11:13]), int(value[14:16]), int(value[17:19]))
    except ValueError:
        _reject("Timestamp must be a valid Gregorian UTC date and time.")


def _list(value, validate_item, *, nonempty=False, ordered=False):
    if type(value) is not list or (nonempty and not value):
        _reject("List field has invalid type or is required to be nonempty.")
    for item in value:
        validate_item(item)
    if ordered and any(left >= right for left, right in zip(value, value[1:])):
        _reject("List must be strictly sorted and duplicate-free.")


def _pin(value):
    _object(value, ("repository_id", "revision"))
    _repo(value["repository_id"])
    _sha(value["revision"])


def _subject(value):
    _object(value, ("repository_id", "revision", "path", "layer", "red_lines"))
    _repo(value["repository_id"])
    _sha(value["revision"])
    _path(value["path"])
    _text(value["layer"])
    _list(value["red_lines"], _text)


def _requirement(value):
    if type(value) is not dict or "kind" not in value:
        _reject("Requirement must be an object with a kind.")
    kind = value["kind"]
    _text(kind)
    if kind == "required":
        _object(value, ("kind",))
    elif kind == "minimum_basis_points":
        _object(value, ("kind", "value"))
        if type(value["value"]) is not int or not 0 <= value["value"] <= 10000:
            _reject("Minimum must be a native integer in 0..10000.")
    elif kind == "required_set":
        _object(value, ("kind", "values"))
        _list(value["values"], _id, ordered=True)
    else:
        _reject("Requirement kind is not supported in v1.", "policy_kind_unsupported")


def _rules(value, *, nonempty=False):
    if type(value) is not dict or (nonempty and not value):
        _reject("Rules must be an object; baseline rules must be nonempty.")
    for rule_id in sorted(value):
        _id(rule_id)
        _requirement(value[rule_id])


def _condition(value):
    _object(value, ("event", "condition"))
    _id(value["event"])
    _text(value["condition"])


def _approval(value):
    _object(value, ("schema", "approval_id", "evidence_ref", "waiver"))
    _version(value["schema"])
    _id(value["approval_id"])
    _text(value["evidence_ref"])
    waiver = value["waiver"]
    _object(waiver, ("policy", "repository_id", "paths", "revisions", "rule_id",
                     "before", "after", "reason", "expires_at", "review_event",
                     "alternative_verification", "revocation_events"))
    _pin(waiver["policy"])
    _repo(waiver["repository_id"])
    _list(waiver["paths"], _path, nonempty=True, ordered=True)
    _list(waiver["revisions"], _sha, nonempty=True, ordered=True)
    _id(waiver["rule_id"])
    _requirement(waiver["before"])
    if waiver["after"] is not None:
        _requirement(waiver["after"])
    _text(waiver["reason"])
    if waiver["expires_at"] is not None:
        _timestamp(waiver["expires_at"])
    if waiver["review_event"] is not None:
        _condition(waiver["review_event"])
    if waiver["expires_at"] is None and waiver["review_event"] is None:
        _reject("Waiver requires expiry, review event, or both.")
    _condition(waiver["alternative_verification"])
    revocations = waiver["revocation_events"]
    _list(revocations, _condition, nonempty=True)
    event_ids = [item["event"] for item in revocations]
    if any(left >= right for left, right in zip(event_ids, event_ids[1:])):
        _reject("Revocation events must be sorted by unique event ID.")


def _approvals(value, *, claims=False):
    _list(value, _approval)
    ids = [item["approval_id"] for item in value]
    if len(set(ids)) != len(ids):
        _reject("Approval IDs must be unique within each record list.")
    if claims:
        rule_ids = [item["waiver"]["rule_id"] for item in value]
        if len(set(rule_ids)) != len(rule_ids):
            _reject("Candidate may claim only one exception per rule.")


def _inputs(baseline, candidate, approvals, observation):
    _object(baseline, ("schema", "policy", "subject", "rules"))
    _version(baseline["schema"])
    _pin(baseline["policy"])
    _subject(baseline["subject"])
    _rules(baseline["rules"], nonempty=True)
    _object(candidate, ("schema", "policy", "rules", "exceptions"))
    _version(candidate["schema"])
    _pin(candidate["policy"])
    _rules(candidate["rules"])
    _approvals(candidate["exceptions"], claims=True)
    _approvals(approvals)
    _object(observation, ("schema", "now", "events"))
    _version(observation["schema"])
    _timestamp(observation["now"])
    if type(observation["events"]) is not dict:
        _reject("Observation events must be an object.")
    for event_id in sorted(observation["events"]):
        _id(event_id)
        state = observation["events"][event_id]
        if type(state) is not str or state not in ("occurred", "not_occurred", "unknown"):
            _reject("Event state must be occurred, not_occurred, or unknown.")


def _difference(before, after):
    if after is None:
        return "policy_requirement_missing"
    if before["kind"] != after["kind"]:
        return "policy_kind_changed"
    if before["kind"] == "minimum_basis_points" and after["value"] < before["value"]:
        return "policy_requirement_weakened"
    if before["kind"] == "required_set" and not set(before["values"]) <= set(after["values"]):
        return "policy_requirement_weakened"
    return None


def _event(condition, events, expected, failure):
    state = events.get(condition["event"], "unknown")
    if state == "unknown":
        _reject("Required condition has no known observation.", "policy_condition_unknown")
    if state != expected:
        _reject("Observed condition does not meet the waiver requirement.", failure)


def _claim(claim, records, baseline, candidate, observation):
    if records.get(claim["approval_id"]) != claim:
        _reject("Claim must match a complete external approval record.", "policy_approval_mismatch")
    waiver = claim["waiver"]
    subject = baseline["subject"]
    if waiver["policy"] != baseline["policy"]:
        _reject("Waiver policy pin must equal the baseline pin.", "policy_pin_mismatch")
    if (waiver["repository_id"] != subject["repository_id"]
            or subject["path"] not in waiver["paths"]
            or subject["revision"] not in waiver["revisions"]):
        _reject("Waiver must cover the exact subject repository, path and revision.", "policy_scope_mismatch")
    rule_id = waiver["rule_id"]
    if rule_id not in baseline["rules"]:
        _reject("Exception does not address a baseline rule.", "policy_exception_unused")
    before = baseline["rules"][rule_id]
    after = candidate["rules"].get(rule_id)
    if waiver["before"] != before or waiver["after"] != after:
        _reject("Waiver before and after must equal the actual rule content.", "policy_approval_mismatch")
    if _difference(before, after) is None:
        _reject("Exception does not address an actual weakening or removal.", "policy_exception_unused")
    if waiver["expires_at"] is not None and observation["now"] >= waiver["expires_at"]:
        _reject("Waiver expiry must be strictly later than observation time.", "policy_exception_expired")
    if waiver["review_event"] is not None:
        _event(waiver["review_event"], observation["events"], "not_occurred", "policy_review_due")
    for condition in waiver["revocation_events"]:
        _event(condition, observation["events"], "not_occurred", "policy_exception_revoked")
    _event(waiver["alternative_verification"], observation["events"], "occurred", "policy_alternative_unmet")


def evaluate_policy(*, baseline: dict, candidate: dict, approvals: list,
                    observation: dict) -> dict:
    """Return eligibility, one first finding on failure, and sorted applied IDs.

    Inputs are caller-authenticated native data, never read or authenticated here.
    The caller must not mutate them concurrently. See the v1 contract for trust,
    literal path semantics, ordering, limits and decoder requirements.
    """
    layer, path, red_lines = "policy", "", []
    # Independent subject validation permits safe attribution even when another
    # input is malformed. Never inspect custom mappings or trust a partial subject.
    if (type(baseline) is dict and all(type(key) is str for key in baseline)
            and "subject" in baseline):
        try:
            subject = baseline["subject"]
            _native_tree(subject)
            _subject(subject)
        except _Invalid:
            pass
        else:
            layer, path = subject["layer"], subject["path"]
            red_lines = list(subject["red_lines"])
    try:
        _native_tree(baseline, candidate, approvals, observation)
        _inputs(baseline, candidate, approvals, observation)
        if candidate["policy"] != baseline["policy"]:
            _reject("Candidate policy pin must equal the baseline pin.", "policy_pin_mismatch")
        records = {item["approval_id"]: item for item in approvals}
        applied = []
        covered = set()
        for claim in sorted(candidate["exceptions"], key=lambda item: item["approval_id"]):
            _claim(claim, records, baseline, candidate, observation)
            applied.append(claim["approval_id"])
            covered.add(claim["waiver"]["rule_id"])
        for rule_id in sorted(baseline["rules"]):
            difference = _difference(baseline["rules"][rule_id], candidate["rules"].get(rule_id))
            if difference == "policy_kind_changed":
                _reject("Baseline rule kind cannot be substituted.", difference)
            if difference is not None and rule_id not in covered:
                _reject("Baseline rule requires an exact eligible exception.", difference)
        return {"eligible": True, "findings": [], "applied_exceptions": applied}
    except _Invalid as error:
        return {"eligible": False, "findings": [{
            "layer": layer, "path": path, "kind": error.kind,
            "detail": error.detail, "red_lines": red_lines,
        }], "applied_exceptions": []}
