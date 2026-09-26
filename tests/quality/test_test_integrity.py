"""Test-integrity: per-assertion/per-test evidence and PR-body explanations."""
from __future__ import annotations

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

    def check(self, body: str | None = BODY.format(section="none")) -> dict:
        head = self.commit()
        return ti.evaluate(str(self.root), base=self.base, head=head, body=body)


class TestIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        # Direct evaluator calls need the same Git isolation as subprocess
        # fixtures, including when verify is launched from pre-push.
        isolated = mock.patch.dict(os.environ, environment(), clear=True)
        isolated.start()
        self.addCleanup(isolated.stop)
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

    def test_block_commented_swift_suite_requires_declaration(self):
        self.repo.write("Tests/ParserTests.swift", "/*\n" + SWIFT + "*/\n")
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(["Tests/ParserTests.swift"], result["undeclared"])
        self.assertEqual({"assertion_removed", "test_removed"}, self.kinds(result))
        self.assertEqual(3, sum(loss["kind"] == "assertion_removed" for loss in result["losses"]))
        self.assertEqual({"testRejectsTraversal", "testLength"},
                         {loss["detail"] for loss in result["losses"] if loss["kind"] == "test_removed"})
        body = self.repo.root / "pr-body.md"
        body.write_text(BODY.format(section="none"))
        failed = subprocess.run(
            [sys.executable, str(SCRIPT), "--base", self.repo.base, "--head", self.repo.git("rev-parse", "HEAD").strip(),
             "--body-file", str(body)],
            cwd=self.repo.root, env=self.repo.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, failed.returncode)
        self.assertEqual(["Tests/ParserTests.swift"], json.loads(failed.stdout)["undeclared"])

    def test_documentation_comments_and_reformatting_pass(self):
        self.repo.write("Tests/ParserTests.swift", '/*\n' + SWIFT + '\n/* nested */\n*/\n' + SWIFT)
        self.repo.base = self.repo.commit()
        self.repo.write("Tests/ParserTests.swift", SWIFT.replace(
            'XCTAssertEqual(parse("a"), "a")',
            'XCTAssertEqual(\n            parse("a"), /* explanation */\n            "a"\n        ) // retained'))
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual(("pass", []), (result["verdict"], result["losses"]))

    def test_swift_literal_suite_cannot_replace_executable_tests(self):
        for opening, closing in (('let example = """\n', '\n"""\n'),
                                 ('let example = #"""\n', '\n"""#\n')):
            with self.subTest(opening=opening):
                self.repo.write("Tests/ParserTests.swift", opening + SWIFT + closing)
                result = self.repo.check(BODY.format(section="none"))
                self.assertEqual("fail", result["verdict"])
                self.assertEqual({"assertion_removed", "test_removed"}, self.kinds(result))

    def test_python_docstring_cannot_replace_executable_tests(self):
        self.repo.write("pytests/test_t.py", '"""\n' + PY + '"""\n')
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(["pytests/test_t.py"], result["undeclared"])
        self.assertEqual({"assertion_removed", "test_removed"}, self.kinds(result))

    def test_removing_literal_test_snippets_passes(self):
        snippets = {"Tests/DocsTests.swift": 'let example = #"""\n' + SWIFT + '"""#\n',
                    "pytests/test_docs.py": '"""\n' + PY + '"""\n',
                    "web/docs.test.js": 'const example = `\ntest("sample", () => {\n'
                                        '  expect(value).toBe("/* sample */");\n});\n`;\n'}
        for path, text in snippets.items():
            self.repo.write(path, text)
        self.repo.base = self.repo.commit()
        for path in snippets:
            self.repo.write(path, "\n")
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual(("pass", []), (result["verdict"], result["losses"]))

    def test_multiline_documentation_skip_snippets_pass(self):
        self.repo.write("Tests/DocsTests.swift", '/*\nXCTSkip("example")\n*/\n'
                        'let example = #"""\n.disabled()\n"""#\n')
        self.repo.write("pytests/test_docs.py", '"""\n@unittest.skip("example")\n"""\n')
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual(("pass", []), (result["verdict"], result["losses"]))

    def test_multiline_and_raw_assertion_literal_changes_are_losses(self):
        for before, after in (('"""\na\nb\n"""', '"""\na b\n"""'),
                              ('#"a"  "b"#', '#"a" "b"#')):
            with self.subTest(before=before):
                path = "Tests/LiteralTests.swift"
                self.repo.write(path, "XCTAssertEqual(value, " + before + ")\n")
                self.repo.base = self.repo.commit()
                self.repo.write(path, "XCTAssertEqual(value, " + after + ")\n")
                result = self.repo.check(BODY.format(section="none"))
                self.assertEqual("fail", result["verdict"])
                self.assertEqual([path], result["undeclared"])

    def test_comment_delimiters_inside_assertion_literals_remain_data(self):
        for path, before, after in (
                ("Tests/LiteralTests.swift", 'XCTAssertEqual(value, "https://a/*b*/")',
                 'XCTAssertEqual(value, "https://a/*c*/")'),
                ("pytests/test_literal.py", 'assert value == "#a//b"', 'assert value == "#a//c"')):
            with self.subTest(path=path):
                self.repo.write(path, before + "\n")
                self.repo.base = self.repo.commit()
                self.repo.write(path, after + "\n")
                result = self.repo.check(BODY.format(section="none"))
                self.assertEqual("fail", result["verdict"])
                self.assertEqual([path], result["undeclared"])

    def test_jest_literal_name_remains_a_test_name(self):
        path = "web/parser.test.js"
        self.repo.write(path, 'test("rejects input", () => {\n  expect(valid).toBe(false);\n});\n')
        self.repo.base = self.repo.commit()
        self.repo.edit(path, '"rejects input"', '"other input"')
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual([{"kind": "test_removed", "file": path, "detail": "rejects input"}], result["losses"])

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

    def test_skip_in_git_quoted_unicode_path_requires_declaration(self):
        path = "Tests/验证Tests.swift"
        self.repo.write(path, SWIFT)
        self.repo.base = self.repo.commit()
        self.repo.edit(path, "func testLength() {",
                       'func testLength() throws {\n        throw XCTSkip("temporarily skipped")')
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual([path], result["undeclared"])
        self.assertEqual([{"kind": "skip_added", "file": path,
                           "detail": 'XCTSkip("temporarily skipped")'}], result["losses"])

    def test_skip_paths_preserve_quoted_and_literal_filename_identity(self):
        paths = ["Tests/验证Tests.swift", "Tests/space nameTests.swift", "Tests/tab\tTests.swift",
                 'Tests/quote"Tests.swift', "Tests/back\\slashTests.swift", "Tests/[ab]Tests.swift"]
        for path in paths + ["Tests/aTests.swift"]:
            self.repo.write(path, SWIFT)
        self.repo.base = self.repo.commit()
        for path in paths:
            self.repo.edit(path, "func testLength() {",
                           'func testLength() throws {\n        throw XCTSkip("later")')
        # A glob-shaped path must not also read these unrelated hunks.
        self.repo.edit("Tests/aTests.swift", 'parse("a")', 'parse("b")')
        for quote_path in ("true", "false"):
            with self.subTest(quote_path=quote_path):
                self.repo.git("config", "core.quotepath", quote_path)
                result = self.repo.check(BODY.format(section="none"))
                self.assertEqual("fail", result["verdict"])
                skips = [loss for loss in result["losses"] if loss["kind"] == "skip_added"]
                self.assertEqual(sorted(paths), sorted(loss["file"] for loss in skips))
                self.assertTrue(set(paths) <= set(result["undeclared"]))

    def test_quoted_paths_keep_multiline_skip_snippets_non_executable(self):
        for path in ("Tests/验证Tests.swift", 'Tests/tab\tquote"Tests.swift'):
            self.repo.write(path, SWIFT)
        self.repo.base = self.repo.commit()
        for path in ("Tests/验证Tests.swift", 'Tests/tab\tquote"Tests.swift'):
            self.repo.write(path, '/*\nXCTSkip("example")\n*/\n'
                            'let example = """\nXCTSkip("example")\n"""\n' + SWIFT)
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual(("pass", []), (result["verdict"], result["losses"]))

    def test_malformed_git_inventory_fails_closed(self):
        head = self.repo.commit()
        git = ti._git
        for raw in ("M\0", "M\0tests/a.py", "R100\0a\0b\0", "M\0\0", "M\0a\0M\0a\0"):
            with self.subTest(raw=raw):
                def broken_diff(root, *args):
                    return raw if "--name-status" in args else git(root, *args)
                with mock.patch.object(ti, "_git", side_effect=broken_diff):
                    result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=head, body=None)
                self.assertEqual("fail", result["verdict"])
                self.assertIn("fail-closed", result["problems"][0])

    def test_python_skip_and_deleted_file(self):
        self.repo.edit("pytests/test_t.py", "    def test_one(self):\n", "    @unittest." + "skip('x')\n    def test_one(self):\n")
        self.assertIn("skip_added", self.kinds(self.repo.check()))
        repo = Repo()
        self.addCleanup(repo.close)
        repo.git("rm", "-q", "pytests/test_t.py")
        result = repo.check()
        self.assertTrue({"test_file_deleted", "test_removed", "assertion_removed"} <= self.kinds(result))

    def test_skip_markers_in_comments_or_literals_are_not_code(self):
        self.repo.write("tests/test_documentation.py", '# .enabled(if: false) is a disabled trait\n'
                        'example = "@unittest.skip(\'example\')"\n')
        self.repo.write("Tests/DocsTests.swift", '// .disabled() is a disabled trait\n'
                        'let example = "XCTSkip(\\\"example\\\")"\n')
        self.assertEqual("pass", self.repo.check(BODY.format(section="none"))["verdict"])

    def test_body_none_with_loss_fails_without_an_explanation(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        for section in ("none", "None.", "", "- n/a"):
            with self.subTest(section=section):
                result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=self.repo.commit(),
                                     body=BODY.format(section=section))
                self.assertTrue(any("says none" in p for p in result["problems"]), result["problems"])

    def test_body_must_name_each_file(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.edit("pytests/test_t.py", "        self.assertEqual(1, 1)\n", "        pass\n")
        result = self.repo.check(BODY.format(section="Tests/ParserTests.swift: removed"))
        self.assertTrue(any("does not name: pytests/test_t.py" in p for p in result["problems"]), result["problems"])

    def test_missing_section_with_loss_fails(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.assertEqual("fail", self.repo.check("## Intent\nx\n")["verdict"])

    def test_bad_revisions_fail_closed(self):
        result = ti.evaluate(str(self.repo.root), base="f" * 40, head=self.repo.base, body=None)
        self.assertEqual("fail", result["verdict"])
        self.assertIn("fail-closed", result["problems"][0])
        self.assertEqual("fail", ti.evaluate(str(self.repo.root), base="", head="", body=None)["verdict"])

    def test_unreadable_base_test_fails_closed(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        head = self.repo.commit()
        git = ti._git

        def fail_base_read(root, *args):
            if args == ("show", f"{self.repo.base}:Tests/ParserTests.swift"):
                raise ti.IntegrityError("test blob unavailable")
            return git(root, *args)

        with mock.patch.object(ti, "_git", side_effect=fail_base_read):
            result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=head, body=None)
        self.assertEqual("fail", result["verdict"])
        self.assertTrue(any("test blob unavailable" in problem and "fail-closed" in problem
                            for problem in result["problems"]), result)

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

    def test_test_path_classification(self):
        for path in ("Tests/A.swift", "Packages/X/Tests/Y/ZTests.swift", "scripts/tests/test_app.py",
                     "tests/test_x.py", "pkg/a_test.go", "web/a.test.ts", "src/test_util.py"):
            self.assertTrue(ti.is_test_path(path), path)
        for path in ("scripts/quality/test_integrity.py", ".github/test-weakening.md", "src/parser.swift"):
            self.assertFalse(ti.is_test_path(path), path)

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
                          'XCTAssertEqual(parse("a"),"a","parses (plain) input")'], ti.assertions(self.MULTI))

    def test_string_literal_whitespace_change_is_a_loss(self):
        path = self.multi_base()
        self.repo.edit(path, '            "parses (plain) input"', '            "parses  (plain) input"')
        result = self.repo.check()
        self.assertEqual("fail", result["verdict"])
        self.assertEqual([path], result["undeclared"])

    def test_single_quoted_and_template_literal_contents_are_preserved(self):
        for before, after in (("expect(value).toBe('a, b')", "expect(value).toBe('a,b')"),
                              ('expect(value).toBe(`a  b`)', 'expect(value).toBe(`a b`)')):
            with self.subTest(before=before):
                self.assertNotEqual(ti.assertions(before), ti.assertions(after))

    def test_s5_probe_shape_is_blocked(self):
        # S5 G1 replay: one assertion deleted from an input-validation test, template says "none".
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        result = self.repo.check(BODY.format(section="none"))
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(1, len(result["problems"]))

    def test_explained_loss_needs_no_ledger_codeowners_or_owner(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        result = self.repo.check(BODY.format(section="- Tests/ParserTests.swift: replaced obsolete parser behavior"))
        self.assertEqual("pass", result["verdict"])
        self.assertEqual({"assertion_removed"}, self.kinds(result))
        self.assertEqual([], result["undeclared"])
        self.assertTrue(result["body_checked"])

    def test_local_detection_without_body_reports_losses_without_approval(self):
        self.repo.git("rm", "-q", "pytests/test_t.py")
        result = self.repo.check(body=None)
        self.assertEqual("pass", result["verdict"])
        self.assertIn("test_file_deleted", self.kinds(result))
        self.assertFalse(result["body_checked"])

    def test_legacy_owner_ledger_does_not_replace_pr_explanation(self):
        self.repo.edit("Tests/ParserTests.swift", '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        self.repo.write(".github/test-weakening.md",
                        "- Tests/ParserTests.swift: old declaration (approved: @owner)\n")
        self.assertEqual("fail", self.repo.check(BODY.format(section="none"))["verdict"])

    def test_explained_skip_needs_no_owner(self):
        self.repo.edit("pytests/test_t.py", "    def test_one(self):\n",
                       "    @unittest.skip('unsupported platform')\n    def test_one(self):\n")
        result = self.repo.check(BODY.format(section="pytests/test_t.py: skip unsupported platform"))
        self.assertEqual("pass", result["verdict"])
        self.assertIn("skip_added", self.kinds(result))


class LexicalEdgeTests(unittest.TestCase):
    def test_multiple_assertions_and_names_on_one_line_are_multisets(self):
        text = 'test("one", () => { expect(1).toBe(1); expect(2).toBe(2); }); test("two", () => {});'
        self.assertEqual({"one": 1, "two": 1}, ti._names(text, "x.test.js"))
        self.assertEqual(["expect(1).toBe(1)", "expect(2).toBe(2)"], ti.assertions(text, "x.test.js"))

    def test_literal_call_with_later_code_is_not_name(self):
        self.assertEqual({}, ti._names("const doc = 'test(\"fake\", () => {})'; live();", "x.test.js"))

    def test_assertion_outside_literal_on_same_line(self):
        self.assertEqual(['expect(real).toBe(true)'], ti.assertions(
            'const doc = "expect(fake)"; expect(real).toBe(true);', "x.test.js"))

    def test_multiline_python_brackets_and_jest_chain(self):
        self.assertEqual(["assert value ==[1,2]"], ti.assertions('assert value == [\n 1,\n 2\n]\n', "test_x.py"))
        self.assertEqual(['expect(value).toEqual([1,2])'], ti.assertions(
            'expect(value).toEqual([\n1,\n2\n]);', "x.test.js"))

    def test_fluent_assertion_chain_and_python_continuation(self):
        self.assertEqual(["expect(value).not.toBe(false)"], ti.assertions(
            "expect(value)\n .not\n .toBe(false);", "x.test.js"))
        self.assertEqual(["assert value == 1"], ti.assertions(
            "assert value " + "\\" + "\n == 1\n", "test_x.py"))

    def test_escaped_and_multiline_jest_names(self):
        text = "test('can" + "\\" + "'t fail', () => {}); test(\n `multi\nline`, () => {});"
        self.assertEqual({"can" + "\\" + "'t fail": 1, "multi\nline": 1}, ti._names(text, "x.test.js"))

    def test_go_raw_backslash_does_not_escape_closing_tick(self):
        text = "value := `ends in " + "\\" + "`\nfunc TestLive(t *testing.T) {\n t.Fatal(value)\n}"
        self.assertEqual({"TestLive": 1}, ti._names(text, "x_test.go"))
        self.assertEqual(["t.Fatal(value)"], ti.assertions(text, "x_test.go"))

    def test_unbalanced_recognized_statement_fails_closed(self):
        with self.assertRaises(ti.IntegrityError):
            ti.assertions('XCTAssertTrue(\n value\n', "Tests/X.swift")

    def test_git_process_timeout_and_invalid_utf8_fail_closed(self):
        for error in (OSError("unavailable"), subprocess.TimeoutExpired("git", 120)):
            with mock.patch.object(ti.subprocess, "run", side_effect=error):
                with self.assertRaises(ti.IntegrityError):
                    ti._git(".", "diff")
        with mock.patch.object(ti.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"\xff", b"")):
            with self.assertRaises(ti.IntegrityError):
                ti._git(".", "diff")

    def test_section_rejects_prefix_duplicates_and_fenced_examples(self):
        entry = 'Tests/A.swift: moved to focused cases'
        for text in ('## ' + ti.SECTION + ' extra\n' + entry,
                     '```md\n## ' + ti.SECTION + '\n' + entry + '\n```',
                     '~~~\n## ' + ti.SECTION + '\n' + entry + '\n~~~',
                     '## ' + ti.SECTION + '\n' + entry + '\n## ' + ti.SECTION + '\n' + entry):
            self.assertIsNone(ti.section_text(text))
        self.assertEqual('', ti.section_text('## ' + ti.SECTION + '\n<!--\n' + entry + '\n-->'))

    def test_exact_path_and_nonplaceholder_rationale(self):
        path = "tests/test_a.py"
        for line in (path, path + ".bak: cleanup", "prefix/" + path + ": cleanup",
                     path + ": none", path + ": TODO", path + ": <reason>", path + ": - [ ]"):
            self.assertFalse(ti._declared(line, path), line)
        for form in (path, '`' + path + '`', json.dumps(path)):
            self.assertTrue(ti._declared('- ' + form + ': superseded by new boundary cases', path))


