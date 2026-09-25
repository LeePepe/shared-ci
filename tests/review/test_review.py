"""Review scripts: verdict validation, prompt rendering, architecture facts, and
end-to-end codex/kimi scripts with stub CLIs (no network, no real models)."""
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
REVIEW = REPO / "scripts" / "review"
sys.path.insert(0, str(REPO / "tests" / "repo"))
from fixture import ContractRepo, environment  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location("review_" + name, REVIEW / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verdict = load("verdict")
render_prompt = load("render_prompt")
PASS = {"verdict": "pass", "summary": "ok", "blockers": [], "notes": [{"file": "a.py", "line": 1, "note": "nit"}]}
CHANGES = {"verdict": "changes", "summary": "bad", "notes": [],
           "blockers": [{"file": "a.py", "line": 3, "severity": "high", "why": "@owner <b>leak</b> `x`"}]}


class VerdictTests(unittest.TestCase):
    def run_verdict(self, raw, mode="gate"):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write(raw)
        self.addCleanup(os.unlink, handle.name)
        return subprocess.run([sys.executable, "-I", "-B", str(REVIEW / "verdict.py"), "--tool", "codex",
                               "--mode", mode, "--marker", "<!-- m -->", "--head", "h" * 40, handle.name],
                              capture_output=True, text=True, timeout=20)

    def test_pass_exits_zero(self):
        result = self.run_verdict(json.dumps(PASS))
        self.assertEqual(0, result.returncode)
        self.assertIn("codex review: pass", result.stdout)
        self.assertIn("Reviewed head: `" + "h" * 40, result.stdout)

    def test_changes_exit_one_and_neutralised(self):
        result = self.run_verdict(json.dumps(CHANGES))
        self.assertEqual(1, result.returncode)
        self.assertIn("changes requested (1 blocking)", result.stdout)
        self.assertNotIn("@owner", result.stdout)
        self.assertNotIn("<b>", result.stdout)

    def test_invalid_verdict_fails_closed(self):
        for raw in ("", "not json", json.dumps({"verdict": "maybe"}),
                    json.dumps({**CHANGES, "blockers": []}), json.dumps({**PASS, "blockers": CHANGES["blockers"]})):
            result = self.run_verdict(raw)
            self.assertEqual(3, result.returncode, raw)
            self.assertIn("unavailable", result.stdout)

    def test_advisory_never_fails(self):
        self.assertEqual(0, self.run_verdict(json.dumps(CHANGES), mode="advisory").returncode)
        self.assertEqual(0, self.run_verdict("garbage", mode="advisory").returncode)

    def test_stream_json_extraction(self):
        stream = "\n".join([json.dumps({"role": "user", "content": "x"}),
                            json.dumps({"role": "assistant", "content": json.dumps(PASS)})])
        self.assertEqual("pass", verdict.validate(verdict._extract(stream))["verdict"])


class RenderPromptTests(unittest.TestCase):
    TEMPLATE = (REVIEW / "review-prompt.md").read_text()

    def test_single_pass_substitution(self):
        out = render_prompt.render(self.TEMPLATE, {"ARCHITECTURE": "arch", "CHANGED": "{{DIFF}}", "DIFF": "d $(x) `y`"})
        self.assertIn("{{DIFF}}", out)          # injected placeholder not re-expanded
        self.assertIn("d $(x) `y`", out)        # never shell-evaluated

    def test_missing_placeholder_errors(self):
        with self.assertRaises(ValueError):
            render_prompt.render("no placeholders", {})

    def test_prompt_contains_architecture_dimension(self):
        self.assertIn("Architecture conformance", self.TEMPLATE)
        self.assertIn("allowed direction", self.TEMPLATE)


class ArchContextTests(unittest.TestCase):
    def test_reports_layers_direction_and_unmapped(self):
        repo = ContractRepo()
        self.addCleanup(repo.close)
        result = subprocess.run([sys.executable, "-I", "-B", str(REVIEW / "arch_context.py")],
                                input="src/app/main.py\nsrc/core/model.py\nlib/new.py\nREADME.md\n",
                                cwd=repo.root, env=repo.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        out = result.stdout
        self.assertIn("- src/app/main.py -> App", out)
        self.assertIn("- lib/new.py -> UNMAPPED", out)
        self.assertIn("- README.md -> excluded", out)
        self.assertIn("- App -> Core", out)
        self.assertIn("- Core -> (nothing)", out)
        self.assertIn("App: wiring only", out)
        self.assertIn("touches 2 layers", out)

    def test_missing_layer_map_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q"], cwd=temp, env=environment(), check=True)
            result = subprocess.run([sys.executable, "-I", "-B", str(REVIEW / "arch_context.py")], input="a\n",
                                    cwd=temp, env=environment(), capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode)
        self.assertIn("unavailable", result.stdout)


STUB_GH = """#!/bin/sh
# Records publication attempts; faults are entirely offline.
case "$*" in
  *"--paginate"*) echo "${STUB_COMMENT_ID:-}" ;;
  *)
    method=""; prev=""
    for a in "$@"; do
      [ "$prev" = "-X" ] && method="$a"
      case "$a" in body=*) body="${a#body=}";; esac
      prev="$a"
    done
    printf '%s\\n' "$method" >> "$STUB_OUT/publish-attempts"
    printf '%s' "$body" > "$STUB_OUT/attempted-comment"
    [ "${STUB_PUBLISH_FAIL:-}" = "all" ] && exit 1
    [ "${STUB_PUBLISH_FAIL:-}" = "$method" ] && exit 1
    printf '%s' "$body" > "$STUB_OUT/comment"
    ;;
esac
exit 0
"""
STUB_CODEX = """#!/bin/sh
# Writes $STUB_VERDICT to the -o file; records the prompt (last argument).
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; last="$a"; done
printf '%s' "$last" > "$STUB_OUT/prompt"
[ -n "$STUB_FAIL" ] && exit 7
printf '%s' "$STUB_VERDICT" > "$out"
"""
STUB_KIMI = """#!/bin/sh
[ -n "$STUB_FAIL" ] && exit 5
printf '%s\\n' "{\\"role\\":\\"assistant\\",\\"content\\":$(printf '%s' "$STUB_VERDICT" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}"
"""


class ReviewScriptEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base")
        self.base = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.write("src/app/main.py", "Y = 3\n")
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "head")
        self.head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.git("checkout", "-q", "--detach", self.base)  # trusted base workspace
        self.repo.git("remote", "add", "origin", str(self.repo.root))
        self.tools = pathlib.Path(tempfile.mkdtemp(prefix="review-stubs-"))
        self.out = pathlib.Path(tempfile.mkdtemp(prefix="review-out-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tools), str(self.out)]))
        for name, body in (("gh", STUB_GH), ("codex", STUB_CODEX), ("kimi", STUB_KIMI)):
            path = self.tools / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def run_script(self, script, verdict_json, fail="", **overrides):
        for name in ("comment", "attempted-comment", "publish-attempts", "prompt"):
            (self.out / name).unlink(missing_ok=True)
        env = dict(self.repo.env, PATH=f"{self.tools}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                   PR_NUMBER="7", BASE_SHA=self.base, HEAD_SHA=self.head, BASE_REPO="o/r",
                   SHARED_CI_DIR=str(REPO), STUB_OUT=str(self.out), STUB_VERDICT=verdict_json,
                   STUB_FAIL=fail, CODEX_REVIEW_HOME=str(self.out / "home"))
        env.update(overrides)
        result = subprocess.run(["bash", str(REVIEW / script)], cwd=self.repo.root, env=env,
                                capture_output=True, text=True, timeout=60)
        comment = (self.out / "comment").read_text() if (self.out / "comment").exists() else ""
        return result, comment

    def test_codex_pass(self):
        result, comment = self.run_script("codex-review.sh", json.dumps(PASS))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("codex review: pass", comment)
        prompt = (self.out / "prompt").read_text()
        self.assertIn("src/app/main.py -> App", prompt)
        self.assertIn("Y = 3", prompt)

    def test_codex_blockers_fail_with_comment(self):
        result, comment = self.run_script("codex-review.sh", json.dumps(CHANGES))
        self.assertEqual(1, result.returncode)
        self.assertIn("changes requested", comment)

    def test_codex_cli_failure_fails_closed(self):
        result, comment = self.run_script("codex-review.sh", json.dumps(PASS), fail="1")
        self.assertEqual(1, result.returncode)
        self.assertIn("unavailable", comment)

    def test_codex_garbage_fails_closed(self):
        result, comment = self.run_script("codex-review.sh", "not json")
        self.assertEqual(1, result.returncode)
        self.assertIn("unavailable", comment)

    def test_codex_workspace_stays_on_base(self):
        self.run_script("codex-review.sh", json.dumps(PASS))
        self.assertEqual(self.base, self.repo.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual("Y = 2\n", (self.repo.root / "src/app/main.py").read_text())

    def test_codex_pass_requires_published_record(self):
        for existing in ("", "42"):
            with self.subTest(existing=existing):
                result, comment = self.run_script(
                    "codex-review.sh", json.dumps(PASS),
                    STUB_COMMENT_ID=existing, STUB_PUBLISH_FAIL="all")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual("", comment)
                self.assertNotIn("[codex-review] pass", result.stdout)
                self.assertIn("could not post", result.stderr)

    def test_codex_empty_diff_requires_published_record(self):
        for failure in ("", "all"):
            with self.subTest(failure=failure):
                result, comment = self.run_script(
                    "codex-review.sh", json.dumps(PASS), HEAD_SHA=self.base,
                    STUB_PUBLISH_FAIL=failure)
                self.assertEqual(1 if failure else 0, result.returncode)
                self.assertFalse((self.out / "prompt").exists())
                if failure:
                    self.assertEqual("", comment)
                    self.assertIn("could not post", result.stderr)
                else:
                    self.assertIn("No committed diff", comment)

    def test_codex_failures_stay_failed_when_publication_fails(self):
        for raw, fail in ((json.dumps(CHANGES), ""), (json.dumps(PASS), "1"), ("junk", "")):
            with self.subTest(raw=raw, fail=fail):
                result, comment = self.run_script(
                    "codex-review.sh", raw, fail, STUB_PUBLISH_FAIL="all")
                self.assertEqual(1, result.returncode)
                self.assertEqual("", comment)
                self.assertNotIn("[codex-review] pass", result.stdout)
                self.assertIn("could not post", result.stderr)

    def test_codex_existing_patch_and_post_fallback(self):
        for failure, attempts in (("", "PATCH\n"), ("PATCH", "PATCH\nPOST\n")):
            with self.subTest(failure=failure):
                result, comment = self.run_script(
                    "codex-review.sh", json.dumps(PASS),
                    STUB_COMMENT_ID="42", STUB_PUBLISH_FAIL=failure)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("codex review: pass", comment)
                self.assertEqual(attempts, (self.out / "publish-attempts").read_text())

    def test_codex_oversize_diff_unavailable_before_model(self):
        diff = self.repo.git("diff", "--no-ext-diff", f"{self.base}...{self.head}").stdout
        result, comment = self.run_script(
            "codex-review.sh", json.dumps(PASS), REVIEW_MAX_BYTES=str(len(diff.encode()) - 1))
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse((self.out / "prompt").exists())
        self.assertIn("unavailable", comment)
        self.assertIn("exceeds", result.stderr)
        self.assertIn("REVIEW_MAX_BYTES", result.stderr)

    def test_codex_admitted_diff_is_complete_at_and_below_limit(self):
        diff = self.repo.git("diff", "--no-ext-diff", f"{self.base}...{self.head}").stdout
        for budget in (str(len(diff.encode())), str(len(diff.encode()) + 1), "000" + str(len(diff.encode())), "9" * 100):
            with self.subTest(budget=budget):
                result, _ = self.run_script("codex-review.sh", json.dumps(PASS), REVIEW_MAX_BYTES=budget)
                self.assertEqual(0, result.returncode, result.stderr)
                prompt = (self.out / "prompt").read_text()
                self.assertIn(diff, prompt)
                self.assertNotIn("diff truncated", prompt)

    def test_codex_invalid_budgets_fail_before_model(self):
        for budget in ("", "0", "000", "-1", "1.5", "abc", " 200000", "+200000", "1e6",
                       "1;touch budget-executed", "$(touch budget-executed)"):
            with self.subTest(budget=budget):
                result, comment = self.run_script(
                    "codex-review.sh", json.dumps(PASS), REVIEW_MAX_BYTES=budget)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertFalse((self.out / "prompt").exists())
                self.assertIn("unavailable", comment)
                self.assertIn("positive integer", result.stderr)
                self.assertIn("REVIEW_MAX_BYTES", result.stderr)
                self.assertFalse((self.repo.root / "budget-executed").exists())

    def test_codex_invalid_budget_cannot_pass_on_empty_diff(self):
        result, comment = self.run_script(
            "codex-review.sh", json.dumps(PASS), HEAD_SHA=self.base, REVIEW_MAX_BYTES="0")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse((self.out / "prompt").exists())
        self.assertIn("unavailable", comment)
        self.assertIn("positive integer", result.stderr)

    def test_codex_budget_failure_stays_failed_when_publication_fails(self):
        result, comment = self.run_script(
            "codex-review.sh", json.dumps(PASS), REVIEW_MAX_BYTES="1", STUB_PUBLISH_FAIL="all")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertEqual("", comment)
        self.assertFalse((self.out / "prompt").exists())
        self.assertIn("exceeds", result.stderr)
        self.assertIn("could not post", result.stderr)

    def test_codex_utf8_budget_counts_bytes(self):
        self.repo.write("src/app/main.py", 'Y = "完整 diff"\n')
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "utf8")
        self.head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.repo.git("checkout", "-q", "--detach", self.base)
        diff = self.repo.git("diff", "--no-ext-diff", f"{self.base}...{self.head}").stdout
        self.assertGreater(len(diff.encode()), len(diff))
        for budget, expected in ((len(diff), 1), (len(diff.encode()), 0)):
            with self.subTest(budget=budget):
                result, comment = self.run_script(
                    "codex-review.sh", json.dumps(PASS), REVIEW_MAX_BYTES=str(budget))
                self.assertEqual(expected, result.returncode, result.stderr)
                if expected:
                    self.assertFalse((self.out / "prompt").exists())
                    self.assertIn("unavailable", comment)
                else:
                    self.assertIn(diff, (self.out / "prompt").read_text())

    def test_kimi_publication_and_model_failures_remain_advisory(self):
        for raw, fail in ((json.dumps(PASS), ""), (json.dumps(CHANGES), ""),
                          ("junk", ""), (json.dumps(PASS), "1")):
            with self.subTest(raw=raw, fail=fail):
                result, comment = self.run_script("kimi-review.sh", raw, fail, STUB_PUBLISH_FAIL="all")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("", comment)
                self.assertIn("could not post", result.stderr)

    def test_kimi_is_advisory(self):
        for verdict_json, fail in ((json.dumps(CHANGES), ""), (json.dumps(PASS), "1"), ("junk", "")):
            result, comment = self.run_script("kimi-review.sh", verdict_json, fail)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("kimi", comment)


if __name__ == "__main__":
    unittest.main()
