"""Unit tests for Kimi once-per-PR quota guard, docs-only skip, slim diff context,
and best-effort owner/target-scope wiring in scripts/review/kimi-review.sh."""
from __future__ import annotations

import json
import pathlib
import unittest

import test_review
from test_review import PASS, REVIEW


class KimiReviewQuotaAndSlimTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_review.ReviewScriptEndToEndTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.repo = self.fixture.repo
        self.base = self.fixture.base
        self.head = self.fixture.head
        self.tools = self.fixture.tools
        self.out = self.fixture.out
        self.run_script = self.fixture.run_script
        self.owner_comment = self.fixture.owner_comment
        # Extend gh stub so `--paginate` body queries return STUB_EXISTING_STICKY when set,
        # while id queries (`| .id`) continue returning STUB_COMMENT_ID.
        gh_path = self.tools / "gh"
        gh_text = gh_path.read_text(encoding="utf-8")
        gh_text = gh_text.replace(
            '  *"--paginate"*) echo "${STUB_COMMENT_ID:-}" ;;',
            '  *"--paginate"*".body // empty"*)\n'
            '    printf "%s" "${STUB_EXISTING_STICKY:-}"\n'
            '    ;;\n'
            '  *"--paginate"*) echo "${STUB_COMMENT_ID:-}" ;;',
        )
        gh_path.write_text(gh_text, encoding="utf-8")

    def test_once_per_pr_skips_when_completed_sticky_exists(self):
        for body in (
            "<!-- shared-ci-kimi-review -->\n## kimi advisory review: pass\n\nReviewed head: `abc`\n",
            "<!-- shared-ci-kimi-review -->\n## kimi advisory review: findings\n\nReviewed head: `abc`\n",
            "<!-- kimi-advisory-review -->\n## ✅ Kimi advisory review: pass\n",
            "<!-- kimi-advisory-review -->\n## ⚠️ Kimi advisory review\n",
        ):
            with self.subTest(body=body.splitlines()[1]):
                output_file = self.out / "gh-output"
                output_file.unlink(missing_ok=True)
                result, comment = self.run_script(
                    "kimi-review.sh",
                    json.dumps(PASS),
                    STUB_EXISTING_STICKY=body,
                    GITHUB_OUTPUT=str(output_file),
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(
                    "[kimi-review] PR #7 already has a completed Kimi review; skipping per once-per-PR quota policy.",
                    result.stdout,
                )
                self.assertFalse((self.out / "prompt").exists(), "kimi binary must not be invoked")
                self.assertEqual("", comment, "existing sticky comment must not be overwritten")
                self.assertIn("completed=true", output_file.read_text(encoding="utf-8").splitlines())

    def test_once_per_pr_reruns_when_previous_sticky_was_unavailable_or_forced(self):
        unavailable_body = (
            "<!-- shared-ci-kimi-review -->\n## kimi review unavailable\n\nReviewed head: `abc`\n"
        )
        result, comment = self.run_script(
            "kimi-review.sh",
            json.dumps(PASS),
            STUB_EXISTING_STICKY=unavailable_body,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.out / "prompt").exists())
        self.assertIn("kimi advisory review: pass", comment)

        # Force rerun overrides completed sticky guard
        completed_body = (
            "<!-- shared-ci-kimi-review -->\n## kimi advisory review: pass\n\nReviewed head: `abc`\n"
        )
        result, comment = self.run_script(
            "kimi-review.sh",
            json.dumps(PASS),
            STUB_EXISTING_STICKY=completed_body,
            KIMI_FORCE_RERUN="1",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.out / "prompt").exists())
        self.assertIn("kimi advisory review: pass", comment)

    def test_docs_only_diff_skips_kimi_invocation_and_marks_completed(self):
        self.repo.git("checkout", "-q", self.base)
        self.repo.write("docs/notes.md", "# Updated documentation\n")
        self.repo.git("add", "docs/notes.md")
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "docs only")
        docs_head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.git("checkout", "-q", "--detach", self.base)

        output_file = self.out / "gh-output-docs"
        result, comment = self.run_script(
            "kimi-review.sh",
            json.dumps(PASS),
            HEAD_SHA=docs_head,
            GITHUB_OUTPUT=str(output_file),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.out / "prompt").exists(), "kimi binary must not be invoked on docs-only diff")
        self.assertIn("No non-documentation code changes; skipped Kimi LLM invocation to conserve quota.", comment)
        self.assertIn("completed=true", output_file.read_text(encoding="utf-8").splitlines())

    def test_slim_diff_defaults_and_single_attempt(self):
        source = (REVIEW / "kimi-review.sh").read_text(encoding="utf-8")
        self.assertIn('MAX_BYTES="${REVIEW_MAX_BYTES:-40000}"', source)
        self.assertIn('KIMI_MAX_ATTEMPTS="${KIMI_MAX_ATTEMPTS:-1}"', source)
        self.assertIn("--unified=15", source)

    def test_owner_decisions_and_target_scope_wired_into_prompt_best_effort(self):
        pr_body = (
            "## Target scope\n\n"
            "### Paths\n"
            "- `src/app/**`\n\n"
            "### Acceptance\n"
            "- Keep app entry working.\n"
        )
        result, comment = self.run_script(
            "kimi-review.sh",
            json.dumps(PASS),
            OWNER_DECISION_USER_ID="1001",
            STUB_COMMENTS=self.owner_comment(),
            STUB_PR=json.dumps({"title": "Scoped PR", "body": pr_body}),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("kimi advisory review: pass", comment)
        prompt = (self.out / "prompt").read_text(encoding="utf-8")
        self.assertIn("### Owner decision comment 17", prompt)
        self.assertIn("> Owner decision: accept this scoped test policy exception.", prompt)
        self.assertIn('"paths": ["src/app/**"]', prompt)
        self.assertIn('"acceptance": ["Keep app entry working."]', prompt)


if __name__ == "__main__":
    unittest.main()