class GitEdgeTests(unittest.TestCase):
    setUp = TestIntegrityTests.setUp

    def test_duplicate_evidence_loss_stays_with_the_actually_changed_file(self):
        removed = "pytests/test_dup_a.py"
        retained = "pytests/test_dup_z.py"
        text = "def test_duplicate():\n    assert ready\n"
        self.repo.write(removed, text)
        self.repo.write(retained, text)
        self.repo.base = self.repo.commit()
        self.repo.write(removed, "pass\n")
        self.repo.write(retained, "# unrelated comment\n" + text)
        result = self.repo.check(BODY.format(section=removed + ": duplicate coverage consolidated"))
        self.assertEqual("pass", result["verdict"], result)
        self.assertEqual({removed}, {row["file"] for row in result["losses"]})
        self.assertEqual({"assertion_removed", "test_removed"}, {row["kind"] for row in result["losses"]})

    def test_uncommented_skip_is_detected_without_added_marker_line(self):
        path = "Tests/Skip.swift"
        self.repo.write(path, '/*\nXCTSkip("later")\n*/\n')
        self.repo.base = self.repo.commit()
        self.repo.write(path, 'XCTSkip("later")\n')
        result = self.repo.check()
        self.assertEqual("fail", result["verdict"])
        self.assertEqual(["skip_added"], [row["kind"] for row in result["losses"]])

    def test_unchanged_skip_reformat_is_not_new(self):
        path = "tests/test_skip.py"
        self.repo.write(path, '@unittest.skip("platform")\ndef test_a(): pass\n')
        self.repo.base = self.repo.commit()
        self.repo.write(path, '@unittest.skip(\n    "platform"\n)\ndef test_a(): pass\n')
        self.assertEqual([], self.repo.check()["losses"])

    def test_duplicate_skip_added_is_detected(self):
        path = "tests/test_skip.py"
        self.repo.write(path, 'pytest.skip("later")\n')
        self.repo.base = self.repo.commit()
        self.repo.write(path, 'pytest.skip("later")\npytest.skip("later")\n')
        self.assertEqual(1, len(self.repo.check()["losses"]))

    def test_rename_keeps_names_but_requires_deleted_path_reason(self):
        old = "Tests/ParserTests.swift"
        self.repo.git("mv", old, "Tests/RenamedTests.swift")
        result = self.repo.check()
        self.assertEqual([{"kind": "test_file_deleted", "file": old, "detail": "test file deleted"}], result["losses"])
        self.assertEqual("pass", self.repo.check(BODY.format(section=old + ": renamed for ownership clarity"))["verdict"])

    def test_rename_to_non_test_path_cannot_hide_loss(self):
        self.repo.git("mv", "pytests/test_t.py", "src/example.py")
        result = self.repo.check()
        self.assertEqual({"test_removed", "assertion_removed", "test_file_deleted"}, {r["kind"] for r in result["losses"]})

    def test_newline_tab_quote_unicode_paths_use_json_declarations(self):
        paths = ['pytests/test_a\nb.py', 'pytests/test_tab\t.py', 'pytests/test_"quote.py', 'pytests/test_验证.py']
        for path in paths:
            self.repo.write(path, "assert ready\n")
        self.repo.base = self.repo.commit()
        for path in paths:
            self.repo.write(path, "pass\n")
        section = '\n'.join('- ' + json.dumps(path) + ': duplicate case covered in new suite' for path in paths)
        result = self.repo.check(BODY.format(section=section))
        self.assertEqual("pass", result["verdict"], result)
        self.assertEqual(set(paths), {r["file"] for r in result["losses"]})

    def test_body_prefix_or_placeholder_cannot_authorize_loss(self):
        path = "pytests/test_t.py"
        self.repo.write(path, "pass\n")
        for section in (path + '.bak: removed obsolete case', path + ':', path + ': TBD',
                        '```\n' + path + ': removed obsolete case\n```'):
            self.assertEqual("fail", self.repo.check(BODY.format(section=section))["verdict"])

    def test_body_unavailable_is_explicit_local_report(self):
        self.repo.write("pytests/test_t.py", "pass\n")
        result = self.repo.check(body=None)
        self.assertEqual(("pass", False, "unavailable-local"), (result["verdict"], result["body_checked"], result["body_status"]))
        self.assertTrue(result["losses"])

    def test_invalid_body_type_fails_closed(self):
        result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=self.repo.base, body={})
        self.assertEqual("fail", result["verdict"])

    def test_live_api_errors_fail_even_with_general_pr_body_check_disabled(self):
        for error in (ti.IntegrityError("stale head"), OSError("offline"), ValueError("invalid JSON")):
            stdout = io.StringIO()
            with mock.patch.dict(os.environ, {"CHECK_PR_BODY": "false"}), \
                    mock.patch.object(ti.os, "getcwd", return_value=str(self.repo.root)), \
                    mock.patch.object(ti, "_live_body", side_effect=error) as live, \
                    mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", io.StringIO()):
                result = ti.main(["--base", self.repo.base, "--head", self.repo.base, "--live-body"])
            self.assertEqual(1, result)
            live.assert_called_once_with(self.repo.base, self.repo.base)
            self.assertEqual("fail", json.loads(stdout.getvalue())["verdict"])

    def test_cli_missing_body_file_and_live_context_produce_failure_json(self):
        for flags in (("--body-file", "missing-body.md"), ("--live-body",)):
            result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--base', self.repo.base,
                                     '--head', self.repo.base, *flags], cwd=self.repo.root,
                                    env=self.repo.env, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertEqual("unavailable-error", json.loads(result.stdout)["body_status"])


class LiveBodyTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ, {"REPO": "org/repo", "PR_NUMBER": "12", "GH_TOKEN": "fixture"}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def fetch(self, data):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(data).encode()
        with mock.patch.object(ti.urllib.request, "urlopen", return_value=response) as request:
            result = ti._live_body("a" * 40, "b" * 40)
            self.assertEqual("https://api.github.com/repos/org/repo/pulls/12", request.call_args.args[0].full_url)
            return result

    def test_live_body_and_null_body(self):
        for body in ("edited live rationale", None):
            self.assertEqual(body or "", self.fetch({"head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}, "body": body}))

    def test_missing_malformed_stale_api_fields_fail(self):
        valid = {"head": {"sha": "a" * 40}, "base": {"sha": "b" * 40}, "body": "reason"}
        for bad in ([], {}, {**valid, "head": None}, {**valid, "head": {"sha": "c" * 40}},
                    {**valid, "base": {"sha": "c" * 40}}, {**valid, "body": []},
                    {k: v for k, v in valid.items() if k != "body"}):
            with self.subTest(data=bad), self.assertRaises(ti.IntegrityError):
                self.fetch(bad)

    def test_malformed_context_never_calls_api(self):
        for key, value in (("REPO", "org/repo/other"), ("PR_NUMBER", "../12"), ("GH_TOKEN", "")):
            with mock.patch.dict(os.environ, {key: value}), mock.patch.object(ti.urllib.request, "urlopen") as request:
                with self.assertRaises(ti.IntegrityError):
                    ti._live_body("a" * 40, "b" * 40)
                request.assert_not_called()

    def test_api_transport_and_json_errors_are_not_success(self):
        for error in (OSError("offline"), ValueError("malformed JSON")):
            with mock.patch.object(ti.urllib.request, "urlopen", side_effect=error), self.assertRaises(type(error)):
                ti._live_body("a" * 40, "b" * 40)


class ReviewRepairTests(unittest.TestCase):
    setUp = TestIntegrityTests.setUp

    def cli(self, section):
        head = self.repo.git("rev-parse", "HEAD").strip()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md") as body:
            body.write(BODY.format(section=section))
            body.flush()
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--base", self.repo.base,
                                     "--head", head, "--body-file", body.name], cwd=self.repo.root,
                                    env=self.repo.env, capture_output=True, text=True, timeout=30)
        return result.returncode, json.loads(result.stdout)

    def test_parameterized_skip_chains_and_aliases_require_rationale(self):
        path = "web/parameterized.test.js"
        pairs = (("test", "test.skip"), ("it", "it.skip"), ("describe", "describe.skip"),
                 ("it", "xit"), ("test", "xtest"), ("describe", "xdescribe"),
                 ("test.concurrent", "test.concurrent.skip"), ("it.concurrent", "it.concurrent.skip"))
        for original, skipped in pairs:
            for table in ("([1, 2])", "`value\n${1}\n${2}\n`"):
                with self.subTest(skipped=skipped, table=table):
                    tail = '.each' + table + '("positive", value => { expect(value).toBeGreaterThan(0); });\n'
                    self.repo.write(path, original + tail)
                    self.repo.base = self.repo.commit()
                    self.repo.write(path, skipped + tail)
                    self.repo.commit()
                    rc, result = self.cli("none")
                    self.assertEqual(1, rc, result)
                    self.assertIn("skip_added", {loss["kind"] for loss in result["losses"]})
                    self.assertEqual([path], result["undeclared"])
                    rc, result = self.cli('`' + path + '`: skip unsupported data cases pending platform repair')
                    self.assertEqual(0, rc, result)
                    self.assertTrue(result["body_checked"])

    def test_skip_failing_forms_require_rationale(self):
        path = "web/failing.test.js"
        for skipped in ("test.skip.failing", "it.skip.failing", "xit.failing", "xtest.failing"):
            with self.subTest(skipped=skipped):
                tail = '("broken case", () => { expect(value).toBe(true); });\n'
                self.repo.write(path, "test.failing" + tail)
                self.repo.base = self.repo.commit()
                self.repo.write(path, skipped + tail)
                self.repo.commit()
                rc, result = self.cli("none")
                self.assertEqual(1, rc, result)
                self.assertIn("skip_added", {loss["kind"] for loss in result["losses"]})

    def test_parameterized_skip_examples_are_not_executable_markers(self):
        path = "web/examples.test.js"
        active = 'test.each([1])("case", value => { expect(value).toBe(1); });\n'
        self.repo.write(path, active)
        self.repo.base = self.repo.commit()
        examples = ('test.skip.each`value\n${1}`("case", () => {});',
                    'describe.skip.each([1])("suite", () => {});',
                    'xit.each([1])("case", () => {});')
        self.repo.write(path, active + "/*\n" + "\n".join(examples) + "\n*/\n" +
                        "const examples = " + json.dumps("\n".join(examples)) + ";\n")
        self.repo.commit()
        rc, result = self.cli("none")
        self.assertEqual((0, []), (rc, result["losses"]), result)

    def test_skip_chain_whitespace_comments_and_reformatting(self):
        path = "web/format.test.js"
        before = 'test.each([1])("case", value => { expect(value).toBe(1); });\n'
        after = before.replace("test.each", "test /* note */ . skip . each")
        self.repo.write(path, before)
        self.repo.base = self.repo.commit()
        self.repo.write(path, after)
        self.repo.commit()
        rc, result = self.cli("none")
        self.assertEqual(1, rc, result)
        self.assertIn("skip_added", {loss["kind"] for loss in result["losses"]})
        self.repo.base = self.repo.git("rev-parse", "HEAD").strip()
        self.repo.write(path, after.replace("test /* note */ . skip . each", "test.skip.each"))
        self.repo.commit()
        rc, result = self.cli("none")
        self.assertEqual((0, []), (rc, result["losses"]), result)

    def test_formatted_placeholder_reasons_fail_real_cli(self):
        path = "pytests/test_reason.py"
        self.repo.write(path, "def test_case():\n    assert ready\n    assert ready\n")
        self.repo.base = self.repo.commit()
        self.repo.write(path, "def test_case():\n    assert ready\n")
        self.repo.commit()
        for reason in ("none", "`none`", "``None``", "**`none`**", "_none_", "__TODO__",
                       "~~n/a~~", "*`TBD`*.", "`<reason>`", "` `", "** **", "`- [ ]`"):
            with self.subTest(reason=reason):
                rc, result = self.cli('- `' + path + '`: ' + reason)
                self.assertEqual(1, rc, result)
                self.assertEqual([path], result["undeclared"])

    def test_substantive_formatted_reasons_remain_valid(self):
        path = "pytests/test_reason.py"
        self.repo.write(path, "def test_case():\n    assert ready\n    assert ready\n")
        self.repo.base = self.repo.commit()
        self.repo.write(path, "def test_case():\n    assert ready\n")
        self.repo.commit()
        for reason in ("Removed duplicate `assert ready` while retaining equivalent coverage.",
                       "`Removed redundant duplicate; original case remains`",
                       "**Replaced the `none` case with boundary coverage**",
                       "~~Obsolete duplicate removed after consolidation~~"):
            with self.subTest(reason=reason):
                rc, result = self.cli('- `' + path + '`: ' + reason)
                self.assertEqual(0, rc, result)
                self.assertTrue(result["losses"])
                self.assertEqual([], result["undeclared"])


class SectionHeadingCompatibilityTests(unittest.TestCase):
    def test_exact_heading_levels_spacing_case_and_closing_hashes(self):
        for level in (2, 3):
            for indent in range(4):
                for gap in (" ", "\t", " \t ", "\u00a0", "\u2003", "\x1f"):
                    for title in (ti.SECTION, ti.SECTION.upper()):
                        for suffix in ("", "  ", "\t", "#", "####", " ##\t", "\u00a0###\u2003"):
                            heading = " " * indent + "#" * level + gap + title + suffix
                            with self.subTest(heading=heading):
                                self.assertEqual("reason", ti.section_text(heading + "\nreason\n"))

    def test_nonexact_headings_do_not_open_section(self):
        for heading in (
                "# " + ti.SECTION, "#### " + ti.SECTION, "##### " + ti.SECTION,
                "###### " + ti.SECTION, "####### " + ti.SECTION,
                "    ## " + ti.SECTION, "\t## " + ti.SECTION, "##" + ti.SECTION,
                "##\u200b" + ti.SECTION, "## prefix " + ti.SECTION,
                "## " + ti.SECTION + " extra", "## " + ti.SECTION + " # #",
                "## " + ti.SECTION + "\x00", "## " + ti.SECTION.replace(" or ", "  or "),
                "## " + ti.SECTION.replace(" or ", "\tor ")):
            with self.subTest(heading=heading):
                self.assertIsNone(ti.section_text(heading + "\nreason\n"))

    def test_all_heading_levels_end_the_section(self):
        for level in range(1, 7):
            for title in ("Other", ti.SECTION + " extra", "#", " # # "):
                boundary = "#" * level + " " + title
                with self.subTest(boundary=boundary):
                    self.assertEqual("before", ti.section_text(
                        "## " + ti.SECTION + "\nbefore\n" + boundary + "\nafter\n"))

    def test_titleless_and_nonheading_lines_keep_original_boundary_rules(self):
        for line in ("##", "## ", "##\t", "##\u00a0", "####### title", "##title",
                     "    ## title", "\t## title", "", "ordinary body"):
            with self.subTest(line=line):
                self.assertEqual("before\n" + line + "\nafter", ti.section_text(
                    "## " + ti.SECTION + "\nbefore\n" + line + "\nafter\n"))
        # Two whitespace characters suffice: the old matcher used the second
        # as its required one-character title, even though it is visually empty.
        for line in ("##  ", "##\t\t", "## \u00a0", "## \t "):
            with self.subTest(line=line):
                self.assertEqual("before", ti.section_text(
                    "## " + ti.SECTION + "\nbefore\n" + line + "\nafter\n"))

    def test_normalized_duplicate_headings_are_rejected(self):
        first = "## " + ti.SECTION + "\nfirst\n"
        for second in ("###\t" + ti.SECTION.upper() + "###",
                       "   ## " + ti.SECTION + " ##\t"):
            with self.subTest(second=second):
                self.assertIsNone(ti.section_text(first + "# Other\nbody\n" + second + "\nsecond"))
        self.assertEqual("first", ti.section_text(first + "## " + ti.SECTION + " extra\nsecond"))

    def test_fences_comments_and_line_endings_keep_section_boundaries(self):
        heading = "## " + ti.SECTION
        body = (heading + "\nbefore\n   ````md\n" + heading + "\n```\n~~~\n"
                "# Other\n   `````\nafter\n<!--" + heading + "-->\n# End\nignored")
        self.assertEqual("before\nafter\n", ti.section_text(body))
        self.assertEqual("before", ti.section_text(heading + "\nbefore\n~~~\n" + heading + "\nignored"))
        self.assertIsNone(ti.section_text("<!--\n" + heading + "\nreason"))
        self.assertEqual("reason", ti.section_text(
            "## removed or <!-- hidden -->weakened tests or policy\r\nreason\r\n"))
        for newline in ("\r", "\r\n", "\v", "\f", "\x85", "\u2028", "\u2029"):
            with self.subTest(newline=newline):
                self.assertEqual("reason", ti.section_text(heading + newline + "reason" + newline))

    def test_long_valid_headings_and_unrelated_body_are_not_capped(self):
        padding = " " * 16384
        for heading in ("## " + ti.SECTION + padding,
                        "###" + padding + ti.SECTION.upper() + padding + "#" * 16384 + "\t"):
            with self.subTest(level=heading[:3]):
                self.assertEqual("none", ti.section_text(heading + "\nnone\n"))
        content = "notes: " + padding + "x\n" + "body\n" * 4096
        self.assertEqual(content.rstrip("\n"), ti.section_text(
            "unrelated " + padding + "x\n## " + ti.SECTION + "\n" + content))


class SectionHeadingEvaluationTests(unittest.TestCase):
    setUp = TestIntegrityTests.setUp

    def test_heading_boundaries_preserve_real_loss_rationale_requirements(self):
        path = "Tests/ParserTests.swift"
        self.repo.edit(path, '        XCTAssertThrowsError(try parse("../etc"))\n', "")
        head = self.repo.commit()
        entry = path + ": redundant assertion replaced by focused traversal cases"
        heading = "## " + ti.SECTION
        for body, verdict in (
                (heading + "\n" + entry, "pass"),
                ("   ###\t" + ti.SECTION.upper() + "###\n" + entry, "pass"),
                (heading + "\nnone\n", "fail"),
                (heading + "\n" + path + ": `none`", "fail"),
                (heading + "\n" + path + ".bak: redundant case", "fail"),
                (heading + "\n", "fail"),
                (heading + " " * 64 + "x\n" + entry, "fail"),
                (heading + "\n" + entry + "\n### " + ti.SECTION + "\n" + entry, "fail"),
                ("```md\n" + heading + "\n" + entry + "\n```", "fail"),
                (heading + "\n# Other\n" + entry, "fail"),
                (heading + "\n##  \n" + entry, "fail"),
                (heading + "\n## \n" + entry, "pass")):
            with self.subTest(body=body):
                result = ti.evaluate(str(self.repo.root), base=self.repo.base, head=head, body=body)
                self.assertEqual(verdict, result["verdict"], result)
                self.assertEqual([path], [loss["file"] for loss in result["losses"]])
                self.assertEqual(["assertion_removed"], [loss["kind"] for loss in result["losses"]])
                self.assertEqual([] if verdict == "pass" else [path], result["undeclared"])
                self.assertEqual(verdict == "fail", bool(result["problems"]))
                self.assertEqual((True, "supplied"), (result["body_checked"], result["body_status"]))


class SectionHeadingTests(unittest.TestCase):
    def test_long_malformed_heading_completes(self):
        # The old ambiguous whitespace suffix takes seconds even at a fraction
        # of this size. Bound only our child, with ample room for normal startup.
        probe = (
            "import json, runpy, sys; "
            "section_text = runpy.run_path(sys.argv[1])['section_text']; "
            "body = '## Removed or weakened tests or policy' + ' ' * 16384 + 'x\\nnone\\n'; "
            "print(json.dumps(section_text(body)))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", probe, str(SCRIPT)],
            capture_output=True, text=True, timeout=5, check=True)
        self.assertIsNone(json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
