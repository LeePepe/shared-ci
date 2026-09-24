#!/usr/bin/env python3
"""Changed-layer CI selection (stdlib only, fail-closed).

Maps the files a pull request changes to caller layers with the pinned
shared-ci resolver, adds every transitive dependent (a layer B with
`depends_on: [A]` runs when A changes), and prints one JSON selection:

  {"full": bool, "any_layer": bool, "layers": [...], "reason": str,
   "triggers": [...], "changed": [...], "unmapped": [...], "all_layers": [...],
   "event": str, "base": str, "head": str}

Only pull_request / pull_request_target events are selective. Everything else
(push, schedule, workflow_dispatch, merge_group, unknown) is a full run. A PR
is also a full run when any changed path is unmapped, is a dependency manifest
or lockfile, lives under .github/, is scripts/verify or scripts/ci/**, is a
layer-map document (tech-context.md / CONTEXT.md), matches a caller
force-full pattern, or edits the shared-ci pin in AGENTS.md; and whenever git
or the resolver errors. "When in doubt, run everything." A changed file that a
layer gate names in its argv (for example a support-path test script) selects
that layer even when the file itself is a support path.

An empty diff and a support-only diff (docs, paths the layer map excludes)
select no layer: layer lanes short-circuit, contract and workflow-lint still run.

With --github-output the selection is also appended to that file as step
outputs: full, any-layer, layers (JSON list), layers-space, reason, selection.
Exit 0 whenever a selection was printed (including fail-closed full runs);
exit 2 only for usage errors.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
CONTEXT = HERE.parent / "context" / "_context.py"
SELECTIVE_EVENTS = {"pull_request", "pull_request_target"}
SHA = re.compile(r"^[0-9a-f]{40}$")

# Dependency manifests and lockfiles, any directory.
MANIFESTS = (
    "**/Package.swift", "**/Package.resolved", "**/Podfile", "**/Podfile.lock", "**/Cartfile",
    "**/Cartfile.resolved", "**/package.json", "**/package-lock.json", "**/npm-shrinkwrap.json",
    "**/pnpm-lock.yaml", "**/pnpm-workspace.yaml", "**/yarn.lock", "**/bun.lockb", "**/bun.lock",
    "**/requirements*.txt", "**/constraints*.txt", "**/pyproject.toml", "**/poetry.lock",
    "**/uv.lock", "**/Pipfile", "**/Pipfile.lock", "**/setup.py", "**/setup.cfg",
    "**/Cargo.toml", "**/Cargo.lock", "**/go.mod", "**/go.sum", "**/Gemfile", "**/Gemfile.lock",
    "**/build.gradle", "**/build.gradle.kts", "**/settings.gradle", "**/settings.gradle.kts",
    "**/gradle.lockfile", "**/gradle/libs.versions.toml", "**/pom.xml", "**/Directory.Packages.props",
    "**/packages.lock.json", "**/*.csproj", "**/composer.json", "**/composer.lock",
    "**/mix.exs", "**/mix.lock", "**/flake.nix", "**/flake.lock", ".tool-versions", ".nvmrc",
    ".python-version", "**/.xcode-version", "**/rust-toolchain", "**/rust-toolchain.toml",
)
CI_WIRING = (".github/**", "scripts/verify", "scripts/ci/**")
LAYER_MAP = ("**/tech-context.md", "**/CONTEXT.md")
PIN_FILE = "AGENTS.md"
PIN_LINE = re.compile(r"shared-ci(?:@|/blob/|/\.github/)", re.IGNORECASE)


def _load_context() -> Any:
    spec = importlib.util.spec_from_file_location("shared_ci_select_context", CONTEXT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CONTEXT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: pathlib.Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False, timeout=120)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"git {args[0]} failed: {detail[-1] if detail else result.returncode}")
    return result.stdout


def changed_files(root: pathlib.Path, base: str, head: str) -> list[str]:
    """Paths changed between merge-base(base, head) and head; renames count both sides."""
    merge_base = _git(root, "merge-base", base, head).decode().strip()
    if not SHA.match(merge_base):
        raise RuntimeError(f"merge-base returned {merge_base!r}")
    raw = _git(root, "diff", "--name-only", "--no-renames", "-z", merge_base, head, "--")
    return sorted({item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item})


def pin_changed(root: pathlib.Path, base: str, head: str) -> bool:
    """True when the AGENTS.md diff adds or removes a shared-ci pin line."""
    merge_base = _git(root, "merge-base", base, head).decode().strip()
    diff = _git(root, "diff", "-U0", "--no-renames", merge_base, head, "--", PIN_FILE).decode("utf-8", "replace")
    return any(line[:1] in "+-" and not line.startswith(("+++", "---")) and PIN_LINE.search(line)
               for line in diff.splitlines())


def dependents_closure(layers: dict[str, dict[str, Any]], seeds: set[str]) -> set[str]:
    """Seeds plus every layer that transitively depends on one of them."""
    reverse: dict[str, set[str]] = {name: set() for name in layers}
    for name, data in layers.items():
        for dependency in data.get("dependencies", []) or []:
            reverse.setdefault(dependency, set()).add(name)
        for dependent in data.get("dependents", []) or []:
            reverse.setdefault(name, set()).add(dependent)
    selected, pending = set(), list(seeds)
    while pending:
        layer = pending.pop()
        if layer in selected:
            continue
        selected.add(layer)
        pending.extend(sorted(reverse.get(layer, ())))
    return selected


def gate_files(layers: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """Repository path named literally in a layer gate's argv -> the layers whose gate runs it."""
    owners: dict[str, set[str]] = {}
    for name, data in layers.items():
        for gate in data.get("gates", []) or []:
            for token in gate.get("command", []) or []:
                if not isinstance(token, str) or "{" in token or token.startswith("-"):
                    continue
                path = token[2:] if token.startswith("./") else token
                if "/" in path and not path.startswith("/"):
                    owners.setdefault(path, set()).add(name)
    return owners


