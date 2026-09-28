#!/usr/bin/env python3
"""Admit unedited, Owner-authored PR comments bound to the exact review head.

Run with python3 -I -B in the trusted workflow context; never read PR-head files.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

NOT_CONFIGURED = "(Owner decision input is not configured for this repository.)"
MAX_DECISIONS = 5
MAX_DECISION_BYTES = 4000
MAX_TOTAL_BYTES = 12000


def parse_records(output: str) -> list[dict]:
    """Decode gh's JSON lines; malformed records are errors even if not the Owner's."""
    lines = output.split("\n")
    if lines[-1] == "":
        lines.pop()
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            raise ValueError("Invalid JSON in Owner decision comments.") from None
        if (not isinstance(record, dict)
                or any(type(record.get(key)) is not int for key in ("id", "user_id"))
                or any(not isinstance(record.get(key), str)
                       for key in ("created_at", "updated_at", "body"))):
            raise ValueError("Owner decision comment record has missing fields or wrong types.")
        records.append(record)
    return records


def admit(records: list[dict], owner_id: int, head_sha: str) -> list[dict]:
    """Select decisions by numeric author, exact head token and unedited timestamp."""
    token = re.compile(r"(?<![0-9a-fA-F])" + re.escape(head_sha) + r"(?![0-9a-fA-F])")
    decisions = [record for record in records
                 if type(record["user_id"]) is int and record["user_id"] == owner_id
                 and token.search(record["body"])
                 and record["created_at"] == record["updated_at"]]
    if len(decisions) > MAX_DECISIONS:
        raise ValueError(f"Owner decisions exceed {MAX_DECISIONS} comments.")
    total = 0
    for record in decisions:
        body = record["body"]
        if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159
               for char in body):
            raise ValueError("Owner decision body contains forbidden control characters.")
        size = len(body.encode("utf-8"))
        if size > MAX_DECISION_BYTES:
            raise ValueError(f"Owner decision body exceeds {MAX_DECISION_BYTES} UTF-8 bytes.")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ValueError(f"Owner decisions exceed {MAX_TOTAL_BYTES} UTF-8 bytes in total.")
    return decisions


def render(decisions: list[dict]) -> str:
    """Render admitted decisions deterministically, with bodies kept inside quotes."""
    if not decisions:
        return "(No Owner decision names the current head SHA.)\n"
    lines = []
    for record in sorted(decisions, key=lambda record: record["id"]):
        lines.append(f"### Owner decision comment {record['id']} (created {record['created_at']})")
        body = record["body"].replace("\r\n", "\n").replace("\r", "\n")
        body = re.sub(r"\{{2,}", lambda match: " ".join(match.group()), body)
        body = re.sub(r"={4,}", lambda match: " ".join(match.group()), body)
        lines.extend("> " + line for line in body.split("\n"))
    return "\n".join(lines) + "\n"


def main() -> int:
    owner = os.environ.get("OWNER_DECISION_USER_ID", "")
    if not owner:
        print(NOT_CONFIGURED)
        return 0
    patterns = {"OWNER_DECISION_USER_ID": r"[1-9][0-9]{0,19}",
                "HEAD_SHA": r"[0-9a-f]{40}", "PR_NUMBER": r"[1-9][0-9]*",
                "BASE_REPO": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"}
    for name, pattern in patterns.items():
        if not re.fullmatch(pattern, os.environ.get(name, "")):
            print(f"owner-decisions: invalid {name}.", file=sys.stderr)
            return 1
    endpoint = f"repos/{os.environ['BASE_REPO']}/issues/{os.environ['PR_NUMBER']}/comments?per_page=100"
    try:
        result = subprocess.run(
            ["gh", "api", "--paginate", endpoint, "--jq",
             ".[] | {id: .id, user_id: .user.id, created_at: .created_at, updated_at: .updated_at, body: .body}"],
            capture_output=True, encoding="utf-8", check=True, timeout=60)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        print("owner-decisions: PR comment API failed or returned invalid UTF-8.", file=sys.stderr)
        return 1
    try:
        decisions = admit(parse_records(result.stdout), int(owner), os.environ["HEAD_SHA"])
        output = render(decisions)
        sys.stdout.buffer.write(output.encode("utf-8"))
    except UnicodeError:
        print("owner-decisions: invalid UTF-8 comment text.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"owner-decisions: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
