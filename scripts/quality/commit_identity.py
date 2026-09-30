#!/usr/bin/env python3
"""Check raw author/committer emails in base..head (stdlib, Python 3.9+).

Exit 0: clean (including an empty range); 1: offenders; 2: usage/Git errors.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from typing import Optional


def git(root: str, *args: str, input: bytes = b"") -> bytes:
    # Do not let replacement objects or presentation settings rewrite metadata.
    result = subprocess.run(["git", "--no-replace-objects", "-C", root, *args],
                            input=input, capture_output=True, timeout=60)
    if result.returncode:
        # Git diagnostics may contain untrusted names or other commit content.
        raise ValueError(f"git {args[0]} failed; check the repository and revisions")
    return result.stdout


def revision(root: str, value: str) -> str:
    if not value.strip():
        raise ValueError("base and head must be nonempty commit revisions")
    return git(root, "rev-parse", "--verify", "--end-of-options",
               value + "^{commit}").decode("ascii").strip()


def identities(root: str, base: str, head: str) -> list[tuple[str, str, str]]:
    base, head = revision(root, base), revision(root, head)
    commits = git(root, "rev-list", f"{base}..{head}", "--").decode("ascii").splitlines()
    if not commits:
        return []
    raw = git(root, "log", "--no-walk=unsorted", "--no-patch", "--no-decorate",
              "--no-mailmap", "--no-show-signature", "--format=%H%x1f%ae%x1f%ce",
              "-z", "--stdin", input=("\n".join(commits) + "\n").encode("ascii"))
    # NUL records and unit-separated fields; names and subjects are never read.
    records = raw.decode("utf-8").split("\0")
    if records.pop() != "":
        raise ValueError("unterminated Git identity record")
    rows = []
    for record in records:
        fields = record.split("\x1f")
        if len(fields) != 3:
            raise ValueError("malformed Git identity record")
        rows.append(tuple(fields))
    if len(rows) != len(commits) or {row[0] for row in rows} != set(commits):
        raise ValueError("Git identity records do not match the commit range")
    return rows


def allow_patterns(values: list[str]) -> list[str]:
    patterns = []
    for value in values:
        for part in re.split(r"[,\r\n]", value):
            pattern = part.strip()
            if not pattern:
                continue
            local, separator, domain = pattern.rpartition("@")
            if not separator:
                raise ValueError(f"invalid allow pattern {json.dumps(pattern)}: must contain @")
            if local and domain and set(local + domain) <= {"*", "?"}:
                raise ValueError(f"invalid allow pattern {json.dumps(pattern)}: too broad; "
                                 "both sides of @ contain only wildcards")
            patterns.append(pattern.lower())
    return patterns


# GitHub login: alphanumerics with single inner hyphens, at most 39 chars; Apps add "[bot]".
GITHUB_LOGIN = r"[a-z0-9](?:-?[a-z0-9]){0,38}"
NOREPLY_LOCAL = re.compile(r"(?:[1-9][0-9]*\+)?(?=[a-z0-9-]{1,39}(?:\[bot\])?$)"
                           + GITHUB_LOGIN + r"(?:\[bot\])?")


def basic_reason(email: str) -> Optional[str]:
    local, separator, domain = email.rpartition("@")
    if not separator:
        return "missing @"
    if not local:
        return "missing local part"
    domain = domain.removesuffix(".")
    if not domain:
        return "missing domain"
    if domain.endswith(("localhost", ".local", ".localdomain")):
        return "local hostname domain"
    if "." not in domain:
        return "domain has no dot"
    return None


def rejection_reason(email: str, role: str, patterns: list[str], mode: str) -> Optional[str]:
    email = email.lower()
    if any(fnmatch.fnmatchcase(email, pattern) for pattern in patterns):
        return None
    reason = basic_reason(email)
    if mode != "noreply":
        return reason
    # noreply only narrows basic: a malformed identity never passes, even with the suffix.
    local, _, domain = email.rpartition("@")
    if not reason and domain == "users.noreply.github.com" and NOREPLY_LOCAL.fullmatch(local):
        return None
    # GitHub web-flow writes committer metadata, not contributor identity.
    if role == "committer" and email == "noreply@github.com":
        return None
    return "not a GitHub noreply address"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--mode", choices=("basic", "noreply"), default="basic",
                        help="identity policy (default: basic)")
    parser.add_argument("--allow", action="append", default=[],
                        help="case-insensitive email glob(s), comma/newline separated; repeatable")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        patterns = allow_patterns(args.allow)
        print(f"commit-identity: mode {args.mode}", flush=True)
        print(f"commit-identity: allow patterns {json.dumps(patterns)}", flush=True)
        rows = identities(args.root, args.base, args.head)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"commit-identity: {error}", file=sys.stderr)
        return 2
    offenders = 0
    for sha, author, committer in rows:
        for role, email in (("author", author), ("committer", committer)):
            reason = rejection_reason(email, role, patterns, args.mode)
            if reason is not None:
                # Do not emit raw email addresses to avoid leaking private identities in logs.
                print(f"commit-identity: {sha[:12]} {role}: {reason}",
                      file=sys.stderr)
                offenders += 1
    if offenders:
        identity = ("your GitHub noreply address" if args.mode == "noreply"
                    else "a valid email address with a non-local, dotted domain")
        print(f"Fix: set git user.email to {identity} and rewrite the branch commits "
              "to correct both author and committer emails.", file=sys.stderr)
        return 1
    print(f"commit-identity: ok ({len(rows)} commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
