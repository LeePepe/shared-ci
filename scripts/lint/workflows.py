#!/usr/bin/env python3
"""workflow-lint: fail-closed checks for GitHub workflow files (stdlib only).

Rules (finding kind -> meaning):
  shared_ci_ref_not_sha   `uses: LeePepe/shared-ci/...@ref` whose ref is not a full 40-char SHA
  self_hosted_unguarded   job that may run on self-hosted without the job-level fork guard
  prt_checks_out_pr_code  pull_request_target workflow checking out PR head code
  runner_context_unavailable  runner context referenced at a workflow key that cannot use it
  workflow_unparseable    file outside the supported YAML subset (never silently skipped)

Usage: workflows.py [--root DIR] [FILE...]   (default: .github/workflows/*.y*ml)
Exit 0 clean, 1 findings, 2 usage error. Findings are JSON lines on stderr.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
SHA = re.compile(r"^[0-9a-f]{40}$")
GUARD = "github.event.pull_request.head.repo.full_name == github.repository"
# A self-hosted job may also run for non-PR events (push, dispatch) whose code is trusted.
GUARD_FORMS = {GUARD, f"github.event.pull_request == null || {GUARD}"}
SHARED_CI = re.compile(r"^leepepe/shared-ci(/|$)", re.IGNORECASE)
USES_LINE = re.compile(r"""^\s*(?:-\s*)?uses:\s*["']?([^\s"'#]+)""")
# Single-quoted expression strings may contain `}}` and escaped quotes (`''`).
EXPRESSION = re.compile(r"\$\{\{((?:'[^']*'|[^'])*?)\}\}", re.DOTALL)
EXPRESSION_TOKEN = re.compile(r"'[^']*'|[A-Za-z_][A-Za-z0-9_-]*|[^\s]")
RUNNER_STEP_KEYS = {"continue-on-error", "env", "if", "name", "run", "timeout-minutes",
                    "with", "working-directory"}


def _load_frontmatter() -> Any:
    path = HERE.parents[0] / "context" / "_frontmatter.py"
    spec = importlib.util.spec_from_file_location("shared_ci_frontmatter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fm = _load_frontmatter()


def finding(path: str, kind: str, detail: str) -> dict[str, Any]:
    return {"layer": "workflow", "path": path, "kind": kind, "detail": detail, "red_lines": []}


def _strip_expression(value: str) -> str:
    value = value.strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2]
    return " ".join(value.split())


def _unwrap(text: str) -> str:
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        for index, char in enumerate(text):
            depth += char == "("
            depth -= char == ")"
            if depth == 0 and index != len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def conjuncts(expression: str) -> list[str]:
    """Top-level `&&` operands (parentheses and quotes respected)."""
    text = _unwrap(_strip_expression(expression))
    parts, depth, quote, start, index = [], 0, "", 0, 0
    while index < len(text):
        char = text[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0 and text.startswith("&&", index):
            parts.append(text[start:index])
            start = index + 2
            index += 1
        index += 1
    parts.append(text[start:])
    return [" ".join(_unwrap(part).split()) for part in parts if part.strip()]


def has_fork_guard(condition: Any) -> bool:
    if not isinstance(condition, str):
        return False
    return any(part in GUARD_FORMS for part in conjuncts(condition))


def may_be_self_hosted(runs_on: Any) -> bool:
    """Literal self-hosted labels, groups and any expression count as possibly self-hosted."""
    if runs_on is None:
        return False  # Reusable-workflow call jobs; checked in the called workflow.
    if isinstance(runs_on, str):
        return "${{" in runs_on or runs_on.strip().lower() == "self-hosted"
    if isinstance(runs_on, list):
        return any(may_be_self_hosted(item) if isinstance(item, str) else True for item in runs_on)
    if isinstance(runs_on, dict):
        if "group" in runs_on:
            return True
        return may_be_self_hosted(runs_on.get("labels"))
    return True


def _triggers(data: dict[str, Any]) -> set[str]:
    on = data.get("on", data.get(True))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {item for item in on if isinstance(item, str)}
    if isinstance(on, dict):
        return {key for key in on if isinstance(key, str)}
    return set()


def _uses_findings(path: str, text: str) -> list[dict[str, Any]]:
    """Line-based so that refs inside any job/step shape are caught."""
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        match = USES_LINE.match(line)
        if not match:
            continue
        target = match.group(1)
        if not SHARED_CI.match(target):
            continue
        ref = target.rpartition("@")[2] if "@" in target else ""
        if not SHA.match(ref):
            findings.append(finding(f"{path}:{number}", "shared_ci_ref_not_sha",
                                    f"{target} must pin a full 40-char commit SHA, not {ref or 'no ref'!r}"))
    return findings


def _pr_head_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = _strip_expression(value)
    return bool(re.search(r"github\.event\.pull_request\.head\.(sha|ref)|github\.head_ref"
                          r"|refs/pull/", text))


def _references_runner(value: str, implicit: bool = False) -> bool:
    expressions = ([value] if implicit and "${{" not in value
                   else [match.group(1) for match in EXPRESSION.finditer(value)])
    for expression in expressions:
        previous = ""
        for token in EXPRESSION_TOKEN.findall(expression):
            if token.lower() == "runner" and previous != ".":
                return True
            previous = token
    return False


def _runner_available(keys: tuple[Any, ...]) -> bool:
    """Only runner availability from GitHub's workflow context table, not other contexts.

    https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
    """
    if len(keys) < 4 or keys[0] != "jobs":
        return False
    field = keys[2:]
    if field[0] == "steps" and len(field) >= 3 and isinstance(field[1], int):
        step_key = field[2]
        return (step_key in RUNNER_STEP_KEYS
                and len(field) == (4 if step_key in {"env", "with"} else 3))
    return ((field[0] == "outputs" and len(field) == 2)
            or field == ("environment", "url")
            or (len(field) == 3 and field[:2] == ("container", "env"))
            or (len(field) == 4 and field[0] == "services" and field[2] == "env"))


def _runner_findings(path: str, value: Any, keys: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [item for key, child in value.items()
                for item in _runner_findings(path, child, keys + (key,))]
    if isinstance(value, list):
        return [item for index, child in enumerate(value)
                for item in _runner_findings(path, child, keys + (index,))]
    # Job `if` also accepts an expression without ${{ }}.
    implicit = len(keys) == 3 and keys[0] == "jobs" and keys[2] == "if"
    if (isinstance(value, str) and not _runner_available(keys)
            and _references_runner(value, implicit)):
        location = ".".join(str(key) for key in keys)
        return [finding(f"{path}#{location}", "runner_context_unavailable",
                        f"runner context is not available at `{location}`")]
    return []


def lint_text(path: str, text: str) -> list[dict[str, Any]]:
    findings = _uses_findings(path, text)
    try:
        data = _fm.parse(text)
    except _fm.FrontmatterError as error:
        return findings + [finding(path, "workflow_unparseable", str(error))]
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        return findings + [finding(path, "workflow_unparseable", "no jobs mapping")]
    findings.extend(_runner_findings(path, data))
    target = "pull_request_target" in _triggers(data)
    for job_id, job in data["jobs"].items():
        if not isinstance(job, dict):
            findings.append(finding(f"{path}#{job_id}", "workflow_unparseable", "job is not a mapping"))
            continue
        if may_be_self_hosted(job.get("runs-on")) and not has_fork_guard(job.get("if")):
            findings.append(finding(
                f"{path}#{job_id}", "self_hosted_unguarded",
                f"job may run on self-hosted; add a top-level `if:` conjunct `{GUARD}`"))
        if target:
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or not str(step.get("uses", "")).startswith("actions/checkout"):
                    continue
                options = step.get("with") or {}
                if isinstance(options, dict) and (_pr_head_ref(options.get("ref"))
                                                  or _pr_head_ref(options.get("repository"))):
                    findings.append(finding(f"{path}#{job_id}", "prt_checks_out_pr_code",
                                            "pull_request_target must not check out PR head code"))
    return findings


def default_files(root: pathlib.Path) -> list[pathlib.Path]:
    directory = root / ".github" / "workflows"
    return sorted(p for p in directory.glob("*") if p.suffix in (".yml", ".yaml") and p.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workflow-lint")
    parser.add_argument("--root", default=".")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    files = [root / name for name in args.files] if args.files else default_files(root)
    if not files:
        print(json.dumps({"ok": False, "files": 0, "findings": 1}))
        print(json.dumps(finding(".github/workflows", "workflow_unparseable", "no workflow files")),
              file=sys.stderr)
        return 1
    findings: list[dict[str, Any]] = []
    for file in files:
        relative = file.relative_to(root).as_posix() if file.is_relative_to(root) else str(file)
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            findings.append(finding(relative, "workflow_unparseable", f"cannot read: {error}"))
            continue
        findings.extend(lint_text(relative, text))
    for item in findings:
        print(json.dumps(item, ensure_ascii=False), file=sys.stderr)
    print(json.dumps({"ok": not findings, "files": len(files), "findings": len(findings)}))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
