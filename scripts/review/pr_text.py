#!/usr/bin/env python3
"""Fetch author-controlled PR title/body as untrusted review data.

Run with python3 -I -B in the trusted workflow context; gh inherits GH_TOKEN.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

MAX_TITLE_BYTES = 300
MAX_BODY_BYTES = 8000


def render(title: str, body: str) -> str:
    """Bound author text before escaping, quote every line, then report truncation."""
    texts, markers = [], []
    for label, text, limit in (("title", title, MAX_TITLE_BYTES),
                               ("body", body, MAX_BODY_BYTES)):
        encoded = text.encode("utf-8")
        if len(encoded) > limit:
            text = encoded[:limit].decode("utf-8", "ignore")
            markers.append(f"(PR {label} truncated to {limit} UTF-8 bytes.)")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\{{2,}", lambda match: " ".join(match.group()), text)
        text = re.sub(r"={4,}", lambda match: " ".join(match.group()), text)
        texts.append(text)
    title, body = texts
    lines = ["> Title: " + title.replace("\n", " "), "> "]
    lines.extend("> " + line for line in body.split("\n"))
    return "\n".join(lines + markers)


def main() -> int:
    patterns = {"PR_NUMBER": r"[1-9][0-9]*",
                "BASE_REPO": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"}
    for name, pattern in patterns.items():
        if not re.fullmatch(pattern, os.environ.get(name, "")):
            print(f"pr-text: invalid {name}.", file=sys.stderr)
            return 1
    endpoint = f"repos/{os.environ['BASE_REPO']}/pulls/{os.environ['PR_NUMBER']}"
    try:
        result = subprocess.run(["gh", "api", endpoint], capture_output=True,
                                encoding="utf-8", check=True, timeout=60)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        print("pr-text: PR API failed or returned invalid UTF-8.", file=sys.stderr)
        return 1
    try:
        record = json.loads(result.stdout)
        if (not isinstance(record, dict) or not isinstance(record.get("title"), str)
                or "body" not in record
                or (record["body"] is not None and not isinstance(record["body"], str))):
            raise ValueError("PR record has missing fields or wrong types.")
        output = render(record["title"], record["body"] or "(empty)")
        sys.stdout.buffer.write(output.encode("utf-8"))
    except (ValueError, UnicodeError):
        print("pr-text: invalid PR JSON or title/body text.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
