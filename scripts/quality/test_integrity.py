#!/usr/bin/env python3
"""Test-integrity evidence: report losses and require an accurate PR explanation.

Compares the PR head with merge-base(base, head); stdlib only, fail-closed.

Losses (no netting: adding unrelated tests never offsets a loss):
  assertion_removed  a lexical assertion statement (balanced delimiters) present at the base of a changed
                     test file and absent, whitespace-normalized, from every
                     changed test file at the head
  test_removed       a test name present at the base and absent at the head
  skip_added         a new lexical skip/disable occurrence in a test file
  test_file_deleted  a deleted test file (its tests and assertions are losses too)

Explanation (when a PR body is supplied):
  * the PR body section "Removed or weakened tests or policy"
    declares each affected file with a non-placeholder rationale;
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
import urllib.request
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
SECTION = "removed or weakened tests or policy"
TEST_PATH = re.compile(
    r"(^|/)(Tests?|tests?|__tests__|spec|specs)/|(^|/)test_[^/]+\.py$|_test\.(py|go)$|"
    r"Tests?\.swift$|\.(test|spec)\.[cm]?[jt]sx?$|Test\.(kt|java)$")
ASSERTION = re.compile(
    r"#expect\b|#require\b|\bXCTAssert\w*\s*\(|\bXCTFail\s*\(|\bXCTUnwrap\s*\(|"
    r"\bself\.assert\w+\s*\(|\bassert\b(?!\s*\()|\bpytest\.raises\s*\(|\bexpect\s*\(|\bassert\w*\s*\(|"
    r"\bt\.(Error|Errorf|Fatal|Fatalf|Fail|FailNow)\s*\(|\brequire\.\w+\s*\(")
TEST_NAME = [
    re.compile(r"\bfunc\s+(test\w*)\s*\("),                       # XCTest
    re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\("),          # unittest / pytest
    re.compile(r"\bfunc\s+(Test\w+)\s*\(\s*t\s+\*testing\.T"),     # Go
]
SKIP = re.compile(
    r"\.disabled\b|\bXCTSkip\w*\s*\(|withKnownIssue\s*\(|@unittest\.skip|\bpytest\.mark\.(skip|xfail)|"
    r"\bpytest\.skip\s*\(|\bpytest\.xfail\s*\(|\bself\.skipTest\s*\(|\b(?:it|test|describe)\.(skip|todo)\s*\(|\bx(?:it|describe|test)\s*\(|"
    r"\bt\.Skip(?:f|Now)?\s*\(|@Disabled\b|@Ignore\b|\.enabled\s*\(\s*if\s*:")


class IntegrityError(Exception):
    """Repository state cannot be read; the check fails closed."""


def _git(root: str, *args: str) -> str:
    # Never invoke caller-configured external diff/textconv programs.
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                check=False, timeout=120)
        if result.returncode != 0:
            raise IntegrityError(f"git {args[0]} failed ({result.returncode})")
        return result.stdout.decode("utf-8", "strict")
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise IntegrityError("Git data unavailable or not UTF-8") from error


def _norm(line: str) -> str:
    return " ".join(line.split())


LITERAL_START = re.compile(r'(#+)?("""|\'\'\'|["\'`])')


def _names(text: str, path: str = "") -> collections.Counter[str]:
    """Recognized names, including multiple calls on one line; literals are data only."""
    source, code = _source_views(text, path)
    names: collections.Counter[str] = collections.Counter()
    for pattern in TEST_NAME:
        for match in re.finditer(pattern.pattern, code, re.MULTILINE):
            names[match.group(1)] += 1
    # Swift attributes may span lines. Do not cross another declaration/body.
    for match in re.finditer(r"@Test\b[^{};]*?\bfunc\s+(\w+)\s*\(", code):
        if not match.group(1).startswith("test"):
            names[match.group(1)] += 1
    for match in re.finditer(r"\b(?:it|test)\s*\(", code):
        tail = source[match.end():].lstrip()
        literal = LITERAL_START.match(tail)
        if literal:
            # Tokenization, not a quote regex, preserves escaped/multiline names.
            token = next(token for kind, token in _tokens(tail, path) if kind == "literal")
            opening = literal.group(0)
            closing = literal.group(2) + (literal.group(1) or "")
            names[token[len(opening):-len(closing)]] += 1
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
                    if text.startswith("\\" + hashes, index) and not (path.endswith(".go") and delimiter == "`"):
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
            parts.append(" " if kind == "comment" else re.sub(r"\\\r?\n", " ", token))
    text = "".join(parts)
    text = _norm(text)
    text = re.sub(r"\s*([()\[\]{},.])\s*", r"\1", text)
    text = re.sub(r",([)\]}])", r"\1", text)
    return re.sub(r"\0(\d+)\0", lambda match: literals[int(match.group(1))], text)