def _force_patterns(extra: list[str]) -> list[tuple[str, str]]:
    patterns = [(p, "dependency manifest or lockfile") for p in MANIFESTS]
    patterns += [(p, "CI wiring") for p in CI_WIRING]
    patterns += [(p, "layer map") for p in LAYER_MAP]
    patterns += [(p, "caller force-full pattern") for p in extra]
    return patterns


def _parse_extra(raw: str) -> list[str]:
    return [token for token in re.split(r"[\s,]+", raw or "") if token and not token.startswith("#")]


def select(root: pathlib.Path, *, event: str, base: str, head: str, extra_patterns: list[str],
           ctx: Any | None = None, files: list[str] | None = None) -> dict[str, Any]:
    """Compute the selection. Never raises for repository/resolver problems: those select full."""
    triggers: list[str] = []
    result: dict[str, Any] = {"mode": "changed-only", "event": event, "base": base, "head": head, "changed": [],
                              "unmapped": [], "all_layers": [], "triggers": triggers}
    layers: dict[str, dict[str, Any]] = {}
    try:
        ctx = ctx or _load_context()
        layers = ctx.layer_map(root)
        result["all_layers"] = sorted(layers)
    except Exception as error:  # noqa: BLE001 - fail closed on any resolver problem
        triggers.append(f"resolver error: {error}")

    if event not in SELECTIVE_EVENTS:
        triggers.append(f"event {event or 'unknown'} always runs in full")
    else:
        try:
            if not SHA.match(base or "") or not SHA.match(head or ""):
                raise RuntimeError("pull request base/head SHA unavailable")
            if files is None:
                files = changed_files(root, base, head)
            result["changed"] = list(files)
            if PIN_FILE in files and pin_changed(root, base, head):
                triggers.append(f"{PIN_FILE}: shared-ci pin changed")
        except Exception as error:  # noqa: BLE001
            triggers.append(f"diff error: {error}")

    touched: set[str] = set()
    if ctx is not None and layers:
        patterns = _force_patterns(extra_patterns)
        gated = gate_files(layers)
        for path in result["changed"]:
            touched |= gated.get(path, set())  # a gate script changed: its layer re-runs
            hit = next((reason for pattern, reason in patterns if ctx.match_pattern(path, pattern)), None)
            if hit:
                triggers.append(f"{path}: {hit}")
            try:
                resolution = ctx.resolve(root, path)
            except Exception as error:  # noqa: BLE001
                result["unmapped"].append(path)
                triggers.append(f"{path}: unmapped ({error})")
                continue
            if resolution.classification == "leaf":
                touched.add(resolution.layer)

    full = bool(triggers)
    selected = sorted(layers) if full else sorted(dependents_closure(layers, touched))
    if full:
        reason = "full run: " + triggers[0] + (f" (+{len(triggers) - 1} more)" if len(triggers) > 1 else "")
    elif not result["changed"]:
        reason = "empty diff: no layer changed; only contract and workflow-lint lanes run"
    elif not selected:
        reason = "only support paths changed; no layer selected"
    else:
        added = sorted(set(selected) - touched)
        reason = "changed layers: " + ", ".join(sorted(touched)) + (
            f"; dependents: {', '.join(added)}" if added else "")
    result.update({"full": full, "any_layer": full or bool(selected), "layers": selected,
                   "reason": reason})
    return result


