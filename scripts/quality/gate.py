#!/usr/bin/env python3
"""Fail-closed aggregate gate for quality.yml (stdlib only, deterministic).

Pass only when ALL hold:
  * every selected lane result is `success` and reported tested-sha == expected SHA
  * every unselected lane result is `success` or `skipped`
  * at least one lane is selected, the lane set is exactly the expected set
  * expected SHA (PR head, or push SHA) is a full 40-char SHA
  * for pull requests, every required PR-template section exists and is filled

Anything else (failure, cancelled, unknown/empty result, unexpected skip, SHA
drift, missing lane, placeholder-only section) fails. Input is one JSON object
(file or stdin): {"lanes": {name: {"selected": bool, "result": str,
"tested_sha": str, "ran": bool}}, "expected_lanes": [...], "expected_sha": str,
"event": str, "check_pr_body": bool, "pr_body": str|null,
"required_sections": [...], "selection": {...}, "layer_lanes": [...]}.

Changed-layer selection (optional `selection`, v0.2.0+). `selection` records
the `select` job: {"mode": "changed-only"|"disabled", "result": str,
"full": bool, "any_layer": bool, "layers": [...], "reason": str, "head": str}.
When present, every lane reports `ran` (did its real steps execute) and:
  * the select job result must be `success`; a changed-only selection must be
    computed for the expected SHA;
  * a selected lane that the selection requires (non-layer lanes always, layer
    lanes when `any_layer`) must have ran=true, result success, tested SHA ok;
  * a selected layer lane the selection short-circuits must be `success` and
    report the expected SHA (it may also have run in full);
  * unselected lanes keep the success|skipped rule.
Without `selection` the v0.1.0 rules apply unchanged.
Output: JSON verdict on stdout; exit 0 pass, 1 fail, 2 malformed input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

SHA = re.compile(r"^[0-9a-f]{40}$")
UNSELECTED_OK = {"success", "skipped"}
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER = re.compile(r"^\s*(?:[-*]\s*)?(?:\[[ xX]?\]\s*)?(?:todo|tbd|n/?a\s*$|\.\.\.|_+|<[^>]*>)?\s*[:：]?\s*$",
                          re.IGNORECASE)


def section_bodies(markdown: str) -> dict[str, str]:
    """Map lower-cased `##`/`###` heading text to its body (comments removed)."""
    bodies: dict[str, str] = {}
    current = None
    for line in _COMMENT.sub("", markdown.replace("\r\n", "\n")).split("\n"):
        heading = re.match(r"^#{2,3}\s+(.*?)\s*#*\s*$", line)
        if heading:
            current = heading.group(1).strip().lower()
            bodies.setdefault(current, "")
            continue
        if current is not None:
            bodies[current] += line + "\n"
    return bodies


def section_filled(body: str) -> bool:
    """True when the body has at least one line that is not template placeholder."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") and set(stripped) <= set("|-: "):
            continue
        if _PLACEHOLDER.match(stripped):
            continue
        # A bare label such as "Tested SHA:" is still empty.
        if re.match(r"^[-*]?\s*[\w /()-]{1,40}[:：]\s*(?:`?\s*`?)?$", stripped):
            continue
        return True
    return False


def check_pr_body(body: str | None, required: list[str], expected_sha: str) -> list[str]:
    if body is None or not body.strip():
        return ["PR body is empty; fill the pull request template"]
    problems = []
    bodies = section_bodies(body)
    for title in required:
        key = title.strip().lower()
        match = next((name for name in bodies if name.startswith(key)), None)
        if match is None:
            problems.append(f"PR body is missing section '## {title}'")
        elif not section_filled(bodies[match]):
            problems.append(f"PR body section '## {title}' is empty or placeholder-only")
    evidence = next((text for name, text in bodies.items() if name.startswith("test evidence")), "")
    shas = set(re.findall(r"\b[0-9a-f]{40}\b", evidence))
    if evidence and shas and expected_sha not in shas:
        problems.append("Test evidence names a SHA that is not the PR head; new pushes invalidate old evidence")
    return problems


