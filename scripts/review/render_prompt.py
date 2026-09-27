#!/usr/bin/env python3
"""Render the review prompt template by single-pass placeholder substitution.

Placeholder values come from environment variables or a validated rules file,
and the template is never evaluated by a shell. Injected values containing
`{{...}}` are not substituted again. Missing template or placeholder -> exit
non-zero so the caller fails closed. Adapted from VoxPocket scripts/ci.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

PLACEHOLDERS = ("REPO_RULES", "ARCHITECTURE", "CHANGED", "TRUNCATED", "DIFF")
REQUIRED = ("REPO_RULES", "ARCHITECTURE", "CHANGED", "DIFF")


def render(template: str, values: dict[str, str]) -> str:
    missing = [name for name in REQUIRED if "{{" + name + "}}" not in template]
    if missing:
        raise ValueError("template is missing placeholder(s): " + ", ".join(missing))
    rendered = re.sub(r"\{\{(" + "|".join(PLACEHOLDERS) + r")\}\}",
                      lambda match: values.get(match.group(1), ""), template)
    return rendered.encode("utf-8", "replace").decode("utf-8")


def main() -> int:
    if len(sys.argv) not in (2, 4) or (len(sys.argv) == 4 and sys.argv[2] != "--rules-file"):
        print(f"usage: {sys.argv[0]} <template.md> [--rules-file FILE]", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        print(f"render-prompt: template not found: {path}", file=sys.stderr)
        return 2
    try:
        values = {name: os.environ.get(name, "") for name in PLACEHOLDERS}
        if len(sys.argv) == 4:
            # Preserve exact newlines; shell command substitution strips them.
            values["REPO_RULES"] = pathlib.Path(sys.argv[3]).read_bytes().decode("utf-8")
        output = render(path.read_text(encoding="utf-8"), values)
    except (ValueError, OSError) as error:
        print(f"render-prompt: {error}", file=sys.stderr)
        return 3
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
