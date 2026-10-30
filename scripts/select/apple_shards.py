#!/usr/bin/env python3
"""Discover XCTest methods and plan deterministic simulator shards.

The planner deliberately uses only the Python standard library so it can run
from a clean CI checkout before any project-specific dependencies are loaded.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
from typing import Dict, Iterable, List, Optional


LIVE_SKIP_MARKER = "XCTSkipUnless(ProcessInfo.processInfo.environment["
CLASS_PATTERN = re.compile(r"\bfinal\s+class\s+([A-Za-z_]\w*)\s*:")
METHOD_PATTERN = re.compile(r"\bfunc\s+(test\w+)\s*\(")


def _matching_brace(text: str, opening: int) -> int:
    """Return the closing brace for ``opening``, ignoring strings/comments."""
    depth = 0
    index = opening
    state = "normal"
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line_comment":
            if character == "\n":
                state = "normal"
        elif state == "block_comment":
            if character == "*" and following == "/":
                state = "normal"
                index += 1
        elif state == "string":
            if character == "\\":
                index += 1
            elif character == '"':
                state = "normal"
        else:
            if character == "/" and following == "/":
                state = "line_comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block_comment"
                index += 1
            elif character == '"':
                state = "string"
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return len(text)


def _swift_files(directory: pathlib.Path) -> Iterable[pathlib.Path]:
    return sorted(
        (path for path in directory.rglob("*.swift") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def _discover_file(path: pathlib.Path, target_name: str) -> List[str]:
    text = path.read_text(encoding="utf-8")
    discovered: List[str] = []
    for class_match in CLASS_PATTERN.finditer(text):
        opening = text.find("{", class_match.end())
        if opening < 0:
            continue
        closing = _matching_brace(text, opening)
        class_body = text[opening + 1:closing]
        class_name = class_match.group(1)
        for method_match in METHOD_PATTERN.finditer(class_body):
            method_opening = class_body.find("{", method_match.end())
            if method_opening < 0:
                continue
            method_closing = _matching_brace(class_body, method_opening)
            method_body = class_body[method_match.start():method_closing]
            if LIVE_SKIP_MARKER in method_body:
                continue
            discovered.append(f"{target_name}/{class_name}/{method_match.group(1)}")
    return discovered


def discover_xcuitests(root: pathlib.Path, ui_dir: str = "AppUITests") -> List[str]:
    """Return active final-class XCTest methods in deterministic source order."""
    target_name = pathlib.Path(ui_dir).name or "AppUITests"
    directory = root / ui_dir
    if not directory.exists():
        return []
    discovered: List[str] = []
    for path in _swift_files(directory):
        discovered.extend(_discover_file(path, target_name))
    return discovered


DEFAULT_DEVICES = ["iPhone 17 Pro", "iPad Pro 11-inch (M5)"]
DEFAULT_UNIT_TARGETS = [
    "SearchTelemetryTests",
    "SearchWallpaperFeatureTests",
    "SearchLocationFeatureTests",
    "SearchUITests",
    "SearchFeaturesTests",
    "AppTests",
]


def plan_apple_shards(
    root: pathlib.Path,
    *,
    ui_dir: str = "AppUITests",
    max_per_shard: int = 5,
    devices: Optional[List[str]] = None,
    unit_targets: Optional[List[str]] = None,
    skip_targets: Optional[List[str]] = None,
    skip_all: bool = False,
) -> Dict[str, object]:
    """Build a balanced per-device matrix with unit tests on shard zero."""
    clamped_max = max(1, int(max_per_shard))
    devices = DEFAULT_DEVICES if devices is None else devices
    unit_targets = DEFAULT_UNIT_TARGETS if unit_targets is None else unit_targets
    skip_set = set(skip_targets or [])
    target_name = pathlib.Path(ui_dir).name or "AppUITests"

    empty = {
        "skip_all_apple_tests": True,
        "max_per_shard": clamped_max,
        "ui_tests": [],
        "shard_count_per_device": 0,
        "shards": [],
    }
    if skip_all:
        return empty

    active_units = [target for target in unit_targets if target not in skip_set]
    ui_tests = [] if target_name in skip_set else discover_xcuitests(root, ui_dir)
    if not active_units and not ui_tests:
        return empty

    shard_count = math.ceil(len(ui_tests) / clamped_max) if ui_tests else 1
    shards: List[Dict[str, object]] = []
    for device in devices:
        for shard_index in range(shard_count):
            start = (shard_index * len(ui_tests)) // shard_count
            end = ((shard_index + 1) * len(ui_tests)) // shard_count
            ui_slice = ui_tests[start:end]
            unit_slice = active_units if shard_index == 0 else []
            targets = [*unit_slice, *ui_slice]
            if not targets:
                continue
            shards.append({
                "device": device,
                "shard_index": shard_index,
                "shard_total": shard_count,
                "name": f"{device} ({shard_index + 1}/{shard_count})",
                "only_test_targets": ",".join(targets),
            })

    return {
        "skip_all_apple_tests": not shards,
        "max_per_shard": clamped_max,
        "ui_tests": ui_tests,
        "shard_count_per_device": 0 if not shards else shard_count,
        "shards": shards,
    }


def _csv(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_github_output(path: pathlib.Path, plan: Dict[str, object]) -> None:
    matrix = {"include": plan["shards"]}
    with path.open("a", encoding="utf-8") as output:
        output.write(f"skip_all_apple_tests={'1' if plan['skip_all_apple_tests'] else '0'}\n")
        output.write(f"shards_matrix={json.dumps(matrix, ensure_ascii=False, separators=(',', ':'))}\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--ui-dir", default="AppUITests")
    parser.add_argument("--max-per-shard", type=int, default=5)
    parser.add_argument("--devices")
    parser.add_argument("--unit-targets")
    parser.add_argument("--skip-targets")
    parser.add_argument("--skip-all", action="store_true")
    parser.add_argument("--github-output", type=pathlib.Path)
    args = parser.parse_args(argv)
    plan = plan_apple_shards(
        args.root,
        ui_dir=args.ui_dir,
        max_per_shard=args.max_per_shard,
        devices=_csv(args.devices),
        unit_targets=_csv(args.unit_targets),
        skip_targets=_csv(args.skip_targets),
        skip_all=args.skip_all,
    )
    print(json.dumps(plan, ensure_ascii=False, separators=(",", ":")))
    if args.github_output is not None:
        _write_github_output(args.github_output, plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