def _statements(text: str, pattern: re.Pattern, path: str) -> list[str]:
    """Extract lexical statements using masked delimiters, retaining literal values."""
    source, code = _source_views(text, path)
    statements = []
    for match in pattern.finditer(code):
        start = match.start()
        depth = 0
        end = start
        for end in range(start, len(code)):
            char = code[end]
            if depth == 0 and char in ";\n\r}":
                # Fluent assertion chains can continue after a newline.
                if char in "\n\r" and code[end + 1:].lstrip().startswith("."):
                    continue
                # Explicit Python line continuations are formatting.
                if char in "\n\r" and code[start:end].rstrip().endswith("\\"):
                    continue
                break
            if char in "([{":
                depth += 1
            elif char in ")]}":
                if depth == 0:
                    break
                depth -= 1
        else:
            end = len(code)
        if depth:
            raise IntegrityError("unbalanced recognized test statement")
        statement = source[start:end]
        # A same-line next statement must not become part of this assertion.
        statements.append(_statement(statement, path))
    return statements


def assertions(text: str, path: str = "") -> list[str]:
    return _statements(text, ASSERTION, path)


def _inventory(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    fields = raw.split("\0")
    if fields.pop() != "" or len(fields) % 2:
        raise IntegrityError("malformed NUL-delimited Git inventory")
    changed = {}
    for kind, path in zip(fields[::2], fields[1::2]):
        if kind not in {"A", "M", "D", "T"} or not path or path in changed:
            raise IntegrityError("invalid Git change record")
        changed[path] = kind
    return changed


def _removed(base_items: dict[str, collections.Counter], head_items: dict[str, collections.Counter]):
    """Preserve same-file occurrences first, then match actual cross-file moves."""
    remaining = {}
    available: collections.Counter = collections.Counter()
    for path in base_items.keys() | head_items.keys():
        before = base_items.get(path, collections.Counter())
        after = head_items.get(path, collections.Counter())
        remaining[path] = before - after
        available.update(after - before)
    for path, items in sorted(remaining.items()):
        for item, count in sorted(items.items()):
            keep = min(count, available[item])
            available[item] -= keep
            for _ in range(count - keep):
                yield path, item


def losses(root: str, base: str, head: str) -> list[dict[str, str]]:
    """Every loss in merge-base(base, head)..head, each with its file."""
    merge_base = _git(root, "merge-base", base, head).strip()
    if not SHA.match(merge_base):
        raise IntegrityError(f"merge-base returned {merge_base!r}")
    changed = _inventory(_git(root, "diff", "--no-ext-diff", "--no-textconv",
                              "--name-status", "--no-renames", "-z", merge_base, head, "--"))
    tests = {path: kind for path, kind in changed.items() if is_test_path(path)}
    found: list[dict[str, str]] = []
    base_texts = {path: _show(root, merge_base, path) for path, kind in tests.items() if kind != "A"}
    head_texts = {path: _show(root, head, path) for path, kind in tests.items() if kind != "D"}
    for path, text in sorted(head_texts.items()):
        before = collections.Counter(_statements(base_texts.get(path, ""), SKIP, path))
        after = collections.Counter(_statements(text, SKIP, path))
        for marker, count in sorted((after - before).items()):
            for _ in range(count):
                found.append({"kind": "skip_added", "file": path, "detail": marker[:160]})
    # Match unchanged same-path evidence before cross-file moves, so a duplicate
    # in another edited file cannot transfer a loss to that innocent file.
    base_statements = {path: collections.Counter(assertions(text, path)) for path, text in base_texts.items()}
    head_statements = {path: collections.Counter(assertions(text, path)) for path, text in head_texts.items()}
    for path, statement in _removed(base_statements, head_statements):
        found.append({"kind": "assertion_removed", "file": path, "detail": statement[:160]})
    base_names = {path: _names(text, path) for path, text in base_texts.items()}
    head_names = {path: _names(text, path) for path, text in head_texts.items()}
    for path, kind in sorted(tests.items()):
        if kind == "D":
            found.append({"kind": "test_file_deleted", "file": path, "detail": "test file deleted"})
    for path, name in _removed(base_names, head_names):
        found.append({"kind": "test_removed", "file": path, "detail": name})
    return found


def section_text(body: str) -> str | None:
    """One exact section, ignoring HTML comments and fenced examples."""
    body = re.sub(r"<!--.*?(?:-->|$)", "", body.replace("\r\n", "\n"), flags=re.DOTALL)
    sections = []
    current = None
    fence = None
    for line in body.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        heading = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            current = None
            if len(heading.group(1)) in (2, 3) and heading.group(2).lower() == SECTION:
                sections.append([])
                current = sections[-1]
        elif current is not None:
            current.append(line)
    return "\n".join(sections[0]) if len(sections) == 1 else None


def says_none(text: str) -> bool:
    value = text.strip().strip("-* ").rstrip(".").lower()
    return value in {"", "none", "n/a", "no", "nothing", "tbd", "todo", "...", "…"} or bool(
        re.fullmatch(r"<[^>]*>|\[[ xX]\]", value))


def _declared(section: str, path: str) -> bool:
    # JSON encoding handles newlines, tabs, quotes and backticks in Git paths.
    forms = {path, "`" + path + "`", json.dumps(path, ensure_ascii=False), json.dumps(path)}
    for line in section.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+)?", "", line)
        for form in forms:
            if line.startswith(form + ":"):
                reason = line[len(form) + 1:].strip()
                if not says_none(reason):
                    return True
    return False


