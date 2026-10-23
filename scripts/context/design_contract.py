#!/usr/bin/env python3
"""Validate a project design contract and scan UI sources for raw colors."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence


REQUIRED_HEADINGS = (
    "## Design system & version",
    "## Semantic token profile",
    "## Required view states",
    "## Redlines & CI gate",
)
REQUIRED_STATES = ("populated", "empty", "loading", "error")
SUPPORTED_SUFFIXES = frozenset({".swift", ".tsx", ".ts", ".jsx", ".css", ".scss"})
SKIP_DIRECTORY_NAMES = frozenset({"tokens", "generated", "tests", "__tests__"})
ALLOW_PATTERN = re.compile(r"design-contract-allow:\s*\S+")

RAW_HEX_COLOR = re.compile(
    r"(?<![A-Za-z0-9_])#(?:[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|"
    r"[0-9A-Fa-f]{4}|[0-9A-Fa-f]{3})(?![A-Za-z0-9_])"
)
RAW_RGB_COLOR = re.compile(
    r"(?:\b(?:Color|UIColor|NSColor)\s*\(\s*(?:red\s*:|\.sRGB\b)|"
    r"\brgba?\s*\(\s*)",
    re.DOTALL | re.MULTILINE,
)


@dataclass(frozen=True)
class DesignViolation:
    """A single source-level design-contract violation."""

    path: str
    line: int
    rule: str
    snippet: str


def audit_contract(contract_path: Path) -> list[str]:
    """Return all completeness errors found in a design contract."""

    errors: list[str] = []
    if not contract_path.is_file():
        return [f"design contract not found: {contract_path}"]

    try:
        content = contract_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [f"design contract is not valid UTF-8: {contract_path}"]

    if not content.strip():
        errors.append("design contract is empty")

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"(?m)^{re.escape(heading)}\s*$", content):
            errors.append(f"missing required section: {heading}")

    lowered = content.casefold()
    for state in REQUIRED_STATES:
        if state not in lowered:
            errors.append(f"missing required view state: {state}")
    for appearance in ("light", "dark"):
        if appearance not in lowered:
            errors.append(f"missing required appearance mode: {appearance}")
    return errors


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_skipped_source(root: Path, path: Path) -> bool:
    relative = Path(_relative_path(root, path))
    directory_parts = relative.parts[:-1]
    if any(
        component.casefold() in SKIP_DIRECTORY_NAMES
        or component.casefold().endswith(("tests", "tokens"))
        for component in directory_parts
    ):
        return True

    filename = relative.name
    stem = relative.stem
    lowered_filename = filename.casefold()
    lowered_stem = stem.casefold()
    suffix = path.suffix.casefold()
    if lowered_filename.endswith((f".test{suffix}", f".spec{suffix}")):
        return True
    if lowered_stem.startswith(("test_", "generated")):
        return True
    if re.search(r"(?:^|[_-])(?:test|tests|token|tokens|palette)$", stem, re.I):
        return True
    return bool(
        re.search(r"(?:[a-z0-9])(?:Test|Tests|Token|Tokens|Palette)$", stem)
    )


def _matches_exclude(path: Path, root: Path, exclude_globs: Sequence[str]) -> bool:
    relative = _relative_path(root, path)
    return any(
        path.match(pattern) or Path(relative).match(pattern)
        for pattern in exclude_globs
    )


def _violation(
    root: Path, path: Path, line_number: int, rule: str, line: str
) -> DesignViolation:
    snippet = line.strip()
    if len(snippet) > 240:
        snippet = snippet[:237] + "..."
    return DesignViolation(
        path=_relative_path(root, path),
        line=line_number,
        rule=rule,
        snippet=snippet,
    )


def _scan_file(root: Path, path: Path) -> list[DesignViolation]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [
            _violation(
                root,
                path,
                0,
                "UNREADABLE_UI_SOURCE",
                "unable to read UI source as UTF-8",
            )
        ]

    lines = content.splitlines()
    findings: list[DesignViolation] = []
    for line_number, line in enumerate(lines, start=1):
        for _match in RAW_HEX_COLOR.finditer(line):
            if ALLOW_PATTERN.search(line):
                continue
            findings.append(
                _violation(root, path, line_number, "RAW_HEX_COLOR", line)
            )
    for match in RAW_RGB_COLOR.finditer(content):
        line_number = content.count("\n", 0, match.start()) + 1
        argument_line = content.count("\n", 0, match.end()) + 1
        start_text = lines[line_number - 1] if line_number <= len(lines) else ""
        argument_text = (
            lines[argument_line - 1] if argument_line <= len(lines) else ""
        )
        if ALLOW_PATTERN.search(start_text) or ALLOW_PATTERN.search(argument_text):
            continue
        findings.append(
            _violation(root, path, line_number, "RAW_RGB_COLOR", start_text)
        )
    return findings


def scan_ui_sources(
    root: Path,
    ui_paths: Sequence[str],
    exclude_globs: Sequence[str] = (),
) -> list[DesignViolation]:
    """Scan configured UI paths for raw color literals and constructors."""

    root = root.resolve()
    findings: list[DesignViolation] = []
    for ui_path in ui_paths:
        candidate = Path(ui_path)
        candidate = candidate if candidate.is_absolute() else root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            findings.append(
                DesignViolation(
                    path=candidate.as_posix(),
                    line=0,
                    rule="UI_PATH_OUTSIDE_ROOT",
                    snippet=f"UI path must be inside root: {ui_path}",
                )
            )
            continue
        if not candidate.is_dir():
            findings.append(
                DesignViolation(
                    path=_relative_path(root, candidate),
                    line=0,
                    rule="UI_PATH_MISSING",
                    snippet=f"UI path is not a directory: {ui_path}",
                )
            )
            continue

        for path in sorted(candidate.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.casefold() not in SUPPORTED_SUFFIXES
                or _is_skipped_source(root, path)
                or _matches_exclude(path, root, exclude_globs)
            ):
                continue
            findings.extend(_scan_file(root, path))
    return findings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit docs/design-contract.md and scan UI sources."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--contract", default="docs/design-contract.md")
    parser.add_argument("--ui-path", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _report(
    contract_path: Path,
    contract_errors: Sequence[str],
    violations: Sequence[DesignViolation],
) -> dict[str, object]:
    return {
        "ok": not contract_errors and not violations,
        "contract": contract_path.as_posix(),
        "contract_errors": list(contract_errors),
        "violations": [asdict(violation) for violation in violations],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the design-contract audit CLI and return a process status."""

    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    contract_arg = Path(args.contract)
    contract_path = (
        contract_arg.resolve() if contract_arg.is_absolute() else root / contract_arg
    )
    contract_errors = audit_contract(contract_path)
    violations = (
        scan_ui_sources(root, args.ui_path, args.exclude) if args.ui_path else []
    )
    report = _report(contract_path, contract_errors, violations)

    if args.as_json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    elif report["ok"]:
        sys.stdout.write("design contract: ok\n")
    else:
        for error in contract_errors:
            sys.stderr.write(f"design contract: {error}\n")
        for violation in violations:
            sys.stderr.write(
                f"{violation.path}:{violation.line}: "
                f"{violation.rule}: {violation.snippet}\n"
            )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
