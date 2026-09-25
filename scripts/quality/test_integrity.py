#!/usr/bin/env python3
"""Test-integrity evidence: report losses and require an accurate PR explanation.

Compares the PR head with merge-base(base, head); stdlib only, fail-closed.

Losses (no netting: adding unrelated tests never offsets a loss):
  assertion_removed  an assertion statement (a multiline call is one statement,
                     joined by paren depth) present at the base of a changed
                     test file and absent, whitespace-normalized, from every
                     changed test file at the head
  test_removed       a test name present at the base and absent at the head
  skip_added         a new skip/disable marker in a test file
  test_file_deleted  a deleted test file (its tests and assertions are losses too)

Explanation (when a PR body is supplied):
  * the PR body section "Removed or weakened tests or policy"
    is not "none" and names every affected file (G6: cross-checked against the diff);
    conversely a body that says "none" never passes with a loss.
  * test changes need ordinary AI review, not an Owner approval or ledger.
    CI/gate/policy changes retain their separate protected-path review.

Output: JSON {"verdict", "losses", "undeclared", "problems"}; exit 0 pass,
1 fail, 2 usage. Heuristic by design: it recognizes common XCTest, Swift
Testing, unittest/pytest, Go and Jest/Vitest shapes; unknown frameworks are
still covered by `test_file_deleted` and the protocol rule.
Lexical filtering handles comments and quoted/raw/multiline literals, not a
language grammar. Interpolated expressions, regex literals, conditional
compilation, helper indirection and test reachability need independent review;
this check does not prove that a retained assertion executes or stays strong.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
SECTION = "removed or weakened tests or policy"
TEST_PATH = re.compile(
    r"(^|/)(Tests?|tests?|__tests__|spec|specs)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|"
    r"Tests?\.swift$|\.(test|spec)\.[cm]?[jt]sx?$|Test\.(kt|java)$")
ASSERTION = re.compile(
    r"#expect\b|#require\b|\bXCTAssert\w*\s*\(|\bXCTFail\s*\(|\bXCTUnwrap\s*\(|"
    r"\bself\.assert\w+\s*\(|^\s*assert\b|\bpytest\.raises\s*\(|\bexpect\s*\(|\bassert\w*\s*\(|"
    r"\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\brequire\.\w+\s*\(")
TEST_NAME = [
    re.compile(r"\bfunc\s+(test\w*)\s*\("),                       # XCTest
    re.compile(r"@Test\b[^\n]*?\bfunc\s+(\w+)\s*\("),              # Swift Testing (same line)
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),          # unittest / pytest
    re.compile(r"\bfunc\s+(Test\w+)\s*\(\s*t\s+\*testing\.T"),     # Go
    re.compile(r"""\b(?:it|test)\s*\(\s*(["'`])(.+?)\1"""),        # Jest / Vitest / Mocha
]
SKIP = re.compile(
    r"\.disabled\b|\bXCTSkip\w*\s*\(|withKnownIssue\s*\(|@unittest\.skip|\bpytest\.mark\.(skip|xfail)|"
    r"\bself\.skipTest\s*\(|\b(?:it|test|describe)\.(skip|todo)\s*\(|\bx(?:it|describe|test)\s*\(|"
    r"\bt\.Skip(?:f|Now)?\s*\(|@Disabled\b|@Ignore\b|\.enabled\s*\(\s*if\s*:")


class IntegrityError(Exception):
    """Repository state cannot be read; the check fails closed."""


def _git(root: str, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False, timeout=120)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise IntegrityError(f"git {args[0]} failed: {detail[-1] if detail else result.returncode}")
    return result.stdout.decode("utf-8", "replace")


def _norm(line: str) -> str:
    return " ".join(line.split())


SWIFT_TEST_ATTR = re.compile(r"@Test\b")
SWIFT_FUNC = re.compile(r"\bfunc\s+(\w+)\s*\(")
LITERAL_START = re.compile(r'(#+)?("""|\'\'\'|["\'`])')


def _names(text: str, path: str = "") -> collections.Counter[str]:
    """Test names; a multiline `@Test(` / traits / `func name(` counts once."""
    names: collections.Counter[str] = collections.Counter()
    pending = False
    source, code = _source_views(text, path)
    for line, visible in zip(source.splitlines(), code.splitlines()):
        if pending:
            func = SWIFT_FUNC.search(visible)
            if func:
                names[func.group(1)] += 1
                pending = False
                continue
        for pattern in TEST_NAME:
            # Jest names are literal data, but the test/it call must be code.
            matches = pattern.finditer(line if pattern is TEST_NAME[-1] else visible)
            match = next((m for m in matches if visible[m.start():m.end()].strip()), None)
            if match:
                names[match.group(match.lastindex)] += 1
                pending = False
                break
        else:
            if SWIFT_TEST_ATTR.search(visible):
                pending = True
    return names


def _show(root: str, rev: str, path: str) -> str:
    # Callers establish presence before reading. A missing or unreadable blob
    # must not turn into empty source, which could hide assertions at the base.
    return _git(root, "show", f"{rev}:{path}")


TEST_DIR = re.compile(r"(^|/)(Tests?|tests?|__tests__|spec|specs)/")


def is_test_path(path: str) -> bool:
    """Test sources; a `test_*.py` tool under scripts/ outside a test directory is not a test."""
    if not TEST_PATH.search(path):
        return False
    return not (path.startswith("scripts/") and not TEST_DIR.search(path))


def _tokens(text: str, path: str = ""):
    """Lexical regions only; never interpret interpolation or control flow.

    Keep complete literal values and newlines. Swift block comments nest;
    Python uses # comments (not Swift's #expect or other languages' //).
    """
    index = 0
    plain = 0
    python = path.endswith(".py")
    while index < len(text):
        start = index
        kind = ""
        if text.startswith("#" if python else "//", index):
            kind = "comment"
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
        elif not python and text.startswith("/*", index):
            kind = "comment"
            index += 2
            depth = 1
            while index < len(text) and depth:
                if text.startswith("*/", index):
                    depth -= 1
                    index += 2
                elif (not path or path.endswith(".swift")) and text.startswith("/*", index):
                    depth += 1
                    index += 2
                else:
                    index += 1
        else:
            literal = LITERAL_START.match(text, index)
            if literal:
                kind = "literal"
                hashes = literal.group(1) or ""
                delimiter = literal.group(2) + hashes
                index += len(literal.group(0))
                while index < len(text):
                    if text.startswith("\\" + hashes, index):
                        index += len(hashes) + 2
                    elif text.startswith(delimiter, index):
                        index += len(delimiter)
                        break
                    else:
                        index += 1
        if kind:
            yield "code", text[plain:start]
            yield kind, text[start:index]
            plain = index
        else:
            index += 1
    yield "code", text[plain:]


def _source_views(text: str, path: str = "") -> tuple[str, str]:
    """Same offsets/newlines: comment-free source and executable-token view."""
    source, code = [], []
    for kind, token in _tokens(text, path):
        masked = re.sub(r"[^\n\r]", " ", token)
        source.append(masked if kind == "comment" else token)
        code.append(token if kind == "code" else masked)
    return "".join(source), "".join(code)


def _statement(text: str, path: str = "") -> str:
    """Normalize formatting outside literals, never assertion data inside them."""
    literals: list[str] = []
    parts = []
    for kind, token in _tokens(text, path):
        if kind == "literal":
            literals.append(token)
            parts.append(f"\0{len(literals) - 1}\0")
        else:
            parts.append(" " if kind == "comment" else token)
    text = "".join(parts)
    text = _norm(text)
    text = re.sub(r"\s*([()\[\]{},])\s*", r"\1", text)
    text = re.sub(r",([)\]}])", r"\1", text)
    return re.sub(r"\0(\d+)\0", lambda match: literals[int(match.group(1))], text)


def assertions(text: str, path: str = "") -> list[str]:
    """Normalized assertion statements; a call spanning lines (by paren depth) is one statement.

    Changing or deleting any line of a multiline `#expect(` / `XCTAssertEqual(` changes
    the whole statement, so it cannot slip through a line-based diff.
    """
    statements: list[str] = []
    source, code = _source_views(text, path)
    lines = source.splitlines()
    visible = code.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = ASSERTION.search(visible[index])
        if not match:
            index += 1
            continue
        parts = [line]
        tail = visible[index][match.start():]
        depth = tail.count("(") - tail.count(")")
        while depth > 0 and index + 1 < len(lines) and len(parts) < 200:
            index += 1
            parts.append(lines[index])
            tail = visible[index]
            depth += tail.count("(") - tail.count(")")
        statements.append(_statement("\n".join(parts), path))
        index += 1
    return statements


def losses(root: str, base: str, head: str) -> list[dict[str, str]]:
    """Every loss in merge-base(base, head)..head, each with its file."""
    merge_base = _git(root, "merge-base", base, head).strip()
    if not SHA.match(merge_base):
        raise IntegrityError(f"merge-base returned {merge_base!r}")
    status = _git(root, "diff", "--name-status", "--no-renames", "-z", merge_base, head, "--").split("\0")
    changed = {status[i + 1]: status[i] for i in range(0, len(status) - 1, 2) if status[i]}
    tests = {path: kind for path, kind in changed.items() if is_test_path(path)}
    found: list[dict[str, str]] = []
    base_texts = {path: _show(root, merge_base, path) for path, kind in tests.items() if kind != "A"}
    head_texts = {path: _show(root, head, path) for path, kind in tests.items() if kind != "D"}
    head_code = {path: _source_views(text, path)[1].splitlines() for path, text in head_texts.items()}
    for path in sorted(head_texts):
        # Use the NUL-delimited inventory as identity, never a quoted diff
        # header. Literal pathspecs also prevent filename glob characters from
        # selecting another file's hunks.
        diff = _git(root, "--literal-pathspecs", "diff", "--unified=0", "--no-color", "--no-renames",
                    merge_base, head, "--", path)
        head_line = None
        for line in diff.splitlines():
            if line.startswith("@@ "):
                hunk = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if not hunk:
                    raise IntegrityError("cannot parse test diff hunk")
                head_line = int(hunk.group(1)) - 1
            elif head_line is not None and line.startswith(("+", " ")):
                # Inspect the whole blob's lexical context, not an isolated
                # added line inside a multiline comment or literal.
                if not 0 <= head_line < len(head_code[path]):
                    raise IntegrityError("cannot locate test diff line")
                if line.startswith("+") and SKIP.search(head_code[path][head_line]):
                    found.append({"kind": "skip_added", "file": path, "detail": line[1:].strip()[:160]})
                head_line += 1
    # Assertion statements: multiset across all changed test files (moves pass, no netting).
    head_statements: collections.Counter[str] = collections.Counter()
    for path, text in head_texts.items():
        head_statements.update(assertions(text, path))
    for path in sorted(base_texts):
        for statement in assertions(base_texts[path], path):
            if head_statements[statement] > 0:
                head_statements[statement] -= 1
            else:
                found.append({"kind": "assertion_removed", "file": path, "detail": statement[:160]})
    base_names = {path: _names(text, path) for path, text in base_texts.items()}
    head_names: collections.Counter[str] = collections.Counter()
    for path, text in head_texts.items():
        head_names += _names(text, path)
    for path, kind in sorted(tests.items()):
        if kind == "D":
            found.append({"kind": "test_file_deleted", "file": path, "detail": "test file deleted"})
    for path, names in sorted(base_names.items()):  # multiset: a move between files passes
        for name in sorted(names):
            keep = min(names[name], head_names[name])
            head_names[name] -= keep
            for _ in range(names[name] - keep):
                found.append({"kind": "test_removed", "file": path, "detail": name})
    return found


def section_text(body: str) -> str | None:
    text = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.DOTALL)
    parts = re.split(r"(?m)^#{2,3}\s+", text)
    for part in parts[1:]:
        heading, _, rest = part.partition("\n")
        if heading.strip().lower().startswith(SECTION):
            return rest
    return None


