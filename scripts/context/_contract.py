"""Repository contract v1 checks that are decidable from the caller's Git tree.

Parameters (limits, required PR sections, forbidden patterns, shared library
names) come from `schemas/repo-contract-v1.json` in this same shared-ci checkout,
so documentation, schema and checker cannot drift apart. Every finding uses the
schema-1 finding shape with layer `contract` and kind `contract_<item>`.
Items 3 and 5 are partly enforced elsewhere (workflow-lint, ruleset readback).
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
CONTRACT_FILE = HERE.parents[1] / "schemas" / "repo-contract-v1.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
USES = re.compile(r"""^\s*-?\s*uses:\s*["']?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/([^@\s"']+)@([^\s"'#]+)""")
POINTER = re.compile(
    r"(?:github\.com/LeePepe/shared-ci/blob/|LeePepe/shared-ci@)([0-9A-Za-z._/-]+?)/ai/agent-protocol\.md",
    re.IGNORECASE)


def load_contract() -> dict[str, Any]:
    data = json.loads(CONTRACT_FILE.read_text(encoding="utf-8"))
    return data["x-contract"]


def _git_files(root: pathlib.Path) -> dict[str, str]:
    """Tracked path -> git mode (e.g. 100644, 100755, 120000)."""
    result = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=root,
                            capture_output=True, check=False)
    if result.returncode != 0:
        return {}
    files = {}
    for item in result.stdout.split(b"\0"):
        if not item:
            continue
        meta, _, path = item.partition(b"\t")
        files[path.decode("utf-8", errors="surrogateescape")] = meta.split(b" ")[0].decode()
    return files


def _text(root: pathlib.Path, path: str, limit: int = 2_000_000) -> str | None:
    target = root / path
    try:
        if target.is_symlink() or not target.is_file() or target.stat().st_size > limit:
            return None
        raw = target.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", errors="replace")


def section(markdown: str, title: str) -> str | None:
    """Body of the `## title` section (case-insensitive prefix match), else None."""
    lines = markdown.splitlines()
    wanted = title.strip().lower()
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,3})\s+(.*?)\s*#*\s*$", line)
        if match and match.group(2).strip().lower().startswith(wanted):
            level = len(match.group(1))
            body = []
            for following in lines[index + 1:]:
                heading = re.match(r"^(#{1,6})\s", following)
                if heading and len(heading.group(1)) <= level:
                    break
                body.append(following)
            return "\n".join(body)
    return None


def workflow_refs(root: pathlib.Path, files: dict[str, str]) -> list[tuple[str, int, str, str]]:
    """(file, line, path, ref) for every `uses: LeePepe/shared-ci/...@ref`."""
    refs = []
    for path in sorted(files):
        if not re.match(r"^\.github/workflows/[^/]+\.ya?ml$", path):
            continue
        text = _text(root, path) or ""
        for number, line in enumerate(text.splitlines(), 1):
            match = USES.match(line)
            if match and match.group(1).lower() == "leepepe" and match.group(2).lower() == "shared-ci":
                refs.append((path, number, match.group(3), match.group(4)))
    return refs


class _Report:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.findings: list[Any] = []

    def add(self, item: str, path: str, detail: str) -> None:
        self.findings.append(self.ctx.Finding("contract", path, "contract_" + item, detail))


def _agents(report: _Report, root: pathlib.Path, contract: dict, refs: list) -> str:
    text = _text(root, "AGENTS.md")
    if text is None:
        report.add("agents", "AGENTS.md", "AGENTS.md is missing")
        return ""
    limit = contract["agents_max_lines"]
    count = len(text.splitlines())
    if count > limit:
        report.add("agents", "AGENTS.md", f"{count} lines exceeds {limit}")
    pointers = POINTER.findall(text)
    if not pointers:
        report.add("agents", "AGENTS.md", "missing protocol pointer to shared-ci@<40-char SHA>/ai/agent-protocol.md")
    for pointer in pointers:
        if not SHA.match(pointer):
            report.add("agents", "AGENTS.md", f"protocol pointer {pointer!r} is not a full 40-char SHA")
    caller = {ref for _, _, _, ref in refs}
    if pointers and caller and set(pointers) != caller:
        report.add("agents", "AGENTS.md",
                   f"protocol pointer {sorted(set(pointers))} differs from workflow pins {sorted(caller)}")
    for title in contract["agents_sections"]:
        if section(text, title) is None:
            report.add("agents", "AGENTS.md", f"missing section '## {title}'")
    return text


