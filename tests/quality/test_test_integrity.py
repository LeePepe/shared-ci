"""Test-integrity (G5/G6): per-assertion/per-test losses, Owner-gated ledger, PR-body cross-check."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "quality" / "test_integrity.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_test_integrity", SCRIPT)
ti = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ti)

SWIFT = """import XCTest

final class ParserTests: XCTestCase {
    func testRejectsTraversal() {
        XCTAssertThrowsError(try parse("../etc"))
        XCTAssertEqual(parse("a"), "a")
    }

    func testLength() {
        XCTAssertLessThan(limit, 100)
    }
}
"""
PY = """import unittest


class T(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1, 1)
"""
LEDGER = "# Declared test weakening\\n\\n"
BODY = """## Existing behaviour
x

## Removed or weakened tests or policy
{section}

## Test evidence
y
"""


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid", "LC_ALL": "C.UTF-8"})
    return env


class Repo:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-ti-")
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = environment()
        self.git("init", "-q", "-b", "main")
        self.write("Tests/ParserTests.swift", SWIFT)
        self.write("pytests/test_t.py", PY)
        self.write("src/parser.swift", "let x = 1\n")
        self.write(".github/test-weakening.md", LEDGER.replace("\\n", "\n"))
        self.write(".github/CODEOWNERS", "/.github/ @owner\n")
        self.base = self.commit()

    def close(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True, timeout=20).stdout

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def edit(self, path: str, old: str, new: str) -> None:
        text = (self.root / path).read_text(encoding="utf-8")
        assert old in text, old
        self.write(path, text.replace(old, new))

    def commit(self) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "c")
        return self.git("rev-parse", "HEAD").strip()

    def declare(self, path: str, approver: str = "@owner") -> None:
        text = (self.root / ".github/test-weakening.md").read_text()
        self.write(".github/test-weakening.md", text + f"- {path}: flaky upstream API, tracked in #9 (approved: {approver})\n")

    def check(self, body: str | None = None) -> dict:
        head = self.commit()
        return ti.evaluate(str(self.root), base=self.base, head=head, body=body)


class TestIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def kinds(self, result: dict) -> set[str]:
        return {loss["kind"] for loss in result["losses"]}

    def test_no_test_change_passes(self):
        self.repo.write("src/parser.swift", "let x = 2\n")
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual(("pass", []), (result["verdict"], result["losses"]))

    def test_added_tests_pass(self):
        self.repo.edit("pytests/test_t.py", "        self.assertEqual(1, 1)\n",
                       "        self.assertEqual(1, 1)\n\n    def test_two(self):\n        self.assertTrue(True)\n")
        self.assertEqual("pass", self.repo.check(BODY.format(section="none"))["verdict"])

    def test_removed_assertion_fails(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        result = self.repo.check()
        self.assertEqual("fail", result["verdict"])
        self.assertEqual({"assertion_removed"}, self.kinds(result))
        self.assertEqual(["Tests/ParserTests.swift"], result["undeclared"])

    def test_unrelated_added_tests_do_not_net_out_a_deletion(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.edit("pytests/test_t.py", "        self.assertEqual(1, 1)\n",
                       "        self.assertEqual(1, 1)\n        self.assertTrue(1)\n        self.assertTrue(2)\n")
        result = self.repo.check()
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(["Tests/ParserTests.swift"], result["undeclared"])

    def test_moved_or_reindented_assertion_is_not_a_loss(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.write("Tests/TraversalTests.swift",
                        'import XCTest\nfinal class TraversalTests: XCTestCase {\n    func testRejectsTraversal2() {\n'
                        '            XCTAssertThrowsError(try parse("../etc"))\n    }\n}\n')
        self.assertEqual("pass", self.repo.check()["verdict"])

    def test_removed_test_function_fails_even_when_moved_name_absent(self):
        self.repo.edit("Tests/ParserTests.swift", "    func testLength() {\n        XCTAssertLessThan(limit, 100)\n    }\n", "")
        result = self.repo.check()
        self.assertIn("test_removed", self.kinds(result))
        self.assertTrue(any(l["detail"] == "testLength" for l in result["losses"]))

    def test_test_moved_to_another_file_is_not_removed(self):
        block = "    func testLength() {\n        XCTAssertLessThan(limit, 100)\n    }\n"
        self.repo.edit("Tests/ParserTests.swift", block, "")
        self.repo.write("Tests/LimitTests.swift", "import XCTest\nfinal class LimitTests: XCTestCase {\n" + block + "}\n")
        self.assertEqual("pass", self.repo.check()["verdict"])

    def test_skip_marker_fails(self):
        for old, new in (("    func testLength() {\n", "    func testLength() throws {\n        throw XC" + "TSkip(\"later\")\n"),):
            self.repo.edit("Tests/ParserTests.swift", old, new)
        self.assertIn("skip_added", self.kinds(self.repo.check()))

    def test_python_skip_and_deleted_file(self):
        self.repo.edit("pytests/test_t.py", "    def test_one(self):\n", "    @unittest." + "skip('x')\n    def test_one(self):\n")
        self.assertIn("skip_added", self.kinds(self.repo.check()))
        repo = Repo()
        self.addCleanup(repo.close)
        repo.git("rm", "-q", "pytests/test_t.py")
        result = repo.check()
        self.assertTrue({"test_file_deleted", "test_removed", "assertion_removed"} <= self.kinds(result))

    def test_declared_in_ledger_with_owner_passes(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.declare("Tests/ParserTests.swift")
        body = BODY.format(section="- Tests/ParserTests.swift: traversal assertion removed, Owner approved")
        self.assertEqual("pass", self.repo.check(body)["verdict"])

    def test_ledger_needs_approver_and_the_right_file(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        text = (self.repo.root / ".github/test-weakening.md").read_text()
        self.repo.write(".github/test-weakening.md", text + "- Tests/ParserTests.swift: no approver\n"
                        "- Tests/Other.swift: wrong file (approved: @owner)\n")
        self.assertEqual(["Tests/ParserTests.swift"], self.repo.check()["undeclared"])

    def test_preexisting_ledger_line_does_not_declare_a_new_loss(self):
        self.repo.declare("Tests/ParserTests.swift")
        self.repo.base = self.repo.commit()
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.assertEqual(["Tests/ParserTests.swift"], self.repo.check()["undeclared"])

    def test_body_none_with_loss_fails_even_if_ledgered(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.declare("Tests/ParserTests.swift")
        for section in ("none", "None.", "", "- n/a"):
            with self.subTest(section=section):
                result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=self.repo.commit(),
                                     body=BODY.format(section=section))
                self.assertTrue(any("says none" in p for p in result["problems"]), result["problems"])

    def test_body_must_name_each_file(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.edit("pytests/test_t.py", "        self.assertEqual(1, 1)\n", "        pass\n")
        self.repo.declare("Tests/ParserTests.swift")
        self.repo.declare("pytests/test_t.py")
        result = self.repo.check(BODY.format(section="Tests/ParserTests.swift: removed"))
        self.assertTrue(any("does not name: pytests/test_t.py" in p for p in result["problems"]), result["problems"])

    def test_missing_section_with_loss_fails(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.declare("Tests/ParserTests.swift")
        self.assertEqual("fail", self.repo.check("## Intent\nx\n")["verdict"])

    def test_bad_revisions_fail_closed(self):
        result = ti.evaluate(str(self.repo.root), base="f" * 40, head=self.repo.base, body=None)
        self.assertEqual("fail", result["verdict"])
        self.assertIn("fail-closed", result["problems"][0])
        self.assertEqual("fail", ti.evaluate(str(self.repo.root), base="", head="", body=None)["verdict"])

    def test_cli(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        head = self.repo.commit()
        body = self.repo.root.parent / (self.repo.root.name + ".body")
        body.write_text(BODY.format(section="none"))
        self.addCleanup(body.unlink)
        run = lambda *a: subprocess.run([sys.executable, str(SCRIPT), *a], cwd=self.repo.root, env=self.repo.env,
                                        capture_output=True, text=True, timeout=30)
        failed = run("--base", self.repo.base, "--head", head, "--body-file", str(body))
        self.assertEqual(1, failed.returncode)
        self.assertEqual("fail", json.loads(failed.stdout)["verdict"])
        self.assertEqual(0, run("--base", self.repo.base, "--head", self.repo.base).returncode)
        self.assertEqual(1, run("--base", "nope", "--head", head).returncode)
        self.assertEqual(2, run().returncode)

    def test_duplicate_assertions_are_a_multiset(self):
        line = "        XCTAssertLessThan(limit, 100)\n"
        self.repo.edit("Tests/ParserTests.swift", line, line + line)
        self.repo.base = self.repo.commit()
        self.repo.edit("Tests/ParserTests.swift", line + line, "")
        self.repo.write("Tests/Moved.swift", "import XCTest\n" + line)
        result = self.repo.check()
        self.assertEqual(1, sum(l["kind"] == "assertion_removed" for l in result["losses"]), result["losses"])

    def test_duplicate_test_names_are_a_multiset(self):
        self.repo.write("Tests/OtherTests.swift", "import XCTest\nfinal class O: XCTestCase {\n"
                        "    func testLength() {\n        XCTAssertTrue(true)\n    }\n}\n")
        self.repo.base = self.repo.commit()
        self.repo.git("rm", "-q", "Tests/OtherTests.swift")
        result = self.repo.check()
        self.assertTrue(any(l["kind"] == "test_removed" and l["detail"] == "testLength" for l in result["losses"]))

    def test_ledger_not_owner_gated_fails_closed(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.declare("Tests/ParserTests.swift")
        self.repo.write(".github/CODEOWNERS", "/src/ @owner\n")
        body = BODY.format(section="Tests/ParserTests.swift removed")
        result = self.repo.check(body)
        self.assertTrue(any("CODEOWNERS does not cover" in p for p in result["problems"]), result["problems"])

    def test_test_path_classification(self):
        for path in ("Tests/A.swift", "Packages/X/Tests/Y/ZTests.swift", "scripts/tests/test_app.py",
                     "tests/test_x.py", "pkg/a_test.go", "web/a.test.ts", "src/test_util.py"):
            self.assertTrue(ti.is_test_path(path), path)
        for path in ("scripts/quality/test_integrity.py", ".github/test-weakening.md", "src/parser.swift"):
            self.assertFalse(ti.is_test_path(path), path)

    def test_codeowners_last_match_wins(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.declare("Tests/ParserTests.swift")
        body = BODY.format(section="Tests/ParserTests.swift removed")
        cases = {"/.github/ @owner\n": True, "* @owner\n": True, "/.github/** @owner\n": True,
                 ".github/test-weakening.md @owner\n": True, "/.github/ @owner\n/.github/test-weakening.md\n": False,
                 "/.github/ @owner\n*.md\n": False, "/src/ @owner\n": False, "": False}
        for text, gated in cases.items():
            with self.subTest(codeowners=text):
                self.repo.write(".github/CODEOWNERS", text)
                result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=self.repo.commit(), body=body)
                self.assertEqual(gated, result["verdict"] == "pass", result["problems"])

    def test_ledger_line_needs_reason(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        text = (self.repo.root / ".github/test-weakening.md").read_text()
        self.repo.write(".github/test-weakening.md", text + "- Tests/ParserTests.swift: (approved: @owner)\n")
        self.assertEqual(["Tests/ParserTests.swift"], self.repo.check()["undeclared"])

    # ---- parity with VoxPocket #65 (Swift Testing fixtures) ------------------
    SWIFT_TESTING = ('import Testing\n\n@Test func accepts() {\n    #expect(valid("a"))\n}\n\n'
                     '@Test func rejects() {\n    #expect(!valid("../secret"))\n    #expect(!valid("bad\\n"))\n}\n')

    def swift_testing_base(self):
        self.repo.write("Packages/F/Tests/FTests/ValidTests.swift", self.SWIFT_TESTING)
        self.repo.base = self.repo.commit()
        return "Packages/F/Tests/FTests/ValidTests.swift"

    def test_parity_weakened_in_place_blocks(self):
        path = self.swift_testing_base()
        self.repo.edit(path, '#expect(!valid("../secret"))', "#expect(true)")
        self.assertIn("assertion_removed", self.kinds(self.repo.check()))

    def test_parity_removed_swift_testing_function_blocks(self):
        path = self.swift_testing_base()
        self.repo.edit(path, '@Test func accepts() {\n    #expect(valid("a"))\n}\n', "")
        self.repo.write("Packages/F/Tests/FTests/Other.swift",
                        'import Testing\n\n@Test func replacement() {\n    #expect(valid("a"))\n}\n')
        result = self.repo.check()
        self.assertTrue(any(l["kind"] == "test_removed" and l["detail"] == "accepts" for l in result["losses"]))

    def test_parity_split_file_passes(self):
        path = self.swift_testing_base()
        head, tail = self.SWIFT_TESTING.split("@Test func rejects")
        self.repo.write(path, head)
        self.repo.write("Packages/F/Tests/FTests/Other.swift", "import Testing\n\n@Test func rejects" + tail)
        self.assertEqual("pass", self.repo.check()["verdict"])

    def test_parity_disabled_marker_blocks(self):
        path = self.swift_testing_base()
        self.repo.edit(path, "@Test func rejects", "@Test(." + "disabled()) func rejects")
        self.assertIn("skip_added", self.kinds(self.repo.check()))

    def test_parity_offset_by_unrelated_swift_testing_addition_blocks(self):
        path = self.swift_testing_base()
        self.repo.edit(path, '    #expect(!valid("../secret"))\n', "")
        self.repo.write("Packages/F/Tests/FTests/Other.swift",
                        'import Testing\n\n@Test func unrelated() {\n    #expect(valid("zzz"))\n}\n')
        self.assertEqual([path], self.repo.check()["undeclared"])

    def test_parity_enabled_if_marker_blocks(self):
        # VoxPocket #65 codex round 2: `.enabled(if: false)` disabled a test undetected.
        for trait in ("@Test(." + "enabled(if: false)) func rejects",
                      "@Test(\n    .en" + "abled( if : Env.never)\n)\nfunc rejects",
                      "@Test(\n    .en" + "abled(if: false)\n)\nfunc rejects"):  # #65 fixture
            with self.subTest(trait=trait):
                repo = Repo()
                self.addCleanup(repo.close)
                self.repo = repo
                path = self.swift_testing_base()
                repo.edit(path, "@Test func rejects", trait)
                self.assertIn("skip_added", self.kinds(repo.check()))

    def test_retagging_a_test_is_not_a_loss(self):
        path = self.swift_testing_base()
        self.repo.edit(path, "@Test func accepts", "@Test(.tags(.fast)) func accepts")
        self.assertEqual("pass", self.repo.check()["verdict"])

    def test_unwrap_and_raises_are_assertions(self):
        self.repo.write("Tests/UnwrapTests.swift", "import XCTest\nfinal class U: XCTestCase {\n"
                        "    func testU() throws {\n        _ = try XCTUnwrap(value)\n        XCTAssertTrue(true)\n    }\n}\n")
        self.repo.write("pytests/test_r.py", "import pytest\n\ndef test_r():\n    with pytest.raises(ValueError):\n        f()\n")
        self.repo.base = self.repo.commit()
        self.repo.edit("Tests/UnwrapTests.swift", "        _ = try XCTUnwrap(value)\n", "")
        self.repo.edit("pytests/test_r.py", "    with pytest.raises(ValueError):\n        f()\n", "    f()\n")
        result = self.repo.check()
        self.assertEqual({"Tests/UnwrapTests.swift", "pytests/test_r.py"},
                         {l["file"] for l in result["losses"] if l["kind"] == "assertion_removed"})

    def test_multiline_swift_testing_name_is_tracked(self):
        multi = 'import Testing\n\n@Test(\n    .tags(.fast)\n)\nfunc multi() {\n    #expect(true)\n}\n'
        self.repo.write("Tests/MultiTests.swift", multi)
        self.repo.base = self.repo.commit()
        self.assertEqual({"multi": 1}, dict(ti._names(multi)))
        self.repo.write("Tests/MultiTests.swift", "import Testing\n")
        result = self.repo.check()
        self.assertTrue(any(l["kind"] == "test_removed" and l["detail"] == "multi" for l in result["losses"]))

    # ---- multiline assertions (VoxPocket #65 codex round 4) ------------------
    MULTI = ('import XCTest\nimport Testing\n\n@Test func rejects() {\n    #expect(\n        !valid("../secret")\n    )\n}\n\n'
             'final class E: XCTestCase {\n    func testEq() {\n        XCTAssertEqual(\n            parse("a"),\n'
             '            "a",\n            "parses (plain) input"\n        )\n    }\n}\n')

    def multi_base(self):
        self.repo.write("Tests/MultiAssertTests.swift", self.MULTI)
        self.repo.base = self.repo.commit()
        return "Tests/MultiAssertTests.swift"

    def test_multiline_expect_condition_change_fails(self):
        path = self.multi_base()
        self.repo.edit(path, '        !valid("../secret")\n', "        true\n")
        result = self.repo.check()
        self.assertEqual([path], result["undeclared"])
        self.assertIn("assertion_removed", self.kinds(result))

    def test_multiline_xctassert_argument_deleted_fails(self):
        path = self.multi_base()
        self.repo.edit(path, '            "a",\n', "")
        self.assertIn("assertion_removed", self.kinds(self.repo.check()))

    def test_multiline_assertion_moved_to_another_file_passes(self):
        path = self.multi_base()
        block = '        XCTAssertEqual(\n            parse("a"),\n            "a",\n            "parses (plain) input"\n        )\n'
        self.repo.edit(path, block, "")
        self.repo.write("Tests/MovedTests.swift", "import XCTest\nfinal class M: XCTestCase {\n    func testEq() {\n"
                        + block.replace("        ", "      ") + "    }\n}\n")
        self.assertEqual("pass", self.repo.check()["verdict"])

    def test_multiline_assertion_reformatted_in_place_passes(self):
        path = self.multi_base()
        self.repo.edit(path, '    #expect(\n        !valid("../secret")\n    )\n', '    #expect(!valid("../secret"))\n')
        result = self.repo.check()
        self.assertTrue(all(l["kind"] != "assertion_removed" or "secret" not in l["detail"] for l in result["losses"]),
                        result["losses"])

    def test_assertions_statement_joining(self):
        self.assertEqual(['#expect(!valid("../secret"))',
                          'XCTAssertEqual(parse("a"),"a","parses(plain)input")'], ti.assertions(self.MULTI))

    def test_s5_probe_shape_is_blocked(self):
        # S5 G1 replay: one assertion deleted from an input-validation test, template says "none".
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(2, len(result["problems"]))


if __name__ == "__main__":
    unittest.main()
