"""Owner comment admission through pure functions and the isolated CLI."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "review" / "owner_decisions.py"
spec = importlib.util.spec_from_file_location("owner_decisions", SCRIPT)
owner_decisions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner_decisions)
HEAD = "a" * 40
CREATED = "2026-09-28T10:00:00Z"


def record(**overrides):
    return dict(dict(id=7, user_id=1001, user_type="User", created_at=CREATED, updated_at=CREATED,
                     body=f"For {HEAD}: accept the scoped policy exception."), **overrides)


class OwnerDecisionTests(unittest.TestCase):
    def test_only_unedited_owner_comments_naming_full_current_head_are_admitted(self):
        valid = record()
        ignored = [record(user_id=2002), record(body="b" * 40), record(body=HEAD[:7]),
                   record(updated_at="2026-09-28T10:01:00Z"), record(body="f" + HEAD),
                   record(body=HEAD + "F"), record(body=HEAD.upper())]
        records = owner_decisions.parse_records("\n".join(json.dumps(r) for r in ignored + [valid]))
        self.assertEqual([valid], owner_decisions.admit(records, 1001, HEAD))

    def test_non_human_author_with_matching_id_is_ignored(self):
        for user_type in ("Bot", "Organization", "user", ""):
            with self.subTest(user_type=user_type):
                self.assertEqual([], owner_decisions.admit([record(user_type=user_type)], 1001, HEAD))

    def test_invalid_json_or_record_types_fail_closed(self):
        for raw in ("not json", "\n", "[]", "null", "true", "{}",
                    json.dumps(record()) + "\n{broken"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                owner_decisions.parse_records(raw)
        for field, values in (("id", [True, "7", None]), ("user_id", [True, "1001", 1001.0]),
                              ("user_type", [None, 1]), ("created_at", [None, 1]), ("updated_at", [[], False]),
                              ("body", [None, {}, 1])):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    owner_decisions.parse_records(json.dumps(record(**{field: value})))
        self.assertEqual([], owner_decisions.parse_records(""))

    def test_count_bound_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "5 comments"):
            owner_decisions.admit([record(id=i) for i in range(6)], 1001, HEAD)
        self.assertEqual(5, len(owner_decisions.admit([record(id=i) for i in range(5)], 1001, HEAD)))

    def test_per_comment_bound_counts_utf8_bytes(self):
        exact = record(body=HEAD + " " + "é" * 1979 + "x")
        self.assertEqual([exact], owner_decisions.admit([exact], 1001, HEAD))
        with self.assertRaisesRegex(ValueError, "4000 UTF-8 bytes"):
            owner_decisions.admit([record(body=exact["body"] + "x")], 1001, HEAD)

    def test_total_bound_fails_closed(self):
        records = [record(id=i, body=HEAD + " " + "x" * 3959) for i in range(3)]
        self.assertEqual(records, owner_decisions.admit(records, 1001, HEAD))
        with self.assertRaisesRegex(ValueError, "12000 UTF-8 bytes"):
            owner_decisions.admit(records + [record(id=4)], 1001, HEAD)

    def test_admitted_controls_and_non_utf8_text_fail_closed(self):
        for control in ("\x00", "\x08", "\x0b", "\x0c", "\x1f", "\x7f", "\x80", "\x85", "\x9f", "\ud800"):
            with self.subTest(control=repr(control)), self.assertRaises(ValueError):
                owner_decisions.admit([record(body=HEAD + " " + control)], 1001, HEAD)
        valid = record(body=HEAD + "\t\r\ntext")
        self.assertEqual([valid], owner_decisions.admit([valid], 1001, HEAD))

    def test_bounds_and_control_checks_apply_only_to_admitted_comments(self):
        ignored = record(user_id=2002, body=HEAD + " " + "\x00" * 13000)
        self.assertEqual([], owner_decisions.admit([ignored] * 6, 1001, HEAD))
        self.assertEqual([], owner_decisions.admit([record(user_id=True)], 1, HEAD))

    def test_render_quotes_every_line_and_neutralises_template_and_delimiters(self):
        decisions = [record(id=9, body="last"), record(id=3, body="first\r\n\n{{DIFF}}\n========\n====\rnext\n")]
        rendered = owner_decisions.render(decisions)
        self.assertEqual(
            "### Owner decision comment 3 (created 2026-09-28T10:00:00Z)\n"
            "> first\n> \n> { {DIFF}}\n> = = = = = = = =\n> = = = =\n> next\n> \n"
            "### Owner decision comment 9 (created 2026-09-28T10:00:00Z)\n> last\n", rendered)
        self.assertEqual(rendered, owner_decisions.render(list(reversed(decisions))))

    def test_render_no_matching_decisions(self):
        self.assertEqual("(No Owner decision names the current head SHA.)\n", owner_decisions.render([]))

    def test_render_neutralises_overlapping_placeholder_openers(self):
        rendered = owner_decisions.render([record(body="{{{DIFF}}\n{{{{DIFF}}")])
        self.assertNotIn("{{", rendered)
        self.assertIn("> { { {DIFF}}\n> { { { {DIFF}}\n", rendered)


class OwnerDecisionCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        gh = self.root / "gh"
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLED"\n'
                      '[ -n "$STUB_COMMENTS_FAIL" ] && exit 1\nprintf "%s" "$STUB_COMMENTS"\n')
        gh.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root), CALLED=str(self.root / "called"),
                        OWNER_DECISION_USER_ID="1001", HEAD_SHA=HEAD, BASE_REPO="o/r", PR_NUMBER="7",
                        STUB_COMMENTS=json.dumps(record()), STUB_COMMENTS_FAIL="")

    def run_cli(self, **overrides):
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                              env=dict(self.env, **overrides), capture_output=True, text=True, timeout=10)

    def test_feature_off_never_calls_gh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            gh = root / "gh"
            gh.write_text('#!/bin/sh\nprintf called > "$CALLED"\nexit 1\n')
            gh.chmod(0o755)
            env = dict(os.environ, PATH=str(root), CALLED=str(root / "called"))
            env.pop("OWNER_DECISION_USER_ID", None)
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("(Owner decision input is not configured for this repository.)\n",
                             result.stdout)
            self.assertFalse((root / "called").exists())

    def test_cli_fetches_paginated_json_lines_and_renders_decisions(self):
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("### Owner decision comment 7", result.stdout)
        self.assertIn("> For " + HEAD, result.stdout)
        self.assertEqual(["api", "--paginate", "repos/o/r/issues/7/comments?per_page=100", "--jq",
                          ".[] | {id: .id, user_id: .user.id, user_type: .user.type, created_at: .created_at, updated_at: .updated_at, body: .body}"],
                         (self.root / "called").read_text().splitlines())

    def test_empty_configuration_skips_validation_and_api(self):
        result = self.run_cli(OWNER_DECISION_USER_ID="", HEAD_SHA="invalid", STUB_COMMENTS_FAIL="1")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.root / "called").exists())

    def test_invalid_environment_fails_before_api(self):
        for field, values in (("OWNER_DECISION_USER_ID", ["0", "01", "-1", " 1001", "1001\n", "9" * 21, "1;echo"]),
                              ("HEAD_SHA", ["", HEAD[:7], "b" * 41, "g" * 40, HEAD.upper()]),
                              ("PR_NUMBER", ["", "0", "-7", "1.5", "7;echo"]),
                              ("BASE_REPO", ["", "o", "o/r/x", "o/r?x", "o/ r"])):
            for value in values:
                with self.subTest(field=field, value=value):
                    result = self.run_cli(**{field: value})
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertIn(field, result.stderr)
                    self.assertEqual("", result.stdout)
                    self.assertFalse((self.root / "called").exists())

    def test_api_nonzero_and_malformed_json_fail_closed(self):
        for overrides in ({"STUB_COMMENTS_FAIL": "1"}, {"STUB_COMMENTS": "{bad json"},
                          {"STUB_COMMENTS": json.dumps(record(body=None))}):
            with self.subTest(overrides=overrides):
                result = self.run_cli(**overrides)
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr)

    def test_api_timeout_and_oserror_fail_closed(self):
        for error in (subprocess.TimeoutExpired("gh", 60), OSError("not executable")):
            with self.subTest(error=error), mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(subprocess, "run", side_effect=error) as run, \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(1, owner_decisions.main())
                self.assertTrue(stderr.getvalue())
                self.assertEqual(60, run.call_args.kwargs["timeout"])

    def test_cli_bound_failure_emits_no_partial_decisions(self):
        result = self.run_cli(STUB_COMMENTS="\n".join(json.dumps(record(id=i)) for i in range(6)))
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("5 comments", result.stderr)


if __name__ == "__main__":
    unittest.main()