def _required_checks(agents: str) -> list[str]:
    body = section(agents, "Required checks") or ""
    return [name for name in re.findall(r"`([^`]+)`", body) if name.strip()]


def _agent_files(report: _Report, root: pathlib.Path, contract: dict, agents: str) -> None:
    checks = _required_checks(agents)
    for path in contract["agent_files"]:
        text = _text(root, path)
        if text is None:
            continue
        if "AGENTS.md" not in text:
            report.add("agent_files", path, "must defer to AGENTS.md")
        count = len([line for line in text.splitlines() if line.strip()])
        if count > contract["agent_file_max_lines"]:
            report.add("agent_files", path, f"{count} non-empty lines; keep tool-specific notes only")
        if POINTER.search(text) or re.search(r"shared-ci[^\n]*@[0-9a-f]{40}", text):
            report.add("agent_files", path, "duplicates the shared-ci pin; it belongs in AGENTS.md only")
        for name in checks:
            if f"`{name}`" in text:
                report.add("agent_files", path, f"duplicates required check {name!r} from AGENTS.md")


def _ci(report: _Report, root: pathlib.Path, files: dict, refs: list) -> None:
    ci_files = [p for p in (".github/workflows/ci.yml", ".github/workflows/ci.yaml") if p in files]
    if not ci_files:
        report.add("ci", ".github/workflows/ci.yml", "caller workflow is missing")
    elif not any(file in ci_files and path == ".github/workflows/quality.yml" for file, _, path, _ in refs):
        report.add("ci", ci_files[0], "does not call LeePepe/shared-ci/.github/workflows/quality.yml")
    for file in ci_files:
        job = _quality_job(root, file)
        if job is not None and job != "quality":
            report.add("ci", file, f"job {job!r} calls quality.yml; name it 'quality' so the "
                                   "required check is 'quality / aggregate'")
    for file, line, path, ref in refs:
        if not SHA.match(ref):
            report.add("ci", f"{file}:{line}", f"{path}@{ref} is not pinned to a full 40-char SHA")
    if len({ref for *_, ref in refs}) > 1:
        report.add("ci", ".github/workflows", f"mixed shared-ci pins: {sorted({r for *_, r in refs})}")


def _quality_job(root: pathlib.Path, path: str) -> str | None:
    """Job id that calls shared-ci quality.yml, or None when not determinable."""
    try:
        data = _frontmatter().parse(_text(root, path) or "")
    except ValueError:
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    for job_id, job in (jobs or {}).items():
        uses = job.get("uses", "") if isinstance(job, dict) else ""
        if isinstance(uses, str) and re.match(r"(?i)^leepepe/shared-ci/\.github/workflows/quality\.ya?ml@", uses):
            return str(job_id)
    return None


