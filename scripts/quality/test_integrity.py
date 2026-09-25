#!/usr/bin/env python3
"""Test-integrity check: removed or weakened tests must be declared and Owner-gated.

Compares the PR head with merge-base(base, head); stdlib only, fail-closed.

Losses (no netting: adding unrelated tests never offsets a loss):
  assertion_removed  an assertion statement (a multiline call is one statement,
                     joined by paren depth) present at the base of a changed
                     test file and absent, whitespace-normalized, from every
                     changed test file at the head
  test_removed       a test name present at the base and absent at the head
  skip_added         a new skip/disable marker in a test file
  test_file_deleted  a deleted test file (its tests and assertions are losses too)

Declaration (all required when there is any loss):
  * the ledger `.github/test-weakening.md` gains, in this diff, a line
    `- <test file path>: <reason> (approved: @<owner>)` for every affected file.
    The ledger lives under /.github/, which the repository contract requires
    CODEOWNERS to cover, so every declared loss needs Owner code-owner review
    (the check fails if CODEOWNERS at head does not cover it; the approver text
    is informational, the ruleset's code-owner review is the approval);
  * for pull requests, the PR body section "Removed or weakened tests or policy"
    is not "none" and names every affected file (G6: cross-checked against the diff);
    conversely a body that says "none" never passes with a loss.

Output: JSON {"verdict", "losses", "undeclared", "problems"}; exit 0 pass,
1 fail, 2 usage. Heuristic by design: it recognizes common XCTest, Swift
Testing, unittest/pytest, Go and Jest/Vitest shapes; unknown frameworks are
still covered by `test_file_deleted` and the protocol rule.
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
LEDGER = ".github/test-weakening.md"
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


def _names(text: str) -> collections.Counter[str]:
    """Test names; a multiline `@Test(` / traits / `func name(` counts once."""
    names: collections.Counter[str] = collections.Counter()
    pending = False
    for line in text.splitlines():
        if pending:
            func = SWIFT_FUNC.search(line)
            if func:
                names[func.group(1)] += 1
                pending = False
                continue
        for pattern in TEST_NAME:
            match = pattern.search(line)
            if match:
                names[match.group(match.lastindex)] += 1
                pending = False
                break
        else:
            if SWIFT_TEST_ATTR.search(line):
                pending = True
    return names


def _show(root: str, rev: str, path: str) -> str:
    # Callers establish presence before reading. A missing or unreadable blob
    # must not turn into empty source, which could hide assertions at the base.
    return _git(root, "show", f"{rev}:{path}")


TEST_DIR = re.compile(r"(^|/)(Tests?|tests?|__tests__|spec|specs)/")


def is_test_path(path: str) -> bool:
    """Test sources; a `test_*.py` tool under scripts/ outside a test directory is not a test."""
    if path == LEDGER or not TEST_PATH.search(path):
        return False
    return not (path.startswith("scripts/") and not TEST_DIR.search(path))


def _strip_strings(line: str) -> str:
    """Line with string/char/template literals removed for lexical checks."""
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`', '""', line)


def _skip_marker(path: str, line: str) -> bool:
    """Do not mistake a documented skip spelling for executable skip code."""
    code = _strip_strings(line)
    if path.endswith(".py"):
        code = code.split("#", 1)[0]
    else:
        code = code.split("//", 1)[0]
        code = re.sub(r"/\*.*?\*/", "", code)
    return SKIP.search(code) is not None


def _statement(text: str) -> str:
    """Normalize formatting outside literals, never assertion data inside them."""
    literals: list[str] = []

    def protect(match: re.Match[str]) -> str:
        literals.append(match.group(0))
        return f"\0{len(literals) - 1}\0"

    text = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',
                  protect, text, flags=re.DOTALL)
    text = _norm(text)
    text = re.sub(r"\s*([()\[\]{},])\s*", r"\1", text)
    text = re.sub(r",([)\]}])", r"\1", text)
    return re.sub(r"\0(\d+)\0", lambda match: literals[int(match.group(1))], text)


def assertions(text: str) -> list[str]:
    """Normalized assertion statements; a call spanning lines (by paren depth) is one statement.

    Changing or deleting any line of a multiline `#expect(` / `XCTAssertEqual(` changes
    the whole statement, so it cannot slip through a line-based diff.
    """
    statements: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = ASSERTION.search(line)
        if not match:
            index += 1
            continue
        parts = [line]
        tail = _strip_strings(line[match.start():])
        depth = tail.count("(") - tail.count(")")
        while depth > 0 and index + 1 < len(lines) and len(parts) < 200:
            index += 1
            parts.append(lines[index])
            code = _strip_strings(lines[index])
            depth += code.count("(") - code.count(")")
        statements.append(_statement(" ".join(parts)))
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
    diff = _git(root, "diff", "--unified=0", "--no-color", "--no-renames", merge_base, head, "--",
                *sorted(tests)) if tests else ""
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current and line.startswith("+") and _skip_marker(current, line[1:]):
            found.append({"kind": "skip_added", "file": current, "detail": line[1:].strip()[:160]})
    base_texts = {path: _show(root, merge_base, path) for path, kind in tests.items() if kind != "A"}
    head_texts = {path: _show(root, head, path) for path, kind in tests.items() if kind != "D"}
    # Assertion statements: multiset across all changed test files (moves pass, no netting).
    head_statements: collections.Counter[str] = collections.Counter()
    for text in head_texts.values():
        head_statements.update(assertions(text))
    for path in sorted(base_texts):
        for statement in assertions(base_texts[path]):
            if head_statements[statement] > 0:
                head_statements[statement] -= 1
            else:
                found.append({"kind": "assertion_removed", "file": path, "detail": statement[:160]})
    base_names = {path: _names(text) for path, text in base_texts.items()}
    head_names: collections.Counter[str] = collections.Counter()
    for text in head_texts.values():
        head_names += _names(text)
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


def ledger_entries(root: str, base: str, head: str) -> dict[str, str]:
    """Test file -> ledger line, for ledger lines ADDED in this diff with an approver."""
    merge_base = _git(root, "merge-base", base, head).strip()
    diff = _git(root, "diff", "--unified=0", "--no-color", merge_base, head, "--", LEDGER)
    entries = {}
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        match = re.match(r"^\+\s*[-*]\s*`?([^`:\s][^`:]*?)`?\s*:\s*(\S.*?)\s*\(approved:\s*@[\w.-]+\)\s*$", line)
        if match:
            entries[match.group(1).strip()] = line[1:].strip()
    return entries


CODEOWNERS_FILES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def _codeowners_match(pattern: str, path: str) -> bool:
    """CODEOWNERS (gitignore-style) pattern match for one repository path."""
    anchored = pattern.startswith("/") or "/" in pattern.rstrip("/")
    body = pattern.strip("/")
    directory = pattern.endswith("/")
    regex = ""
    index = 0
    while index < len(body):
        if body.startswith("**", index):
            regex += ".*"
            index += 2
        elif body[index] == "*":
            regex += "[^/]*"
            index += 1
        elif body[index] == "?":
            regex += "[^/]"
            index += 1
        else:
            regex += re.escape(body[index])
            index += 1
    regex = ("^" if anchored else "^(?:.*/)?") + regex + ("/.*$" if directory else "(?:/.*)?$")
    return re.match(regex, path) is not None


def ledger_is_owner_gated(root: str, head: str) -> bool:
    """True when the LAST matching CODEOWNERS rule for the ledger at head names an owner.

    GitHub uses the first CODEOWNERS file found and last-match-wins; a later
    ownerless rule on the ledger removes the Owner gate, so this fails closed.
    """
    for path in CODEOWNERS_FILES:
        if not _git(root, "ls-tree", "--name-only", head, "--", path).strip():
            continue
        # The first existing file wins even when it is empty. Its existence,
        # not its content, prevents fallback to a lower-priority CODEOWNERS.
        text = _show(root, head, path)
        owners = None
        for line in text.splitlines():
            parts = line.split("#", 1)[0].split()
            if parts and _codeowners_match(parts[0], LEDGER):
                owners = parts[1:]
        return bool(owners)
    return False


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
        if files:
            if not ledger_is_owner_gated(root, head):
                problems.append(f"CODEOWNERS does not cover {LEDGER} (e.g. `/.github/ @owner`); "
                                "a declared loss would not need Owner approval")
            entries = ledger_entries(root, base, head)
            undeclared = [path for path in files if path not in entries]
            for path in undeclared:
                problems.append(f"{path}: removed or weakened tests are not declared in {LEDGER} "
                                f"(add `- {path}: <reason> (approved: @<owner>)`; CODEOWNERS makes the Owner approve)")
            if body is not None:
                section = section_text(body)
                if section is None or says_none(section):
                    problems.append("PR body section 'Removed or weakened tests or policy' says none, "
                                    f"but the diff removes or weakens tests in: {', '.join(files)}")
                else:
                    missing = [path for path in files if path not in section]
                    if missing:
                        problems.append("PR body section 'Removed or weakened tests or policy' does not "
                                        f"name: {', '.join(missing)}")
    except IntegrityError as error:
        problems.append(f"test-integrity cannot read the diff (fail-closed): {error}")
    return {"verdict": "fail" if problems else "pass", "losses": found,
            "undeclared": undeclared, "problems": problems}


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
