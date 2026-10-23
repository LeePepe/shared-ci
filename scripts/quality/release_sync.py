#!/usr/bin/env python3
"""Cross-target atomic version sync and post-release live-readback verifier.

Stdlib-only Python 3.9+ engine for multi-language version synchronization
(`package.json`, `Cargo.toml`, `project.yml`, `*.pbxproj`, `VERSION`) and
fail-closed post-release readback verification (`/api/live` JSON endpoint,
`SHA256SUMS` artifact digests, and GitHub Release metadata).

Exit codes:
  0  All checks passed / version sync applied cleanly
  1  Version drift, stale version string, or readback verification mismatch
  2  Invalid CLI arguments, unparseable manifest, or unsafe/symlinked path
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import http.client
import json
import os
import pathlib
import re
import stat
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SEMVER_TOKEN_RE = re.compile(
    r"(?<![0-9A-Za-z._-])v?((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?)(?![0-9A-Za-z._-])"
)
CARGO_SECTION_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
CARGO_VERSION_RE = re.compile(r'^(\s*version\s*=\s*)"([^"\r\n]+)"(\s*(?:#.*)?)$')
PROJECT_YML_VERSION_RE = re.compile(
    r'^(\s*MARKETING_VERSION\s*:\s*)(["\']?)([^"\'\s#]+)(\2)(\s*(?:#.*)?)$',
    re.MULTILINE,
)
PBXPROJ_VERSION_RE = re.compile(
    r'^(\s*MARKETING_VERSION\s*=\s*)(["\']?)([^"\';\s]+)(\2)(\s*;\s*(?://.*|/\*.*\*/\s*)?)$',
    re.MULTILINE,
)

ROOT_MANIFEST_CANDIDATES = (
    "VERSION",
    "package.json",
    "Cargo.toml",
    "project.yml",
)
WORKSPACE_DIRS = ("packages", "apps")
WORKSPACE_MANIFEST_NAMES = ("package.json", "Cargo.toml", "project.yml")


class ReleaseSyncError(ValueError):
    """Raised when input or repository target state is invalid or unsafe."""

    def __init__(self, message: str, code: str = "invalid_input") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TargetRecord:
    path: str
    kind: str
    previous_version: str
    version: str
    drifted: bool
    updated: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "previous_version": self.previous_version,
            "version": self.version,
            "drifted": self.drifted,
            "updated": self.updated,
        }


@dataclass(frozen=True)
class Finding:
    path: str
    kind: str
    detail: str
    expected: str = ""
    actual: str = ""

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": self.path,
            "kind": self.kind,
            "detail": self.detail,
        }
        if self.expected:
            result["expected"] = self.expected
        if self.actual:
            result["actual"] = self.actual
        return result


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
    root: pathlib.Path, rel_path: str, *, expect_dir: bool = False
) -> pathlib.Path:
    if not _valid_local_path(rel_path):
        raise ReleaseSyncError(
            f"unsafe_target: path must be a safe repository-relative path: {rel_path!r}",
            code="unsafe_target",
        )
    target = root / rel_path
    symlink = _has_symlink_ancestor(root, target)
    if symlink is not None:
        rel_symlink = symlink.relative_to(root).as_posix()
        raise ReleaseSyncError(
            f"symlink_target: {rel_path} traverses symlink {rel_symlink}",
            code="symlink_target",
        )
    if not _within_root(root, target):
        raise ReleaseSyncError(
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
            continue
        is_last = index == len(parts) - 1
        if stat.S_ISLNK(st.st_mode):
            raise ReleaseSyncError(
                f"symlink_target: {rel_path} traverses symlink {current.relative_to(root).as_posix()}",
                code="symlink_target",
            )
        if not is_last and not stat.S_ISDIR(st.st_mode):
            raise ReleaseSyncError(
                f"unsafe_target: ancestor {current.relative_to(root).as_posix()} is not a directory",
                code="unsafe_target",
            )
        if is_last:
            if expect_dir and not stat.S_ISDIR(st.st_mode):
                raise ReleaseSyncError(
                    f"unsafe_target: expected directory at {rel_path}",
                    code="unsafe_target",
                )
            if not expect_dir and not stat.S_ISREG(st.st_mode):
                raise ReleaseSyncError(
                    f"unsafe_target: existing target {rel_path} is not a regular file",
                    code="unsafe_target",
                )
    return target


def _validate_repo_root(repo_root: pathlib.Path) -> pathlib.Path:
    if repo_root.is_symlink():
        raise ReleaseSyncError(
            f"symlink_target: repository root is a symlink: {repo_root}",
            code="symlink_target",
        )
    if not repo_root.is_dir():
        raise ReleaseSyncError(
            f"invalid_input: repository root is not a directory: {repo_root}",
            code="invalid_input",
        )
    return repo_root.resolve(strict=True)


def validate_semver(version: str) -> str:
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        raise ReleaseSyncError(
            f"invalid_input: invalid SemVer version {version!r}",
            code="invalid_input",
        )
    return version


def bump_semver(version: str, part: str) -> str:
    match = SEMVER_RE.fullmatch(version)
    if not match:
        raise ReleaseSyncError(
            f"invalid_input: cannot bump non-SemVer version {version!r}",
            code="invalid_input",
        )
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ReleaseSyncError(
        f"invalid_input: unsupported bump part {part!r}; expected patch, minor, or major",
        code="invalid_input",
    )


def _classify_target(rel_path: str) -> str:
    name = pathlib.PurePosixPath(rel_path).name
    if name == "VERSION":
        return "version_file"
    if name == "package.json":
        return "package_json"
    if name == "Cargo.toml":
        return "cargo_toml"
    if name == "project.yml":
        return "project_yml"
    if name.endswith(".pbxproj"):
        return "pbxproj"
    raise ReleaseSyncError(
        f"invalid_input: unsupported version target file type: {rel_path}",
        code="invalid_input",
    )


def _parse_and_render_target(
    rel_path: str, kind: str, content: str, new_version: str | None
) -> tuple[list[str], str]:
    """Extract version(s) in `content` and optionally render updated content for `new_version`."""
    if kind == "version_file":
        raw = content.strip()
        if not raw or "\n" in raw or not SEMVER_RE.fullmatch(raw):
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} does not contain a single valid SemVer string",
                code="invalid_input",
            )
        rendered = f"{new_version}\n" if new_version is not None else content
        return [raw], rendered

    if kind == "package_json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as error:
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} is not valid JSON: {error}",
                code="invalid_input",
            ) from None
        if not isinstance(data, dict) or not isinstance(data.get("version"), str):
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} is missing a string 'version' field",
                code="invalid_input",
            )
        current = validate_semver(data["version"])
        if new_version is None:
            return [current], content
        updated_data = dict(data)
        updated_data["version"] = new_version
        return [current], json.dumps(updated_data, indent=2, ensure_ascii=False) + "\n"

    if kind == "cargo_toml":
        lines = content.splitlines(keepends=True)
        section = ""
        found_versions: list[str] = []
        out_lines: list[str] = []
        for line in lines:
            stripped = line.rstrip("\r\n")
            newline = line[len(stripped):] or "\n"
            sec_match = CARGO_SECTION_RE.match(stripped)
            if sec_match:
                section = sec_match.group(1).strip()
                out_lines.append(line)
                continue
            if section in ("package", "workspace.package"):
                ver_match = CARGO_VERSION_RE.match(stripped)
                if ver_match:
                    ver = validate_semver(ver_match.group(2))
                    found_versions.append(ver)
                    if new_version is not None:
                        out_lines.append(
                            f'{ver_match.group(1)}"{new_version}"{ver_match.group(3)}{newline}'
                        )
                    else:
                        out_lines.append(line)
                    continue
            out_lines.append(line)
        if not found_versions:
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} has no [package] version field",
                code="invalid_input",
            )
        rendered = "".join(out_lines)
        if not rendered.endswith("\n"):
            rendered += "\n"
        return found_versions, rendered if new_version is not None else content

    if kind == "project_yml":
        matches = list(PROJECT_YML_VERSION_RE.finditer(content))
        if not matches:
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} has no MARKETING_VERSION entry",
                code="invalid_input",
            )
        versions = [validate_semver(m.group(3)) for m in matches]
        if new_version is None:
            return versions, content
        rendered = PROJECT_YML_VERSION_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{new_version}{m.group(4)}{m.group(5)}",
            content,
        )
        if not rendered.endswith("\n"):
            rendered += "\n"
        return versions, rendered

    if kind == "pbxproj":
        matches = list(PBXPROJ_VERSION_RE.finditer(content))
        if not matches:
            raise ReleaseSyncError(
                f"invalid_input: {rel_path} has no MARKETING_VERSION setting",
                code="invalid_input",
            )
        versions = [validate_semver(m.group(3)) for m in matches]
        if new_version is None:
            return versions, content
        rendered = PBXPROJ_VERSION_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{new_version}{m.group(4)}{m.group(5)}",
            content,
        )
        if not rendered.endswith("\n"):
            rendered += "\n"
        return versions, rendered

    raise ReleaseSyncError(f"invalid_input: unknown target kind {kind!r}", code="invalid_input")


def _discover_xcode_targets_in_dir(root: pathlib.Path, directory: pathlib.Path) -> list[str]:
    found: list[str] = []
    for entry in sorted(directory.iterdir()):
        rel_entry = entry.relative_to(root).as_posix()
        if entry.name.endswith(".pbxproj"):
            _ensure_safe_target(root, rel_entry)
            found.append(rel_entry)
        elif entry.name.endswith(".xcodeproj"):
            _ensure_safe_target(root, rel_entry, expect_dir=True)
            pbx = entry / "project.pbxproj"
            rel_pbx = pbx.relative_to(root).as_posix()
            if pbx.exists() or pbx.is_symlink():
                _ensure_safe_target(root, rel_pbx)
                found.append(rel_pbx)
    return found


def discover_version_targets(root: pathlib.Path) -> list[str]:
    targets: list[str] = []
    for rel in ROOT_MANIFEST_CANDIDATES:
        candidate = root / rel
        if candidate.exists() or candidate.is_symlink():
            _ensure_safe_target(root, rel)
            targets.append(rel)

    targets.extend(_discover_xcode_targets_in_dir(root, root))

    for ws_name in WORKSPACE_DIRS:
        ws_dir = root / ws_name
        if not ws_dir.exists() and not ws_dir.is_symlink():
            continue
        _ensure_safe_target(root, ws_name, expect_dir=True)
        for pkg_dir in sorted(ws_dir.iterdir()):
            rel_pkg = pkg_dir.relative_to(root).as_posix()
            if pkg_dir.is_symlink():
                _ensure_safe_target(root, rel_pkg, expect_dir=True)
            if not pkg_dir.is_dir():
                continue
            _ensure_safe_target(root, rel_pkg, expect_dir=True)
            for manifest_name in WORKSPACE_MANIFEST_NAMES:
                manifest = pkg_dir / manifest_name
                rel_manifest = manifest.relative_to(root).as_posix()
                if manifest.exists() or manifest.is_symlink():
                    _ensure_safe_target(root, rel_manifest)
                    targets.append(rel_manifest)
            targets.extend(_discover_xcode_targets_in_dir(root, pkg_dir))

    seen: set[str] = set()
    ordered: list[str] = []
    for rel in targets:
        if rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    return ordered


def _split_csv_args(values: list[str] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for raw in values:
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned:
                items.append(cleaned)
    return items


def _stage_sibling_temp(target_path: pathlib.Path, payload: bytes, mode: int) -> pathlib.Path:
    tmp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            prefix=f".{target_path.name}.tmp-",
            delete=False,
        ) as tmp_file:
            tmp_path = pathlib.Path(tmp_file.name)
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.chmod(tmp_path, mode)
        return tmp_path
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _atomic_apply_writes(
    root: pathlib.Path,
    planned_writes: list[tuple[str, pathlib.Path, bytes, int, bytes]],
) -> None:
    staged: list[tuple[str, pathlib.Path, bytes, int, pathlib.Path]] = []
    try:
        for rel, target_path, orig_bytes, mode, new_bytes in planned_writes:
            _ensure_safe_target(root, rel)
            tmp_path = _stage_sibling_temp(target_path, new_bytes, mode)
            staged.append((rel, target_path, orig_bytes, mode, tmp_path))
    except Exception as error:
        for _, _, _, _, tmp_path in staged:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(error, ReleaseSyncError):
            raise
        raise ReleaseSyncError(
            f"write_failed: failed to stage version updates before replacement: {error}",
            code="write_failed",
        ) from None

    committed: list[tuple[str, pathlib.Path, bytes, int]] = []
    failed_rel = ""
    try:
        for rel, target_path, orig_bytes, mode, tmp_path in staged:
            failed_rel = rel
            _ensure_safe_target(root, rel)
            if tmp_path.is_symlink():
                raise ReleaseSyncError(
                    f"symlink_target: staged temporary file became a symlink for {rel}",
                    code="symlink_target",
                )
            os.replace(tmp_path, target_path)
            committed.append((rel, target_path, orig_bytes, mode))
    except Exception as error:
        for _, _, _, _, tmp_path in staged:
            try:
                if tmp_path.exists() or tmp_path.is_symlink():
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        rollback_errors: list[str] = []
        for c_rel, c_target, c_orig_bytes, c_mode in reversed(committed):
            rb_tmp: pathlib.Path | None = None
            try:
                _ensure_safe_target(root, c_rel)
                rb_tmp = _stage_sibling_temp(c_target, c_orig_bytes, c_mode)
                os.replace(rb_tmp, c_target)
            except Exception:
                if rb_tmp is not None:
                    try:
                        rb_tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    _ensure_safe_target(root, c_rel)
                    with open(c_target, "wb") as fh:
                        fh.write(c_orig_bytes)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.chmod(c_target, c_mode)
                except Exception as rb_err:
                    rollback_errors.append(f"{c_rel}: {rb_err}")
        if rollback_errors:
            raise ReleaseSyncError(
                f"write_failed: failed to update {failed_rel} ({error}); "
                f"rollback errors: {'; '.join(rollback_errors)}",
                code="write_failed",
            ) from None
        if isinstance(error, ReleaseSyncError):
            raise
        raise ReleaseSyncError(
            f"write_failed: failed to update {failed_rel} "
            f"(rolled back {len(committed)} target(s)): {error}",
            code="write_failed",
        ) from None


def run_version_sync(
    repo_root: pathlib.Path,
    *,
    version: str | None = None,
    bump: str | None = None,
    apply: bool = False,
    targets: list[str] | None = None,
    check_stale_files: list[str] | None = None,
    check_stale_enabled: bool = False,
    previous_version: str | None = None,
) -> dict[str, Any]:
    root = _validate_repo_root(repo_root)
    if version is not None and bump is not None:
        raise ReleaseSyncError(
            "invalid_input: --version and --bump are mutually exclusive",
            code="invalid_input",
        )
    if version is not None:
        validate_semver(version)
    if previous_version is not None:
        validate_semver(previous_version)

    target_rels = list(targets) if targets else discover_version_targets(root)
    if not target_rels:
        raise ReleaseSyncError(
            "invalid_input: no version targets discovered or specified",
            code="invalid_input",
        )

    # Atomically validate all target paths and parse current versions before any write.
    parsed_targets: list[tuple[str, pathlib.Path, str, bytes, int, str, list[str]]] = []
    for rel in target_rels:
        target_path = _ensure_safe_target(root, rel)
        if not target_path.is_file():
            raise ReleaseSyncError(
                f"invalid_input: target file does not exist: {rel}",
                code="invalid_input",
            )
        kind = _classify_target(rel)
        try:
            mode = stat.S_IMODE(target_path.lstat().st_mode)
            orig_bytes = target_path.read_bytes()
            content = orig_bytes.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise ReleaseSyncError(
                f"invalid_input: cannot read {rel}: {error}",
                code="invalid_input",
            ) from None
        found_versions, _ = _parse_and_render_target(rel, kind, content, None)
        parsed_targets.append((rel, target_path, kind, orig_bytes, mode, content, found_versions))

    stale_rels = list(check_stale_files) if check_stale_files else []
    stale_paths: list[tuple[str, pathlib.Path]] = []
    for rel in stale_rels:
        stale_path = _ensure_safe_target(root, rel)
        if not stale_path.is_file():
            raise ReleaseSyncError(
                f"invalid_input: stale-check file does not exist: {rel}",
                code="invalid_input",
            )
        stale_paths.append((rel, stale_path))

    canonical_previous = parsed_targets[0][6][0]
    if version is not None:
        expected_version = version
    elif bump is not None:
        expected_version = bump_semver(canonical_previous, bump)
    else:
        if apply:
            raise ReleaseSyncError(
                "invalid_input: --apply requires --version or --bump",
                code="invalid_input",
            )
        expected_version = canonical_previous

    # Render updates in memory and validate all outputs before touching disk.
    planned_writes: list[tuple[str, pathlib.Path, bytes, int, bytes]] = []
    records: list[TargetRecord] = []
    findings: list[Finding] = []
    observed_previous_versions: set[str] = set()
    if previous_version is not None:
        observed_previous_versions.add(previous_version)

    for rel, target_path, kind, orig_bytes, mode, content, found_versions in parsed_targets:
        for v in found_versions:
            if v != expected_version:
                observed_previous_versions.add(v)
        unique_versions = sorted(set(found_versions))
        prev_display = unique_versions[0] if len(unique_versions) == 1 else ",".join(unique_versions)
        has_drift = any(v != expected_version for v in found_versions)
        _, rendered = _parse_and_render_target(rel, kind, content, expected_version)
        rendered_bytes = rendered.encode("utf-8")
        needs_write = has_drift or (rendered_bytes != orig_bytes and apply)
        if apply and needs_write:
            planned_writes.append((rel, target_path, orig_bytes, mode, rendered_bytes))
        if not apply and has_drift:
            findings.append(
                Finding(
                    path=rel,
                    kind="version_mismatch",
                    expected=expected_version,
                    actual=prev_display,
                    detail=f"{rel} has version {prev_display}, expected {expected_version}",
                )
            )
        records.append(
            TargetRecord(
                path=rel,
                kind=kind,
                previous_version=prev_display,
                version=expected_version if (apply or not has_drift) else prev_display,
                drifted=has_drift,
                updated=bool(apply and needs_write),
            )
        )

    if apply and planned_writes:
        _atomic_apply_writes(root, planned_writes)

    if check_stale_enabled or stale_paths:
        scan_list = stale_paths if stale_paths else [(rel, p) for rel, p, _, _, _, _, _ in parsed_targets]
        for rel, scan_path in scan_list:
            _ensure_safe_target(root, rel)
            try:
                text = scan_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise ReleaseSyncError(
                    f"invalid_input: cannot read {rel}: {error}",
                    code="invalid_input",
                ) from None
            stale_hits: set[str] = set()
            for old_ver in sorted(observed_previous_versions):
                if old_ver != expected_version and re.search(
                    r"(?<![0-9A-Za-z._-])v?" + re.escape(old_ver) + r"(?![0-9A-Za-z._-])",
                    text,
                ):
                    stale_hits.add(old_ver)
            for token_match in SEMVER_TOKEN_RE.finditer(text):
                candidate_ver = token_match.group(1)
                if candidate_ver != expected_version and (
                    not observed_previous_versions or candidate_ver in observed_previous_versions
                    or (rel, scan_path) in stale_paths
                ):
                    stale_hits.add(candidate_ver)
            for stale_ver in sorted(stale_hits):
                findings.append(
                    Finding(
                        path=rel,
                        kind="stale_version",
                        expected=expected_version,
                        actual=stale_ver,
                        detail=f"{rel} contains leftover version string {stale_ver} (expected {expected_version})",
                    )
                )

    drifted_count = sum(1 for r in records if r.drifted)
    ok = len(findings) == 0 and (apply or drifted_count == 0)
    return {
        "ok": ok,
        "mode": "apply" if apply else "check",
        "version": expected_version,
        "previous_version": canonical_previous,
        "drifted_count": drifted_count,
        "targets": [r.as_dict() for r in records],
        "findings": [f.as_dict() for f in findings],
    }


class _NoRedirectHttpOnlyProcessor(urllib.request.HTTPErrorProcessor):
    """Ensure only http/https schemes are ever followed."""


def _validate_live_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ReleaseSyncError("invalid_input: --live-url must be a non-empty URL", code="invalid_input")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        raise ReleaseSyncError(
            f"unsafe_target: --live-url contains control or whitespace characters: {url!r}",
            code="unsafe_target",
        )
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
        raise ReleaseSyncError(
            f"unsafe_target: --live-url must use http:// or https:// scheme with a host: {url!r}",
            code="unsafe_target",
        )
    return url


def _resolve_readback_file(root: pathlib.Path, raw_path: str) -> tuple[str, pathlib.Path]:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ReleaseSyncError(
            f"unsafe_target: invalid file path {raw_path!r}",
            code="unsafe_target",
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw_path):
        raise ReleaseSyncError(
            f"unsafe_target: control character in path {raw_path!r}",
            code="unsafe_target",
        )
    candidate = pathlib.Path(raw_path)
    if ".." in candidate.parts:
        raise ReleaseSyncError(
            f"unsafe_target: path traversal '..' is not allowed: {raw_path!r}",
            code="unsafe_target",
        )
    if not candidate.is_absolute():
        safe = _ensure_safe_target(root, raw_path)
        return raw_path, safe

    # If an absolute path is inside `root`, enforce full ancestor symlink checks from `root`.
    try:
        rel_to_root = candidate.relative_to(root)
    except ValueError:
        rel_to_root = None
    if rel_to_root is not None:
        rel_str = rel_to_root.as_posix()
        safe = _ensure_safe_target(root, rel_str)
        return rel_str, safe

    raise ReleaseSyncError(
        f"unsafe_target: path {raw_path!r} resolves outside repository root {root}",
        code="unsafe_target",
    )


def _check_live_endpoint(
    live_url: str,
    expected_version: str,
    expected_sha: str | None,
    *,
    timeout: float,
    retries: int,
) -> tuple[dict[str, Any], list[Finding]]:
    _validate_live_url(live_url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
    )
    last_error = ""
    status_code = 0
    raw_body = ""
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        req = urllib.request.Request(
            live_url,
            headers={"Accept": "application/json", "User-Agent": "shared-ci-release-sync/1.0"},
            method="GET",
        )
        try:
            with opener.open(req, timeout=timeout) as resp:
                status_code = getattr(resp, "status", 200)
                final_url = resp.geturl()
                _validate_live_url(final_url)
                raw_body = resp.read(1_048_576).decode("utf-8", errors="strict")
                if status_code == 200:
                    break
                last_error = f"HTTP {status_code}"
        except urllib.error.HTTPError as error:
            status_code = error.code
            last_error = f"HTTP {error.code}"
        except (urllib.error.URLError, http.client.HTTPException, OSError, UnicodeError) as error:
            status_code = 0
            last_error = str(error)
        if attempt + 1 < attempts:
            time.sleep(0.05)

    findings: list[Finding] = []
    if status_code != 200:
        findings.append(
            Finding(
                path=live_url,
                kind="live_http_error",
                expected="200",
                actual=str(status_code or "error"),
                detail=f"live readback request to {live_url} failed: {last_error}",
            )
        )
        return {"url": live_url, "status": status_code, "ok": False}, findings

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as error:
        findings.append(
            Finding(
                path=live_url,
                kind="live_invalid_json",
                detail=f"live readback response from {live_url} is not valid JSON: {error}",
            )
        )
        return {"url": live_url, "status": status_code, "ok": False}, findings

    if not isinstance(payload, dict):
        findings.append(
            Finding(
                path=live_url,
                kind="live_invalid_json",
                detail=f"live readback response from {live_url} must be a JSON object",
            )
        )
        return {"url": live_url, "status": status_code, "ok": False}, findings

    observed_version = payload.get("version")
    normalized_observed = (
        observed_version[1:]
        if isinstance(observed_version, str) and observed_version.startswith("v")
        else observed_version
    )
    if not isinstance(observed_version, str) or normalized_observed != expected_version:
        findings.append(
            Finding(
                path=live_url,
                kind="live_version_mismatch",
                expected=expected_version,
                actual=str(observed_version or ""),
                detail=(
                    f"live endpoint reported version {observed_version!r}, "
                    f"expected {expected_version!r}"
                ),
            )
        )

    observed_sha: Any = None
    for sha_key in ("sha", "commit", "git_sha", "revision"):
        if sha_key in payload:
            observed_sha = payload[sha_key]
            break
    if expected_sha is not None:
        if not isinstance(observed_sha, str) or observed_sha.lower() != expected_sha:
            findings.append(
                Finding(
                    path=live_url,
                    kind="live_sha_mismatch",
                    expected=expected_sha,
                    actual=str(observed_sha or ""),
                    detail=(
                        f"live endpoint reported sha {observed_sha!r}, "
                        f"expected {expected_sha!r}"
                    ),
                )
            )

    check_summary = {
        "url": live_url,
        "status": status_code,
        "observed_version": observed_version,
        "observed_sha": observed_sha,
        "ok": len(findings) == 0,
    }
    return check_summary, findings


def _parse_checksums_file(rel_path: str, content: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_no, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ReleaseSyncError(
                f"invalid_input: malformed checksum line at {rel_path}:{line_no}",
                code="invalid_input",
            )
        digest, raw_name = parts[0], parts[1].strip()
        if raw_name.startswith("*"):
            raw_name = raw_name[1:].strip()
        if not SHA256_RE.fullmatch(digest):
            raise ReleaseSyncError(
                f"invalid_input: invalid SHA-256 digest at {rel_path}:{line_no}",
                code="invalid_input",
            )
        if not _valid_local_path(raw_name):
            raise ReleaseSyncError(
                f"unsafe_target: unsafe artifact path {raw_name!r} in {rel_path}:{line_no}",
                code="unsafe_target",
            )
        entries[raw_name] = digest.lower()
    if not entries:
        raise ReleaseSyncError(
            f"invalid_input: checksums file {rel_path} contains no valid entries",
            code="invalid_input",
        )
    return entries


def _check_artifacts_checksums(
    root: pathlib.Path,
    checksums_arg: str,
    artifact_args: list[str],
) -> tuple[dict[str, Any], list[Finding]]:
    checksums_rel, checksums_path = _resolve_readback_file(root, checksums_arg)
    if not checksums_path.is_file():
        raise ReleaseSyncError(
            f"invalid_input: checksums file does not exist: {checksums_rel}",
            code="invalid_input",
        )
    try:
        checksums_text = checksums_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ReleaseSyncError(
            f"invalid_input: cannot read checksums file {checksums_rel}: {error}",
            code="invalid_input",
        ) from None

    expected_digests = _parse_checksums_file(checksums_rel, checksums_text)
    basename_map: dict[str, list[str]] = {}
    for name, digest in expected_digests.items():
        base = pathlib.PurePosixPath(name).name
        basename_map.setdefault(base, []).append(digest)

    findings: list[Finding] = []
    verified_artifacts: list[dict[str, Any]] = []
    for raw_artifact in artifact_args:
        art_rel, art_path = _resolve_readback_file(root, raw_artifact)
        if not art_path.is_file():
            findings.append(
                Finding(
                    path=art_rel,
                    kind="artifact_missing",
                    detail=f"artifact file {art_rel} does not exist",
                )
            )
            verified_artifacts.append({"path": art_rel, "ok": False})
            continue
        actual_digest = hashlib.sha256(art_path.read_bytes()).hexdigest().lower()
        expected_digest = expected_digests.get(art_rel)
        if expected_digest is None:
            base = pathlib.PurePosixPath(art_rel).name
            candidates = basename_map.get(base, [])
            if len(candidates) == 1:
                expected_digest = candidates[0]
        if expected_digest is None:
            findings.append(
                Finding(
                    path=art_rel,
                    kind="artifact_missing_checksum",
                    detail=f"artifact {art_rel} is not listed in {checksums_rel}",
                )
            )
            verified_artifacts.append(
                {"path": art_rel, "actual_sha256": actual_digest, "ok": False}
            )
            continue
        matched = actual_digest == expected_digest
        if not matched:
            findings.append(
                Finding(
                    path=art_rel,
                    kind="checksum_mismatch",
                    expected=expected_digest,
                    actual=actual_digest,
                    detail=(
                        f"SHA-256 mismatch for {art_rel}: "
                        f"expected {expected_digest}, got {actual_digest}"
                    ),
                )
            )
        verified_artifacts.append(
            {
                "path": art_rel,
                "expected_sha256": expected_digest,
                "actual_sha256": actual_digest,
                "ok": matched,
            }
        )

    return (
        {
            "checksums_file": checksums_rel,
            "artifacts": verified_artifacts,
            "ok": len(findings) == 0,
        },
        findings,
    )


def _check_release_metadata(
    root: pathlib.Path,
    release_json_arg: str,
    expected_version: str,
    expected_assets: list[str],
) -> tuple[dict[str, Any], list[Finding]]:
    rel_path, json_path = _resolve_readback_file(root, release_json_arg)
    if not json_path.is_file():
        raise ReleaseSyncError(
            f"invalid_input: release JSON file does not exist: {rel_path}",
            code="invalid_input",
        )
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseSyncError(
            f"invalid_input: invalid release JSON in {rel_path}: {error}",
            code="invalid_input",
        ) from None
    if not isinstance(data, dict):
        raise ReleaseSyncError(
            f"invalid_input: release JSON in {rel_path} must be a JSON object",
            code="invalid_input",
        )

    findings: list[Finding] = []
    tag_name = data.get("tag_name")
    valid_tags = {expected_version, f"v{expected_version}"}
    if not isinstance(tag_name, str) or tag_name not in valid_tags:
        findings.append(
            Finding(
                path=rel_path,
                kind="release_tag_mismatch",
                expected=f"v{expected_version}",
                actual=str(tag_name or ""),
                detail=(
                    f"release tag_name is {tag_name!r}, "
                    f"expected 'v{expected_version}' or '{expected_version}'"
                ),
            )
        )

    draft = data.get("draft")
    if draft is not False:
        findings.append(
            Finding(
                path=rel_path,
                kind="release_is_draft",
                expected="false",
                actual=str(draft),
                detail=f"release draft flag is {draft!r}, expected False",
            )
        )

    raw_assets = data.get("assets")
    asset_sizes: dict[str, int] = {}
    if not isinstance(raw_assets, list) or not raw_assets:
        findings.append(
            Finding(
                path=rel_path,
                kind="release_assets_empty",
                detail="release metadata contains no assets",
            )
        )
    else:
        for index, asset in enumerate(raw_assets):
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str) or not asset["name"]:
                findings.append(
                    Finding(
                        path=rel_path,
                        kind="release_asset_invalid",
                        detail=f"release asset at index {index} is missing a valid name",
                    )
                )
                continue
            name = asset["name"]
            size = asset.get("size")
            state = asset.get("state", "uploaded")
            if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
                findings.append(
                    Finding(
                        path=rel_path,
                        kind="release_asset_empty",
                        expected=">0",
                        actual=str(size),
                        detail=f"release asset {name!r} has non-positive size {size!r}",
                    )
                )
            if state != "uploaded":
                findings.append(
                    Finding(
                        path=rel_path,
                        kind="release_asset_state",
                        expected="uploaded",
                        actual=str(state),
                        detail=f"release asset {name!r} state is {state!r}, expected 'uploaded'",
                    )
                )
            asset_sizes[name] = size if isinstance(size, int) else 0

    for expected_name in expected_assets:
        if expected_name not in asset_sizes:
            findings.append(
                Finding(
                    path=rel_path,
                    kind="release_asset_missing",
                    expected=expected_name,
                    actual="missing",
                    detail=f"expected release asset {expected_name!r} is missing from release metadata",
                )
            )

    return (
        {
            "release_json": rel_path,
            "tag_name": tag_name,
            "draft": draft,
            "assets": asset_sizes,
            "ok": len(findings) == 0,
        },
        findings,
    )


def run_readback(
    repo_root: pathlib.Path,
    *,
    expected_version: str,
    expected_sha: str | None = None,
    live_url: str | None = None,
    checksums_file: str | None = None,
    artifacts: list[str] | None = None,
    release_json: str | None = None,
    expected_assets: list[str] | None = None,
    timeout: float = 10.0,
    retries: int = 0,
) -> dict[str, Any]:
    root = _validate_repo_root(repo_root)
    validate_semver(expected_version)
    if expected_sha is not None and not SHA_RE.fullmatch(expected_sha):
        raise ReleaseSyncError(
            f"invalid_input: --expected-sha must be a 40-char lowercase hex SHA, got {expected_sha!r}",
            code="invalid_input",
        )
    if timeout <= 0:
        raise ReleaseSyncError("invalid_input: --timeout must be positive", code="invalid_input")
    if retries < 0:
        raise ReleaseSyncError("invalid_input: --retries must be non-negative", code="invalid_input")

    artifact_list = list(artifacts) if artifacts else []
    if bool(checksums_file) != bool(artifact_list):
        raise ReleaseSyncError(
            "invalid_input: --checksums-file and --artifact must be provided together",
            code="invalid_input",
        )
    if not live_url and not checksums_file and not release_json:
        raise ReleaseSyncError(
            "invalid_input: at least one readback source (--live-url, --checksums-file, or --release-json) is required",
            code="invalid_input",
        )

    checks: dict[str, Any] = {}
    findings: list[Finding] = []

    if live_url:
        live_summary, live_findings = _check_live_endpoint(
            live_url,
            expected_version,
            expected_sha,
            timeout=timeout,
            retries=retries,
        )
        checks["live"] = live_summary
        findings.extend(live_findings)

    if checksums_file:
        checksum_summary, checksum_findings = _check_artifacts_checksums(
            root, checksums_file, artifact_list
        )
        checks["checksums"] = checksum_summary
        findings.extend(checksum_findings)

    if release_json:
        asset_names = list(expected_assets) if expected_assets else [
            pathlib.PurePosixPath(a).name for a in artifact_list
        ]
        release_summary, release_findings = _check_release_metadata(
            root, release_json, expected_version, asset_names
        )
        checks["release"] = release_summary
        findings.extend(release_findings)

    return {
        "ok": len(findings) == 0,
        "expected_version": expected_version,
        "expected_sha": expected_sha,
        "checks": checks,
        "findings": [f.as_dict() for f in findings],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release_sync.py",
        description="Cross-target atomic version sync and post-release live-readback verifier.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    vs = subparsers.add_parser(
        "version-sync",
        help="Check or synchronize version strings across repository manifests.",
    )
    vs.add_argument("--root", default=".", help="Repository root directory (default: .).")
    ver_group = vs.add_mutually_exclusive_group()
    ver_group.add_argument("--version", default=None, help="Target SemVer version string.")
    ver_group.add_argument(
        "--bump",
        choices=("patch", "minor", "major"),
        default=None,
        help="Bump canonical SemVer version by patch, minor, or major.",
    )
    mode_group = vs.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--check",
        action="store_true",
        help="Verify all version targets match expected version (default).",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Atomically update all version targets to the target version.",
    )
    vs.add_argument(
        "--targets",
        action="append",
        default=[],
        help="Comma-separated repository-relative target file paths (default: auto-discover).",
    )
    vs.add_argument(
        "--check-stale",
        nargs="*",
        action="extend",
        default=None,
        help="Scan specified files (or discovered targets) for leftover previous version strings.",
    )
    vs.add_argument(
        "--previous-version",
        default=None,
        help="Explicit previous SemVer string to scan for when --check-stale is enabled.",
    )

    rb = subparsers.add_parser(
        "readback",
        help="Verify live deployment endpoint, artifact SHA256SUMS, and GitHub Release metadata.",
    )
    rb.add_argument("--root", default=".", help="Repository root directory (default: .).")
    rb.add_argument(
        "--expected-version",
        required=True,
        help="Expected SemVer version string.",
    )
    rb.add_argument(
        "--expected-sha",
        default=None,
        help="Expected 40-character lowercase commit SHA.",
    )
    rb.add_argument(
        "--live-url",
        default=None,
        help="Live HTTP/HTTPS endpoint URL returning JSON with version (and optional sha/commit).",
    )
    rb.add_argument(
        "--checksums-file",
        default=None,
        help="Path to SHA256SUMS file.",
    )
    rb.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="Artifact path(s) to verify against --checksums-file.",
    )
    rb.add_argument(
        "--release-json",
        default=None,
        help="Path to GitHub Release JSON file.",
    )
    rb.add_argument(
        "--expected-asset",
        action="append",
        default=[],
        help="Expected asset filename(s) in --release-json.",
    )
    rb.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10.0).",
    )
    rb.add_argument(
        "--retries",
        type=int,
        default=0,
        help="Number of HTTP retry attempts on transient failure (default: 0).",
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
        if args.subcommand == "version-sync":
            stale_arg = args.check_stale
            check_stale_enabled = stale_arg is not None
            stale_files = _split_csv_args(stale_arg) if stale_arg else []
            report = run_version_sync(
                repo_root,
                version=args.version,
                bump=args.bump,
                apply=bool(args.apply),
                targets=_split_csv_args(args.targets),
                check_stale_files=stale_files,
                check_stale_enabled=check_stale_enabled,
                previous_version=args.previous_version,
            )
        else:
            report = run_readback(
                repo_root,
                expected_version=args.expected_version,
                expected_sha=args.expected_sha,
                live_url=args.live_url,
                checksums_file=args.checksums_file,
                artifacts=_split_csv_args(args.artifact),
                release_json=args.release_json,
                expected_assets=_split_csv_args(args.expected_asset),
                timeout=args.timeout,
                retries=args.retries,
            )
    except ReleaseSyncError as error:
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
