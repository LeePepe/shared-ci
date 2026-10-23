#!/usr/bin/env python3
"""Fail-closed G2 security scanner: identity/secret patterns, gitleaks, and osv-scanner.

Stdlib-only Python 3.9+ engine enforcing repository identity/secret hygiene,
optional or required gitleaks secret scanning, and optional or required
osv-scanner lockfile vulnerability auditing.

Exit codes:
  0  All enabled checks passed with zero findings
  1  Identity/secret/vulnerability findings detected or required scanner binary missing
  2  Invalid CLI arguments, unsafe target path, or symlinked path/ancestor
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
PROVIDER_CONTRACT_FILE = HERE.parents[1] / "schemas" / "repo-contract-v1.json"

LOCKFILE_NAMES: frozenset[str] = frozenset(
    {
        "Package.resolved",
        "package-lock.json",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "Cargo.lock",
        "uv.lock",
        "poetry.lock",
        "requirements.txt",
        "go.sum",
    }
)

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".shared-ci",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Written with character classes so this source file never self-matches contract audit.
DEFAULT_FORBIDDEN_PATTERNS: tuple[dict[str, str], ...] = (
    {"name": "credential profile directory", "regex": "github[-]identity"},
    {"name": "gh config override", "regex": "GH[_]CONFIG_DIR"},
    {"name": "macOS home path", "regex": "/User[s]/"},
    {"name": "personal profile path", "regex": "profile[s]/LeePepe"},
)

BUILTIN_SECRET_PATTERNS: tuple[dict[str, str], ...] = (
    {"name": "GitHub personal access token", "regex": r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"},
    {"name": "GitHub fine-grained PAT", "regex": r"\bgithub[_]pat_[A-Za-z0-9_]{22,255}\b"},
    {"name": "AWS access key ID", "regex": r"\bAKIA[0-9A-Z]{16}\b"},
    {
        "name": "Private key block",
        "regex": r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE [K]EY-----",
    },
    {
        "name": "API secret key token",
        "regex": r"(?<![A-Za-z0-9_.-])sk-(?:live-|test-|proj-|ant-)?[A-Za-z0-9]{24,}\b",
    },
    {"name": "Slack token", "regex": r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"},
)

MAX_TEXT_BYTES = 2_000_000


class SecurityScanError(ValueError):
    """Raised when input or repository target state is invalid or unsafe."""

    def __init__(self, message: str, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScanFinding:
    scanner: str
    kind: str
    path: str
    rule: str
    detail: str
    line: int = 0

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "scanner": self.scanner,
            "kind": self.kind,
            "path": self.path,
            "rule": self.rule,
            "detail": self.detail,
        }
        if self.line > 0:
            payload["line"] = self.line
        return payload


def _valid_local_path(value: str) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


def _within_root(root: pathlib.Path, target: pathlib.Path) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        resolved_target = target.resolve(strict=False)
    except OSError:
        return False
    return resolved_root in resolved_target.parents


def _has_symlink_ancestor(root: pathlib.Path, target: pathlib.Path) -> pathlib.Path | None:
    try:
        rel = target.relative_to(root)
    except ValueError:
        return target
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return current
    return None


def _ensure_safe_target(
    root: pathlib.Path,
    rel_path: str,
    *,
    expect_dir: bool = False,
    must_exist: bool = False,
) -> pathlib.Path:
    if not _valid_local_path(rel_path):
        raise SecurityScanError(
            f"unsafe_target: path must be a safe repository-relative path: {rel_path!r}",
            code="unsafe_target",
        )
    target = root / rel_path
    symlink = _has_symlink_ancestor(root, target)
    if symlink is not None:
        rel_symlink = symlink.relative_to(root).as_posix()
        raise SecurityScanError(
            f"symlink_target: {rel_path} traverses symlink {rel_symlink}",
            code="symlink_target",
        )
    if not _within_root(root, target):
        raise SecurityScanError(
            f"unsafe_target: {rel_path} resolves outside repository root {root}",
            code="unsafe_target",
        )
    current = root
    parts = rel_path.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            st = current.lstat()
        except FileNotFoundError:
            if must_exist and index == len(parts) - 1:
                raise SecurityScanError(
                    f"invalid_input: required target does not exist: {rel_path}",
                    code="invalid_input",
                ) from None
            continue
        is_last = index == len(parts) - 1
        if stat.S_ISLNK(st.st_mode):
            raise SecurityScanError(
                f"symlink_target: {rel_path} traverses symlink {current.relative_to(root).as_posix()}",
                code="symlink_target",
            )
        if not is_last and not stat.S_ISDIR(st.st_mode):
            raise SecurityScanError(
                f"unsafe_target: ancestor {current.relative_to(root).as_posix()} is not a directory",
                code="unsafe_target",
            )
        if is_last:
            if expect_dir and not stat.S_ISDIR(st.st_mode):
                raise SecurityScanError(
                    f"unsafe_target: expected directory at {rel_path}",
                    code="unsafe_target",
                )
            if not expect_dir and not stat.S_ISREG(st.st_mode):
                raise SecurityScanError(
                    f"unsafe_target: existing target {rel_path} is not a regular file",
                    code="unsafe_target",
                )
    return target


def _validate_repo_root(repo_root: pathlib.Path) -> pathlib.Path:
    if repo_root.is_symlink():
        raise SecurityScanError(
            f"symlink_target: repository root is a symlink: {repo_root}",
            code="symlink_target",
        )
    if not repo_root.is_dir():
        raise SecurityScanError(
            f"invalid_input: repository root is not a directory: {repo_root}",
            code="invalid_input",
        )
    return repo_root.resolve(strict=True)


def _validate_binary_name(bin_arg: str, flag_name: str) -> str:
    if (
        not isinstance(bin_arg, str)
        or not bin_arg.strip()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in bin_arg)
    ):
        raise SecurityScanError(
            f"invalid_input: {flag_name} must be a non-empty binary name or path",
            code="invalid_input",
        )
    return bin_arg


def _load_forbidden_patterns(root: pathlib.Path) -> list[tuple[str, re.Pattern[str], str]]:
    contract_entries: list[dict[str, str]] = list(DEFAULT_FORBIDDEN_PATTERNS)
    local_schema_rel = "schemas/repo-contract-v1.json"
    local_schema_candidate = root / local_schema_rel
    if os.path.lexists(local_schema_candidate):
        safe_schema = _ensure_safe_target(root, local_schema_rel, must_exist=True)
        try:
            raw = json.loads(safe_schema.read_text(encoding="utf-8"))
            loaded = raw.get("x-contract", {}).get("forbidden_patterns")
            if isinstance(loaded, list) and loaded:
                contract_entries = [
                    {"name": str(item["name"]), "regex": str(item["regex"])}
                    for item in loaded
                    if isinstance(item, dict) and "name" in item and "regex" in item
                ]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SecurityScanError(
                f"invalid_input: cannot parse {local_schema_rel}: {error}",
                code="invalid_input",
            ) from None
    elif PROVIDER_CONTRACT_FILE.is_file():
        try:
            raw = json.loads(PROVIDER_CONTRACT_FILE.read_text(encoding="utf-8"))
            loaded = raw.get("x-contract", {}).get("forbidden_patterns")
            if isinstance(loaded, list) and loaded:
                contract_entries = [
                    {"name": str(item["name"]), "regex": str(item["regex"])}
                    for item in loaded
                    if isinstance(item, dict) and "name" in item and "regex" in item
                ]
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

    compiled: list[tuple[str, re.Pattern[str], str]] = []
    for entry in contract_entries:
        compiled.append((entry["name"], re.compile(entry["regex"]), "forbidden_identity"))
    for entry in BUILTIN_SECRET_PATTERNS:
        compiled.append((entry["name"], re.compile(entry["regex"]), "secret_pattern"))
    return compiled


def _is_git_worktree(root: pathlib.Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _walk_worktree_files(root: pathlib.Path) -> list[tuple[str, bytes]]:
    discovered: list[tuple[str, bytes]] = []

    def _walk_dir(current_dir: pathlib.Path, rel_prefix: str) -> None:
        try:
            entries = sorted(current_dir.iterdir(), key=lambda p: p.name)
        except OSError as error:
            raise SecurityScanError(
                f"invalid_input: cannot list directory {rel_prefix or '.'}: {error}",
                code="invalid_input",
            ) from None

        for entry in entries:
            name = entry.name
            if name in IGNORED_DIRS or name.startswith(".audit-selected."):
                continue
            rel_path = f"{rel_prefix}/{name}" if rel_prefix else name
            try:
                st = entry.lstat()
            except OSError as error:
                raise SecurityScanError(
                    f"invalid_input: cannot stat {rel_path}: {error}",
                    code="invalid_input",
                ) from None
            if stat.S_ISLNK(st.st_mode):
                _ensure_safe_target(root, rel_path)
            if stat.S_ISDIR(st.st_mode):
                _ensure_safe_target(root, rel_path, expect_dir=True)
                _walk_dir(entry, rel_path)
            elif stat.S_ISREG(st.st_mode):
                safe_file = _ensure_safe_target(root, rel_path)
                if st.st_size <= MAX_TEXT_BYTES:
                    discovered.append((rel_path, safe_file.read_bytes()))
                else:
                    discovered.append((rel_path, b""))

    _walk_dir(root, "")
    return discovered


def _collect_staged_files(root: pathlib.Path) -> list[tuple[str, bytes]]:
    if not _is_git_worktree(root):
        return _walk_worktree_files(root)

    diff_proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if diff_proc.returncode != 0:
        return _walk_worktree_files(root)

    raw_paths = [
        item.decode("utf-8", errors="surrogateescape")
        for item in diff_proc.stdout.split(b"\0")
        if item
    ]

    # Check index stage modes to detect staged symlinks (mode 120000).
    stage_modes: dict[str, str] = {}
    ls_proc = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if ls_proc.returncode == 0:
        for row in ls_proc.stdout.split(b"\0"):
            if not row:
                continue
            meta, _, raw_p = row.partition(b"\t")
            parts = meta.split(b" ")
            if len(parts) >= 3 and parts[2] == b"0":
                stage_modes[raw_p.decode("utf-8", errors="surrogateescape")] = parts[0].decode("ascii")

    collected: list[tuple[str, bytes]] = []
    for rel_path in sorted(set(raw_paths)):
        if stage_modes.get(rel_path) == "120000":
            raise SecurityScanError(
                f"symlink_target: staged path {rel_path} is a symlink in git index",
                code="symlink_target",
            )
        safe_path = _ensure_safe_target(root, rel_path)
        cat_proc = subprocess.run(
            ["git", "cat-file", "-p", f":0:{rel_path}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if cat_proc.returncode == 0:
            raw_bytes = cat_proc.stdout if len(cat_proc.stdout) <= MAX_TEXT_BYTES else b""
        elif safe_path.is_file():
            size = safe_path.stat().st_size
            raw_bytes = safe_path.read_bytes() if size <= MAX_TEXT_BYTES else b""
        else:
            continue
        collected.append((rel_path, raw_bytes))
    return collected


def _scan_identity_and_patterns(
    root: pathlib.Path,
    files: list[tuple[str, bytes]],
) -> tuple[dict[str, Any], list[ScanFinding]]:
    patterns = _load_forbidden_patterns(root)
    findings: list[ScanFinding] = []
    scanned_count = 0

    for rel_path, raw_bytes in files:
        _ensure_safe_target(root, rel_path)
        if not raw_bytes or b"\0" in raw_bytes[:8192]:
            continue
        scanned_count += 1
        text = raw_bytes.decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            for pattern_name, regex, kind in patterns:
                if regex.search(line):
                    findings.append(
                        ScanFinding(
                            scanner="identity",
                            kind=kind,
                            path=rel_path,
                            line=line_no,
                            rule=pattern_name,
                            detail=f"forbidden identity or secret pattern: {pattern_name}",
                        )
                    )

    summary = {
        "status": "pass" if not findings else "fail",
        "files_scanned": scanned_count,
        "findings_count": len(findings),
    }
    return summary, findings


def _run_gitleaks(
    root: pathlib.Path,
    files: list[tuple[str, bytes]],
    *,
    staged: bool,
    require_gitleaks: bool,
    gitleaks_bin: str,
    gitleaks_config: str | None,
) -> tuple[dict[str, Any], list[ScanFinding]]:
    _validate_binary_name(gitleaks_bin, "--gitleaks-bin")
    config_path: pathlib.Path | None = None
    if gitleaks_config is not None:
        config_path = _ensure_safe_target(root, gitleaks_config, must_exist=True)
    elif os.path.lexists(root / ".gitleaks.toml"):
        config_path = _ensure_safe_target(root, ".gitleaks.toml", must_exist=True)

    resolved_bin = shutil.which(gitleaks_bin)
    if resolved_bin is None:
        if require_gitleaks:
            finding = ScanFinding(
                scanner="gitleaks",
                kind="scanner_missing",
                path="",
                rule="gitleaks-binary",
                detail=f"required gitleaks binary not found: {gitleaks_bin}",
            )
            return (
                {
                    "status": "missing",
                    "required": True,
                    "binary": gitleaks_bin,
                    "findings_count": 1,
                },
                [finding],
            )
        return (
            {
                "status": "skipped",
                "required": False,
                "binary": gitleaks_bin,
                "reason": "binary_not_installed",
                "findings_count": 0,
            },
            [],
        )

    findings: list[ScanFinding] = []
    with tempfile.TemporaryDirectory(prefix="shared-ci-gitleaks-") as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        report_file = temp_path / "gitleaks-report.json"
        if staged and _is_git_worktree(root):
            scan_source = temp_path / "staged"
            scan_source.mkdir(parents=True, exist_ok=True)
            for rel_path, raw_bytes in files:
                dest = scan_source / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw_bytes)
        else:
            scan_source = root

        cmd = [
            resolved_bin,
            "detect",
            "--no-git",
            "--redact",
            "--no-banner",
            "--source",
            str(scan_source),
            "--report-format",
            "json",
            "--report-path",
            str(report_file),
        ]
        if config_path is not None:
            cmd.extend(["--config", str(config_path)])

        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

        if report_file.is_file():
            try:
                report_data = json.loads(report_file.read_text(encoding="utf-8"))
                if isinstance(report_data, list):
                    for item in report_data:
                        if not isinstance(item, dict):
                            continue
                        raw_file = str(item.get("File") or "")
                        try:
                            rel_item = pathlib.Path(raw_file).resolve().relative_to(scan_source.resolve()).as_posix()
                        except ValueError:
                            rel_item = raw_file
                        line_no = int(item.get("StartLine") or 0) if isinstance(item.get("StartLine"), int) else 0
                        rule_id = str(item.get("RuleID") or "gitleaks-rule")
                        desc = str(item.get("Description") or "gitleaks detected a potential secret")
                        findings.append(
                            ScanFinding(
                                scanner="gitleaks",
                                kind="secret_leak",
                                path=rel_item,
                                line=line_no,
                                rule=rule_id,
                                detail=desc,
                            )
                        )
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass

        if proc.returncode != 0 and not findings:
            findings.append(
                ScanFinding(
                    scanner="gitleaks",
                    kind="secret_leak",
                    path="",
                    rule="gitleaks-exit",
                    detail=f"gitleaks exited non-zero (exit {proc.returncode})",
                )
            )

    passed = proc.returncode == 0 and len(findings) == 0
    return (
        {
            "status": "pass" if passed else "fail",
            "required": bool(require_gitleaks),
            "binary": gitleaks_bin,
            "exit_code": proc.returncode,
            "findings_count": len(findings),
        },
        findings,
    )


def _discover_lockfiles(
    root: pathlib.Path,
    files: list[tuple[str, bytes]],
    *,
    staged: bool,
) -> list[str]:
    lockfiles: list[str] = []
    for rel_path, _ in files:
        if pathlib.PurePosixPath(rel_path).name in LOCKFILE_NAMES:
            _ensure_safe_target(root, rel_path)
            lockfiles.append(rel_path)
    if not lockfiles and staged:
        for rel_path, _ in _walk_worktree_files(root):
            if pathlib.PurePosixPath(rel_path).name in LOCKFILE_NAMES:
                _ensure_safe_target(root, rel_path)
                lockfiles.append(rel_path)
    return sorted(set(lockfiles))


def _run_osv(
    root: pathlib.Path,
    files: list[tuple[str, bytes]],
    *,
    staged: bool,
    require_osv: bool,
    osv_bin: str,
    osv_config: str | None,
) -> tuple[dict[str, Any], list[ScanFinding]]:
    _validate_binary_name(osv_bin, "--osv-bin")
    config_path: pathlib.Path | None = None
    if osv_config is not None:
        config_path = _ensure_safe_target(root, osv_config, must_exist=True)
    elif os.path.lexists(root / "osv-scanner.toml"):
        config_path = _ensure_safe_target(root, "osv-scanner.toml", must_exist=True)

    lockfiles = _discover_lockfiles(root, files, staged=staged)
    resolved_bin = shutil.which(osv_bin)
    if resolved_bin is None:
        if require_osv:
            finding = ScanFinding(
                scanner="osv",
                kind="scanner_missing",
                path="",
                rule="osv-binary",
                detail=f"required osv-scanner binary not found: {osv_bin}",
            )
            return (
                {
                    "status": "missing",
                    "required": True,
                    "binary": osv_bin,
                    "lockfiles": lockfiles,
                    "findings_count": 1,
                },
                [finding],
            )
        return (
            {
                "status": "skipped",
                "required": False,
                "binary": osv_bin,
                "lockfiles": lockfiles,
                "reason": "binary_not_installed",
                "findings_count": 0,
            },
            [],
        )

    if not lockfiles:
        return (
            {
                "status": "pass",
                "required": bool(require_osv),
                "binary": osv_bin,
                "lockfiles": [],
                "findings_count": 0,
            },
            [],
        )

    file_map = dict(files)
    findings: list[ScanFinding] = []
    with tempfile.TemporaryDirectory(prefix="shared-ci-osv-") as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        cmd = [resolved_bin, "--format", "json"]
        if config_path is not None:
            cmd.extend(["--config", str(config_path)])

        for rel_lock in lockfiles:
            safe_lock = _ensure_safe_target(root, rel_lock)
            if staged and rel_lock in file_map:
                staged_lock = temp_path / rel_lock
                staged_lock.parent.mkdir(parents=True, exist_ok=True)
                staged_lock.write_bytes(file_map[rel_lock])
                cmd.extend(["--lockfile", str(staged_lock)])
            else:
                cmd.extend(["--lockfile", str(safe_lock)])

        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
                if isinstance(payload, dict):
                    for result_entry in payload.get("results") or []:
                        if not isinstance(result_entry, dict):
                            continue
                        src_info = result_entry.get("source") or {}
                        raw_src = str(src_info.get("path") or (lockfiles[0] if lockfiles else ""))
                        rel_src = raw_src
                        for base_candidate in (temp_path, root):
                            try:
                                rel_src = pathlib.Path(raw_src).resolve().relative_to(base_candidate.resolve()).as_posix()
                                break
                            except ValueError:
                                continue
                        for pkg_entry in result_entry.get("packages") or []:
                            if not isinstance(pkg_entry, dict):
                                continue
                            for vuln in pkg_entry.get("vulnerabilities") or []:
                                if not isinstance(vuln, dict):
                                    continue
                                vuln_id = str(vuln.get("id") or "OSV-UNKNOWN")
                                summary_text = str(vuln.get("summary") or "dependency vulnerability detected")
                                findings.append(
                                    ScanFinding(
                                        scanner="osv",
                                        kind="vulnerability",
                                        path=rel_src,
                                        rule=vuln_id,
                                        detail=summary_text,
                                    )
                                )
            except json.JSONDecodeError:
                pass

        if proc.returncode != 0 and not findings:
            findings.append(
                ScanFinding(
                    scanner="osv",
                    kind="vulnerability",
                    path=lockfiles[0],
                    rule="osv-exit",
                    detail=f"osv-scanner exited non-zero (exit {proc.returncode})",
                )
            )

    passed = proc.returncode == 0 and len(findings) == 0
    return (
        {
            "status": "pass" if passed else "fail",
            "required": bool(require_osv),
            "binary": osv_bin,
            "lockfiles": lockfiles,
            "exit_code": proc.returncode,
            "findings_count": len(findings),
        },
        findings,
    )


def run_security_scan(
    repo_root: pathlib.Path,
    *,
    staged: bool = False,
    require_gitleaks: bool = False,
    require_osv: bool = False,
    gitleaks_bin: str = "gitleaks",
    osv_bin: str = "osv-scanner",
    gitleaks_config: str | None = None,
    osv_config: str | None = None,
) -> dict[str, Any]:
    root = _validate_repo_root(repo_root)
    files = _collect_staged_files(root) if staged else _walk_worktree_files(root)

    identity_summary, identity_findings = _scan_identity_and_patterns(root, files)
    gitleaks_summary, gitleaks_findings = _run_gitleaks(
        root,
        files,
        staged=staged,
        require_gitleaks=require_gitleaks,
        gitleaks_bin=gitleaks_bin,
        gitleaks_config=gitleaks_config,
    )
    osv_summary, osv_findings = _run_osv(
        root,
        files,
        staged=staged,
        require_osv=require_osv,
        osv_bin=osv_bin,
        osv_config=osv_config,
    )

    all_findings = [*identity_findings, *gitleaks_findings, *osv_findings]
    ok = (
        len(all_findings) == 0
        and identity_summary["status"] == "pass"
        and gitleaks_summary["status"] in ("pass", "skipped")
        and osv_summary["status"] in ("pass", "skipped")
    )
    return {
        "ok": ok,
        "mode": "staged" if staged else "worktree",
        "scanners": {
            "identity": identity_summary,
            "gitleaks": gitleaks_summary,
            "osv": osv_summary,
        },
        "findings": [item.as_dict() for item in all_findings],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="security_scan.py",
        description="Fail-closed G2 security scanner (identity/secrets, gitleaks, osv-scanner).",
    )
    parser.add_argument("--root", default=".", help="Repository root directory (default: .).")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Scan only staged files from the Git index (falls back to worktree if not a Git repo).",
    )
    parser.add_argument(
        "--require-gitleaks",
        action="store_true",
        help="Fail closed (exit 1) if the gitleaks binary is not installed.",
    )
    parser.add_argument(
        "--require-osv",
        action="store_true",
        help="Fail closed (exit 1) if the osv-scanner binary is not installed.",
    )
    parser.add_argument(
        "--gitleaks-bin",
        default="gitleaks",
        help="gitleaks binary name or path (default: gitleaks).",
    )
    parser.add_argument(
        "--osv-bin",
        default="osv-scanner",
        help="osv-scanner binary name or path (default: osv-scanner).",
    )
    parser.add_argument(
        "--gitleaks-config",
        default=None,
        help="Optional repository-relative gitleaks config path.",
    )
    parser.add_argument(
        "--osv-config",
        default=None,
        help="Optional repository-relative osv-scanner config path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    raw_root = pathlib.Path(args.root)
    repo_root = raw_root if raw_root.is_symlink() else raw_root.resolve(strict=False)

    try:
        report = run_security_scan(
            repo_root,
            staged=bool(args.staged),
            require_gitleaks=bool(args.require_gitleaks),
            require_osv=bool(args.require_osv),
            gitleaks_bin=args.gitleaks_bin,
            osv_bin=args.osv_bin,
            gitleaks_config=args.gitleaks_config,
            osv_config=args.osv_config,
        )
    except SecurityScanError as error:
        print(
            json.dumps(
                {"ok": False, "code": error.code, "error": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