def evaluate(root: str, *, base: str, head: str, body: str | None) -> dict[str, Any]:
    problems: list[str] = []
    found: list[dict[str, str]] = []
    undeclared: list[str] = []
    try:
        if body is not None and not isinstance(body, str):
            raise IntegrityError("PR body must be text")
        if not SHA.fullmatch(base or "") or not SHA.fullmatch(head or ""):
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
                undeclared = [path for path in files if not _declared(section, path)]
                if undeclared:
                    problems.append("PR body section 'Removed or weakened tests or policy' does not "
                                    f"name: {', '.join(undeclared)}")
    except IntegrityError as error:
        problems.append(f"test-integrity cannot read the diff (fail-closed): {error}")
    return {"verdict": "fail" if problems else "pass", "losses": found,
            "undeclared": undeclared, "problems": problems, "body_checked": body is not None,
            "body_status": "supplied" if body is not None else "unavailable-local"}


def _live_body(head: str, base: str) -> str:
    """Fetch current PR data, not the possibly stale webhook body."""
    repo = os.environ.get("REPO", "")
    number = os.environ.get("PR_NUMBER", "")
    token = os.environ.get("GH_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[1-9][0-9]*", number) or not token:
        raise IntegrityError("live PR API context missing or malformed")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise IntegrityError("live PR API response is not an object")
    for name, sha in (("head", head), ("base", base)):
        ref = data.get(name)
        if not isinstance(ref, dict) or ref.get("sha") != sha:
            raise IntegrityError(f"live PR {name} missing or moved; rerun for current commits")
    if "body" not in data or (data["body"] is not None and not isinstance(data["body"], str)):
        raise IntegrityError("live PR body missing or malformed")
    return data["body"] or ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test-integrity")
    parser.add_argument("--base", required=True, help="full base commit SHA")
    parser.add_argument("--head", required=True, help="full head commit SHA")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--body-file", help="supplied PR body; omission is local reporting only")
    group.add_argument("--live-body", action="store_true", help="fetch current PR body (required in CI)")
    args = parser.parse_args(argv)
    try:
        if not SHA.fullmatch(args.base) or not SHA.fullmatch(args.head):
            raise IntegrityError("base/head must be full 40-char SHAs")
        for sha in (args.base, args.head):
            if _git(os.getcwd(), "rev-parse", "--verify", sha + "^{commit}").strip() != sha:
                raise IntegrityError("revision is not a commit")
        if args.live_body:
            body = _live_body(args.head, args.base)
        elif args.body_file:
            with open(args.body_file, encoding="utf-8") as handle:
                body = handle.read()
        else:
            body = None
        result = evaluate(os.getcwd(), base=args.base, head=args.head, body=body)
        if args.live_body:
            result["body_status"] = "live"
    except (IntegrityError, OSError, ValueError) as error:
        result = {"verdict": "fail", "losses": [], "undeclared": [],
                  "problems": [f"test-integrity input unavailable (fail-closed): {type(error).__name__}"],
                  "body_checked": False, "body_status": "unavailable-error"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # JSON-escape untrusted filenames/details: no raw workflow commands in logs.
    for problem in result["problems"]:
        print(json.dumps(problem), file=sys.stderr)
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
