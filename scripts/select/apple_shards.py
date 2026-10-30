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
CLASS_PATTERN = re.compile(
    r"\b(?:final\s+)?class\s+([A-Za-z_]\w*)\s*:\s*([^{}]+?)\s*\{",
    re.MULTILINE,
)
EXTENSION_PATTERN = re.compile(
    r"\bextension\s+([A-Za-z_]\w*)(?:\s*:[^{]+)?\s*\{",
    re.MULTILINE,
)
METHOD_PATTERN = re.compile(r"\bfunc\s+(test\w+)\s*\(")


def _matching_brace(text: str, opening: int) -> int:
    """Return the closing brace for ``opening``, ignoring strings/comments."""
    if opening < 0 or opening >= len(text) or text[opening] != "{":
        return -1
    depth = 0
    index = opening
    state = "normal"
    block_comment_depth = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line_comment":
            if character == "\n":
                state = "normal"
        elif state == "block_comment":
            if character == "/" and following == "*":
                block_comment_depth += 1
                index += 1
            elif character == "*" and following == "/":
                block_comment_depth -= 1
                if block_comment_depth == 0:
                    state = "normal"
                index += 1
        elif state == "string":
            if character == "\\":
                index += 1
            elif character == '"':
                state = "normal"
        elif state == "multiline_string":
            if text.startswith('"""', index):
                state = "normal"
                index += 2
        else:
            if character == "/" and following == "/":
                state = "line_comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block_comment"
                block_comment_depth = 1
                index += 1
            elif text.startswith('"""', index):
                state = "multiline_string"
                index += 2
            elif character == '"':
                state = "string"
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    return -1


def _balanced_braces(text: str) -> bool:
    """Return whether braces are balanced outside strings and comments."""
    depth = 0
    index = 0
    state = "normal"
    block_comment_depth = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "line_comment":
            if character == "\n":
                state = "normal"
        elif state == "block_comment":
            if character == "/" and following == "*":
                block_comment_depth += 1
                index += 1
            elif character == "*" and following == "/":
                block_comment_depth -= 1
                if block_comment_depth == 0:
                    state = "normal"
                index += 1
        elif state == "string":
            if character == "\\":
                index += 1
            elif character == '"':
                state = "normal"
        elif state == "multiline_string":
            if text.startswith('"""', index):
                state = "normal"
                index += 2
        else:
            if character == "/" and following == "/":
                state = "line_comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block_comment"
                block_comment_depth = 1
                index += 1
            elif text.startswith('"""', index):
                state = "multiline_string"
                index += 2
            elif character == '"':
                state = "string"
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth < 0:
                    return False
        index += 1
    return depth == 0 and state in {"normal", "line_comment"}


def _swift_files(directory: pathlib.Path) -> Iterable[pathlib.Path]:
    return sorted(
        (path for path in directory.rglob("*.swift") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def _is_test_class(inheritance: str) -> bool:
    return any(
        token == "XCTestCase" or token.endswith("TestBase") or token.endswith("Tests")
        for token in re.findall(r"[A-Za-z_]\w*", inheritance)
    )


def discover_xcuitests(root: pathlib.Path, ui_dir: str = "AppUITests") -> List[str]:
    """Return active XCTest methods, or the whole target when discovery is uncertain."""
    target_name = pathlib.Path(ui_dir).name or "AppUITests"
    directory = root / ui_dir
    if not directory.exists():
        return []
    try:
        swift_files = list(_swift_files(directory))
    except OSError:
        return [target_name]
    if not swift_files:
        return []

    sources: List[tuple[pathlib.Path, str]] = []
    try:
        for path in swift_files:
            sources.append((path, path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError):
        return [target_name]

    if any(not _balanced_braces(text) for _, text in sources):
        return [target_name]

    test_class_names = set()
    for _, text in sources:
        for class_match in CLASS_PATTERN.finditer(text):
            if _is_test_class(class_match.group(2)):
                test_class_names.add(class_match.group(1))

    bodies: List[tuple[int, int, str, int, int]] = []
    for file_index, (_, text) in enumerate(sources):
        for class_match in CLASS_PATTERN.finditer(text):
            class_name = class_match.group(1)
            if class_name not in test_class_names:
                continue
            opening = class_match.end() - 1
            closing = _matching_brace(text, opening)
            if closing < 0:
                return [target_name]
            bodies.append((file_index, class_match.start(), class_name, opening, closing))
        for extension_match in EXTENSION_PATTERN.finditer(text):
            class_name = extension_match.group(1)
            if class_name not in test_class_names:
                continue
            opening = extension_match.end() - 1
            closing = _matching_brace(text, opening)
            if closing < 0:
                return [target_name]
            bodies.append((file_index, extension_match.start(), class_name, opening, closing))
    bodies.sort(key=lambda body: (body[0], body[1]))

    discovered: List[str] = []
    for file_index, (_, text) in enumerate(sources):
        file_bodies = [body for body in bodies if body[0] == file_index]
        for method_match in METHOD_PATTERN.finditer(text):
            containing = next(
                (
                    body
                    for body in file_bodies
                    if body[3] < method_match.start() < body[4]
                ),
                None,
            )
            if containing is None:
                return [target_name]
            method_opening = text.find("{", method_match.end())
            if method_opening < 0:
                return [target_name]
            method_closing = _matching_brace(text, method_opening)
            if method_closing < 0:
                return [target_name]
            if LIVE_SKIP_MARKER in text[method_match.start():method_closing]:
                continue
            discovered.append(
                f"{target_name}/{containing[2]}/{method_match.group(1)}"
            )

    return discovered or [target_name]


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
    devices = (
        list(DEFAULT_DEVICES)
        if devices is None
        else [d.strip() for d in devices if d and d.strip()]
    )
    if not devices:
        raise ValueError("devices must not be empty")
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
    parsed_devices = None if args.devices is None else _csv(args.devices)
    plan = plan_apple_shards(
        args.root,
        ui_dir=args.ui_dir,
        max_per_shard=args.max_per_shard,
        devices=parsed_devices,
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