def _frontmatter() -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location("shared_ci_frontmatter", HERE / "_frontmatter.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verify(report: _Report, root: pathlib.Path, files: dict) -> None:
    if files.get("scripts/verify") != "100755":
        report.add("verify", "scripts/verify", "scripts/verify must be tracked and executable")
    hooks = [p for p in (".githooks/pre-push", ".githooks/pre-commit") if p in files]
    if not hooks:
        report.add("verify", ".githooks/pre-push", "no .githooks/pre-push or pre-commit hook")
    elif not any("scripts/verify" in (_text(root, hook) or "") for hook in hooks):
        report.add("verify", hooks[0], "hooks do not invoke scripts/verify")
    for hook in hooks:
        if files[hook] != "100755":
            report.add("verify", hook, "hook must be executable")
    workflows = [p for p in files if re.match(r"^\.github/workflows/ci\.ya?ml$", p)]
    if workflows and not any("scripts/verify" in (_text(root, p) or "") for p in workflows):
        report.add("verify", workflows[0], "CI does not invoke scripts/verify")


def _codeowners(report: _Report, root: pathlib.Path, files: dict, contract: dict) -> None:
    owners = [p for p in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS") if p in files]
    if not owners:
        report.add("ruleset", ".github/CODEOWNERS", "CODEOWNERS is missing (review gate for important paths)")
        return
    patterns = {line.split()[0] for line in (_text(root, owners[0]) or "").splitlines()
                if line.strip() and not line.lstrip().startswith("#")}
    for required in contract["codeowners_required"]:
        if required not in patterns:
            report.add("ruleset", owners[0], f"CODEOWNERS does not cover {required}")


def _pr_template(report: _Report, root: pathlib.Path, files: dict, contract: dict) -> None:
    names = [p for p in files if p.lower() in (".github/pull_request_template.md",
                                                 "pull_request_template.md",
                                                 "docs/pull_request_template.md")]
    if not names:
        report.add("pr_template", ".github/pull_request_template.md", "PR template is missing")
        return
    text = _text(root, names[0]) or ""
    for title in contract["pr_sections"]:
        if section(text, title) is None:
            report.add("pr_template", names[0], f"missing required section '## {title}'")


def _resolved_pins(root: pathlib.Path, files: dict) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for path in files:
        name = pathlib.PurePosixPath(path).name
        text = _text(root, path) if name in ("Package.resolved", "package-lock.json") else None
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if name == "Package.resolved":
            for pin in data.get("pins", data.get("object", {}).get("pins", [])):
                identity = str(pin.get("identity") or pin.get("package") or "").lower()
                state = pin.get("state", {})
                pins.setdefault(identity, set()).update(
                    str(v) for v in (state.get("version"), state.get("revision")) if v)
        else:
            for key, info in (data.get("packages") or {}).items():
                if key.startswith("node_modules/") and isinstance(info, dict) and info.get("version"):
                    pins.setdefault(key.rsplit("/", 1)[-1].lower(), set()).add(str(info["version"]))
    return pins


def _dependencies(report: _Report, root: pathlib.Path, files: dict, contract: dict, agents: str) -> None:
    declared: dict[str, str] = {}
    body = section(agents, "Dependencies") or ""
    for line in body.splitlines():
        match = re.match(r"^\s*[-*]\s+`?([A-Za-z0-9_.-]+)`?\s+`?([A-Za-z0-9_.+-]+)`?(.*)$", line)
        if not match or match.group(1).lower() not in contract["shared_libraries"]:
            continue
        name, version, rest = match.group(1).lower(), match.group(2), match.group(3)
        declared[name] = version
        if not re.search(r"[@/]" + re.escape(version) + r"/ai/", rest):
            report.add("dependencies", "AGENTS.md", f"{name} {version} must point to that version's ai/ docs")
    pins = _resolved_pins(root, files)
    for name in contract["shared_libraries"]:
        observed = pins.get(name, set())
        if name in declared and observed and declared[name] not in observed:
            report.add("dependencies", "AGENTS.md",
                       f"{name} declared {declared[name]} but lockfile pins {sorted(observed)}")
        if observed and name not in declared:
            report.add("dependencies", "AGENTS.md", f"{name} is pinned in a lockfile but not declared")


def _identity(report: _Report, root: pathlib.Path, files: dict, contract: dict) -> None:
    # Regexes are written so that their own source text never matches them;
    # shared-ci can therefore apply the same check to itself.
    patterns = [(entry["name"], re.compile(entry["regex"])) for entry in contract["forbidden_patterns"]]
    for path in sorted(files):
        if files[path] == "120000":
            continue
        text = _text(root, path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for name, pattern in patterns:
                if pattern.search(line):
                    report.add("identity", f"{path}:{number}",
                               f"forbidden personal identity or local path pattern: {name}")


def audit(ctx: Any, root: pathlib.Path) -> list[Any]:
    contract = load_contract()
    report = _Report(ctx)
    files = _git_files(root)
    refs = workflow_refs(root, files)
    agents = _agents(report, root, contract, refs)
    _agent_files(report, root, contract, agents)
    _ci(report, root, files, refs)
    _verify(report, root, files)
    _codeowners(report, root, files, contract)
    _pr_template(report, root, files, contract)
    _dependencies(report, root, files, contract, agents)
    _identity(report, root, files, contract)
    return report.findings
