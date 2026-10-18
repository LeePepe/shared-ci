#!/usr/bin/env python3
"""Admit optional PR Target scope and filter validated Codex findings.

Paths are exact repository paths or literal subtree prefixes ending in /**.
No PR text is evaluated, imported or used as repository/Owner authority.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

MAX_SCOPE_BYTES = 8000
SAFETY_CATEGORIES = ("security", "privacy", "data_loss")


def valid_path(path: str) -> bool:
    return (bool(path) and not path.startswith("/") and "\\" not in path
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in path)
            and all(part not in ("", ".", "..") for part in path.split("/")))


def parse(body: str) -> dict[str, Any] | None:
    """Read one top-level ## Target scope section, ignoring fenced examples."""
    sections: list[list[str]] = []
    current: list[str] | None = None
    fence = ""
    for line in body.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            if current is not None:
                current.append(line)
            continue
        if fence:
            if current is not None:
                current.append(line)
            continue
        heading = re.match(r"^ {0,3}(#{1,2})[ \t]+(.+?)\s*#*\s*$", line)
        if heading:
            current = None
            if heading.group(1) == "##" and heading.group(2).casefold() == "target scope":
                current = []
                sections.append(current)
        elif current is not None:
            current.append(line)
    if not sections:
        return None
    if len(sections) != 1:
        raise ValueError("declare exactly one Target scope section")
    lines = sections[0]
    if len("\n".join(lines).encode("utf-8")) > MAX_SCOPE_BYTES:
        raise ValueError(f"Target scope exceeds {MAX_SCOPE_BYTES} UTF-8 bytes; never truncated")
    scope: dict[str, Any] = {"paths": [], "acceptance": []}
    part = ""
    seen = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line in ("### Paths", "### Acceptance"):
            part = "paths" if line == "### Paths" else "acceptance"
            if part in seen:
                raise ValueError("duplicate Target scope subsection")
            seen.add(part)
            continue
        if part == "paths":
            match = re.fullmatch(r"- `([^`]+)`", line)
            path = match.group(1) if match else ""
            prefix = path[:-3] if path.endswith("/**") else path
            if not valid_path(prefix) or any(char in prefix for char in "*?[]"):
                raise ValueError("Target paths must be backticked canonical paths or directory/**")
            scope[part].append(path)
        elif part == "acceptance" and line.startswith("- ") and line[2:].strip():
            scope[part].append(line[2:])
        else:
            raise ValueError("Target scope requires ### Paths and ### Acceptance bullet lists")
    if not scope["paths"] or not scope["acceptance"]:
        raise ValueError("Target scope requires nonempty Paths and Acceptance lists")
    return scope


def contains(paths: list[str], path: str) -> bool:
    return any(path.startswith(pattern[:-2]) if pattern.endswith("/**") else path == pattern
               for pattern in paths)


def apply(data: dict[str, Any], scope: dict[str, Any] | None) -> dict[str, Any]:
    """Filter only after the original verdict has passed structural validation."""
    if scope is None:
        return data
    blockers, followups = [], []
    for item in data["blockers"]:
        for field in ("introduced", "acceptance_failure"):
            if type(item.get(field)) is not bool:
                raise ValueError(f"scoped blockers require boolean {field}")
        if ("safety_category" not in item
                or item["safety_category"] not in (None, *SAFETY_CATEGORIES)):
            raise ValueError("scoped blockers require safety_category: null, security, privacy or data_loss")
        if not valid_path(item["file"]):
            raise ValueError("scoped blockers require a canonical repository file path")
        if item["introduced"] or item["acceptance_failure"] or item["safety_category"] is not None:
            blockers.append(item)
        else:
            followups.append(item)
    for path in scope["outside"]:
        blockers.append({"file": path, "line": None, "severity": "high",
                         "why": "Changed file is outside the declared Target paths."})
    return {**data, "verdict": "changes" if blockers else "pass", "blockers": blockers,
            "follow_ups": followups,
            "summary": (f"Target scope: {len(blockers)} blocking finding(s); "
                        f"{len(followups)} pre-existing follow-up(s). "
                        f"Reviewer summary before scope filtering: {data['summary']}")}


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: target_scope.py PR_JSON CHANGED_NUL SCOPE_JSON", file=sys.stderr)
        return 2
    try:
        record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
        scope = parse(record["body"] or "")
        if scope is not None:
            raw = pathlib.Path(sys.argv[2]).read_bytes()
            if raw and not raw.endswith(b"\0"):
                raise ValueError("changed paths must be NUL-terminated")
            paths = raw.decode("utf-8").split("\0")[:-1]
            scope["outside"] = [path for path in paths if not contains(scope["paths"], path)]
        pathlib.Path(sys.argv[3]).write_text(json.dumps(scope), encoding="utf-8")
        # Quoted JSON keeps arbitrary acceptance text and delimiters on one data line.
        print("> " + (json.dumps(scope, ensure_ascii=True) if scope is not None
                       else "No Target scope declared; existing review behavior applies."))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        print(f"target-scope: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
