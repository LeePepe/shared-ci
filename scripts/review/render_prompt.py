#!/usr/bin/env python3
"""Render the review prompt template by single-pass placeholder substitution.

Placeholder values come from environment variables or admitted input files,
and the template is never evaluated by a shell. Injected values containing
`{{...}}` are not substituted again. Missing template or placeholder -> exit
non-zero so the caller fails closed. Adapted from VoxPocket scripts/ci.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

PLACEHOLDERS = ("REPO_RULES", "ARCHITECTURE", "OWNER_DECISIONS", "CHANGED", "TRUNCATED", "DIFF")
REQUIRED = ("REPO_RULES", "ARCHITECTURE", "CHANGED", "DIFF")
OWNER_DEFAULT = "(Owner decision input is not configured for this repository.)"


def render(template: str, values: dict[str, str]) -> str:
    missing = [name for name in REQUIRED if "{{" + name + "}}" not in template]
    if missing:
        raise ValueError("template is missing placeholder(s): " + ", ".join(missing))
    values = {"OWNER_DECISIONS": OWNER_DEFAULT, **values}
    rendered = re.sub(r"\{\{(" + "|".join(PLACEHOLDERS) + r")\}\}",
                      lambda match: values.get(match.group(1), ""), template)
    return rendered.encode("utf-8", "replace").decode("utf-8")


def main() -> int:
    allowed = {"--rules-file": "REPO_RULES", "--owner-file": "OWNER_DECISIONS"}
    args = sys.argv[2:]
    if (len(sys.argv) < 2 or len(args) % 2
            or any(arg not in allowed for arg in args[::2])
            or len(set(args[::2])) != len(args[::2])):
        print(f"usage: {sys.argv[0]} <template.md> [--rules-file FILE] [--owner-file FILE]", file=sys.stderr)
        return 2
    options = dict(zip(args[::2], args[1::2]))
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        print(f"render-prompt: template not found: {path}", file=sys.stderr)
        return 2
    try:
        values = {name: os.environ.get(name, "") for name in PLACEHOLDERS if name != "OWNER_DECISIONS"}
        for option, filename in options.items():
            # Preserve exact newlines; shell command substitution strips them.
            values[allowed[option]] = pathlib.Path(filename).read_bytes().decode("utf-8")
        output = render(path.read_text(encoding="utf-8"), values)
    except (ValueError, OSError) as error:
        print(f"render-prompt: {error}", file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
