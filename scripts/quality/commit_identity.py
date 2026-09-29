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


def allowed(email: str, role: str, patterns: list[str]) -> bool:
    email = email.lower()
    return (fnmatch.fnmatchcase(email, "*@users.noreply.github.com")
            # GitHub web-flow writes committer metadata, not contributor identity.
            or role == "committer" and email == "noreply@github.com"
            or any(fnmatch.fnmatchcase(email, pattern) for pattern in patterns))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--allow", action="append", default=[],
                        help="case-insensitive email glob(s), comma/newline separated; repeatable")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    patterns = [pattern.strip().lower() for value in args.allow
                for pattern in re.split(r"[,\r\n]", value) if pattern.strip()]
    try:
        rows = identities(args.root, args.base, args.head)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"commit-identity: {error}", file=sys.stderr)
        return 2
    offenders = 0
    for sha, author, committer in rows:
        for role, email in (("author", author), ("committer", committer)):
            if not allowed(email, role, patterns):
                # Escape controls so an email cannot inject workflow log commands.
                print(f"commit-identity: {sha[:12]} {role} {json.dumps(email)}", file=sys.stderr)
                offenders += 1
    if offenders:
        print("Fix: set git user.email to your GitHub noreply address and rewrite the branch commits "
              "to correct both author and committer emails.", file=sys.stderr)
        return 1
    print(f"commit-identity: ok ({len(rows)} commits)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
