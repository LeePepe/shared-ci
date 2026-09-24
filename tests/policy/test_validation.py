"""Synthetic public-interface cases. Execution requires the separate review gate.

The loader reads only the reviewed evaluator source (no bytecode cache lookup).
Schema reads below are the only other repository reads. No context fixtures.
"""

import ast
import copy
import json
from pathlib import Path
import re
import unittest


_ROOT = Path(__file__).parents[2]
_MODULE = _ROOT / "scripts/policy/validate.py"
_SOURCE = _MODULE.read_text(encoding="utf-8")
_NAMESPACE = {"__name__": "policy_under_test"}
exec(compile(_SOURCE, str(_MODULE), "exec"), _NAMESPACE)
evaluate_policy = _NAMESPACE["evaluate_policy"]


def _fixture(path="src/a.py"):
    baseline = {
        "schema": 1,
        "policy": {"repository_id": "101", "revision": "a" * 40},
        "subject": {"repository_id": "202", "revision": "b" * 40,
                    "path": path, "layer": "synthetic-layer",
                    "red_lines": ["Synthetic constraint"]},
        "rules": {"check": {"kind": "required"},
                  "score": {"kind": "minimum_basis_points", "value": 7500},
                  "suite": {"kind": "required_set", "values": ["Alpha", "Beta"]}},
    }
    return {
        "baseline": baseline,
        "candidate": {"schema": 1, "policy": copy.deepcopy(baseline["policy"]),
                      "rules": copy.deepcopy(baseline["rules"]), "exceptions": []},
        "approvals": [],
        "observation": {"schema": 1, "now": "2030-02-28T12:00:00Z",
                        "events": {"Alternative": "occurred", "Review": "not_occurred",
                                   "Revocation": "not_occurred"}},
    }


def _grant(data, rule="score", approval_id="ApprovalA", after="lower"):
    """Create independently copied synthetic records; no real authority implied."""
    if after == "lower":
        after = {"kind": "minimum_basis_points", "value": 7000}
    before = copy.deepcopy(data["baseline"]["rules"][rule])
    if after is None:
        data["candidate"]["rules"].pop(rule)
    else:
        data["candidate"]["rules"][rule] = copy.deepcopy(after)
    approval = {
        "schema": 1, "approval_id": approval_id,
        "evidence_ref": "Synthetic evidence record",
        "waiver": {
            "policy": copy.deepcopy(data["baseline"]["policy"]),
            "repository_id": data["baseline"]["subject"]["repository_id"],
            "paths": [data["baseline"]["subject"]["path"]],
            "revisions": [data["baseline"]["subject"]["revision"]],
            "rule_id": rule, "before": before, "after": copy.deepcopy(after),
            "reason": "Synthetic rationale", "expires_at": "2030-03-01T00:00:00Z",
            "review_event": {"event": "Review", "condition": "Synthetic review trigger"},
            "alternative_verification": {"event": "Alternative", "condition": "Synthetic alternative"},
            "revocation_events": [{"event": "Revocation", "condition": "Synthetic revoke trigger"}],
        },
    }
    data["candidate"]["exceptions"].append(copy.deepcopy(approval))
    data["approvals"].append(copy.deepcopy(approval))
    return data["candidate"]["exceptions"][-1]


def _sync(data):
    data["approvals"] = copy.deepcopy(data["candidate"]["exceptions"])


def _assign(root, keys, value):
    for key in keys[:-1]:
        root = root[key]
    root[keys[-1]] = value


def _nodes(value):
    if type(value) is dict:
        return 1 + sum(1 + _nodes(child) for child in value.values())
    if type(value) is list:
        return 1 + sum(_nodes(child) for child in value)
    return 1


