#!/usr/bin/env python3
"""Synchronize and audit consumer repository contract files and shared-ci pins.

Checks or updates `.github/repo-contract.json`, directory-only `AGENTS.md`,
tool pointer files (`CLAUDE.md`, `.github/copilot-instructions.md`, `GEMINI.md`,
`.cursorrules`), and `LeePepe/shared-ci/...@<sha>` workflow pins across one or
more consumer repositories using Python 3.9+ stdlib only.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import pathlib
import re
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"
CONTRACT_SCHEMA = REPO_ROOT / "schemas" / "repo-contract-v1.json"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ROUTE_RE = re.compile(
    r"^\s*(?:(?:[-*]|\d+\.)\s+)?(?:[^`\[\]<>:]+:\s*)?\[[^\[\]]+\]\(([^\s)]+)\)[.;]?\s*$"
)
POINTER_RE = re.compile(
    r"(github\.com/LeePepe/shared-ci/blob/|LeePepe/shared-ci@)"
    r"([0-9A-Za-z._<>/-]+?)(/ai/agent-protocol\.md)",
    re.IGNORECASE,
)
WORKFLOW_USES_RE = re.compile(
    r"(?i)(LeePepe/shared-ci/[^@\s\"']+@)([0-9A-Za-z._<>/-]+)"
)
SHARED_CI_PIN_DUP_RE = re.compile(r"shared-ci[^\n]*@[0-9a-f]{40}", re.IGNORECASE)

DEFAULT_GUIDE = "docs/repository-guide.md"
METADATA_REL = ".github/repo-contract.json"
REQUIRED_AGENT_FILES = ("CLAUDE.md", ".github/copilot-instructions.md")
OPTIONAL_AGENT_FILES = ("GEMINI.md", ".cursorrules")

AGENT_FILE_TEMPLATES: dict[str, str] = {
    "CLAUDE.md": (
        "# CLAUDE.md\n\n"
        "Read `AGENTS.md` first, then follow its links to the authoritative repository rules.\n"
    ),
    ".github/copilot-instructions.md": (
        "# Copilot instructions\n\n"
        "Read `AGENTS.md` first, then follow its links to the authoritative repository rules.\n"
    ),
    "GEMINI.md": (
        "# GEMINI.md\n\n"
        "Read `AGENTS.md` first, then follow its links to the authoritative repository rules.\n"
    ),
    ".cursorrules": (
        "Read `AGENTS.md` first, then follow its links to the authoritative repository rules.\n"
    ),
}


class SyncError(ValueError):
    """Invalid input or target repository state."""


@dataclass(frozen=True)
class FileChange:
    path: str
    action: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "action": self.action, "reason": self.reason}


@dataclass(frozen=True)
class RepoSyncResult:
    repo: str
    pin: str
    guide: str
    drifted: bool
    applied: bool
    changes: tuple[FileChange, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "pin": self.pin,
            "guide": self.guide,
            "drifted": self.drifted,
            "applied": self.applied,
            "changes": [change.as_dict() for change in self.changes],
        }


def _valid_local_path(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def _extract_required_checks(guide_text: str) -> list[str]:
    lines = guide_text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,3})\s+(.*?)\s*#*\s*$", line)
        if match and match.group(2).strip().lower().startswith("required checks"):
            level = len(match.group(1))
            body: list[str] = []
            for following in lines[index + 1:]:
                heading = re.match(r"^(#{1,6})\s", following)
                if heading and len(heading.group(1)) <= level:
                    break
                body.append(following)
            return [name for name in re.findall(r"`([^`]+)`", "\n".join(body)) if name.strip()]
    return []


def _render_agents_template(pin: str, guide: str) -> str:
    template = (TEMPLATES_DIR / "AGENTS.md").read_text(encoding="utf-8")
    rendered = template.replace("<40-char-sha>", pin)
    if guide != DEFAULT_GUIDE:
        rendered = rendered.replace(DEFAULT_GUIDE, guide)
    return rendered


def _is_valid_index_agents(text: str, guide: str) -> bool:
    routes: list[str] = []
    local_paths: set[str] = set()
    lines = text.splitlines()
    if not lines or len(lines) > 150:
        return False
    for line in lines:
        if not line.strip() or re.match(r"^#{1,6}\s+", line):
            continue
        match = ROUTE_RE.fullmatch(line)
        if not match:
            return False
        target = match.group(1)
        routes.append(target)
        if not target.startswith("https://"):
            path, _, _ = target.partition("#")
            local_paths.add(path or "AGENTS.md")
    return bool(routes) and guide in local_paths


def _desired_agents(current: str | None, pin: str, guide: str, *, overwrite: bool) -> tuple[str, str]:
    template_rendered = _render_agents_template(pin, guide)
    if current is None:
        return template_rendered, "bootstrap directory-only AGENTS.md from template"
    if overwrite:
        return template_rendered, "overwrite AGENTS.md with template"
    updated = current.replace("<40-char-sha>", pin)
    updated = POINTER_RE.sub(lambda m: f"{m.group(1)}{pin}{m.group(3)}", updated)
    if not _is_valid_index_agents(updated, guide):
        return template_rendered, "upgrade non-index AGENTS.md to directory-only template"
    return updated, "update shared-ci protocol pin in AGENTS.md"


def _agent_file_valid(text: str, required_checks: list[str], max_lines: int = 12) -> bool:
    if "AGENTS.md" not in text:
        return False
    non_empty = [line for line in text.splitlines() if line.strip()]
    if len(non_empty) > max_lines:
        return False
    if POINTER_RE.search(text) or SHARED_CI_PIN_DUP_RE.search(text):
        return False
    for check_name in required_checks:
        if f"`{check_name}`" in text:
            return False
    return True


def _sync_workflow_text(text: str, pin: str, guide: str) -> str:
    updated = text.replace("<40-char-sha>", pin)
    updated = WORKFLOW_USES_RE.sub(lambda m: f"{m.group(1)}{pin}", updated)
    if (
        "codex-review.yml@" in updated or "kimi-review.yml@" in updated
    ) and "rules-file: AGENTS.md" in updated:
        updated = updated.replace("rules-file: AGENTS.md", f"rules-file: {guide}")
    return updated


def sync_repository(
    repo_root: pathlib.Path,
    pin: str,
    *,
    guide: str | None = None,
    apply: bool = False,
    overwrite_agents: bool = False,
    include_optional_agent_files: bool = False,
) -> RepoSyncResult:
    if not isinstance(pin, str) or not SHA_RE.fullmatch(pin):
        raise SyncError("pin must be a full lowercase 40-char hex SHA")
    if not repo_root.is_dir():
        raise SyncError(f"target repository is not a directory: {repo_root}")
    if guide is not None and not _valid_local_path(guide):
        raise SyncError(f"guide must be a safe repository-relative file path: {guide!r}")

    changes: list[FileChange] = []
    writes: list[tuple[pathlib.Path, str]] = []

    # 1. .github/repo-contract.json
    metadata_path = repo_root / METADATA_REL
    existing_metadata: dict[str, Any] | None = None
    existing_metadata_text: str | None = None
    if metadata_path.is_file() and not metadata_path.is_symlink():
        try:
            existing_metadata_text = metadata_path.read_text(encoding="utf-8")
            parsed = json.loads(existing_metadata_text)
            if isinstance(parsed, dict):
                existing_metadata = parsed
        except (OSError, UnicodeError, json.JSONDecodeError):
            existing_metadata = None

    effective_guide = guide
    if effective_guide is None:
        if (
            existing_metadata is not None
            and isinstance(existing_metadata.get("guide"), str)
            and _valid_local_path(existing_metadata["guide"])
        ):
            effective_guide = existing_metadata["guide"]
        else:
            effective_guide = DEFAULT_GUIDE

    dependencies: dict[str, Any] = {}
    if existing_metadata is not None and isinstance(existing_metadata.get("dependencies"), dict):
        dependencies = {
            k: v for k, v in existing_metadata["dependencies"].items()
            if isinstance(k, str) and k.lower() != "shared-ci"
        }

    desired_metadata_obj = {
        "schema": 1,
        "guide": effective_guide,
        "shared_ci": pin,
        "dependencies": dependencies,
    }
    desired_metadata_text = json.dumps(desired_metadata_obj, indent=2, ensure_ascii=False) + "\n"
    if existing_metadata_text is None:
        changes.append(FileChange(METADATA_REL, "create", "create .github/repo-contract.json"))
        writes.append((metadata_path, desired_metadata_text))
    elif existing_metadata != desired_metadata_obj:
        changes.append(FileChange(METADATA_REL, "update", "sync shared_ci pin and schema in .github/repo-contract.json"))
        writes.append((metadata_path, desired_metadata_text))

    # 2. AGENTS.md
    agents_path = repo_root / "AGENTS.md"
    existing_agents_text: str | None = None
    if agents_path.is_file() and not agents_path.is_symlink():
        existing_agents_text = agents_path.read_text(encoding="utf-8")
    desired_agents_text, agents_reason = _desired_agents(
        existing_agents_text, pin, effective_guide, overwrite=overwrite_agents
    )
    if existing_agents_text is None:
        changes.append(FileChange("AGENTS.md", "create", agents_reason))
        writes.append((agents_path, desired_agents_text))
    elif existing_agents_text != desired_agents_text:
        changes.append(FileChange("AGENTS.md", "update", agents_reason))
        writes.append((agents_path, desired_agents_text))

    # 3. Tool pointer files (CLAUDE.md, .github/copilot-instructions.md, GEMINI.md, .cursorrules)
    guide_file = repo_root / effective_guide
    guide_text = (
        guide_file.read_text(encoding="utf-8")
        if guide_file.is_file() and not guide_file.is_symlink()
        else ""
    )
    required_checks = _extract_required_checks(guide_text)
    agent_candidates = list(REQUIRED_AGENT_FILES)
    for opt in OPTIONAL_AGENT_FILES:
        if include_optional_agent_files or (repo_root / opt).exists():
            agent_candidates.append(opt)

    for rel_path in agent_candidates:
        target = repo_root / rel_path
        canonical = AGENT_FILE_TEMPLATES[rel_path]
        if not target.is_file() or target.is_symlink():
            changes.append(FileChange(rel_path, "create", f"bootstrap tool pointer {rel_path}"))
            writes.append((target, canonical))
        else:
            current_text = target.read_text(encoding="utf-8")
            if not _agent_file_valid(current_text, required_checks):
                changes.append(
                    FileChange(rel_path, "update", f"repair non-compliant tool pointer {rel_path}")
                )
                writes.append((target, canonical))

    # 4. .github/workflows/*.yml and *.yaml
    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir() and not workflows_dir.is_symlink():
        workflow_files = sorted(
            p for p in workflows_dir.iterdir()
            if p.is_file() and not p.is_symlink() and p.suffix in (".yml", ".yaml")
        )
        for wf_path in workflow_files:
            rel_wf = wf_path.relative_to(repo_root).as_posix()
            current_wf = wf_path.read_text(encoding="utf-8")
            desired_wf = _sync_workflow_text(current_wf, pin, effective_guide)
            if desired_wf != current_wf:
                changes.append(
                    FileChange(rel_wf, "update", "sync shared-ci workflow pin and review rules-file")
                )
                writes.append((wf_path, desired_wf))

    if apply:
        for target_path, content in writes:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.is_symlink():
                target_path.unlink()
            target_path.write_text(content, encoding="utf-8")

    return RepoSyncResult(
        repo=str(repo_root),
        pin=pin,
        guide=effective_guide,
        drifted=bool(changes),
        applied=apply and bool(changes),
        changes=tuple(changes),
    )


def sync_repositories(
    repo_roots: list[pathlib.Path],
    pin: str,
    *,
    guide: str | None = None,
    apply: bool = False,
    overwrite_agents: bool = False,
    include_optional_agent_files: bool = False,
) -> dict[str, Any]:
    if not repo_roots:
        raise SyncError("at least one target repository path is required")
    results = [
        sync_repository(
            root,
            pin,
            guide=guide,
            apply=apply,
            overwrite_agents=overwrite_agents,
            include_optional_agent_files=include_optional_agent_files,
        )
        for root in repo_roots
    ]
    drifted_count = sum(1 for item in results if item.drifted)
    return {
        "ok": True if apply else (drifted_count == 0),
        "mode": "apply" if apply else "check",
        "pin": pin,
        "drifted_count": drifted_count,
        "repos": [item.as_dict() for item in results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-contract",
        description="Check or synchronize consumer repository contract files and shared-ci pins.",
    )
    parser.add_argument(
        "repos",
        nargs="*",
        help="Target consumer repository paths (default: current directory).",
    )
    parser.add_argument(
        "--repo",
        dest="extra_repos",
        action="append",
        default=[],
        help="Additional target consumer repository path (may be repeated).",
    )
    parser.add_argument(
        "--pin",
        required=True,
        help="Target 40-character lowercase shared-ci commit SHA.",
    )
    parser.add_argument(
        "--guide",
        default=None,
        help="Repository-relative guide path (default: preserve existing or docs/repository-guide.md).",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="Dry-run mode: emit JSON drift report and exit 1 if any repo drifted (default).",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to disk and emit JSON report.",
    )
    parser.add_argument(
        "--overwrite-agents",
        action="store_true",
        help="Always overwrite AGENTS.md from templates/AGENTS.md even if already index-compliant.",
    )
    parser.add_argument(
        "--all-agent-files",
        action="store_true",
        help="Also create optional GEMINI.md and .cursorrules pointer files when absent.",
    )
    args = parser.parse_args(argv)
    raw_repos = list(args.repos) + list(args.extra_repos)
    if not raw_repos:
        raw_repos = ["."]
    repo_paths = [pathlib.Path(p).resolve() for p in raw_repos]
    try:
        report = sync_repositories(
            repo_paths,
            args.pin,
            guide=args.guide,
            apply=bool(args.apply),
            overwrite_agents=bool(args.overwrite_agents),
            include_optional_agent_files=bool(args.all_agent_files),
        )
    except SyncError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not args.apply and report["drifted_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