def _validate(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("input must be an object")
    lanes = data.get("lanes")
    expected = data.get("expected_lanes")
    if not isinstance(lanes, dict) or not isinstance(expected, list) or not expected:
        raise ValueError("lanes must be an object and expected_lanes a non-empty list")
    for name, lane in lanes.items():
        if not isinstance(lane, dict) or not isinstance(lane.get("selected"), bool):
            raise ValueError(f"lane {name!r} needs a boolean 'selected'")
    if not isinstance(data.get("expected_sha"), str):
        raise ValueError("expected_sha must be a string")
    if not isinstance(data.get("check_pr_body", True), bool):
        raise ValueError("check_pr_body must be a boolean")
    if "selection" in data:
        selection = data["selection"]
        if not isinstance(selection, dict) or selection.get("mode") not in ("changed-only", "disabled"):
            raise ValueError("selection must be an object with mode changed-only|disabled")
        for key in ("full", "any_layer"):
            if not isinstance(selection.get(key), bool):
                raise ValueError(f"selection.{key} must be a boolean")
        if not isinstance(selection.get("layers"), list) or any(
                not isinstance(item, str) for item in selection["layers"]):
            raise ValueError("selection.layers must be a string list")
        layer_lanes = data.get("layer_lanes")
        if not isinstance(layer_lanes, list) or any(not isinstance(item, str) for item in layer_lanes):
            raise ValueError("layer_lanes must be a string list when selection is present")
        for name, lane in lanes.items():
            if not isinstance(lane.get("ran"), bool):
                raise ValueError(f"lane {name!r} needs a boolean 'ran' when selection is present")
    sections = data.get("required_sections", [])
    if not isinstance(sections, list) or any(not isinstance(s, str) for s in sections):
        raise ValueError("required_sections must be a string list")
    return data


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    data = _validate(data)
    lanes: dict[str, dict[str, Any]] = data["lanes"]
    expected_sha = data["expected_sha"]
    problems: list[str] = []
    if not SHA.match(expected_sha):
        problems.append(f"expected SHA {expected_sha!r} is not a full 40-char SHA")
    names = set(lanes)
    wanted = set(data["expected_lanes"])
    for missing in sorted(wanted - names):
        problems.append(f"lane {missing} reported no result")
    for extra in sorted(names - wanted):
        problems.append(f"unexpected lane {extra}")
    selected = [name for name in sorted(names) if lanes[name]["selected"]]
    if not selected:
        problems.append("no lane was selected; an empty gate cannot pass")
    selection = data.get("selection")
    if selection is not None:
        problems.extend(_selection_problems(selection, expected_sha))
    rows = []
    for name in sorted(names):
        lane = lanes[name]
        result = str(lane.get("result") or "unknown")
        tested = str(lane.get("tested_sha") or "")
        row = {"lane": name, "selected": lane["selected"], "result": result, "tested_sha": tested}
        rows.append(row)
        if selection is not None:
            required = name not in data["layer_lanes"] or selection["any_layer"]
            row.update(ran=lane["ran"], required_by_selection=required)
            if lane["selected"] and required and not lane["ran"]:
                problems.append(f"selected lane {name} short-circuited but the selection requires it "
                                f"({selection.get('reason') or 'no reason'})")
                continue
        if lane["selected"]:
            if result != "success":
                problems.append(f"selected lane {name} result is {result!r}, expected 'success'")
            elif tested != expected_sha:
                problems.append(f"selected lane {name} tested {tested or 'no SHA'}, expected {expected_sha}")
        elif result not in UNSELECTED_OK:
            problems.append(f"unselected lane {name} result is {result!r}, expected success or skipped")
    if data.get("check_pr_body", True) and data.get("event") in ("pull_request", "pull_request_target"):
        problems.extend(check_pr_body(data.get("pr_body"), data.get("required_sections", []), expected_sha))
    verdict = "pass" if not problems else "fail"
    output = {"verdict": verdict, "tested_sha": expected_sha if verdict == "pass" else "",
              "lanes": rows, "problems": problems}
    if selection is not None:
        output["selection"] = {key: selection.get(key) for key in
                               ("mode", "result", "full", "any_layer", "layers", "reason", "head")}
        output["short_circuited"] = [row["lane"] for row in rows if row["selected"] and not row["ran"]]
    return output


def _selection_problems(selection: dict[str, Any], expected_sha: str) -> list[str]:
    problems = []
    result = str(selection.get("result") or "unknown")
    if result != "success":
        problems.append(f"select job result is {result!r}, expected 'success'")
    if selection["mode"] == "changed-only":
        head = str(selection.get("head") or "")
        if head != expected_sha:
            problems.append(f"selection was computed for {head or 'no SHA'}, expected {expected_sha}")
        if selection["full"] and not selection["any_layer"]:
            problems.append("selection is full but selects no layer lane")
    elif not selection["full"] or not selection["any_layer"]:
        problems.append("disabled selection must be a full run")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality-gate")
    parser.add_argument("input", nargs="?", help="JSON file (default: stdin)")
    args = parser.parse_args(argv)
    try:
        raw = open(args.input, encoding="utf-8").read() if args.input else sys.stdin.read()
        result = evaluate(json.loads(raw))
    except (OSError, ValueError) as error:
        print(json.dumps({"verdict": "fail", "tested_sha": "", "lanes": [],
                          "problems": [f"malformed gate input: {error}"]}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for problem in result["problems"]:
        print(f"::error::{problem}", file=sys.stderr)
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
