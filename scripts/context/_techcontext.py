"""Simplified per-layer `tech-context.md` layer map (repo-kit format).

Activated only when the caller root has no `CONTEXT.md` but has a root
`docs/architecture/tech-context.md` (or root `tech-context.md`). The root
declares `support` exclusions in frontmatter and a Markdown table listing each
layer's `tech-context.md`. Each leaf declares `layer`, root-relative `owns`
globs, `depends_on`, optional `gate` (id -> command) and `red_lines`.
Leaves are translated into the schema-1 leaf shape so `field`/`run` keep the
existing semantics. Legacy `CONTEXT.md` trees are never routed here.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import shlex
from typing import Any

ROOT_CANDIDATES = ("docs/architecture/tech-context.md", "tech-context.md")
LEAF_NAME = "tech-context.md"
_NONE_TOKENS = {"", "-", "—", "–", "none", "(none)", "(无)", "无", "n/a"}
_ROOT_REASON = "root layer map"


def _sibling(name: str) -> Any:
    path = pathlib.Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("shared_ci_" + name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fm = _sibling("_frontmatter")


def root_context(root: pathlib.Path) -> str | None:
    if (root / "CONTEXT.md").exists() or (root / "CONTEXT.md").is_symlink():
        return None
    for candidate in ROOT_CANDIDATES:
        if (root / candidate).is_file():
            return candidate
    return None


def _read(ctx: Any, root: pathlib.Path, relative: str) -> tuple[dict[str, Any], str]:
    relative = ctx.normalize_path(root, relative)
    path = root / relative
    if not path.is_file():
        raise ctx.ContextError(f"missing context: {relative}", "missing_context")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ctx.ContextError(f"cannot read context {relative}: {error}") from error
    parts = _fm.split_frontmatter(text)
    if parts is None:
        raise ctx.ContextError(f"missing frontmatter: {relative}")
    raw, body = parts
    try:
        data = json.loads(raw) if raw.lstrip().startswith("{") else _fm.parse(raw)
    except (ValueError, json.JSONDecodeError) as error:
        raise ctx.ContextError(f"invalid frontmatter in {relative}: {error}") from error
    if not isinstance(data, dict):
        raise ctx.ContextError(f"frontmatter must be a mapping: {relative}")
    return data, body


def _strings(ctx: Any, data: dict[str, Any], key: str, path: str, *, required: bool = False) -> list[str]:
    value = data.get(key, [] if not required else None)
    if value is None and not required:
        value = []
    if not isinstance(value, list) or (required and not value) or any(
            not isinstance(item, str) or not item.strip() or "\0" in item for item in value):
        raise ctx.ContextError(f"{path}: {key} must be a {'non-empty ' if required else ''}string list",
                               "invalid_leaf")
    return list(value)


def _gates(ctx: Any, data: dict[str, Any], path: str) -> list[dict[str, Any]]:
    gate = data.get("gate")
    if gate is None and isinstance(data.get("test"), str):
        gate = {"test": data["test"]}  # Legacy single-command spelling.
    if gate is None:
        return []
    if not isinstance(gate, dict):
        raise ctx.ContextError(f"{path}: gate must map gate id to a command", "invalid_gate")
    gates = []
    for gate_id, command in gate.items():
        if isinstance(command, str):
            try:
                argv = shlex.split(command)
            except ValueError as error:
                raise ctx.ContextError(f"{path}: gate {gate_id}: {error}", "invalid_gate") from None
        elif isinstance(command, list) and all(isinstance(token, str) for token in command):
            argv = list(command)
        else:
            raise ctx.ContextError(f"{path}: gate {gate_id} must be a string or string list", "invalid_gate")
        kind = gate_id if gate_id in ctx.VALID_GATE_KINDS else "check"
        gates.append({"id": str(gate_id), "kind": kind, "mode": "both", "command": argv})
    return gates


def parse_leaf(ctx: Any, root: pathlib.Path, root_path: str, relative: str) -> dict[str, Any]:
    data, _ = _read(ctx, root, relative)
    layer = data.get("layer")
    if not isinstance(layer, str) or not layer.strip() or layer == "_root":
        raise ctx.ContextError(f"{relative}: layer must be a non-empty layer ID", "invalid_leaf")
    leaf = {key: value for key, value in data.items()
            if key not in {"owns", "depends_on", "depended_by", "gate"}}
    leaf.update({
        "schema": 1, "kind": "leaf", "layer": layer, "parent": root_path,
        "scope": _strings(ctx, data, "owns", relative, required=True),
        "test_paths": [],
        "dependencies": _strings(ctx, data, "depends_on", relative),
        "red_lines": _strings(ctx, data, "red_lines", relative),
        "gates": _gates(ctx, data, relative),
        "format": "tech-context",
    })
    if "depended_by" in data:
        leaf["dependents"] = _strings(ctx, data, "depended_by", relative)
    else:
        leaf.pop("dependents", None)
    ctx.validate_context({k: v for k, v in leaf.items() if k != "format"}, relative)
    leaf["_context_path"] = relative
    return leaf


def _cell(value: str) -> str:
    return value.strip().strip("`").strip()


def parse_table(body: str) -> list[dict[str, Any]]:
    """Rows of the first table whose header has Layer and tech-context columns."""
    lines = [line.strip() for line in body.splitlines()]
    for index, line in enumerate(lines):
        if not line.startswith("|") or index + 1 >= len(lines):
            continue
        header = [cell.strip().lower() for cell in line.strip("|").split("|")]
        if not re.match(r"^\|?\s*:?-{3,}", lines[index + 1]):
            continue
        try:
            layer_col = next(i for i, cell in enumerate(header) if cell == "layer")
            path_col = next(i for i, cell in enumerate(header) if "tech-context" in cell)
        except StopIteration:
            continue
        depends_col = next((i for i, cell in enumerate(header) if "depends" in cell), None)
        rows = []
        for row in lines[index + 2:]:
            if not row.startswith("|"):
                break
            cells = [cell for cell in row.strip("|").split("|")]
            if len(cells) <= max(layer_col, path_col):
                continue
            depends = None
            if depends_col is not None and depends_col < len(cells):
                depends = sorted(
                    token for token in (_cell(part) for part in re.split(r"[,，、]", cells[depends_col]))
                    if token.lower() not in _NONE_TOKENS and not token.endswith("(ext)"))
            rows.append({"layer": _cell(cells[layer_col]), "path": _cell(cells[path_col]),
                         "depends_on": depends})
        return rows
    return []


def load(ctx: Any, root: pathlib.Path, root_path: str) -> dict[str, Any]:
    """Return {root, support, rows, leaves: {path: leaf}, errors: [Finding]}."""
    data, body = _read(ctx, root, root_path)
    support = []
    for entry in data.get("support", []) or []:
        if isinstance(entry, str):
            entry = {"patterns": [entry], "reason": "declared support path"}
        if (not isinstance(entry, dict) or not isinstance(entry.get("patterns"), list)
                or not entry["patterns"] or not isinstance(entry.get("reason"), str)
                or not entry["reason"].strip()
                or any(not isinstance(p, str) or not p for p in entry["patterns"])):
            raise ctx.ContextError(f"{root_path}: support entries need patterns and a reason")
        support.append({"patterns": list(entry["patterns"]), "reason": entry["reason"]})
    rows = parse_table(body)
    if not rows:
        raise ctx.ContextError(f"{root_path}: no layer table with Layer and tech-context columns")
    leaves: dict[str, dict[str, Any]] = {}
    errors = []
    for row in rows:
        try:
            leaves[ctx.normalize_path(root, row["path"])] = parse_leaf(ctx, root, root_path, row["path"])
        except ctx.ContextError as error:
            errors.append(ctx.Finding(row["layer"] or "context", row["path"], error.kind, str(error)))
    return {"root": root_path, "support": support, "rows": rows, "leaves": leaves, "errors": errors}


def resolve(ctx: Any, root: pathlib.Path, root_path: str, raw_path: str, model: dict | None = None):
    path = ctx.normalize_path(root, raw_path)
    if path == root_path:
        return ctx.Resolution(path, "excluded", root_path, (root_path,), reason=_ROOT_REASON)
    model = model or load(ctx, root, root_path)
    if model["errors"]:
        raise ctx.ContextError(model["errors"][0].detail, model["errors"][0].kind)
    owners = [leaf for leaf in model["leaves"].values()
              if any(ctx.match_pattern(path, pattern) for pattern in leaf["scope"])]
    support = [entry for entry in model["support"]
               if any(ctx.match_pattern(path, pattern) for pattern in entry["patterns"])]
    if len(owners) + len(support) == 0:
        raise ctx.ContextError(f"unmapped path at {root_path}: {path}")
    if len(owners) + len(support) > 1:
        raise ctx.ContextError(f"sibling overlap at {root_path}: {path}")
    if support:
        return ctx.Resolution(path, "excluded", root_path, (root_path,), reason=support[0]["reason"])
    leaf = owners[0]
    return ctx.Resolution(path, "leaf", leaf["_context_path"], (root_path, leaf["_context_path"]),
                          layer=leaf["layer"])


def layer_map(ctx: Any, root: pathlib.Path, root_path: str) -> dict[str, dict[str, Any]]:
    model = load(ctx, root, root_path)
    if model["errors"]:
        raise ctx.ContextError(model["errors"][0].detail, model["errors"][0].kind)
    layers: dict[str, dict[str, Any]] = {}
    for leaf in model["leaves"].values():
        if leaf["layer"] in layers:
            raise ctx.ContextError(f"duplicate layer ID: {leaf['layer']}")
        layers[leaf["layer"]] = leaf
    return layers


def _graph_findings(ctx: Any, leaves: dict[str, dict[str, Any]]) -> list[Any]:
    findings = []
    for layer, data in leaves.items():
        path, red = data["_context_path"], tuple(data["red_lines"])
        for dependency in data["dependencies"]:
            if dependency not in leaves:
                findings.append(ctx.Finding(layer, path, "missing_dependency", dependency, red))
            elif "dependents" in leaves[dependency] and layer not in leaves[dependency]["dependents"]:
                findings.append(ctx.Finding(layer, path, "reciprocal_dependency_drift",
                                            f"{dependency}.depended_by omits {layer}", red))
        for dependent in data.get("dependents", []):
            if dependent not in leaves:
                findings.append(ctx.Finding(layer, path, "missing_dependency", dependent, red))
            elif layer not in leaves[dependent]["dependencies"]:
                findings.append(ctx.Finding(layer, path, "reciprocal_dependency_drift",
                                            f"{dependent}.depends_on omits {layer}", red))
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(layer: str) -> None:
        if state.get(layer) == 2:
            return
        if state.get(layer) == 1:
            cycle = stack[stack.index(layer):] + [layer]
            findings.append(ctx.Finding(layer, leaves[layer]["_context_path"], "dependency_cycle",
                                        " -> ".join(cycle), tuple(leaves[layer]["red_lines"])))
            return
        state[layer] = 1
        stack.append(layer)
        for dependency in leaves[layer]["dependencies"]:
            if dependency in leaves:
                visit(dependency)
        stack.pop()
        state[layer] = 2

    for layer in leaves:
        visit(layer)
    return findings


def audit(ctx: Any, root: pathlib.Path, root_path: str) -> tuple[list[Any], dict[str, int]]:
    try:
        model = load(ctx, root, root_path)
    except ctx.ContextError as error:
        return [ctx.Finding("context", root_path, error.kind, str(error))], {"leaf": 0, "excluded": 0, "total": 0}
    findings = list(model["errors"])
    leaves: dict[str, dict[str, Any]] = {}
    for leaf in model["leaves"].values():
        if leaf["layer"] in leaves:
            findings.append(ctx.Finding(leaf["layer"], leaf["_context_path"], "duplicate_layer_id",
                                        f"also declared by {leaves[leaf['layer']]['_context_path']}"))
        else:
            leaves[leaf["layer"]] = leaf
    for row in model["rows"]:
        leaf = model["leaves"].get(row["path"])
        if leaf is None:
            continue
        if leaf["layer"] != row["layer"]:
            findings.append(ctx.Finding(leaf["layer"], row["path"], "layer_table_drift",
                                        f"table says {row['layer']!r}; frontmatter says {leaf['layer']!r}"))
        if row["depends_on"] is not None and row["depends_on"] != sorted(leaf["dependencies"]):
            findings.append(ctx.Finding(leaf["layer"], row["path"], "layer_table_drift",
                                        f"table depends_on={row['depends_on']} frontmatter={sorted(leaf['dependencies'])}"))
    findings.extend(_graph_findings(ctx, leaves))
    listed = set(model["leaves"]) | {row["path"] for row in model["rows"]}
    counts = {"leaf": 0, "excluded": 0, "total": 0}
    for path in ctx.tracked_files(root):
        counts["total"] += 1
        if pathlib.PurePosixPath(path).name == LEAF_NAME and path != root_path and path not in listed:
            findings.append(ctx.Finding("context", path, "unlisted_layer_context",
                                        f"not listed in the {root_path} layer table"))
        try:
            result = resolve(ctx, root, root_path, path, model)
        except ctx.ContextError as error:
            kind = "sibling_overlap" if "sibling overlap" in str(error) else "unmapped_path"
            findings.append(ctx.Finding("context", path, kind, str(error)))
            continue
        counts[result.classification] += 1
    return findings, counts
