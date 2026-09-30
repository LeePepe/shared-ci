"""Commit identity CLI and its quality-workflow step, using isolated Git repos."""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/quality/commit_identity.py"
NOREPLY = "123+contributor@users.noreply.github.com"
BOT = "456+automation[bot]@users.noreply.github.com"


# Quality-owned test fixture: self-contained YAML parser for workflow testing.
_YAML_KEY = re.compile(r"""^(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_][A-Za-z0-9_./-]*))\s*:(?:\s+|$)(.*)$""")
_YAML_INT = re.compile(r"^-?(?:0|[1-9][0-9]*)$")


def _yaml_strip_comment(line: str) -> str:
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
    return line.rstrip()


def _yaml_scalar(token: str) -> Any:
    token = token.strip()
    if token == "":
        return None
    if token.startswith('"'):
        value = json.loads(token)
        if not isinstance(value, str):
            raise ValueError("invalid double-quoted scalar")
        return value
    if token.startswith("'"):
        if len(token) < 2 or not token.endswith("'"):
            raise ValueError("unterminated single-quoted scalar")
        return token[1:-1].replace("''", "'")
    if token in ("true", "True"):
        return True
    if token in ("false", "False"):
        return False
    if token in ("null", "~", "Null"):
        return None
    if _YAML_INT.match(token):
        return int(token)
    return token


class _YamlFlow:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> Any:
        value = self.value()
        self.space()
        if self.pos != len(self.text):
            raise ValueError(f"trailing flow content: {self.text[self.pos:][:20]!r}")
        return value

    def space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t":
            self.pos += 1

    def value(self) -> Any:
        self.space()
        if self.pos >= len(self.text):
            raise ValueError("unterminated flow collection")
        char = self.text[self.pos]
        if char == "[":
            return self.sequence()
        if char == "{":
            return self.mapping()
        return self.scalar()

    def scalar(self) -> Any:
        start = self.pos
        char = self.text[self.pos]
        if char in "\"'":
            self.pos += 1
            while self.pos < len(self.text):
                if self.text[self.pos] == "\\" and char == '"':
                    self.pos += 2
                    continue
                if self.text[self.pos] == char:
                    if char == "'" and self.text[self.pos + 1:self.pos + 2] == "'":
                        self.pos += 2
                        continue
                    self.pos += 1
                    return _yaml_scalar(self.text[start:self.pos])
                self.pos += 1
            raise ValueError("unterminated quoted scalar")
        while self.pos < len(self.text) and self.text[self.pos] not in ",]}":
            if self.text[self.pos] == ":" and self.text[self.pos + 1:self.pos + 2] in (" ", ""):
                break
            self.pos += 1
        return _yaml_scalar(self.text[start:self.pos])

    def sequence(self) -> list[Any]:
        self.pos += 1
        items: list[Any] = []
        self.space()
        if self.text[self.pos:self.pos + 1] == "]":
            self.pos += 1
            return items
        while True:
            items.append(self.value())
            self.space()
            char = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if char == "]":
                return items
            if char != ",":
                raise ValueError("expected ',' or ']' in flow sequence")

    def mapping(self) -> dict[str, Any]:
        self.pos += 1
        result: dict[str, Any] = {}
        self.space()
        if self.text[self.pos:self.pos + 1] == "}":
            self.pos += 1
            return result
        while True:
            key = self.scalar()
            if not isinstance(key, str) or not key:
                raise ValueError("flow mapping keys must be strings")
            self.space()
            if self.text[self.pos:self.pos + 1] != ":":
                raise ValueError("expected ':' in flow mapping")
            self.pos += 1
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = self.value()
            self.space()
            char = self.text[self.pos:self.pos + 1]
            self.pos += 1
            if char == "}":
                return result
            if char != ",":
                raise ValueError("expected ',' or '}' in flow mapping")


def _yaml_inline(token: str) -> Any:
    token = token.strip()
    if token.startswith(("[", "{")):
        return _YamlFlow(token).parse()
    return _yaml_scalar(token)


