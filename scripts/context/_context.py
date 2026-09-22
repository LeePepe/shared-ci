#!/usr/bin/env python3
"""Reusable recursive layer-context resolver and anti-drift audit.

Derived from LeePepe/AIDash at 30092ed0d09e2b6e7a4a9f49d7cd64627fbf898e,
scripts/context/_context.py (blob 8fbcba556fa83e54d04432e8ccf13e930656d4fc).
Product ownership and policy remain in caller-authored context documents.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


ROOT_CONTEXT = "CONTEXT.md"
VALID_GATE_KINDS = {"build", "check", "lint", "test"}
VALID_GATE_MODES = {"both", "ci", "local"}


class ContextError(Exception):
    """A context document is malformed or cannot be resolved."""

    def __init__(self, detail: str, kind: str = "invalid_context") -> None:
        super().__init__(detail)
        self.kind = kind


@dataclass(frozen=True)
class Finding:
    layer: str
    path: str
    kind: str
    detail: str
    red_lines: tuple[str, ...] = ()

    def emit(self) -> None:
        print(json.dumps({
            "layer": self.layer,
            "path": self.path,
            "kind": self.kind,
            "detail": self.detail,
            "red_lines": list(self.red_lines),
        }, ensure_ascii=False), file=sys.stderr)


@dataclass(frozen=True)
class Resolution:
    path: str
    classification: str
    context: str
    chain: tuple[str, ...]
    layer: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "classification": self.classification,
            "layer": self.layer,
            "context": self.context,
            "chain": list(self.chain),
            "reason": self.reason,
        }


def repo_root(start: pathlib.Path | None = None) -> pathlib.Path:
    command = ["git", "rev-parse", "--show-toplevel"]
    try:
        result = subprocess.run(command, cwd=start, text=True, capture_output=True, check=False)
    except OSError as error:
        raise ContextError(f"cannot discover git worktree: {error}") from error
    if result.returncode != 0:
        raise ContextError("not inside a git worktree")
    return pathlib.Path(result.stdout.strip()).resolve()


def normalize_path(root: pathlib.Path, raw: str, *,
                   allow_external_executable: bool = False) -> str:
    """Check containment before content access; inspect only alias metadata outside.

    The root is the trusted, absolute worktree root. Internal symlinks are
    allowed; relative names stay logical and absolute inputs canonicalize.
    Only argv[0] may opt into retaining an absolute installed-tool spelling
    that never enters root. That exception is never applied after entry.
    """
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ContextError("path must name a repository file", "unsafe_path")

    def relative_parts(value: str) -> list[str] | None:
        """Return the suffix at first root entry, or None for an outside path."""
        path = pathlib.Path(value)
        if not path.is_absolute():
            return list(path.parts)
        try:
            return list(path.relative_to(root).parts)
        except ValueError:
            pass

        # An absolute spelling may reach the canonical root through ancestors
        # such as /tmp -> /private/tmp, or a caller-owned alias. Read link
        # metadata only, stopping as soon as we enter root. Do not resolve the
        # entire target first: that would hide later escapes and re-entry.
        pending_alias = list(path.parts[1:])
        # Use the canonical root's POSIX anchor, including for // spellings.
        ancestor = pathlib.Path(root.anchor)
        alias_links = 0
        while pending_alias:
            part = pending_alias.pop(0)
            if part == "..":
                ancestor = ancestor.parent
                continue
            candidate = ancestor / part
            try:
                inside = candidate.relative_to(root)
            except ValueError:
                pass
            else:
                return list(inside.parts) + pending_alias
            try:
                target = os.readlink(candidate)
            except OSError as error:
                if error.errno == errno.EINVAL:  # Ordinary ancestor, not a link.
                    ancestor = candidate
                    continue
                if error.errno in (errno.ENOENT, errno.ENOTDIR):
                    return None  # Missing installed tools still get launch diagnostics.
                raise ContextError(f"path is outside repository or inaccessible: {raw}",
                                   "unsafe_path") from error
            alias_links += 1
            if alias_links > 40:
                raise ContextError(f"symlink cycle: {raw}", "unsafe_path")
            link = pathlib.Path(target)
            if link.is_absolute():
                ancestor = pathlib.Path(root.anchor)
                pending_alias = list(link.parts[1:]) + pending_alias
            else:
                pending_alias = list(link.parts) + pending_alias
        return None

    # Lexically reject an escape even if a later component would re-enter.
    raw_parts = relative_parts(raw)
    if raw_parts is None:
        if allow_external_executable and pathlib.Path(raw).is_absolute():
            return raw
        raise ContextError(f"path is outside repository: {raw}", "unsafe_path")
    logical: list[str] = []
    for part in raw_parts:
        if part == "..":
            if not logical:
                raise ContextError(f"path is outside repository: {raw}", "unsafe_path")
            logical.pop()
        elif part != ".":
            logical.append(part)
    if not logical:
        raise ContextError("path must name a repository file")

    pending = list(raw_parts)
    resolved: list[str] = []
    links = 0
    while pending:
        part = pending.pop(0)
        if part == ".":
            continue
        if part == "..":
            if not resolved:
                raise ContextError(f"path is outside repository: {raw}", "unsafe_path")
            resolved.pop()
            continue
        candidate = root.joinpath(*resolved, part)
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            resolved.append(part)
            continue
        except OSError as error:
            raise ContextError(f"cannot inspect path {raw}: {error}", "unsafe_path") from error
        if stat.S_ISLNK(mode):
            links += 1
            if links > 40:
                raise ContextError(f"symlink cycle: {raw}", "unsafe_path")
            target = os.readlink(candidate)
            if os.path.isabs(target):
                target_parts = relative_parts(target)
                if target_parts is None:
                    # Root was already entered: do not fall back to the
                    # installed-tool exception, even for an executable.
                    raise ContextError(f"path is outside repository: {raw}", "unsafe_path")
                pending = target_parts + pending
                resolved = []
            else:
                pending = list(pathlib.Path(target).parts) + pending
        else:
            resolved.append(part)
    # The fixed source canonicalized absolute inputs but kept relative logical
    # names. Preserve that successful output contract for internal symlinks.
    if pathlib.Path(raw).is_absolute():
        if not resolved:
            raise ContextError("path must name a repository file")
        return "/".join(resolved)
    normalized = "/".join(logical)
    if ".." in raw_parts:
        # Removing '..' may change which path will be opened after an internal
        # symlink. Validate that returned spelling too, not just the raw walk.
        return normalize_path(root, normalized)
    return normalized


def context_target(root: pathlib.Path, parent: str, target: str) -> str:
    return normalize_path(root, str(pathlib.PurePosixPath(parent).parent / target))


def require_utf8(value: str, field: str) -> None:
    """Reject surrogate code points without echoing unprintable input."""
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ContextError(f"{field} must be encodable as UTF-8", "invalid_gate") from None


def validate_context(data: dict[str, Any], path: str) -> None:
    """Validate the documented schema-1 subset, not arbitrary JSON Schema.

    Missing schema is the fixed source's legacy spelling of schema 1. Unknown
    project metadata is preserved; recognized fields are never silently coerced.
    """
    def fail(detail: str, kind: str = "invalid_context") -> None:
        raise ContextError(f"{path}: {detail}", kind)

    def string(value: Any, field: str, kind: str = "invalid_context") -> None:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            fail(f"{field} must be a non-empty string", kind)

    def strings(obj: dict[str, Any], field: str, kind: str = "invalid_context") -> None:
        value = obj.get(field, [])
        if not isinstance(value, list):
            fail(f"{field} must be a string list", kind)
        for item in value:
            string(item, field, kind)

    if "schema" in data and (type(data["schema"]) is not int or data["schema"] != 1):
        fail("unsupported schema; expected integer 1")
    if data.get("kind") not in ("index", "leaf"):
        fail("kind must be index or leaf")
    for field in ("layer", "parent", "group"):
        if field in data:
            string(data[field], field)
    for field in ("scope", "test_paths", "dependencies", "dependents", "red_lines"):
        strings(data, field)
    for key in ("routes", "exclusions"):
        entries = data.get(key, [])
        if not isinstance(entries, list):
            fail(f"{key} must be a list")
        for entry in entries:
            if not isinstance(entry, dict) or "patterns" not in entry:
                fail(f"invalid {key} entry")
            strings(entry, "patterns")
            if key == "routes":
                string(entry.get("context"), "route context")
                strings(entry, "test_paths")
            else:
                string(entry.get("reason"), "exclusion reason")
    if data["kind"] == "index":
        if any(key in data for key in ("layer", "group", "parent", "scope", "test_paths",
                                       "dependencies", "dependents", "gates", "red_lines", "manifest")):
            fail("index contains leaf fields", "index_contains_leaf_fields")
    else:
        for field in ("layer", "parent"):
            string(data.get(field), field, "invalid_leaf")
        if "scope" not in data:
            fail("leaf requires scope", "invalid_leaf")
        if "routes" in data or "exclusions" in data:
            fail("leaf contains index fields", "invalid_leaf")
    gates = data.get("gates", [])
    if not isinstance(gates, list):
        fail("gates must be a list", "invalid_gate")
    ids: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict):
            fail("gate must be an object", "invalid_gate")
        string(gate.get("id"), "gate id", "invalid_gate")
        if gate["id"] in ids:
            fail("duplicate gate id", "invalid_gate")
        ids.add(gate["id"])
        if gate.get("kind") not in tuple(VALID_GATE_KINDS):
            fail("unknown gate kind", "invalid_gate")
        if gate.get("mode") not in tuple(VALID_GATE_MODES):
            fail("unknown gate mode", "invalid_gate")
        strings(gate, "command", "invalid_gate")
        if not gate.get("command"):
            fail("gate command must not be empty", "invalid_gate")
        for index, token in enumerate(gate["command"]):
            require_utf8(token, f"command argument {index}")
            if "{" in token or "}" in token:
                if token not in ("{test_paths}", "{owned_python_paths}") or index == 0:
                    fail(f"unknown or malformed path placeholder: {token!r}", "invalid_gate")
    if "manifest" in data:
        manifest = data["manifest"]
        if not isinstance(manifest, dict):
            fail("manifest must be an object", "invalid_manifest")
        if manifest.get("kind") not in ("swift-package", "xcodegen-target"):
            fail("unknown manifest kind", "invalid_manifest")
        string(manifest.get("path"), "manifest path", "invalid_manifest")
        strings(manifest, "local_dependencies", "invalid_manifest")
        strings(manifest, "external_dependencies", "invalid_manifest")
        if "target" in manifest or manifest["kind"] == "xcodegen-target":
            string(manifest.get("target"), "manifest target", "invalid_manifest")
        if manifest["kind"] == "swift-package" and manifest.get("external_dependencies"):
            fail("external_dependencies applies only to xcodegen-target", "invalid_manifest")
        if set(manifest.get("local_dependencies", [])) & set(manifest.get("external_dependencies", [])):
            fail("local and external dependencies must be disjoint", "invalid_manifest")


def parse_context(root: pathlib.Path, relative: str) -> dict[str, Any]:
    relative = normalize_path(root, relative)
    path = root / relative
    if not path.is_file():
        raise ContextError(f"missing context: {relative}", "missing_context")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContextError(f"cannot read context {relative}: {error}") from error
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|\Z)", text, re.DOTALL)
    if match is None:
        raise ContextError(f"missing JSON frontmatter: {relative}")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ContextError(f"invalid JSON frontmatter in {relative}: {error}") from error
    if not isinstance(data, dict):
        raise ContextError(f"frontmatter must be an object: {relative}")
    validate_context(data, relative)
    if "parent" in data:
        normalize_path(root, data["parent"])
    data["_context_path"] = relative
    return data


def match_pattern(path: str, pattern: str) -> bool:
    """Match POSIX paths; ** crosses directories and * does not."""
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                if index + 2 < len(pattern) and pattern[index + 2] == "/":
                    pieces.append("(?:.*/)?")
                    index += 3
                else:
                    pieces.append(".*")
                    index += 2
            else:
                pieces.append("[^/]*")
                index += 1
        elif char == "?":
            pieces.append("[^/]")
            index += 1
        else:
            pieces.append(re.escape(char))
            index += 1
    return re.fullmatch("".join(pieces), path) is not None


def relative_to_context(context_path: str, repo_path: str) -> str:
    parent = pathlib.PurePosixPath(context_path).parent
    if str(parent) == ".":
        return repo_path
    prefix = f"{parent.as_posix()}/"
    if not repo_path.startswith(prefix):
        return repo_path
    return repo_path[len(prefix):]


def _matching_entries(data: dict[str, Any], path: str, key: str) -> list[dict[str, Any]]:
    relative = relative_to_context(data["_context_path"], path)
    matched: list[dict[str, Any]] = []
    entries = data.get(key, [])
    if not isinstance(entries, list):
        raise ContextError(f"{key} must be a list: {data['_context_path']}")
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("patterns"), list):
            raise ContextError(f"invalid {key} entry: {data['_context_path']}")
        pattern_fields = ("patterns", "test_paths") if key == "routes" else ("patterns",)
        patterns: list[Any] = []
        for field in pattern_fields:
            value = entry.get(field, [])
            if not isinstance(value, list):
                raise ContextError(f"{field} must be a list: {data['_context_path']}")
            patterns.extend(value)
        if any(isinstance(pattern, str) and match_pattern(relative, pattern)
               for pattern in patterns):
            matched.append(entry)
    return matched


def resolve(root: pathlib.Path, raw_path: str) -> Resolution:
    path = normalize_path(root, raw_path)
    current = ROOT_CONTEXT
    chain: list[str] = []
    visited: set[str] = set()
    while True:
        if current in visited:
            raise ContextError(f"context cycle while resolving {path}: {current}")
        visited.add(current)
        chain.append(current)
        data = parse_context(root, current)
        kind = data.get("kind")
        if kind == "leaf":
            layer = data.get("layer")
            if not isinstance(layer, str) or not layer:
                raise ContextError(f"leaf has no layer: {current}")
            parent = data.get("parent")
            if not isinstance(parent, str) or not parent:
                raise ContextError(f"leaf has no parent: {current}")
            if len(chain) < 2 or normalize_path(root, parent) != chain[-2]:
                raise ContextError(f"parent/leaf ownership mismatch at {current}: {path}")
            relative = relative_to_context(normalize_path(root, parent), path)
            ownership = _list_of_strings(data, "scope") + _list_of_strings(data, "test_paths")
            if not any(match_pattern(relative, pattern) for pattern in ownership):
                raise ContextError(f"parent/leaf ownership mismatch at {current}: {path}")
            return Resolution(path, "leaf", current, tuple(chain), layer=layer)
        if kind != "index":
            raise ContextError(f"invalid context kind in {current}: {kind!r}")
        routes = _matching_entries(data, path, "routes")
        exclusions = _matching_entries(data, path, "exclusions")
        if len(routes) + len(exclusions) == 0:
            raise ContextError(f"unmapped path at {current}: {path}")
        if len(routes) + len(exclusions) > 1:
            raise ContextError(f"sibling overlap at {current}: {path}")
        if exclusions:
            reason = exclusions[0].get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ContextError(f"exclusion has no reason at {current}: {path}")
            return Resolution(path, "excluded", current, tuple(chain), reason=reason)
        target = routes[0].get("context")
        if not isinstance(target, str) or not target:
            raise ContextError(f"route has no context at {current}: {path}")
        current = context_target(root, current, target)


def discover_contexts(root: pathlib.Path) -> tuple[dict[str, dict[str, Any]], list[Finding]]:
    discovered: dict[str, dict[str, Any]] = {}
    findings: list[Finding] = []
    pending = [ROOT_CONTEXT]
    active: set[str] = set()
    completed: set[str] = set()

    def visit(context_path: str) -> None:
        if context_path in active:
            findings.append(Finding("context", context_path, "cycle", "context route cycle"))
            return
        if context_path in completed:
            return
        active.add(context_path)
        try:
            data = parse_context(root, context_path)
        except ContextError as error:
            findings.append(Finding("context", context_path, error.kind, str(error)))
            active.remove(context_path)
            completed.add(context_path)
            return
        discovered[context_path] = data
        if data.get("kind") == "index":
            for route in data.get("routes", []):
                if not isinstance(route, dict) or not isinstance(route.get("context"), str):
                    continue
                try:
                    visit(context_target(root, context_path, route["context"]))
                except ContextError as error:
                    findings.append(Finding("context", context_path, error.kind, str(error)))
        active.remove(context_path)
        completed.add(context_path)

    while pending:
        visit(pending.pop())
    return discovered, findings


def tracked_files(root: pathlib.Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "-z"],
            cwd=root, capture_output=True, check=False,
        )
    except OSError as error:
        raise ContextError(f"cannot enumerate tracked files: {error}") from error
    if result.returncode != 0:
        raise ContextError(result.stderr.decode("utf-8", errors="replace").strip())
    return sorted({item.decode("utf-8", errors="surrogateescape")
                   for item in result.stdout.split(b"\0") if item})


def _list_of_strings(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ContextError(f"{field} must be a string list: {data['_context_path']}")
    return value


def _manifest_text(root: pathlib.Path, manifest: str) -> str:
    path = root / normalize_path(root, manifest)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContextError(f"cannot read manifest {manifest}: {error}", "invalid_manifest") from error


def _swift_package_dependencies(root: pathlib.Path, manifest: str) -> set[str]:
    text = _manifest_text(root, manifest)
    return set(re.findall(r'\.package\(path:\s*"\.\./([^"/]+)"', text))


def _project_target_dependencies(root: pathlib.Path, manifest: str, target: str) -> set[str]:
    lines = _manifest_text(root, manifest).splitlines()
    in_targets = False
    in_target = False
    in_dependencies = False
    dependencies: set[str] = set()
    for line in lines:
        if line == "targets:":
            in_targets = True
            continue
        if not in_targets:
            continue
        target_match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if target_match:
            if in_target:
                break
            in_target = target_match.group(1) == target
            in_dependencies = False
            continue
        if not in_target:
            continue
        if re.match(r"^    dependencies:\s*$", line):
            in_dependencies = True
            continue
        if in_dependencies and re.match(r"^    [A-Za-z]", line):
            in_dependencies = False
        if in_dependencies:
            match = re.match(r"^      - package:\s*([A-Za-z0-9_-]+)\s*$", line)
            if match:
                dependencies.add(match.group(1))
    return dependencies


def audit(root: pathlib.Path) -> tuple[list[Finding], dict[str, int]]:
    contexts, findings = discover_contexts(root)
    leaves: dict[str, dict[str, Any]] = {}
    context_to_layer: dict[str, str] = {}

    for path, data in contexts.items():
        kind = data.get("kind")
        if kind not in {"index", "leaf"}:
            findings.append(Finding("context", path, "invalid_context", f"invalid kind: {kind!r}"))
            continue
        if kind == "leaf":
            layer = data.get("layer")
            if not isinstance(layer, str) or not layer:
                findings.append(Finding("context", path, "invalid_leaf", "missing layer ID"))
                continue
            if layer in leaves:
                findings.append(Finding(layer, path, "duplicate_layer_id",
                                        f"also declared by {leaves[layer]['_context_path']}"))
            else:
                leaves[layer] = data
                context_to_layer[path] = layer
        elif any(key in data for key in ("layer", "group", "dependencies", "gates", "red_lines")):
            findings.append(Finding("context", path, "index_contains_leaf_fields",
                                    "index contexts may contain routes and exclusions only"))

    for parent_path, parent in contexts.items():
        if parent.get("kind") != "index":
            continue
        for route in parent.get("routes", []):
            if not isinstance(route, dict) or not isinstance(route.get("context"), str):
                findings.append(Finding("context", parent_path, "invalid_route", "route is malformed"))
                continue
            try:
                target_path = context_target(root, parent_path, route["context"])
            except ContextError:
                continue  # Already reported by discovery; never follow the target.
            child = contexts.get(target_path)
            if child and child.get("kind") == "leaf":
                expected_parent = child.get("parent")
                if normalize_path(root, expected_parent) != parent_path:
                    findings.append(Finding(str(child.get("layer", "context")), target_path,
                                            "parent_leaf_mismatch",
                                            f"parent={expected_parent!r}; routed by {parent_path!r}"))
                if child.get("scope") != route.get("patterns"):
                    findings.append(Finding(str(child.get("layer", "context")), target_path,
                                            "parent_leaf_mismatch",
                                            "leaf scope differs from parent route patterns"))
                if child.get("test_paths", []) != route.get("test_paths", []):
                    findings.append(Finding(str(child.get("layer", "context")), target_path,
                                            "parent_leaf_mismatch",
                                            "leaf test_paths differ from parent route test_paths"))

    for layer, data in leaves.items():
        path = data["_context_path"]
        red_lines: tuple[str, ...] = ()
        try:
            red_lines = tuple(_list_of_strings(data, "red_lines"))
            _list_of_strings(data, "scope")
            _list_of_strings(data, "test_paths")
            dependencies = _list_of_strings(data, "dependencies")
            dependents = _list_of_strings(data, "dependents")
        except ContextError as error:
            findings.append(Finding(layer, path, "invalid_leaf", str(error)))
            continue
        group = data.get("group")
        if group is not None and (not isinstance(group, str) or not group):
            findings.append(Finding(layer, path, "invalid_leaf",
                                    "group must be a non-empty string", red_lines))
        gates = data.get("gates", [])
        if not isinstance(gates, list):
            findings.append(Finding(layer, path, "invalid_gate", "gates must be a list", red_lines))
            gates = []
        gate_ids: set[str] = set()
        for gate in gates:
            valid = isinstance(gate, dict)
            gate_id = gate.get("id") if valid else None
            gate_kind = gate.get("kind") if valid else None
            command = gate.get("command") if valid else None
            mode = gate.get("mode") if valid else None
            if (not valid or not isinstance(gate_id, str) or not gate_id
                    or gate_id in gate_ids or gate_kind not in VALID_GATE_KINDS
                    or not isinstance(command, list) or not command
                    or any(not isinstance(token, str) or not token for token in command)
                    or mode not in VALID_GATE_MODES):
                findings.append(Finding(layer, path, "invalid_gate", f"invalid gate: {gate!r}", red_lines))
            else:
                gate_ids.add(gate_id)
                placeholders = {token for token in command if token.startswith("{")}
                if placeholders - {"{test_paths}", "{owned_python_paths}"}:
                    findings.append(Finding(layer, path, "invalid_gate",
                                            f"unknown path placeholder: {sorted(placeholders)!r}",
                                            red_lines))
        for dependency in dependencies:
            if dependency not in leaves:
                findings.append(Finding(layer, path, "missing_dependency", dependency, red_lines))
            elif layer not in leaves[dependency].get("dependents", []):
                findings.append(Finding(layer, path, "reciprocal_dependency_drift",
                                        f"{dependency}.dependents omits {layer}", red_lines))
        for dependent in dependents:
            if dependent not in leaves:
                findings.append(Finding(layer, path, "missing_dependency", dependent, red_lines))
            elif layer not in leaves[dependent].get("dependencies", []):
                findings.append(Finding(layer, path, "reciprocal_dependency_drift",
                                        f"{dependent}.dependencies omits {layer}", red_lines))

        manifest = data.get("manifest")
        if manifest is not None:
            if not isinstance(manifest, dict) or manifest.get("kind") not in {
                    "swift-package", "xcodegen-target"} or not isinstance(manifest.get("path"), str):
                findings.append(Finding(layer, path, "invalid_manifest", repr(manifest), red_lines))
            else:
                try:
                    manifest_path = normalize_path(root, manifest["path"])
                except ContextError as error:
                    findings.append(Finding(layer, path, error.kind, str(error), red_lines))
                    continue
                if not (root / manifest_path).is_file():
                    findings.append(Finding(layer, manifest_path, "missing_manifest", "file does not exist", red_lines))
                else:
                    try:
                        if manifest["kind"] == "swift-package":
                            actual = _swift_package_dependencies(root, manifest_path)
                        else:
                            actual = _project_target_dependencies(root, manifest_path, manifest["target"])
                            actual -= set(manifest.get("external_dependencies", []))
                    except ContextError as error:
                        findings.append(Finding(layer, manifest_path, error.kind, str(error), red_lines))
                        continue
                    expected = set(manifest.get("local_dependencies", []))
                    if actual != expected:
                        findings.append(Finding(layer, manifest_path, "manifest_dependency_drift",
                                                f"expected={sorted(expected)} actual={sorted(actual)}", red_lines))

    dependency_state: dict[str, int] = {}
    dependency_stack: list[str] = []

    def visit_dependency(layer: str) -> None:
        state = dependency_state.get(layer, 0)
        if state == 2:
            return
        if state == 1:
            start = dependency_stack.index(layer)
            cycle = dependency_stack[start:] + [layer]
            findings.append(Finding(layer, leaves[layer]["_context_path"], "dependency_cycle",
                                    " -> ".join(cycle),
                                    tuple(leaves[layer].get("red_lines", []))))
            return
        dependency_state[layer] = 1
        dependency_stack.append(layer)
        for dependency in leaves[layer].get("dependencies", []):
            if dependency in leaves:
                visit_dependency(dependency)
        dependency_stack.pop()
        dependency_state[layer] = 2

    for layer in leaves:
        visit_dependency(layer)

    counts = {"leaf": 0, "excluded": 0, "total": 0}
    for path in tracked_files(root):
        counts["total"] += 1
        try:
            result = resolve(root, path)
        except ContextError as error:
            kind = "sibling_overlap" if "sibling overlap" in str(error) else "unmapped_path"
            findings.append(Finding("context", path, kind, str(error)))
            continue
        counts[result.classification] += 1
    return findings, counts


def layer_map(root: pathlib.Path) -> dict[str, dict[str, Any]]:
    contexts, findings = discover_contexts(root)
    if findings:
        raise ContextError(findings[0].detail)
    layers: dict[str, dict[str, Any]] = {}
    for data in contexts.values():
        if data["kind"] == "leaf":
            if data["layer"] in layers:
                raise ContextError(f"duplicate layer ID: {data['layer']}")
            layers[data["layer"]] = data
        else:
            for route in data.get("routes", []):
                child = contexts[context_target(root, data["_context_path"], route["context"])]
                if child["kind"] == "leaf" and (
                        normalize_path(root, child["parent"]) != data["_context_path"]
                        or child["scope"] != route["patterns"]
                        or child.get("test_paths", []) != route.get("test_paths", [])):
                    raise ContextError(f"parent/leaf ownership mismatch at {child['_context_path']}")
    return layers


def command_audit(args: argparse.Namespace, root: pathlib.Path) -> int:
    findings, counts = audit(root)
    for finding in findings:
        finding.emit()
    summary = {"ok": not findings, "classifications": counts, "findings": len(findings)}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not findings else 1


def command_resolve(args: argparse.Namespace, root: pathlib.Path) -> int:
    status = 0
    for raw in args.paths:
        try:
            result = resolve(root, raw)
        except ContextError as error:
            Finding("context", raw, "resolve_failed", str(error)).emit()
            status = 1
            continue
        if args.format == "layer":
            print(result.layer if result.classification == "leaf" else "")
        elif args.format == "context":
            print(result.context)
        else:
            print(json.dumps(result.as_dict(), ensure_ascii=False))
    return status


def command_layers(args: argparse.Namespace, root: pathlib.Path) -> int:
    layers = layer_map(root)
    if getattr(args, "group", None) is not None:
        if args.paths or args.stdin or args.all:
            raise ContextError("--group cannot be combined with paths, --stdin, or --all")
        selected = sorted(name for name, data in layers.items() if data.get("group") == args.group)
        if not selected:
            raise ContextError(f"unknown or empty layer group: {args.group}")
        if args.json:
            print(json.dumps(selected, ensure_ascii=False))
        else:
            for name in selected:
                print(name)
        return 0
    if args.all:
        if args.paths or args.stdin:
            raise ContextError("--all cannot be combined with paths or --stdin")
        if args.json:
            print(json.dumps({name: data["_context_path"] for name, data in sorted(layers.items())},
                             ensure_ascii=False, indent=2))
        else:
            for name in sorted(layers):
                print(name)
        return 0

    raw_paths = list(args.paths)
    if args.stdin:
        raw_paths.extend(line for line in sys.stdin.read().splitlines() if line)
    if not raw_paths:
        raise ContextError("provide one or more paths, --stdin, or --all")

    touched: set[str] = set()
    status = 0
    for raw in raw_paths:
        try:
            result = resolve(root, raw)
        except ContextError as error:
            Finding("context", raw, "resolve_failed", str(error)).emit()
            status = 1
            continue
        if result.classification == "leaf":
            touched.add(result.layer)
    if args.json:
        print(json.dumps(sorted(touched), ensure_ascii=False))
    else:
        for name in sorted(touched):
            print(name)
    return status


def nested_field(data: dict[str, Any], field: str) -> Any:
    value: Any = data
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ContextError(f"unknown field: {field}")
        value = value[part]
    return value


def command_field(args: argparse.Namespace, root: pathlib.Path) -> int:
    layers = layer_map(root)
    if args.layer not in layers:
        raise ContextError(f"unknown layer: {args.layer}")
    value = nested_field(layers[args.layer], args.field)
    if isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def command_contexts(args: argparse.Namespace, root: pathlib.Path) -> int:
    for raw in args.paths:
        result = resolve(root, raw)
        if len(args.paths) > 1:
            print(f"{result.path}:")
        for context in result.chain:
            print(context)
    return 0


def command_run(args: argparse.Namespace, root: pathlib.Path) -> int:
    layers = layer_map(root)
    if args.layer not in layers:
        raise ContextError(f"unknown layer: {args.layer}")
    data = layers[args.layer]
    if args.path is not None:
        normalize_path(root, args.path)
    red_lines = tuple(_list_of_strings(data, "red_lines"))
    gates = data.get("gates", [])
    selected = [gate for gate in gates
                if (args.gate is None or gate.get("id") == args.gate)
                and gate.get("mode") in {"both", args.mode}]
    if not selected:
        raise ContextError(f"unknown or unavailable {args.mode} gate for {args.layer}: {args.gate}")
    owned_files: list[str] | None = None

    def resolved_owned_files() -> list[str]:
        nonlocal owned_files
        if owned_files is None:
            owned_files = []
            for path in tracked_files(root):
                require_utf8(path, "expanded path")
                normalize_path(root, path)  # Unsafe tracked paths must never be skipped.
                try:
                    resolution = resolve(root, path)
                except ContextError:
                    continue
                if resolution.classification == "leaf" and resolution.layer == args.layer:
                    owned_files.append(path)
        return owned_files

    def expand_command(command: list[str]) -> list[str]:
        expanded: list[str] = []
        parent = normalize_path(root, data.get("parent", ROOT_CONTEXT))
        test_patterns = _list_of_strings(data, "test_paths")
        for token in command:
            paths: list[str] = []
            if token == "{test_paths}":
                paths = [
                    path for path in resolved_owned_files()
                    if path.endswith(".py")
                    and any(match_pattern(relative_to_context(parent, path), pattern)
                            for pattern in test_patterns)
                ]
            elif token == "{owned_python_paths}":
                paths = [path for path in resolved_owned_files() if path.endswith(".py")]
            else:
                expanded.append(token)
                continue
            if not paths:
                raise ContextError(f"empty path placeholder for {args.layer}: {token}")
            expanded.extend(paths)
        return expanded

    def validate_command_paths(command: list[str]) -> None:
        positional_only = False
        for index, token in enumerate(command):
            # Also validate expansion output before it reaches path APIs/logging.
            require_utf8(token, f"command argument {index}")
            if index == 0:
                # argv[0] is never an option: a separator makes it an executable
                # pathname regardless of its first character. Bare names use
                # the caller's trusted PATH, retaining the local-symlink check.
                if os.path.isabs(token):
                    normalize_path(root, token, allow_external_executable=True)
                elif "/" in token or token == ".." or (root / token).is_symlink():
                    normalize_path(root, token)
                continue
            if not positional_only:
                if token == "--":
                    positional_only = True
                    continue
                if token.startswith("-"):
                    # Opaque options/option-encoded values are caller-owned.
                    # Do not interpret them as filenames before the separator.
                    continue
            # Ordinary arguments and every token after '--' are positional.
            # A later '--' is a filename, not another option terminator.
            if "/" in token or token == "..":
                normalize_path(root, token)
            elif (root / token).is_symlink():
                normalize_path(root, token)

    def gate_log(gate: dict[str, Any], command: list[str]) -> str:
        line = f"[context/run] {args.layer}:{gate['id']} — {' '.join(command)}"
        require_utf8(line, "gate log")
        return line

    # Check every raw command before expansion can invoke discovery Git, then
    # check expanded paths before executing even the first selected gate.
    for gate in selected:
        gate_log(gate, gate["command"])
        validate_command_paths(gate["command"])
    prepared = [(gate, expand_command(gate["command"])) for gate in selected]
    logs: list[str] = []
    for gate, command in prepared:
        validate_command_paths(command)
        logs.append(gate_log(gate, command))
    for (gate, command), log in zip(prepared, logs):
        print(log, flush=True)
        try:
            result = subprocess.run(command, cwd=root, check=False)
        except OSError as error:
            Finding(args.layer, args.path or data["_context_path"], "gate_execution_failed",
                    f"gate={gate['id']} error={error}", red_lines).emit()
            return 1
        if result.returncode != 0:
            Finding(args.layer, args.path or data["_context_path"], "gate_failed",
                    f"gate={gate['id']} exit={result.returncode}", red_lines).emit()
            return 128 - result.returncode if result.returncode < 0 else result.returncode
    return 0


def parser_for(command_name: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"scripts/context/{command_name}")
    if command_name == "audit":
        parser.set_defaults(handler=command_audit)
    elif command_name == "resolve":
        parser.add_argument("paths", nargs="+")
        parser.add_argument("--format", choices=("json", "layer", "context"), default="json")
        parser.set_defaults(handler=command_resolve)
    elif command_name == "layers":
        parser.add_argument("paths", nargs="*")
        parser.add_argument("--stdin", action="store_true")
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--group")
        parser.add_argument("--json", action="store_true")
        parser.set_defaults(handler=command_layers)
    elif command_name == "field":
        parser.add_argument("layer")
        parser.add_argument("field")
        parser.set_defaults(handler=command_field)
    elif command_name == "contexts":
        parser.add_argument("paths", nargs="+")
        parser.set_defaults(handler=command_contexts)
    elif command_name == "run":
        parser.add_argument("layer")
        parser.add_argument("--gate")
        parser.add_argument("--mode", choices=("local", "ci"), default="local")
        parser.add_argument("--path")
        parser.set_defaults(handler=command_run)
    else:
        raise ContextError(f"unknown context command: {command_name}")
    return parser


def main() -> int:
    command_name = pathlib.Path(sys.argv[0]).name
    try:
        if command_name == "_context.py":
            if len(sys.argv) < 2:
                raise ContextError("missing context command")
            command_name = sys.argv.pop(1)
        root = repo_root()
        parser = parser_for(command_name)
        args = parser.parse_args()
        return args.handler(args, root)
    except ContextError as error:
        Finding("context", ROOT_CONTEXT, "context_error", str(error)).emit()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
