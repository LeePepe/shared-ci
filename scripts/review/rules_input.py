#!/usr/bin/env python3
"""Read complete review rules from one regular blob in the exact trusted base."""
from __future__ import annotations

import os
import re
import subprocess
import sys

MAX_BYTES = 24000
SHA = re.compile(r"[0-9a-f]{40}")


def _git(*args: str) -> bytes:
    # Local replacement refs must not substitute another tree for the trusted SHA.
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1")
    result = subprocess.run(["git", "--literal-pathspecs", *args], env=env,
                            capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise ValueError("cannot read trusted base rules from Git")
    return result.stdout


def read_rules(base: str, path: str) -> bytes:
    if not SHA.fullmatch(base):
        raise ValueError("BASE_SHA must be a full lowercase commit SHA")
    if (not path or path.startswith("/") or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in path)):
        raise ValueError("rules path must be a literal repository-relative file path")
    if _git("cat-file", "-t", base).strip() != b"commit":
        raise ValueError("BASE_SHA must identify a commit")
    entry = _git("ls-tree", "-z", "--full-tree", base, "--", path)
    records = entry.split(b"\0")
    if len(records) != 2 or records[-1] != b"":
        raise ValueError("rules file is missing from the trusted base")
    metadata, separator, name = records[0].partition(b"\t")
    fields = metadata.split()
    if (not separator or name != path.encode("utf-8") or len(fields) != 3
            or fields[0] not in (b"100644", b"100755") or fields[1] != b"blob"):
        raise ValueError("rules must be a regular file in the trusted base")
    blob = fields[2].decode("ascii")
    if not SHA.fullmatch(blob):
        raise ValueError("invalid rules blob identity")
    size = int(_git("cat-file", "-s", blob))
    if not 0 < size <= MAX_BYTES:
        raise ValueError(f"rules must contain 1..{MAX_BYTES} bytes; policy is never truncated")
    data = _git("cat-file", "blob", blob)
    text = data.decode("utf-8")
    if len(data) != size or not text.strip():
        raise ValueError("rules must contain nonempty text")
    if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159 for char in text):
        raise ValueError("rules must be text without binary control characters")
    return data


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: rules_input.py BASE_SHA RULES_PATH", file=sys.stderr)
        return 2
    try:
        data = read_rules(sys.argv[1], sys.argv[2])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"review rules unavailable: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