class _YamlBlock:
    def __init__(self, text: str) -> None:
        self.lines: list[tuple[int, str, str]] = []
        for raw in text.splitlines():
            content = _yaml_strip_comment(raw)
            if not content.strip():
                self.lines.append((-1, "", raw))
                continue
            self.lines.append((len(content) - len(content.lstrip(" ")), content.strip(), raw))
        self.pos = 0

    def skip_blank(self) -> None:
        while self.pos < len(self.lines) and self.lines[self.pos][0] < 0:
            self.pos += 1

    def parse(self) -> Any:
        self.skip_blank()
        if self.pos >= len(self.lines):
            return {}
        value = self.node(self.lines[self.pos][0])
        self.skip_blank()
        if self.pos < len(self.lines):
            raise ValueError(f"unexpected indentation: {self.lines[self.pos][1][:30]!r}")
        return value

    def node(self, indent: int) -> Any:
        self.skip_blank()
        content = self.lines[self.pos][1]
        if content == "-" or content.startswith("- "):
            return self.sequence(indent)
        return self.mapping(indent)

    def block_scalar(self, style: str, parent_indent: int) -> str:
        collected: list[str] = []
        block_indent = None
        while self.pos < len(self.lines):
            indent, _, raw = self.lines[self.pos]
            stripped_indent = len(raw) - len(raw.lstrip(" "))
            if raw.strip() and stripped_indent <= parent_indent:
                break
            if raw.strip() and block_indent is None:
                block_indent = stripped_indent
            collected.append(raw[block_indent:] if block_indent and raw.strip() else raw.strip())
            self.pos += 1
        while collected and not collected[-1]:
            collected.pop()
        joiner = "\n" if style.startswith("|") else " "
        return joiner.join(collected) + ("\n" if style == "|" else "")

    def value_after(self, rest: str, indent: int) -> Any:
        if rest in ("|", "|-", ">", ">-"):
            return self.block_scalar(rest, indent)
        if rest:
            return _yaml_inline(rest)
        self.skip_blank()
        if self.pos < len(self.lines):
            child_indent, child, _ = self.lines[self.pos]
            if child_indent > indent or (child_indent == indent and (child == "-" or child.startswith("- "))):
                return self.node(child_indent)
        return None

    def mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            self.skip_blank()
            if self.pos >= len(self.lines):
                return result
            line_indent, content, _ = self.lines[self.pos]
            if line_indent < indent:
                return result
            if line_indent > indent:
                raise ValueError(f"unexpected indentation: {content[:30]!r}")
            if content == "-" or content.startswith("- "):
                return result
            match = _YAML_KEY.match(content)
            if match is None:
                raise ValueError(f"expected 'key: value': {content[:30]!r}")
            key = next(g for g in match.groups()[:3] if g is not None)
            rest = match.group(4).strip()
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            self.pos += 1
            result[key] = self.value_after(rest, indent)

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            self.skip_blank()
            if self.pos >= len(self.lines):
                return items
            line_indent, content, raw = self.lines[self.pos]
            if line_indent != indent or not (content == "-" or content.startswith("- ")):
                if line_indent > indent:
                    raise ValueError(f"unexpected indentation: {content[:30]!r}")
                return items
            rest = content[1:].strip()
            if not rest:
                self.pos += 1
                items.append(self.value_after("", indent))
                continue
            if _YAML_KEY.match(rest) and not rest.startswith(("[", "{")):
                item_indent = indent + (len(content) - len(rest))
                self.lines[self.pos] = (item_indent, rest, raw)
                items.append(self.mapping(item_indent))
                continue
            self.pos += 1
            items.append(_yaml_inline(rest))


def _parse_yaml(text: str) -> Any:
    return _YamlBlock(text).parse()


class Repo:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-identity-")
        self.root = pathlib.Path(self.temp.name).resolve()
        home = self.root / "home"
        home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
        self.env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
                         "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C.UTF-8",
                         "GIT_AUTHOR_NAME": 'Odd "quoted"\t雪\x1fname',
                         "GIT_COMMITTER_NAME": 'Another "quoted"\t雪\x1fname'})
        self.git("init", "-q", "-b", "main")
        self.git("config", "maintenance.auto", "false")
        # The excluded base deliberately has non-noreply emails.
        self.base = self.commit("base@example.invalid", "base@example.invalid")

    def close(self):
        self.temp.cleanup()

    def git(self, *args, env=None):
        return subprocess.run(["git", *args], cwd=self.root, env=env or self.env,
                              check=True, capture_output=True, text=True, timeout=20).stdout.strip()

    def commit(self, author=NOREPLY, committer=NOREPLY):
        env = dict(self.env, GIT_AUTHOR_EMAIL=author, GIT_COMMITTER_EMAIL=committer)
        self.git("commit", "-q", "--allow-empty", "-m", "subject\n\nOdd body\x1f", env=env)
        return self.git("rev-parse", "HEAD")

    def cli(self, head, *args, base=None):
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                               "--base", self.base if base is None else base, "--head", head,
                               "--root", str(self.root), *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=20)


class CommitIdentityTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    def test_noreply_author_and_committer_with_odd_names_pass(self):
        result = self.repo.cli(self.repo.commit(), "--mode", "noreply")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ok (1 commits)", result.stdout)
        self.assertEqual("", result.stderr)

    def test_bot_noreply_passes(self):
        result = self.repo.cli(self.repo.commit(BOT, BOT), "--mode", "noreply")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_noreply_matching_is_case_insensitive(self):
        result = self.repo.cli(self.repo.commit(NOREPLY.upper(), BOT.upper()), "--mode", "noreply")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_local_author_fails_with_fix_hint_without_names(self):
        head = self.repo.commit("contributor@MacBook-Pro.local")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author: not a GitHub noreply address", result.stderr)
        self.assertNotIn("contributor", result.stderr)
        self.assertNotIn("MacBook-Pro.local", result.stderr)
        self.assertNotIn(f"{head[:12]} committer", result.stderr)
        self.assertNotIn("quoted", result.stderr)
        self.assertEqual(1, result.stderr.count("Fix:"))
        self.assertIn("user.email", result.stderr)
        self.assertIn("rewrite the branch commits", result.stderr)
        self.assertIn("your GitHub noreply address", result.stderr)
        self.assertIn("not a GitHub noreply address", result.stderr)

    def test_non_noreply_committer_fails(self):
        head = self.repo.commit(committer="committer@example.invalid")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} committer: not a GitHub noreply address", result.stderr)
        self.assertNotIn("committer@example.invalid", result.stderr)
        self.assertNotIn(f"{head[:12]} author", result.stderr)

    def test_allowlist_pattern_passes_for_both_roles_case_insensitively(self):
        head = self.repo.commit("author@EXAMPLE.invalid", "committer@example.INVALID")
        result = self.repo.cli(head, "--mode", "noreply", "--allow", "*@Example.Invalid")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_comma_newline_and_repeated_allow_values(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        for args in (("--allow", " , *@ONE.invalid ,\n *@two.invalid\r\n,"),
                     ("--allow", "*@one.invalid", "--allow", "*@TWO.invalid")):
            with self.subTest(args=args):
                result = self.repo.cli(head, "--mode", "noreply", *args)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([
                    "commit-identity: mode noreply",
                    'commit-identity: allow patterns ["*@one.invalid", "*@two.invalid"]',
                    "commit-identity: ok (1 commits)",
                ], result.stdout.splitlines())

    def test_allowlist_is_not_a_substring_match_or_blanket_exception(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        result = self.repo.cli(head, "--mode", "noreply", "--allow", "or@one.invalid")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author:", result.stderr)
        self.assertIn(f"{head[:12]} committer:", result.stderr)
        result = self.repo.cli(head, "--mode", "noreply", "--allow",
                               "or@one.invalid, ,\n, *@ONE.invalid")
        self.assertEqual(1, result.returncode)
        self.assertNotIn(f"{head[:12]} author:", result.stderr)
        self.assertIn(f"{head[:12]} committer:", result.stderr)

    def test_noreply_domain_suffix_spoof_fails(self):
        head = self.repo.commit(NOREPLY + ".invalid")
        self.assertEqual(1, self.repo.cli(head, "--mode", "noreply").returncode)

    def test_noreply_mode_rejects_malformed_noreply_local_parts(self):
        for email in ("@users.noreply.github.com", "+name@users.noreply.github.com",
                      "x@y@users.noreply.github.com", "1+@users.noreply.github.com",
                      "fake_user@users.noreply.github.com", "a.b@users.noreply.github.com",
                      "a[b@users.noreply.github.com", "a--b@users.noreply.github.com",
                      "-ab@users.noreply.github.com", "ab-@users.noreply.github.com",
                      "a[bot]x@users.noreply.github.com", "0+ab@users.noreply.github.com",
                      "a" * 40 + "@users.noreply.github.com",
                      "a-" * 20 + "a@users.noreply.github.com"):
            with self.subTest(email=email):
                for role in ("author", "committer"):
                    head = self.repo.commit(**{role: email})
                    result = self.repo.cli(head, "--mode", "noreply")
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(role, result.stderr)

    def test_noreply_mode_accepts_github_noreply_local_part_shapes(self):
        for email in ("name@users.noreply.github.com", "123+name@users.noreply.github.com",
                      "123+some-app[bot]@users.noreply.github.com", "a-b-c@users.noreply.github.com",
                      "a" * 39 + "@users.noreply.github.com"):
            with self.subTest(email=email):
                result = self.repo.cli(self.repo.commit(email, email), "--mode", "noreply")
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_web_flow_committer_passes_but_author_requires_allowlist(self):
        result = self.repo.cli(self.repo.commit(committer="NOREPLY@GITHUB.COM"), "--mode", "noreply")
        self.assertEqual(0, result.returncode, result.stderr)
        head = self.repo.commit("noreply@github.com", "noreply@github.com")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author:", result.stderr)
        self.assertNotIn(f"{head[:12]} committer:", result.stderr)
        self.assertEqual(0, self.repo.cli(head, "--mode", "noreply",
                                         "--allow", "noreply@github.com").returncode)

    def test_basic_default_and_explicit_mode_accept_non_local_emails_for_both_roles(self):
        for email in ("user@qq.com", "dev@example.com", NOREPLY, BOT, "noreply@github.com",
                      "NOREPLY@GITHUB.COM", "x@local.example", "x@localhost.example",
                      "x@localdomain.example", "x@example.com.", "x@y@example.com"):
            head = self.repo.commit(email, email)
            for args in ((), ("--mode", "basic")):
                with self.subTest(email=email, args=args):
                    result = self.repo.cli(head, *args, base="HEAD^")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("commit-identity: mode basic", result.stdout)
                    self.assertIn("commit-identity: allow patterns []", result.stdout)
                    self.assertIn("ok (1 commits)", result.stdout)
                    self.assertEqual("", result.stderr)

    def test_basic_rejects_invalid_emails_for_both_roles_with_reasons(self):
        cases = [(email, "local hostname domain") for email in (
            "x@host.local", "x@host.localdomain", "x@localhost", "x@LOCALHOST.",
            "x@host.LOCAL.", "x@host.LOCALDOMAIN.", "x@host.localhost", "x@mylocalhost",
        )] + [
            ("no-at", "missing @"), ("", "missing @"), ("x@", "missing domain"),
            ("x@.", "missing domain"), ("@example.com", "missing local part"),
            ("x@intranet", "domain has no dot"), ("x@intranet.", "domain has no dot"),
            ("x\x1b@host.local", "local hostname domain"),
        ]
        for email, reason in cases:
            with self.subTest(email=email):
                head = self.repo.commit(email, email)
                result = self.repo.cli(head, base="HEAD^")
                self.assertEqual(1, result.returncode, result.stderr)
                for role in ("author", "committer"):
                    self.assertIn(f"{head[:12]} {role}: {reason}", result.stderr)
                if email:
                    self.assertNotIn(email, result.stderr)
                self.assertNotIn("\x1b", result.stderr)
                self.assertEqual(1, result.stderr.count("Fix:"))
                self.assertIn("user.email to a valid email address with a non-local, dotted domain",
                              result.stderr)
                self.assertIn("rewrite the branch commits", result.stderr)
                self.assertNotIn("your GitHub noreply address", result.stderr)

    def test_allowlist_overrides_rejection_in_both_modes_for_both_roles(self):
        head = self.repo.commit("author@HOST.local", "committer@host.LOCAL")
        for mode in ("basic", "noreply"):
            with self.subTest(mode=mode):
                self.assertEqual(1, self.repo.cli(head, "--mode", mode).returncode)
                result = self.repo.cli(head, "--mode", mode, "--allow", "*@Host.Local")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(f"commit-identity: mode {mode}", result.stdout)
                self.assertIn('commit-identity: allow patterns ["*@host.local"]', result.stdout)

    def test_invalid_allow_patterns_fail_closed_with_json_escaped_pattern(self):
        for mode in ("basic", "noreply"):
            for pattern in ("*", "*@*", "**@??", "?@?", "one.invalid", 'bad"\x1bpattern'):
                with self.subTest(mode=mode, pattern=pattern):
                    result = self.repo.cli(self.repo.base, "--mode", mode,
                                           "--allow", f" , *@example.com,\n {pattern} \r\n")
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(f"invalid allow pattern {json.dumps(pattern)}", result.stderr)
                    self.assertIn("too broad" if "@" in pattern else "must contain @", result.stderr)
                    self.assertNotIn("\x1b", result.stderr)
                    self.assertEqual("", result.stdout)

    def test_effective_allow_patterns_are_json_escaped(self):
        pattern = 'quoted"\x1b@HOST.local'
        for mode in ("basic", "noreply"):
            with self.subTest(mode=mode):
                result = self.repo.cli(self.repo.base, "--mode", mode, "--allow", pattern)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([
                    f"commit-identity: mode {mode}",
                    f"commit-identity: allow patterns {json.dumps([pattern.lower()])}",
                    "commit-identity: ok (0 commits)",
                ], result.stdout.splitlines())

    def test_invalid_mode_exits_two_even_for_empty_range(self):
        for mode in ("", "strict", "BASIC", "noreply "):
            with self.subTest(mode=mode):
                result = self.repo.cli(self.repo.base, "--mode", mode)
                self.assertEqual(2, result.returncode)
                self.assertIn("--mode", result.stderr)
                self.assertIn("invalid choice", result.stderr)
                self.assertEqual("", result.stdout)

    def test_empty_range_ok(self):
        result = self.repo.cli(self.repo.base)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("ok (0 commits)", result.stdout)

    def test_root_defaults_to_current_repository(self):
        head = self.repo.commit()
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT),
                                 "--base", self.repo.base, "--head", head],
                                cwd=self.repo.root, env=self.repo.env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_both_bad_roles_and_escaped_diagnostics(self):
        head = self.repo.commit("author\x1b@host.local", "committer@host.local")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author: not a GitHub noreply address", result.stderr)
        self.assertIn(f"{head[:12]} committer: not a GitHub noreply address", result.stderr)
        self.assertNotIn("host.local", result.stderr)
        self.assertNotIn("\x1b", result.stderr)
        self.assertEqual(1, result.stderr.count("Fix:"))

    def test_replacement_objects_cannot_hide_offenders(self):
        bad = self.repo.commit("author@host.local")
        good = self.repo.commit()
        self.repo.git("replace", bad, good)
        result = self.repo.cli(bad, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{bad[:12]} author: not a GitHub noreply address", result.stderr)
        self.assertNotIn("host.local", result.stderr)

    def test_bad_revisions_and_empty_endpoints_exit_two(self):
        for base, head in (("unknown", self.repo.base), (self.repo.base, "unknown"),
                           ("", self.repo.base), (self.repo.base, ""),
                           (" ", self.repo.base), ("--all", self.repo.base),
                           (self.repo.base, "HEAD^{tree}")):
            with self.subTest(base=base, head=head):
                result = self.repo.cli(head, base=base)
                self.assertEqual(2, result.returncode, result.stderr)
                # argparse rejects an option-shaped value before configuration is printed.
                expected = ("" if base == "--all" else
                            "commit-identity: mode basic\ncommit-identity: allow patterns []\n")
                self.assertEqual(expected, result.stdout)

    def test_missing_argument_or_non_repository_exit_two(self):
        result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT)],
                                env=self.repo.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(2, result.returncode)
        # A nonexistent root cannot inherit the surrounding test repository.
        result = self.repo.cli(self.repo.base, "--root", str(self.repo.root / "absent"))
        self.assertEqual(2, result.returncode)

    def test_mixed_commits_report_only_offenders_not_just_head(self):
        good = self.repo.commit()
        bad_author = self.repo.commit("author@host.local")
        bad_committer = self.repo.commit(committer="committer@example.invalid")
        head = self.repo.commit()
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        findings = [line for line in result.stderr.splitlines() if line.startswith("commit-identity:")]
        self.assertCountEqual([
            f"commit-identity: {bad_author[:12]} author: not a GitHub noreply address",
            f"commit-identity: {bad_committer[:12]} committer: not a GitHub noreply address",
        ], findings)
        self.assertNotIn("author@host.local", result.stderr)
        self.assertNotIn("committer@example.invalid", result.stderr)
        for sha in (self.repo.base, good, head):
            self.assertNotIn(sha[:12], result.stderr)

    def test_mailmap_and_log_settings_cannot_hide_raw_emails(self):
        head = self.repo.commit("author@host.local")
        (self.repo.root / ".mailmap").write_text(f"<{NOREPLY}> <author@host.local>\n")
        self.repo.git("config", "log.mailmap", "true")
        self.repo.git("config", "log.showSignature", "true")
        self.repo.git("config", "format.pretty", "fuller")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{head[:12]} author: not a GitHub noreply address", result.stderr)
        self.assertNotIn("author@host.local", result.stderr)
        self.assertNotIn("quoted", result.stderr)

    def test_rejected_identities_never_leak_email_addresses_or_names_to_logs(self):
        # Local domain fails in basic mode; valid domain fails in noreply mode.
        local_author = "confidential-author@private.local"
        local_committer = "confidential-committer@private.local"
        head_basic = self.repo.commit(local_author, local_committer)
        result_basic = self.repo.cli(head_basic, "--mode", "basic", base="HEAD^")
        self.assertEqual(1, result_basic.returncode)
        for val in (local_author, local_committer, "private.local", "quoted"):
            self.assertNotIn(val, result_basic.stdout)
            self.assertNotIn(val, result_basic.stderr)

        noreply_author = "confidential-author@private-domain.com"
        noreply_committer = "confidential-committer@private-domain.com"
        head_noreply = self.repo.commit(noreply_author, noreply_committer)
        result_noreply = self.repo.cli(head_noreply, "--mode", "noreply", base="HEAD^")
        self.assertEqual(1, result_noreply.returncode)
        for val in (noreply_author, noreply_committer, "private-domain.com", "quoted"):
            self.assertNotIn(val, result_noreply.stdout)
            self.assertNotIn(val, result_noreply.stderr)

    def test_merge_commits_and_side_branch_commits_are_checked(self):
        self.repo.git("checkout", "-q", "-b", "side")
        side = self.repo.commit("side@host.local")
        self.repo.git("checkout", "-q", "main")
        self.repo.commit()
        self.repo.git("merge", "-q", "--no-ff", "-m", "merge", "side",
                      env=dict(self.repo.env, GIT_AUTHOR_EMAIL=NOREPLY,
                               GIT_COMMITTER_EMAIL="merge@host.local"))
        head = self.repo.git("rev-parse", "HEAD")
        result = self.repo.cli(head, "--mode", "noreply")
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{side[:12]} author: not a GitHub noreply address", result.stderr)
        self.assertIn(f"{head[:12]} committer: not a GitHub noreply address", result.stderr)
        self.assertNotIn("side@host.local", result.stderr)
        self.assertNotIn("merge@host.local", result.stderr)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = _parse_yaml((REPO / ".github/workflows/quality.yml").read_text())
        cls.job = cls.workflow["jobs"]["select"]
        cls.step = next(step for step in cls.job["steps"]
                        if step.get("name") == "Check commit author and committer emails")

    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        provider = self.repo.root / ".shared-ci/scripts/quality"
        provider.mkdir(parents=True)
        shutil.copyfile(SCRIPT, provider / SCRIPT.name)

    def run_step(self, head="", **env):
        environment = dict(self.repo.env, EVENT="pull_request", ENABLED="true", MODE="basic", ALLOW="",
                           BASE_SHA=self.repo.base, HEAD_SHA=head)
        environment.update(env)
        return subprocess.run(["bash", "-euo", "pipefail", "-c", self.step["run"]],
                              cwd=self.repo.root, env=environment,
                              capture_output=True, text=True, timeout=20)

    def test_step_contract_preserves_jobs_and_aggregate(self):
        inputs = self.workflow["on"]["workflow_call"]["inputs"]
        for name, kind, default in (("commit-identity", "boolean", True),
                                     ("commit-identity-mode", "string", "basic"),
                                     ("commit-identity-allow", "string", "")):
            self.assertEqual(kind, inputs[name]["type"])
            self.assertEqual(default, inputs[name]["default"])
        self.assertNotIn("if", self.job)
        self.assertNotIn("if", self.step)
        self.assertNotIn("continue-on-error", self.step)
        self.assertEqual("${{ inputs.commit-identity }}", self.step["env"]["ENABLED"])
        self.assertEqual("${{ inputs.commit-identity-mode }}", self.step["env"]["MODE"])
        self.assertEqual("${{ inputs.commit-identity-allow }}", self.step["env"]["ALLOW"])
        self.assertEqual("${{ github.event.pull_request.base.sha || '' }}", self.step["env"]["BASE_SHA"])
        self.assertEqual("${{ github.event.pull_request.head.sha || github.sha }}", self.step["env"]["HEAD_SHA"])
        self.assertNotIn("${{", self.step["run"])
        checkout = self.job["steps"][0]
        self.assertEqual("inputs.changed-only || (inputs.commit-identity && github.event_name == 'pull_request')",
                         checkout["if"])
        self.assertEqual(0, checkout["with"]["fetch-depth"])
        self.assertEqual(self.step["env"]["HEAD_SHA"], checkout["with"]["ref"])
        self.assertFalse(checkout["with"]["persist-credentials"])
        provider = next(step for step in self.job["steps"] if step.get("with", {}).get("path") == ".shared-ci")
        self.assertEqual("${{ job.workflow_sha }}", provider["with"]["ref"])
        jobs = {"select", "verify", "lint", "build", "test", "contract", "workflow-lint", "test-integrity"}
        self.assertEqual(jobs | {"aggregate"}, set(self.workflow["jobs"]))
        self.assertEqual(jobs, set(self.workflow["jobs"]["aggregate"]["needs"]))
        self.assertEqual("always()", self.workflow["jobs"]["aggregate"]["if"])

    def test_workflow_step_propagates_pass_failure_and_git_error(self):
        self.assertEqual(0, self.run_step(self.repo.commit()).returncode)
        self.assertEqual(1, self.run_step(self.repo.commit("author@host.local")).returncode)
        self.assertEqual(2, self.run_step("unknown").returncode)

    def test_non_pr_events_and_disabled_input_explicitly_skip(self):
        for event in ("push", "schedule", "workflow_dispatch", "merge_group", "pull_request_target"):
            with self.subTest(event=event):
                result = self.run_step(EVENT=event)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("skipped (not a pull_request event:", result.stdout)
        result = self.run_step(ENABLED="false")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("skipped (disabled by input)", result.stdout)

    def test_workflow_allowlist_is_data_not_shell_code(self):
        head = self.repo.commit("author@one.invalid", "committer@two.invalid")
        result = self.run_step(head, MODE="noreply",
                               ALLOW="$(touch injected)@unmatched.invalid, *@ONE.invalid\n*@two.invalid")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.repo.root / "injected").exists())

    def test_workflow_passes_mode_to_script(self):
        head = self.repo.commit("author@example.com", "committer@example.com")
        basic = self.run_step(head)
        self.assertEqual(0, basic.returncode, basic.stderr)
        self.assertIn("commit-identity: mode basic", basic.stdout)
        strict = self.run_step(head, MODE="noreply")
        self.assertEqual(1, strict.returncode, strict.stderr)
        self.assertIn("commit-identity: mode noreply", strict.stdout)
        self.assertIn("not a GitHub noreply address", strict.stderr)

    def test_workflow_rejects_invalid_mode_before_skipping(self):
        for mode in ("", "strict", "BASIC", "$(touch injected)"):
            for env in ({}, {"EVENT": "push"}, {"ENABLED": "false"}):
                with self.subTest(mode=mode, env=env):
                    result = self.run_step(self.repo.base, MODE=mode, **env)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn("invalid mode", result.stderr)
                    self.assertEqual("", result.stdout)
                    self.assertFalse((self.repo.root / "injected").exists())

    def test_workflow_allowlist_overrides_both_modes(self):
        head = self.repo.commit("author@host.local", "committer@host.local")
        for mode in ("basic", "noreply"):
            with self.subTest(mode=mode):
                result = self.run_step(head, MODE=mode, ALLOW="*@HOST.local")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn('commit-identity: allow patterns ["*@host.local"]', result.stdout)

    def test_workflow_propagates_invalid_allowlist_error(self):
        for mode in ("basic", "noreply"):
            for pattern in ("*", "*@*", "one.invalid", "$(touch injected)"):
                with self.subTest(mode=mode, pattern=pattern):
                    result = self.run_step(self.repo.base, MODE=mode, ALLOW=pattern)
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn(f"invalid allow pattern {json.dumps(pattern)}", result.stderr)
                    self.assertFalse((self.repo.root / "injected").exists())


class VerificationTests(unittest.TestCase):
    def test_native_verify_runs_commit_identity_suite(self):
        verify = (REPO / "scripts/verify").read_text()
        self.assertIn(
            '"$python" -I -B -m unittest discover -s tests/quality -p \'test_commit_identity.py\'',
            verify.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