OUTPUT_LIST_CAP = 200


def compact_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Selection record for job outputs: long path lists are capped (counts stay exact)."""
    record = dict(selection)
    for key in ("changed", "unmapped", "triggers"):
        record[key + "_count"] = len(selection[key])
        record[key] = selection[key][:OUTPUT_LIST_CAP]
    return record


def disabled(*, event: str, base: str, head: str) -> dict[str, Any]:
    """changed-only is off: a full run, the diff is not read (v0.1.0 behaviour)."""
    return {"mode": "disabled", "event": event, "base": base, "head": head, "changed": [],
            "unmapped": [], "all_layers": [], "triggers": ["changed-only is disabled"],
            "full": True, "any_layer": True, "layers": [],
            "reason": "full run: changed-only is disabled"}


def write_outputs(path: str, selection: dict[str, Any]) -> None:
    compact = json.dumps(compact_selection(selection), ensure_ascii=False, separators=(",", ":"))
    lines = {
        "full": "true" if selection["full"] else "false",
        "any-layer": "true" if selection["any_layer"] else "false",
        "layers": json.dumps(selection["layers"], separators=(",", ":")),
        "layers-space": " ".join(selection["layers"]),
        "reason": " ".join(selection["reason"].split()),
        "selection": compact,
    }
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in lines.items():
            handle.write(f"{key}={value}\n")


def write_summary(path: str, selection: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"## layer selection: {'full' if selection['full'] else 'changed-only'}\n\n")
        handle.write(f"- reason: {selection['reason']}\n")
        handle.write(f"- layers: {', '.join(selection['layers']) or '(none)'}\n")
        handle.write(f"- changed files: {len(selection['changed'])}\n")
        for trigger in selection["triggers"][:50]:
            handle.write(f"- trigger: {trigger}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shared-ci-select")
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--force-full-paths", default="", help="extra glob patterns (whitespace/comma separated)")
    parser.add_argument("--mode", choices=("changed-only", "disabled"), default="changed-only",
                        help="disabled = v0.1.0 behaviour: a full run without reading the diff")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--step-summary", default="")
    args = parser.parse_args(argv)
    root = pathlib.Path.cwd()
    try:
        root = pathlib.Path(_git(root, "rev-parse", "--show-toplevel").decode().strip())
    except Exception:  # noqa: BLE001 - selection below records the failure and runs full
        pass
    if args.mode == "disabled":
        selection = disabled(event=args.event, base=args.base, head=args.head)
    else:
        selection = select(root, event=args.event, base=args.base, head=args.head,
                           extra_patterns=_parse_extra(args.force_full_paths))
    print(json.dumps(selection, ensure_ascii=False, indent=2))
    if args.github_output:
        write_outputs(args.github_output, selection)
    if args.step_summary:
        write_summary(args.step_summary, selection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