def says_none(text: str) -> bool:
    stripped = [line.strip().strip("-*").strip() for line in text.splitlines() if line.strip()]
    return not stripped or all(line.rstrip(".").lower() in {"none", "n/a", "no", "nothing"} for line in stripped)


def evaluate(root: str, *, base: str, head: str, body: str | None) -> dict[str, Any]:
    problems: list[str] = []
    found: list[dict[str, str]] = []
    undeclared: list[str] = []
    try:
        if not SHA.match(base or "") or not SHA.match(head or ""):
            raise IntegrityError("base/head must be full 40-char SHAs")
        found = losses(root, base, head)
        files = sorted({loss["file"] for loss in found})
        if files and body is not None:
            section = section_text(body)
            if section is None or says_none(section):
                undeclared = files
                problems.append("PR body section 'Removed or weakened tests or policy' says none, "
                                f"but the diff removes or weakens tests in: {', '.join(files)}")
            else:
                undeclared = [path for path in files if path not in section]
                if undeclared:
                    problems.append("PR body section 'Removed or weakened tests or policy' does not "
                                    f"name: {', '.join(undeclared)}")
    except IntegrityError as error:
        problems.append(f"test-integrity cannot read the diff (fail-closed): {error}")
    return {"verdict": "fail" if problems else "pass", "losses": found,
            "undeclared": undeclared, "problems": problems, "body_checked": body is not None}


def _pr_body(args: argparse.Namespace) -> str | None:
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as handle:
            return handle.read()
    event = os.environ.get("GITHUB_EVENT_PATH")
    if args.event_body and event and os.path.isfile(event):
        with open(event, encoding="utf-8") as handle:
            pull_request = json.load(handle).get("pull_request")
        if pull_request is not None:
            return pull_request.get("body") or ""
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test-integrity")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--body-file", help="PR body to cross-check (G6)")
    parser.add_argument("--event-body", action="store_true", help="read the PR body from $GITHUB_EVENT_PATH")
    args = parser.parse_args(argv)
    root = os.getcwd()
    try:
        base = _git(root, "rev-parse", "--verify", args.base + "^{commit}").strip()
        head = _git(root, "rev-parse", "--verify", args.head + "^{commit}").strip()
    except IntegrityError as error:
        base, head = "", ""
        print(f"::error::{error}", file=sys.stderr)
    result = evaluate(root, base=base, head=head, body=_pr_body(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for loss in result["losses"]:
        print(f"[test-integrity] {loss['kind']}: {loss['file']}: {loss['detail']}", file=sys.stderr)
    for problem in result["problems"]:
        print(f"::error::{problem}", file=sys.stderr)
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
