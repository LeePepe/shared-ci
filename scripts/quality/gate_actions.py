#!/usr/bin/env python3
"""Actions adapter: build gate input from quality.yml's environment and run it.

Reads NEEDS_JSON (toJSON(needs)), <LANE>_SELECTED flags, EXPECTED_SHA, EVENT and,
for pull requests, live head-bound PR metadata through the REST API. The full
PR size is checked even when body validation is disabled; edited bodies are
honoured on re-run. When NEEDS_JSON has a `select` job (quality.yml
v0.2.0+), the selection record (its `selection` output) and each lane's `ran`
output are passed to the gate. Any missing/malformed input fails closed.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LANES = ("verify", "lint", "build", "test", "contract", "workflow-lint")
LAYER_LANES = ("verify", "lint", "build", "test")
MAX_PR_LINES = 400
MAX_PR_FILES = 10


def _gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("shared_ci_gate", HERE / "gate.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    data = json.loads((HERE.parents[1] / "schemas" / "repo-contract-v1.json").read_text(encoding="utf-8"))
    return data["x-contract"]


def _flag(name: str) -> bool:
    value = os.environ.get(name, "")
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be 'true' or 'false', got {value!r}")
    return value == "true"


def _checked_pr_body(env: dict[str, str]) -> str:
    """Fetch once, require current-head whole-PR size evidence, then return body."""
    number, repo, token = env.get("PR_NUMBER", ""), env.get("REPO", ""), env.get("GH_TOKEN", "")
    if not number or not repo or not token:
        raise ValueError("PR metadata unavailable: PR_NUMBER, REPO and GH_TOKEN are required")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{number}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https host
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("PR metadata must be an object")
    head = data.get("head")
    expected = env.get("EXPECTED_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", expected) or not isinstance(head, dict) or head.get("sha") != expected:
        raise ValueError("PR head missing, malformed or moved; this run's evidence is stale")
    for field in ("additions", "deletions", "changed_files"):
        value = data.get(field)
        if type(value) is not int or value < 0:
            raise ValueError(f"PR {field} must be a nonnegative integer")
    lines = data["additions"] + data["deletions"]
    files = data["changed_files"]
    if lines > MAX_PR_LINES or files > MAX_PR_FILES:
        raise ValueError(f"PR size exceeds budget: {lines} changed lines (limit {MAX_PR_LINES}), "
                         f"{files} files (limit {MAX_PR_FILES}); return to TL for reslicing")
    return data.get("body") or ""


def build_input(env: dict[str, str], needs: dict, pr_body: str | None) -> dict:
    contract = _contract()
    lanes = {}
    for lane in LANES:
        key = lane.upper().replace("-", "_") + "_SELECTED"
        need = needs.get(lane)
        lanes[lane] = {
            "selected": _flag(key),
            "result": (need or {}).get("result", "unknown"),
            "tested_sha": ((need or {}).get("outputs") or {}).get("tested-sha", ""),
        }
    data = {
        "lanes": lanes, "expected_lanes": list(LANES), "expected_sha": env.get("EXPECTED_SHA", ""),
        "event": env.get("EVENT", ""), "check_pr_body": _flag("CHECK_PR_BODY"),
        "pr_body": pr_body, "required_sections": contract["pr_sections"],
    }
    if "select" in needs:
        data["selection"] = _selection(needs["select"])
        data["layer_lanes"] = list(LAYER_LANES)
        for lane in LANES:
            ran = ((needs.get(lane) or {}).get("outputs") or {}).get("ran", "")
            lanes[lane]["ran"] = ran == "true"
    return data


def _selection(need: dict) -> dict:
    """Selection record from the select job; unparseable output fails closed."""
    if not isinstance(need, dict):
        raise ValueError("select job result is missing")
    raw = ((need.get("outputs") or {}).get("selection") or "")
    record = {"mode": "changed-only", "full": True, "any_layer": True, "layers": [],
              "reason": "select job produced no selection", "head": ""}
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("select job selection output is not an object")
        record.update({key: parsed[key] for key in record if key in parsed})
    record["result"] = need.get("result", "unknown")
    return record


def main() -> int:
    env = dict(os.environ)
    gate = _gate()
    try:
        needs = json.loads(env.get("NEEDS_JSON") or "null")
        if not isinstance(needs, dict):
            raise ValueError("NEEDS_JSON is missing")
        body = None
        if env.get("EVENT") in ("pull_request", "pull_request_target"):
            body = _checked_pr_body(env)
        result = gate.evaluate(build_input(env, needs, body))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"::error::aggregate input invalid: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"## quality / aggregate: {result['verdict']}\n\n")
            selection = result.get("selection")
            if selection:
                handle.write(f"Selection ({selection['mode']}): {selection.get('reason') or ''}; "
                             f"layers: {', '.join(selection.get('layers') or []) or '(none)'}\n\n")
            handle.write("| lane | selected | ran | result | tested SHA |\n|---|---|---|---|---|\n")
            for row in result["lanes"]:
                handle.write(f"| {row['lane']} | {row['selected']} | {row.get('ran', '')} | "
                             f"{row['result']} | {row['tested_sha']} |\n")
            for problem in result["problems"]:
                handle.write(f"\n- {problem}")
    for problem in result["problems"]:
        print(f"::error::{problem}", file=sys.stderr)
    if result["verdict"] == "pass" and env.get("GITHUB_OUTPUT"):
        with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(f"tested-sha={result['tested_sha']}\n")
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