class PolicyValidationTests(unittest.TestCase):
    def success(self, data, ids=()):
        result = evaluate_policy(**data)
        self.assertEqual(result, {"eligible": True, "findings": [],
                                  "applied_exceptions": sorted(ids)})
        return result

    def failure(self, data, kind="policy_input_invalid", *, fallback=False):
        result = evaluate_policy(**data)
        self.assertEqual(set(result), {"eligible", "findings", "applied_exceptions"})
        self.assertIs(result["eligible"], False)
        self.assertEqual(result["applied_exceptions"], [])
        self.assertEqual(len(result["findings"]), 1)
        finding = result["findings"][0]
        self.assertEqual(set(finding), {"layer", "path", "kind", "detail", "red_lines"})
        self.assertEqual(finding["kind"], kind)
        self.assertIsInstance(finding["detail"], str)
        self.assertTrue(finding["detail"])
        subject = ({"layer": "policy", "path": "", "red_lines": []} if fallback
                   else data["baseline"]["subject"])
        for field in ("layer", "path", "red_lines"):
            self.assertEqual(finding[field], subject[field])
        return finding

    def test_e01_exact_baseline(self):
        self.success(_fixture())

    def test_e02_supported_stricter_and_added_rules(self):
        data = _fixture()
        data["candidate"]["rules"]["score"]["value"] = 10000
        data["candidate"]["rules"]["suite"]["values"].append("Gamma")
        data["candidate"]["rules"]["additional"] = {"kind": "required"}
        self.success(data)
        data["baseline"]["rules"]["suite"]["values"] = []
        self.success(data)

    def test_e03_unapproved_weakenings_and_removals(self):
        for rule, after in (("score", {"kind": "minimum_basis_points", "value": 7499}),
                            ("suite", {"kind": "required_set", "values": ["Alpha"]}),
                            ("suite", {"kind": "required_set", "values": ["Delta", "Gamma"]}),
                            ("check", None), ("score", None), ("suite", None)):
            with self.subTest(rule=rule, removed=after is None):
                data = _fixture()
                if after is None:
                    data["candidate"]["rules"].pop(rule)
                else:
                    data["candidate"]["rules"][rule] = after
                self.failure(data, "policy_requirement_missing" if after is None
                             else "policy_requirement_weakened")

    def test_e04_approved_weakening_and_removal(self):
        for rule, after in (("score", {"kind": "minimum_basis_points", "value": 0}),
                            ("suite", {"kind": "required_set", "values": []}),
                            ("check", None), ("score", None), ("suite", None)):
            with self.subTest(rule=rule, removed=after is None):
                data = _fixture()
                _grant(data, rule=rule, after=after)
                self.success(data, ["ApprovalA"])

    def test_e05_exact_pins_no_sha_ordering(self):
        for field, replacement in (("repository_id", "303"), ("revision", "c" * 40),
                                   ("revision", "1" * 40)):
            for target in ("candidate", "waiver"):
                with self.subTest(field=field, target=target, replacement=replacement[:1]):
                    data = _fixture()
                    claim = _grant(data)
                    pin = data["candidate"]["policy"] if target == "candidate" else claim["waiver"]["policy"]
                    pin[field] = replacement
                    _sync(data)
                    self.failure(data, "policy_pin_mismatch")

    def test_e06_exact_scope_not_prefix_directory_glob_or_range(self):
        changes = (("repository_id", "303"), ("revision", "c" * 40),
                   ("path", "src/ab.py"), ("path", "src/a.py/child"),
                   ("path", "src-sibling/a.py"), ("path", "src/A.py"))
        for field, replacement in changes:
            with self.subTest(field=field, replacement=replacement):
                data = _fixture()
                _grant(data)
                data["baseline"]["subject"][field] = replacement
                self.failure(data, "policy_scope_mismatch")
        for spelling in ("src", "src/*", "*", "src/**"):
            with self.subTest(literal_scope=spelling):
                data = _fixture()
                claim = _grant(data)
                claim["waiver"]["paths"] = [spelling]
                _sync(data)
                self.failure(data, "policy_scope_mismatch")

    def test_e07a_literal_utf8_space_and_punctuation_paths(self):
        paths = ("SampleWatch Watch App/Sources/SampleWatchApp.swift",
                 "示例模块/消费者 测试.swift", "assets/100% complete.txt", "src/%61.py",
                 "src/%2F.py", "src/%2e%2e/a.py", "src/*.py", "src/[a]?.py",
                 " leading / trailing ", " ", "🚀/🧪.swift", "src/a:b.py")
        for index, path in enumerate(paths):
            with self.subTest(case=index):
                data = _fixture(path)
                _grant(data)
                self.success(data, ["ApprovalA"])

    def test_e07b_lexical_invalid_paths_in_subject_and_scope(self):
        paths = ("", "/src/a.py", "src//a.py", "src/", "./src/a.py", "src/../a.py",
                 "src/./a.py", ".", "..", "src/..", "src/.", "src\\a.py",
                 "src/\x00a", "src/\x1fa", "src/\x7fa", "src/\x85a", "src/\x9fa",
                 "src/\ud800a", "src/\udfffa")
        for index, path in enumerate(paths):
            for target in ("subject", "scope"):
                with self.subTest(case=index, target=target):
                    data = _fixture()
                    claim = _grant(data)
                    if target == "subject":
                        data["baseline"]["subject"]["path"] = path
                    else:
                        claim["waiver"]["paths"] = [path]
                        _sync(data)
                    self.failure(data, fallback=target == "subject")

    def test_e07cd_no_decoding_normalization_or_alias_expansion(self):
        pairs = (("src/a.py", "src/%61.py"), ("src/a b.py", "src/a%20b.py"),
                 ("src/a.py", "src%2Fa.py"), ("café.swift", "cafe\u0301.swift"),
                 ("src/a.py", "src/A.py"), ("src/a.py", " src/a.py"),
                 ("src/a.py", "src/a.py "), ("src/a b.py", "src/a  b.py"),
                 ("src/a.py", "src∕a.py"), ("src/a.py", "src／a.py"))
        for index, (approved, actual) in enumerate(pairs):
            with self.subTest(case=index):
                data = _fixture(approved)
                _grant(data)
                data["baseline"]["subject"]["path"] = actual
                self.failure(data, "policy_scope_mismatch")
                exact = _fixture(actual)
                _grant(exact)
                self.success(exact, ["ApprovalA"])

    def test_e08_complete_record_binding_every_content_field(self):
        changes = ((["approval_id"], "OtherApproval"),
                   (["evidence_ref"], "Different synthetic evidence"),
                   (["waiver", "policy", "repository_id"], "303"),
                   (["waiver", "policy", "revision"], "c" * 40),
                   (["waiver", "repository_id"], "303"),
                   (["waiver", "paths"], ["src/other.py"]),
                   (["waiver", "revisions"], ["c" * 40]),
                   (["waiver", "rule_id"], "suite"),
                   (["waiver", "before", "value"], 7600),
                   (["waiver", "after", "value"], 6900),
                   (["waiver", "after"], None),
                   (["waiver", "reason"], "Different synthetic reason"),
                   (["waiver", "expires_at"], "2031-01-01T00:00:00Z"),
                   (["waiver", "review_event"], None),
                   (["waiver", "review_event", "event"], "OtherReview"),
                   (["waiver", "review_event", "condition"], "Other review condition"),
                   (["waiver", "alternative_verification", "event"], "OtherAlternative"),
                   (["waiver", "alternative_verification", "condition"], "Other verification"),
                   (["waiver", "revocation_events", 0, "event"], "OtherRevocation"),
                   (["waiver", "revocation_events", 0, "condition"], "Other revocation"))
        for index, (keys, replacement) in enumerate(changes):
            with self.subTest(case=index):
                data = _fixture()
                claim = _grant(data)
                _assign(claim, keys, replacement)
                self.failure(data, "policy_approval_mismatch")
        for original, substituted in (("src/%61.py", "src/a.py"),
                                      ("cafe\u0301.swift", "café.swift")):
            data = _fixture(original)
            claim = _grant(data)
            claim["waiver"]["paths"] = [substituted]
            self.failure(data, "policy_approval_mismatch")

    def test_e08_object_key_order_is_irrelevant(self):
        def reverse_keys(value):
            if type(value) is dict:
                return {key: reverse_keys(value[key]) for key in reversed(value)}
            if type(value) is list:
                return [reverse_keys(item) for item in value]
            return value

        data = _fixture()
        _grant(data)
        data["approvals"] = reverse_keys(data["approvals"])
        self.success(data, ["ApprovalA"])
        self.assertEqual(evaluate_policy(**data), evaluate_policy(**reverse_keys(data)))

    def test_e08_matching_records_still_require_actual_before_after(self):
        for field, value in (("before", {"kind": "minimum_basis_points", "value": 7499}),
                             ("after", {"kind": "minimum_basis_points", "value": 6999}),
                             ("after", None)):
            data = _fixture()
            claim = _grant(data)
            claim["waiver"][field] = value
            _sync(data)
            self.failure(data, "policy_approval_mismatch")

    def test_e09_expiry_edges(self):
        for now, expected in (("2030-02-28T23:59:59Z", None),
                              ("2030-03-01T00:00:00Z", "policy_exception_expired"),
                              ("2030-03-01T00:00:01Z", "policy_exception_expired")):
            data = _fixture()
            _grant(data)
            data["observation"]["now"] = now
            if expected:
                self.failure(data, expected)
            else:
                self.success(data, ["ApprovalA"])

    def test_e09_timestamp_lexical_and_calendar_checks(self):
        invalid = ("2030-02-29T00:00:00Z", "1900-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
                   "2030-04-31T00:00:00Z", "2030-13-01T00:00:00Z", "2030-00-01T00:00:00Z",
                   "2030-01-00T00:00:00Z", "2030-01-01T24:00:00Z", "2030-01-01T00:60:00Z",
                   "2030-01-01T00:00:60Z", "2030-1-01T00:00:00Z", "2030-01-01t00:00:00z",
                   "2030-01-01T00:00:00+00:00", "2030-01-01T00:00:00.0Z",
                   "2030-01-01T00:00:00Z\n", "２０３０-01-01T00:00:00Z", None, 1)
        for index, value in enumerate(invalid):
            for field in ("now", "expires_at"):
                if field == "expires_at" and value is None:
                    continue
                with self.subTest(case=index, field=field):
                    data = _fixture()
                    claim = _grant(data)
                    if field == "now":
                        data["observation"]["now"] = value
                    else:
                        claim["waiver"]["expires_at"] = value
                        _sync(data)
                    self.failure(data)
        for value in ("2000-02-29T00:00:00Z", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"):
            data = _fixture()
            data["observation"]["now"] = value
            self.success(data)

    def test_e10_event_states_and_missing_observations(self):
        cases = (("Review", "occurred", "policy_review_due"),
                 ("Revocation", "occurred", "policy_exception_revoked"),
                 ("Alternative", "not_occurred", "policy_alternative_unmet"))
        for event, state, expected in cases:
            data = _fixture()
            _grant(data)
            data["observation"]["events"][event] = state
            self.failure(data, expected)
        for event in ("Review", "Revocation", "Alternative"):
            for state in (None, "unknown"):
                with self.subTest(event=event, missing=state is None):
                    data = _fixture()
                    _grant(data)
                    if state is None:
                        data["observation"]["events"].pop(event)
                    else:
                        data["observation"]["events"][event] = state
                    self.failure(data, "policy_condition_unknown")

    def test_e10_expiry_or_review_or_both_and_all_revocations(self):
        for field in ("expires_at", "review_event"):
            data = _fixture()
            claim = _grant(data)
            claim["waiver"][field] = None
            _sync(data)
            if field == "review_event":
                data["observation"]["events"].pop("Review")
            self.success(data, ["ApprovalA"])
        data = _fixture()
        claim = _grant(data)
        claim["waiver"]["expires_at"] = None
        claim["waiver"]["review_event"] = None
        _sync(data)
        self.failure(data)
        data = _fixture()
        claim = _grant(data)
        claim["waiver"]["revocation_events"].append({"event": "RevocationB", "condition": "Another trigger"})
        _sync(data)
        self.failure(data, "policy_condition_unknown")
        data["observation"]["events"]["RevocationB"] = "not_occurred"
        self.success(data, ["ApprovalA"])
        data["observation"]["events"]["RevocationB"] = "occurred"
        self.failure(data, "policy_exception_revoked")

    def test_e11_schemas_require_native_integer_one(self):
        for location in ("baseline", "candidate", "observation", "claim", "external"):
            for value, expected in ((2, "policy_schema_unsupported"), (0, "policy_schema_unsupported"),
                                    (True, "policy_input_invalid"), (1.0, "policy_input_invalid"),
                                    ("1", "policy_input_invalid"), (None, "policy_input_invalid")):
                with self.subTest(location=location, type=type(value).__name__):
                    data = _fixture()
                    claim = _grant(data)
                    target = claim if location == "claim" else (data["approvals"][0] if location == "external" else data[location])
                    target["schema"] = value
                    self.failure(data, expected)

    def test_e11_unknown_kinds_and_kind_substitution_cannot_be_waived(self):
        for target in ("baseline", "candidate", "claim", "external", "additional"):
            data = _fixture()
            claim = _grant(data)
            if target in ("baseline", "candidate"):
                data[target]["rules"]["score"] = {"kind": "unsupported"}
            elif target == "additional":
                data["candidate"]["rules"]["extra"] = {"kind": "unsupported"}
            else:
                record = claim if target == "claim" else data["approvals"][0]
                record["waiver"]["after"] = {"kind": "unsupported"}
            self.failure(data, "policy_kind_unsupported")
        for approved in (False, True):
            data = _fixture()
            if approved:
                _grant(data, after={"kind": "required"})
            else:
                data["candidate"]["rules"]["score"] = {"kind": "required"}
            self.failure(data, "policy_kind_changed")

    def test_e11_all_cross_kind_substitutions_fail(self):
        requirements = ({"kind": "required"},
                        {"kind": "minimum_basis_points", "value": 7500},
                        {"kind": "required_set", "values": ["Alpha"]})
        for before in requirements:
            for after in requirements:
                if before["kind"] == after["kind"]:
                    continue
                for approved in (False, True):
                    with self.subTest(before=before["kind"], after=after["kind"], approved=approved):
                        data = _fixture()
                        data["baseline"]["rules"] = {"score": copy.deepcopy(before)}
                        data["candidate"]["rules"] = {"score": copy.deepcopy(after)}
                        if approved:
                            _grant(data, after=after)
                        self.failure(data, "policy_kind_changed")

    def test_e11_all_objects_are_closed_and_all_fields_required(self):
        paths = (("baseline",), ("baseline", "policy"), ("baseline", "subject"),
                 ("baseline", "rules", "check"), ("baseline", "rules", "score"),
                 ("baseline", "rules", "suite"), ("candidate",), ("observation",),
                 ("candidate", "exceptions", 0), ("candidate", "exceptions", 0, "waiver"),
                 ("candidate", "exceptions", 0, "waiver", "review_event"),
                 ("candidate", "exceptions", 0, "waiver", "alternative_verification"),
                 ("candidate", "exceptions", 0, "waiver", "revocation_events", 0))
        for path in paths:
            seed = _fixture()
            _grant(seed)
            original = seed
            for key in path:
                original = original[key]
            for removed in (None, *original):
                with self.subTest(path=path, removed=removed):
                    data = copy.deepcopy(seed)
                    target = data
                    for key in path:
                        target = target[key]
                    if removed is None:
                        target["unexpected"] = "Synthetic extra"
                    else:
                        target.pop(removed)
                    self.failure(data, fallback=path == ("baseline", "subject")
                                 or (path == ("baseline",) and removed == "subject"))
        data = _fixture()
        claim = _grant(data)
        claim["approved"] = True
        _sync(data)
        self.failure(data)

    def test_e12_native_types_and_minimum_limits(self):
        class NativeIntSubclass(int):
            pass

        class NativeDictSubclass(dict):
            pass

        class NativeListSubclass(list):
            pass

        class NativeStringSubclass(str):
            pass

        for value in (True, False, "7500", 7500.0, float("nan"), float("inf"),
                      -float("inf"), -1, 10001, None, NativeIntSubclass(7500)):
            data = _fixture()
            data["candidate"]["rules"]["score"]["value"] = value
            self.failure(data)
        for field, value in (("baseline", NativeDictSubclass()), ("candidate", ()),
                             ("approvals", NativeListSubclass()), ("observation", object())):
            data = _fixture()
            data[field] = value
            self.failure(data, fallback=field == "baseline")
        data = _fixture()
        data["candidate"]["rules"]["score"]["kind"] = NativeStringSubclass("minimum_basis_points")
        self.failure(data)
        for field, value in (("exceptions", ()), ("rules", []), ("policy", None)):
            data = _fixture()
            data["candidate"][field] = value
            self.failure(data)
        for minimum in (0, 10000):
            data = _fixture()
            data["baseline"]["rules"]["score"]["value"] = minimum
            data["candidate"]["rules"]["score"]["value"] = minimum
            self.success(data)

    def test_e12_identifier_repository_and_sha_grammars(self):
        for value in ("", "0", "01", "+1", " 1", "1 ", "１", "synthetic/repo", 101, "1\n"):
            data = _fixture()
            data["candidate"]["policy"]["repository_id"] = value
            self.failure(data)
        for value in ("0" * 40, "A" * 40, "a" * 39, "a" * 41, "g" * 40,
                      "main", "v1.0", "a" * 40 + ".." + "b" * 40, "a" * 40 + "\n"):
            data = _fixture()
            data["candidate"]["policy"]["revision"] = value
            self.failure(data)
        for value in ("", "1First", "a b", "é", "a" * 129, "a\n"):
            data = _fixture()
            data["candidate"]["rules"][value] = {"kind": "required"}
            self.failure(data)
        for value in ("A", "a" * 128, "a_B.c-1"):
            data = _fixture()
            data["candidate"]["rules"][value] = {"kind": "required"}
            self.success(data)

    def test_e12_text_checks_and_explicit_null_only(self):
        for value in ("", " ", "\u00a0", "\u3000", "a\x00b", "a\x9fb", "\ud800", 1, None):
            data = _fixture()
            claim = _grant(data)
            claim["evidence_ref"] = value
            _sync(data)
            self.failure(data)
        data = _fixture()
        claim = _grant(data)
        claim["evidence_ref"] = "\ufeff"
        claim["waiver"]["reason"] = " 合成的理由 🚀 "
        _sync(data)
        self.success(data, ["ApprovalA"])
        for field in ("before", "alternative_verification", "revocation_events", "reason", "paths"):
            data = _fixture()
            claim = _grant(data)
            claim["waiver"][field] = None
            _sync(data)
            self.failure(data)

    def test_e12_sorted_unique_sets_scopes_and_revocations(self):
        for values in (["Beta", "Alpha"], ["Alpha", "Alpha"], [True], ["invalid member"]):
            data = _fixture()
            data["candidate"]["rules"]["suite"]["values"] = values
            self.failure(data)
        for field, values in (("paths", []), ("paths", ["src/a.py", "src/a.py"]),
                              ("paths", ["z.py", "a.py"]), ("revisions", []),
                              ("revisions", ["b" * 40, "b" * 40]),
                              ("revisions", ["c" * 40, "b" * 40]),
                              ("revocation_events", []),
                              ("revocation_events", [{"event": "Z", "condition": "Z trigger"},
                                                     {"event": "A", "condition": "A trigger"}]),
                              ("revocation_events", [{"event": "A", "condition": "First"},
                                                     {"event": "A", "condition": "Second"}])):
            data = _fixture()
            claim = _grant(data)
            claim["waiver"][field] = values
            _sync(data)
            self.failure(data)
        data = _fixture("café.swift")
        claim = _grant(data)
        claim["waiver"]["paths"] = sorted(["café.swift", "cafe\u0301.swift", "src/%61.py", "src/a.py"])
        claim["waiver"]["revisions"] = ["b" * 40, "c" * 40]
        _sync(data)
        self.success(data, ["ApprovalA"])

    def test_e12_cycles_depth_and_node_limits(self):
        for cyclic in ([], {}):
            if type(cyclic) is list:
                cyclic.append(cyclic)
            else:
                cyclic["cycle"] = cyclic
            data = _fixture()
            data["candidate"]["unexpected"] = cyclic
            finding = self.failure(data)
            self.assertIn("cycle", finding["detail"])
        for leaf_depth in (32, 33):
            data = _fixture()
            nested = "leaf"
            for _ in range(leaf_depth - 2):
                nested = [nested]
            data["candidate"]["unexpected"] = nested
            finding = self.failure(data)
            self.assertEqual("depth" in finding["detail"], leaf_depth == 33)
        data = _fixture()
        initial_nodes = sum(_nodes(value) for value in data.values())
        data["baseline"]["subject"]["red_lines"].extend(["Synthetic"] * (100000 - initial_nodes))
        self.success(data)
        data["baseline"]["subject"]["red_lines"].append("Synthetic")
        finding = self.failure(data)
        self.assertIn("100000-node", finding["detail"])

    def test_e12_shared_subtrees_are_not_cycles_and_count_per_occurrence(self):
        data = _fixture()
        data["candidate"]["policy"] = data["baseline"]["policy"]
        data["candidate"]["rules"] = data["baseline"]["rules"]
        self.success(data)
        data = _fixture()
        repeated = ["Synthetic"] * 1000
        data["candidate"]["unexpected"] = [repeated] * 101
        self.assertIn("100000-node", self.failure(data)["detail"])

    def test_e12_custom_values_and_keys_are_not_invoked(self):
        class Trap:
            def __hash__(self):
                return hash("subject")

            def __eq__(self, other):
                raise AssertionError("Custom equality must not be called")

            def __repr__(self):
                raise AssertionError("Custom repr must not be called")

        data = _fixture()
        data["baseline"] = {Trap(): "Synthetic"}
        self.failure(data, fallback=True)
        data = _fixture()
        data["candidate"]["unexpected"] = Trap()
        self.failure(data)

        class TrapMeta(type):
            def __eq__(cls, other):
                raise AssertionError("Custom metaclass equality must not be called")

        class MetaclassValue(metaclass=TrapMeta):
            pass

        data = _fixture()
        data["candidate"]["unexpected"] = MetaclassValue()
        self.failure(data)

    def test_e13_duplicate_ids_claims_and_unused_exceptions(self):
        for field in ("approvals", "exceptions"):
            data = _fixture()
            claim = _grant(data)
            target = data["approvals"] if field == "approvals" else data["candidate"]["exceptions"]
            target.append(copy.deepcopy(claim))
            self.failure(data)
        data = _fixture()
        claim = _grant(data)
        other = copy.deepcopy(claim)
        other["approval_id"] = "ApprovalB"
        data["candidate"]["exceptions"].append(other)
        _sync(data)
        self.failure(data)
        for after in ({"kind": "minimum_basis_points", "value": 7500},
                      {"kind": "minimum_basis_points", "value": 7600}):
            data = _fixture()
            _grant(data, after=after)
            self.failure(data, "policy_exception_unused")
        data = _fixture()
        claim = _grant(data)
        claim["waiver"]["rule_id"] = "additional"
        _sync(data)
        self.failure(data, "policy_exception_unused")

    def test_e13_unreferenced_external_record_eligibility_is_irrelevant(self):
        source = _fixture("unrelated/path.py")
        record = _grant(source)
        record["waiver"]["expires_at"] = "2000-01-01T00:00:00Z"
        record["waiver"]["policy"]["repository_id"] = "404"
        data = _fixture()
        data["approvals"] = [record]
        data["observation"]["events"] = {}
        self.success(data)
        data["approvals"][0]["evidence_ref"] = ""
        self.failure(data)

    def test_e14_deterministic_sorted_results_no_input_or_output_alias_mutation(self):
        data = _fixture()
        _grant(data, approval_id="Zulu")
        _grant(data, rule="check", approval_id="Alpha", after=None)
        snapshot = copy.deepcopy(data)
        first = self.success(data, ["Alpha", "Zulu"])
        self.assertEqual(first, evaluate_policy(**data))
        self.assertTrue(data == snapshot, "Evaluator must preserve every input")
        data["candidate"]["exceptions"].reverse()
        data["approvals"].reverse()
        self.assertEqual(first, evaluate_policy(**data))
        first["applied_exceptions"].clear()
        self.success(data, ["Alpha", "Zulu"])
        data["observation"]["events"]["Alternative"] = "unknown"
        snapshot = copy.deepcopy(data)
        failure = evaluate_policy(**data)
        self.assertEqual(failure, evaluate_policy(**data))
        self.assertTrue(data == snapshot, "Failure must preserve every input")
        failure["findings"][0]["red_lines"].append("Result-local only")
        self.assertTrue(data == snapshot, "Returned findings must not alias mutable inputs")

    def test_e14_no_partial_applied_results(self):
        data = _fixture()
        _grant(data, approval_id="Alpha")
        other = _grant(data, rule="check", approval_id="Zulu", after=None)
        other["waiver"]["expires_at"] = "2000-01-01T00:00:00Z"
        _sync(data)
        self.failure(data, "policy_exception_expired")

    def test_e14_first_failure_order(self):
        data = _fixture()
        _grant(data)
        data["candidate"]["policy"]["revision"] = "c" * 40
        data["approvals"] = []
        self.failure(data, "policy_pin_mismatch")
        data["observation"]["schema"] = 2
        self.failure(data, "policy_schema_unsupported")
        data = _fixture()
        _grant(data, approval_id="Zulu")
        _grant(data, rule="check", approval_id="Alpha", after=None)
        data["approvals"][1]["evidence_ref"] = "Different record"
        data["observation"]["now"] = "2040-01-01T00:00:00Z"
        self.failure(data, "policy_approval_mismatch")
        data["approvals"] = copy.deepcopy(data["candidate"]["exceptions"])
        self.failure(data, "policy_exception_expired")
        data = _fixture()
        data["candidate"]["rules"]["score"]["value"] = 1
        data["candidate"]["rules"].pop("check")
        self.failure(data, "policy_requirement_missing")
        data["baseline"]["rules"] = dict(reversed(list(data["baseline"]["rules"].items())))
        self.failure(data, "policy_requirement_missing")

    def test_e14_within_claim_scope_content_expiry_review_revocation_alternative_order(self):
        data = _fixture()
        claim = _grant(data)
        waiver = claim["waiver"]
        waiver["paths"] = ["wrong/path.py"]
        waiver["before"]["value"] = 7499
        waiver["expires_at"] = "2000-01-01T00:00:00Z"
        _sync(data)
        data["observation"]["events"] = {"Review": "occurred", "Revocation": "occurred", "Alternative": "not_occurred"}
        self.failure(data, "policy_scope_mismatch")
        waiver["paths"] = ["src/a.py"]
        _sync(data)
        self.failure(data, "policy_approval_mismatch")
        waiver["before"]["value"] = 7500
        _sync(data)
        self.failure(data, "policy_exception_expired")
        waiver["expires_at"] = "2031-01-01T00:00:00Z"
        _sync(data)
        self.failure(data, "policy_review_due")
        data["observation"]["events"]["Review"] = "not_occurred"
        self.failure(data, "policy_exception_revoked")
        data["observation"]["events"]["Revocation"] = "not_occurred"
        self.failure(data, "policy_alternative_unmet")

    def test_e15_safe_attribution_and_no_approval_body_disclosure(self):
        data = _fixture()
        claim = _grant(data)
        sentinel = "SYNTHETIC_PRIVATE_BODY_SENTINEL"
        claim["evidence_ref"] = sentinel
        claim["waiver"]["reason"] = sentinel
        claim["waiver"]["review_event"]["condition"] = sentinel
        finding = self.failure(data, "policy_approval_mismatch")
        self.assertNotIn(sentinel, json.dumps(finding))
        data["baseline"]["subject"]["layer"] = ""
        self.failure(data, fallback=True)
        data["baseline"] = None
        self.failure(data, fallback=True)

    def test_observation_and_rule_shape_edge_cases(self):
        for events in ([], None, {"Event": None}, {"Event": "pending"}, {"Event": True}, {"bad event": "occurred"}):
            data = _fixture()
            data["observation"]["events"] = events
            self.failure(data)
        data = _fixture()
        data["baseline"]["rules"] = {}
        self.failure(data)
        data = _fixture()
        data["candidate"]["rules"] = {}
        self.failure(data, "policy_requirement_missing")
        for rule in (None, [], {}, {"kind": 1}, {"kind": ""},
                     {"kind": "required", "value": 1}, {"kind": "required_set", "values": None}):
            data = _fixture()
            data["candidate"]["rules"]["score"] = rule
            self.failure(data)


class ContractMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.input_schema = json.loads((_ROOT / "schemas/policy-input-v1.schema.json").read_text(encoding="utf-8"))
        cls.exception_schema = json.loads((_ROOT / "schemas/policy-exception-v1.schema.json").read_text(encoding="utf-8"))
        cls.finding_schema = json.loads((_ROOT / "schemas/finding-v1.schema.json").read_text(encoding="utf-8"))

    def test_schema_definitions_are_shared_and_refs_document_local(self):
        for key, value in self.exception_schema["$defs"].items():
            self.assertEqual(value, self.input_schema["$defs"][key])

        def inspect(value, schema):
            if type(value) is dict:
                if "$ref" in value:
                    reference = value["$ref"]
                    self.assertTrue(reference.startswith("#/$defs/"))
                    self.assertIn(reference[8:], schema["$defs"])
                if value.get("type") == "object" and "properties" in value:
                    self.assertIs(value["additionalProperties"], False)
                    self.assertEqual(set(value["required"]), set(value["properties"]))
                for child in value.values():
                    inspect(child, schema)
            elif type(value) is list:
                for child in value:
                    inspect(child, schema)

        for schema in (self.input_schema, self.exception_schema):
            inspect(schema, schema)
        self.assertEqual(set(self.input_schema["properties"]), {"baseline", "candidate", "approvals", "observation"})

    def test_schema_path_and_text_patterns_preserve_literals(self):
        valid = ("SampleWatch Watch App/Sources/SampleWatchApp.swift", "示例模块/消费者 测试.swift",
                 "assets/100% complete.txt", "src/%61.py", "src/%2F", "src/%2e%2e",
                 "café.swift", "cafe\u0301.swift", " ", " a / b ", "src/*", "🚀/🧪")
        invalid = ("", "/a", "a/", "a//b", ".", "..", "./a", "a/../b", "a/./b",
                   "a/..", "a/.", "a\\b", "a\x00b", "a\x1fb", "a\x7fb", "a\x9fb", "a\nb")
        for schema in (self.input_schema, self.exception_schema):
            pattern = schema["$defs"]["path"]["pattern"]
            for path in valid:
                self.assertIsNotNone(re.search(pattern, path))
            for path in invalid:
                self.assertIsNone(re.search(pattern, path))
            text_pattern = schema["$defs"]["text"]["pattern"]
            for value in ("text", " 合成 🚀 ", "\ufeff"):
                self.assertIsNotNone(re.search(text_pattern, value))
            for value in ("", " ", "\u00a0", "\u3000", "a\x00b", "a\x9fb"):
                self.assertIsNone(re.search(text_pattern, value))

    def test_existing_finding_shape_and_public_interface(self):
        self.assertEqual(set(self.finding_schema["properties"]), {"layer", "path", "kind", "detail", "red_lines"})
        tree = ast.parse(_SOURCE)
        public = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                  and not node.name.startswith("_")]
        self.assertEqual([node.name for node in public], ["evaluate_policy"])
        self.assertEqual([arg.arg for arg in public[0].args.kwonlyargs], ["baseline", "candidate", "approvals", "observation"])
        self.assertEqual(public[0].args.args, [])
        imports = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertEqual(imports, ["datetime", "re"])
        self.assertFalse(any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
