#!/usr/bin/env python3
"""Render trusted architecture facts for the review prompt (stdlib only).

Run with cwd inside the caller's *base* checkout (trusted tree). Changed paths
arrive on stdin, one per line. For each path it reports the owning layer via
the shared-ci resolver; for each touched layer it reports depends_on and
red lines, plus the full allowed dependency direction. Nothing from the PR
head is executed or parsed here. Resolver failures are reported as text so the
reviewer can flag them; they never crash the review.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
MAX_PATHS = 400


def _context() -> Any:
    path = HERE.parent / "context" / "_context.py"
    spec = importlib.util.spec_from_file_location("shared_ci_context", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def render(paths: list[str]) -> str:
    ctx = _context()
    lines = ["Layer ownership was computed by the shared-ci resolver on the trusted base tree.",
             "Paths that did not exist on base resolve by pattern; a PR that edits layer maps is",
             "reviewed against the base map.", ""]
    try:
        root = ctx.repo_root()
        layers = ctx.layer_map(root)
    except Exception as error:  # noqa: BLE001 - reported to reviewer, never fatal
        return "\n".join(lines + [f"Layer map unavailable on base: {error}",
                                  "Report this as a note; the contract audit lane enforces the map."])
    touched: dict[str, list[str]] = {}
    lines.append("Changed path -> layer:")
    for path in paths[:MAX_PATHS]:
        try:
            result = ctx.resolve(root, path)
        except Exception as error:  # noqa: BLE001
            lines.append(f"- {path} -> UNMAPPED ({error})")
            continue
        if result.classification == "leaf":
            touched.setdefault(result.layer, []).append(path)
            lines.append(f"- {path} -> {result.layer}")
        else:
            lines.append(f"- {path} -> excluded ({result.reason})")
    if len(paths) > MAX_PATHS:
        lines.append(f"- ... {len(paths) - MAX_PATHS} more paths omitted")
    lines += ["", "Allowed dependency direction (layer -> may depend on):"]
    for name in sorted(layers):
        deps = layers[name].get("dependencies", [])
        lines.append(f"- {name} -> {', '.join(deps) if deps else '(nothing)'}")
    lines += ["", "Red lines of touched layers:"]
    for name in sorted(touched):
        for red in layers[name].get("red_lines", []):
            lines.append(f"- {name}: {red}")
    if len(touched) > 1:
        lines += ["", f"This PR touches {len(touched)} layers: {', '.join(sorted(touched))}."]
    return "\n".join(lines)


def main() -> int:
    paths = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    sys.stdout.write(render(paths) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
