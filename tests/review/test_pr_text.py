"""PR title/body ingestion through the isolated CLI and an offline gh stub."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts/review/pr_text.py"


class PRTextCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        gh = self.root / "gh"
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLED"\n'
                      '[ "$GH_TOKEN" = "offline-token" ] || exit 1\n'
                      '[ -n "$STUB_PR_FAIL" ] && exit 1\nprintf "%s" "$STUB_PR"\n')
        gh.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root), CALLED=str(self.root / "called"),
                        GH_TOKEN="offline-token", BASE_REPO="o/r", PR_NUMBER="7",
                        STUB_PR=json.dumps({"title": "Review context", "body": "Requested by the Owner."}),
                        STUB_PR_FAIL="")

    def run_cli(self, **overrides):
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                              env=dict(self.env, **overrides), capture_output=True, timeout=10)

    def test_fetches_title_and_body_with_workflow_token(self):
        result = self.run_cli()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(b"Title: Review context\n\nRequested by the Owner.", result.stdout)
        self.assertEqual(["api", "repos/o/r/pulls/7"],
                         (self.root / "called").read_text().splitlines())

    def test_empty_or_null_body_has_explicit_placeholder(self):
        for body in ("", None):
            with self.subTest(body=body):
                result = self.run_cli(STUB_PR=json.dumps({"title": "Review context", "body": body}))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(b"Title: Review context\n\n(empty)", result.stdout)

    def test_body_truncates_at_utf8_boundary_only_above_8000_bytes(self):
        for body, expected in (
                ("a" * 7997 + "界", "a" * 7997 + "界"),
                ("a" * 7997 + "界x", "a" * 7997 + "界\n\n(PR body truncated to 8000 UTF-8 bytes.)"),
                ("界" * 2667, "界" * 2666 + "\n\n(PR body truncated to 8000 UTF-8 bytes.)"),
                ("x" * 8001, "x" * 8000 + "\n\n(PR body truncated to 8000 UTF-8 bytes.)")):
            with self.subTest(bytes=len(body.encode("utf-8"))):
                result = self.run_cli(STUB_PR=json.dumps({"title": "Review context", "body": body}))
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("Title: Review context\n\n" + expected, result.stdout.decode("utf-8"))

    def test_api_or_parse_failure_emits_no_review_data(self):
        invalid = ["", "{bad json", "[]", "null", "{}",
                   json.dumps({"title": "Review context"}),
                   json.dumps({"title": 7, "body": "text"}),
                   json.dumps({"title": "Review context", "body": []}),
                   json.dumps({"title": "Review context", "body": "\ud800"}),
                   json.dumps({"title": "\ud800", "body": "text"})]
        for overrides in [{"STUB_PR_FAIL": "1"}] + [{"STUB_PR": raw} for raw in invalid]:
            with self.subTest(overrides=overrides):
                result = self.run_cli(**overrides)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertEqual(b"", result.stdout)
                self.assertIn(b"pr-text:", result.stderr)
                self.assertNotIn(b"offline-token", result.stderr)

    def test_invalid_target_is_rejected_before_api(self):
        for field, values in (("PR_NUMBER", ["", "0", "7;echo", "7\n"]),
                              ("BASE_REPO", ["", "o", "o/r/x", "o/r?x"])):
            for value in values:
                with self.subTest(field=field, value=value):
                    result = self.run_cli(**{field: value})
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertEqual(b"", result.stdout)
                    self.assertIn(field.encode(), result.stderr)
                    self.assertFalse((self.root / "called").exists())


if __name__ == "__main__":
    unittest.main()
