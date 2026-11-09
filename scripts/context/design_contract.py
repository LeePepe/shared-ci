#!/usr/bin/env python3
"""Validate a project design contract and scan UI sources for raw colors."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import struct
import sys
import zlib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


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
RAW_HSL_COLOR = re.compile(r"\bhsla?\s*\(", re.IGNORECASE)
FRAME_BEFORE_PADDING = re.compile(
    r"\.frame\s*\(\s*width\s*:\s*[0-9]+(?:\.[0-9]+)?[^)]*\)"
    r"\s*\.padding\s*\(",
    re.DOTALL,
)
MICRO_FONT_SIZE = re.compile(
    r"\.system\s*\(\s*size\s*:\s*"
)
SCALE_FACTOR = re.compile(
    r"\.minimumScaleFactor\s*\(\s*"
)

AUDIT_CODE_RULES = (
    ("HIG-LG-CONTENT", ("desktop", "mobile"), re.compile(r"(List|Form|Table|ForEach)\s*\{[\s\S]{0,240}?\.glassEffect\(")),
    ("HIG-IOS-SCREEN-BOUNDS", ("desktop", "mobile"), re.compile(r"\bUIScreen\.main\b|\buserInterfaceIdiom\s*==\s*\.phone\b|\binterfaceOrientation\.(?:isLandscape|isPortrait)\b")),
    ("HIG-COLOR-RAW-HEX", ("desktop", "mobile"), re.compile(r"Color\(\s*red\s*:[^)]+green\s*:[^)]+blue\s*:")),
    ("HIG-COMPAT-FLAG", ("desktop", "mobile"), re.compile(r"UIDesignRequiresCompatibility")),
    ("SLOP-PURPLE-GRADIENT", ("desktop", "mobile"), re.compile(r"LinearGradient\([^)]*colors\s*:\s*\[\s*(?:\.purple\s*,\s*\.blue|\.blue\s*,\s*\.purple|\.indigo\s*,\s*\.purple)")),
    ("SLOP-LEFT-ACCENT-STRIPE", ("desktop", "mobile"), re.compile(r"Rectangle\(\)\s*\.fill\([^)]+\)\s*\.frame\(\s*width\s*:\s*[3-6]\b")),
    ("HIG-MACOS-HOVER-EFFECT", ("desktop",), re.compile(r"\.hoverEffect\s*\(")),
    ("SLOP-MUDDY-BLACK-GRADIENT", ("desktop", "mobile"), re.compile(r"LinearGradient\([^)]*colors\s*:\s*\[[^\]]*\.black\b")),
    ("DC-001", ("desktop", "mobile"), re.compile(r"struct\s+\w*CardStack\w*\b[\s\S]{0,600}?VStack[^{]*\{\s*ForEach")),
    ("DC-002", ("desktop", "mobile"), re.compile(r"SectorMark[\s\S]{0,800}?ProgressView\(\s*value\s*:")),
    ("DC-003", ("mobile",), re.compile(r"var\s+\w+\s*:\s*some\s+View\s*\{\s*HStack(?:\s*\([^)]*\))?\s*\{\s*ForEach\b")),
    ("DC-004", ("desktop", "mobile"), re.compile(r"Lazy(?:V|H)Stack[^{]*\{[\s\S]{0,220}?ForEach\([^)]*\)\s*\{\s*\w+\s+in\s+if\b")),
    ("DC-005", ("desktop", "mobile"), re.compile(r"var\s+\w*[Hh]eader\w*\s*:\s*some\s+View\s*\{[\s\S]{0,450}?HStack[\s\S]{0,350}?maxWidth\s*:\s*\.infinity[\s\S]{0,600}?var\s+\w*[Rr]ow\w*\s*:\s*some\s+View\s*\{(?![\s\S]{0,450}?maxWidth\s*:\s*\.infinity)[\s\S]{0,450}?HStack[\s\S]{0,350}?\.frame\(\s*width\s*:")),
    ("HIG-CARD-STACK-FLATTENED", ("desktop", "mobile"), re.compile(r"struct\s+\w*CardStack\w*\b[\s\S]{0,600}?VStack[^{]*\{\s*ForEach")),
    ("SLOP-DUPLICATE-DATA-REPRESENTATION", ("desktop", "mobile"), re.compile(r"SectorMark[\s\S]{0,800}?ProgressView\(\s*value\s*:")),
    ("HIG-LAYOUT-OVERFLOW", ("mobile",), re.compile(r"var\s+\w+\s*:\s*some\s+View\s*\{\s*HStack(?:\s*\([^)]*\))?\s*\{\s*ForEach\b")),
    ("HIG-LAZY-LEAF-CONDITIONAL", ("desktop", "mobile"), re.compile(r"Lazy(?:V|H)Stack[^{]*\{[\s\S]{0,220}?ForEach\([^)]*\)\s*\{\s*\w+\s+in\s+if\b")),
    ("HIG-TABLE-COLUMN-MISMATCH", ("desktop", "mobile"), re.compile(r"var\s+\w*[Hh]eader\w*\s*:\s*some\s+View\s*\{[\s\S]{0,450}?HStack[\s\S]{0,350}?maxWidth\s*:\s*\.infinity[\s\S]{0,600}?var\s+\w*[Rr]ow\w*\s*:\s*some\s+View\s*\{(?![\s\S]{0,450}?maxWidth\s*:\s*\.infinity)[\s\S]{0,450}?HStack[\s\S]{0,350}?\.frame\(\s*width\s*:")),
    ("HIG-APPKIT-LEGACY-MOUSELOOP", ("desktop",), re.compile(r"override\s+func\s+mouseDown\b[\s\S]{0,300}?nextEvent\(\s*matching\s*:")),
    ("HIG-DRAG-WILL-BEGIN-UI", ("desktop", "mobile"), re.compile(r"dragInteraction\([^)]*sessionWillBegin[\s\S]{0,240}?(?:present\(|UIAlertController|withAnimation)")),
)
LOCALIZATION_CALL = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*L10n\.(?:tr|format)|NSLocalizedString|LocalizedStringKey|String\s*\(\s*localized|localized)\s*(?:\(|:)\s*\"([a-z0-9_]+(?:\.[a-z0-9_]+)+(?:\s*%[@lld]+)?)\"", re.I)
FORMAT_SPECIFIER = re.compile(r"%(?:@|lld|ld|d|f|s)")


@dataclass(frozen=True)
class DesignViolation:
    """A single source-level design-contract violation."""

    path: str
    line: int
    rule: str
    snippet: str


def read_png_dimensions(path: Path) -> Optional[tuple[int, int]]:
    """Return dimensions when the file has a structurally valid PNG."""

    try:
        data = path.read_bytes()
    except OSError:
        return None
    return _png_dimensions_from_bytes(data)


def audit_screenshot_matrix(
    root: Path,
    screenshot_dir: Path,
    *,
    require_state_matrix: bool = False,
) -> tuple[list[Path], list[DesignViolation]]:
    """Validate screenshot paths, PNG headers, and optional state coverage."""

    root = root.resolve()
    if not screenshot_dir.is_absolute():
        screenshot_dir = root / screenshot_dir
    resolved_dir = screenshot_dir.resolve()
    try:
        resolved_dir.relative_to(root)
    except ValueError:
        return [], [
            DesignViolation(
                path=resolved_dir.as_posix(),
                line=0,
                rule="SCREENSHOT_PATH_OUTSIDE_ROOT",
                snippet=f"screenshot directory must be inside root: {screenshot_dir}",
            )
        ]

    if not resolved_dir.is_dir():
        return [], [
            DesignViolation(
                path=_relative_path(root, resolved_dir),
                line=0,
                rule="SCREENSHOT_PATH_MISSING",
                snippet=f"screenshot directory is not a directory: {screenshot_dir}",
            )
        ]

    valid_paths: list[Path] = []
    violations: list[DesignViolation] = []
    for path in sorted(resolved_dir.rglob("*")):
        if not path.is_file() or path.suffix.casefold() != ".png":
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(root)
        except ValueError:
            violations.append(
                DesignViolation(
                    path=_relative_path(root, path),
                    line=0,
                    rule="SCREENSHOT_PATH_OUTSIDE_ROOT",
                    snippet=f"screenshot resolves outside root: {resolved_path}",
                )
            )
            continue
        if read_png_dimensions(resolved_path) is None:
            violations.append(
                DesignViolation(
                    path=_relative_path(root, path),
                    line=0,
                    rule="INVALID_SCREENSHOT_PNG",
                    snippet="PNG signature or IHDR dimensions are invalid",
                )
            )
            continue
        valid_paths.append(resolved_path)

    if require_state_matrix:
        tokens_by_name = {
            path: set(re.findall(r"[a-z0-9]+", path.stem.casefold()))
            for path in valid_paths
        }
        for state in REQUIRED_STATES:
            for appearance in ("light", "dark"):
                if not any(
                    state in tokens and appearance in tokens
                    for tokens in tokens_by_name.values()
                ):
                    violations.append(
                        DesignViolation(
                            path=_relative_path(root, resolved_dir),
                            line=0,
                            rule="MISSING_STATE_SCREENSHOT",
                            snippet=(
                                f"missing screenshot for state={state} "
                                f"appearance={appearance}"
                            ),
                        )
                    )
    return valid_paths, violations


_JEV_CHECKS = (
    (
        "has_text_truncation",
        "truncation_box",
        "UI_TEXT_TRUNCATION_BOX",
        "truncated or clipped UI text",
    ),
    (
        "has_control_collision",
        "collision_box",
        "UI_CONTROL_COLLISION_BOX",
        "overlapping or colliding UI controls",
    ),
    (
        "has_unreadable_contrast",
        "contrast_box",
        "UI_UNREADABLE_CONTRAST_BOX",
        "unreadable low-contrast text or icon",
    ),
)


def _jev_score(answer: object) -> Optional[float]:
    if isinstance(answer, dict):
        answer = answer.get("value")
    try:
        score = float(answer)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def _jev_box(answer: object) -> object:
    if isinstance(answer, dict):
        if "boxes" in answer:
            return answer["boxes"]
        if "box" in answer:
            return answer["box"]
    return answer


def _jev_request(
    image_path: Path,
    jev_url: str,
    *,
    source_key: str = "",
) -> dict[str, object]:
    image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    questions: dict[str, dict[str, str]] = {}
    statements = {
        "has_text_truncation": (
            "Visible UI text in this screenshot is unintentionally truncated "
            "with an ellipsis (...) or clipped by its container boundary."
        ),
        "has_control_collision": (
            "Two or more UI controls, badges, icons, or text labels overlap "
            "or collide with each other."
        ),
        "has_unreadable_contrast": (
            "Foreground text or iconography is nearly invisible against its "
            "background surface due to wrong light/dark appearance token binding."
        ),
    }
    for noul_key, box_key, _rule, label in _JEV_CHECKS:
        questions[noul_key] = {"type": "noul", "statement": statements[noul_key]}
        questions[box_key] = {"type": "box", "label": label}

    payload = {
        "model": "microsoft-decision-1",
        "state": {
            "image": f"data:image/png;base64,{image}",
            "context": f"UI screenshot verification for {image_path.name!r}.",
        },
        "questions": questions,
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if source_key:
        headers["Authorization"] = f"Bearer {source_key}"
    request = urllib.request.Request(
        jev_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError(f"Jev returned HTTP {response.status}")
        result = json.load(response)
    if not isinstance(result, dict) or not isinstance(result.get("answers"), dict):
        raise ValueError("Jev response is missing an answers object")
    return result


def scan_screenshots_with_jev(
    root: Path,
    screenshot_paths: Sequence[Path],
    jev_url: str,
    *,
    jev_threshold: float = 0.65,
    jev_mode: str = "gate",
) -> tuple[list[DesignViolation], list[DesignViolation]]:
    """Scan valid screenshots and return gate and advisory violations."""

    if _jev_score(jev_threshold) is None:
        raise ValueError("jev_threshold must be finite and between 0 and 1")
    root = root.resolve()
    violations: list[DesignViolation] = []
    advisory_violations: list[DesignViolation] = []
    source_key = os.environ.get("FALCON_SOURCE_KEY", "")
    for image_path in screenshot_paths:
        relative = _relative_path(root, image_path)
        try:
            response = _jev_request(image_path, jev_url, source_key=source_key)
            answers = response["answers"]
            if not isinstance(answers, dict):
                raise ValueError("Jev response answers is not an object")
            for noul_key, box_key, rule, label in _JEV_CHECKS:
                score = _jev_score(answers.get(noul_key))
                if score is None:
                    raise ValueError(
                        f"Jev response has invalid score for {noul_key}"
                    )
                if score < jev_threshold:
                    continue
                box = _jev_box(answers.get(box_key))
                finding = DesignViolation(
                    path=relative,
                    line=0,
                    rule=rule,
                    snippet=f"noul={score:.2f} box={box!r} ({label})",
                )
                (violations if jev_mode == "gate" else advisory_violations).append(
                    finding
                )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            UnicodeError,
            urllib.error.URLError,
        ) as error:
            finding = DesignViolation(
                path=relative,
                line=0,
                rule="JEV_VISION_UNAVAILABLE",
                snippet=str(error),
            )
            (violations if jev_mode == "gate" else advisory_violations).append(
                finding
            )
    return violations, advisory_violations


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

    if re.search(r"(?m)^schema:\s*agent-design-doc/v1\s*$", content):
        for section in range(1, 8):
            if not re.search(rf"(?m)^##\s+{section}\.\s+\S+", content):
                errors.append(f"missing required section: ## {section}.")
    else:
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


def _is_skipped_directory(component: str) -> bool:
    if component.casefold() in SKIP_DIRECTORY_NAMES:
        return True
    if re.search(r"[_-](?:tests|tokens)$", component, re.I):
        return True
    return bool(re.search(r"[a-z0-9](?:Tests|Tokens)$", component))


def _is_skipped_source(root: Path, path: Path) -> bool:
    relative = Path(_relative_path(root, path))
    directory_parts = relative.parts[:-1]
    if any(_is_skipped_directory(component) for component in directory_parts):
        return True

    filename = relative.name
    stem = relative.stem
    lowered_filename = filename.casefold()
    lowered_stem = stem.casefold()
    suffix = path.suffix.casefold()
    if lowered_filename.endswith((f".test{suffix}", f".spec{suffix}")):
        return True
    if lowered_stem.startswith("test_"):
        return True
    if re.search(r"(?:^|[_-])(?:test|tests|token|tokens|palette|generated)$", stem, re.I):
        return True
    if re.search(r"^Generated(?:Colors|Styles|Tokens|Palette)$", stem):
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
    layout = _swiftui_violations(root, path, content, lines)
    layout_at = 0
    for line_number, line in enumerate(lines, start=1):
        for _match in RAW_HEX_COLOR.finditer(line):
            if ALLOW_PATTERN.search(line):
                continue
            findings.append(
                _violation(root, path, line_number, "RAW_HEX_COLOR", line)
            )
        if not ALLOW_PATTERN.search(line):
            for match in RAW_HSL_COLOR.finditer(line):
                findings.append(
                    _violation(root, path, line_number, "raw-hsl-color", line)
                )
        while layout_at < len(layout) and layout[layout_at].line == line_number:
            findings.append(layout[layout_at])
            layout_at += 1
    if layout_at < len(layout):
        findings.extend(layout[layout_at:])
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


def _line_at(lines: Sequence[str], content: str, offset: int) -> tuple[int, str]:
    line_number = content.count("\n", 0, offset) + 1
    if 1 <= line_number <= len(lines):
        return line_number, lines[line_number - 1]
    return line_number, ""


def _range_allowed(lines: Sequence[str], content: str, start: int, end: int) -> bool:
    start_line = content.count("\n", 0, start) + 1
    end_line = content.count("\n", 0, max(end - 1, start)) + 1
    return any(
        ALLOW_PATTERN.search(lines[line_number - 1])
        for line_number in range(start_line, end_line + 1)
        if 1 <= line_number <= len(lines)
    )


def _swiftui_violations(
    root: Path, path: Path, content: str, lines: Sequence[str]
) -> list[DesignViolation]:
    """Find SwiftUI layout and font violations across the whole source."""

    found: list[tuple[int, DesignViolation]] = []
    for match in FRAME_BEFORE_PADDING.finditer(content):
        if _range_allowed(lines, content, match.start(), match.end()):
            continue
        line_number, text = _line_at(lines, content, match.start())
        found.append(
            (
                match.start(),
                _violation(root, path, line_number, "frame-before-padding", text),
            )
        )
    found.extend(
        _numeric_call_violations(
            root,
            path,
            content,
            lines,
            MICRO_FONT_SIZE,
            "micro-font-size",
            11.0,
        )
    )
    found.extend(
        _numeric_call_violations(
            root,
            path,
            content,
            lines,
            SCALE_FACTOR,
            "excessive-scale-factor",
            0.85,
        )
    )
    found.sort(key=lambda item: item[0])
    return [item[1] for item in found]


def _numeric_call_violations(
    root: Path,
    path: Path,
    content: str,
    lines: Sequence[str],
    pattern: re.Pattern[str],
    rule: str,
    threshold: float,
) -> list[tuple[int, DesignViolation]]:
    findings: list[tuple[int, DesignViolation]] = []
    for match in pattern.finditer(content):
        number = re.match(
            r"\s*([0-9]+(?:\.[0-9]*)?|\.[0-9]+)",
            content[match.end() :],
        )
        if number is None:
            continue
        value = float(number.group(1))
        if value >= threshold:
            continue
        end = match.end() + number.end()
        if _range_allowed(lines, content, match.start(), end):
            continue
        line_number, text = _line_at(lines, content, match.start())
        findings.append(
            (
                match.start(),
                _violation(root, path, line_number, rule, text),
            )
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


def _audit_paths(root: Path, paths: Sequence[str], suffixes: Optional[set[str]] = None) -> list[Path]:
    candidates = [root] if not paths else [Path(item) if Path(item).is_absolute() else root / item for item in paths]
    result: list[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file():
            if suffixes is None or candidate.suffix.casefold() in suffixes:
                result.append(candidate)
        elif candidate.is_dir():
            for path in sorted(candidate.rglob("*")):
                if path.is_file() and (suffixes is None or path.suffix.casefold() in suffixes):
                    result.append(path.resolve())
    return result


def _load_code_rules(
    cases_file: Optional[Path],
) -> tuple[list[tuple[str, tuple[str, ...], re.Pattern[str]]], list[DesignViolation]]:
    rules = list(AUDIT_CODE_RULES)
    if cases_file is None:
        return rules, []
    try:
        payload = json.loads(cases_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return rules, [
            DesignViolation(
                cases_file.as_posix(),
                0,
                "INVALID_CASES_FILE",
                f"unable to load cases file: {error}",
            )
        ]
    if isinstance(payload, dict):
        entries = payload.get("rules", payload.get("cases"))
    else:
        entries = payload
    if not isinstance(entries, list) or not entries:
        return rules, [
            DesignViolation(
                cases_file.as_posix(),
                0,
                "INVALID_CASES_FILE",
                "cases file must contain a non-empty list of rules",
            )
        ]
    errors: list[DesignViolation] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(key), str) and entry.get(key).strip()
            for key in ("id", "regex")
        ):
            errors.append(
                DesignViolation(
                    cases_file.as_posix(),
                    0,
                    "INVALID_CASES_FILE",
                    f"entry {index} must define non-empty string 'id' and 'regex'",
                )
            )
            continue
        platforms = entry.get("platforms", ["desktop", "mobile", "web"])
        if isinstance(platforms, str):
            platforms = [platforms]
        if (
            not isinstance(platforms, list)
            or not platforms
            or not all(
                isinstance(item, str) and item in ("desktop", "mobile", "web", "all")
                for item in platforms
            )
        ):
            errors.append(
                DesignViolation(
                    cases_file.as_posix(),
                    0,
                    "INVALID_CASES_FILE",
                    f"entry {entry['id']} has invalid platforms",
                )
            )
            continue
        try:
            rules.append((entry["id"], tuple(platforms), re.compile(entry["regex"])))
        except re.error as error:
            errors.append(
                DesignViolation(
                    cases_file.as_posix(),
                    0,
                    "INVALID_CASES_FILE",
                    f"entry {entry['id']} has invalid regex: {error}",
                )
            )
    return rules, errors


def audit_code(paths: Sequence[Path], platform: str, cases_file: Optional[Path] = None) -> list[DesignViolation]:
    rules, findings = _load_code_rules(cases_file)
    active = {"desktop", "mobile", "web"} if platform == "all" else {platform}
    for path in paths:
        if _is_skipped_source(Path("."), path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            findings.append(DesignViolation(path.as_posix(), 0, "UNREADABLE_UI_SOURCE", "unable to read source as UTF-8"))
            continue
        lines = content.splitlines()
        for rule, platforms, pattern in rules:
            if "all" not in platforms and not active.intersection(platforms):
                continue
            for match in pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                end_line = content.count("\n", 0, max(match.start(), match.end() - 1)) + 1
                spanned = "\n".join(lines[line_number - 1 : end_line])
                line = lines[line_number - 1] if line_number <= len(lines) else ""
                if (
                    re.search(rf"design-contract-allow:\s*{re.escape(rule)}\b", spanned, re.I)
                    or ALLOW_PATTERN.search(spanned)
                ):
                    continue
                findings.append(DesignViolation(path.as_posix(), line_number, rule, line.strip()[:240]))
        for pattern, rule in ((RAW_HEX_COLOR, "RAW_HEX_COLOR"), (RAW_RGB_COLOR, "RAW_RGB_COLOR"), (RAW_HSL_COLOR, "raw-hsl-color")):
            if platform != "web" and rule != "RAW_HEX_COLOR":
                continue
            for match in pattern.finditer(content):
                line_number = content.count("\n", 0, match.start()) + 1
                line = lines[line_number - 1] if line_number <= len(lines) else ""
                if ALLOW_PATTERN.search(line):
                    continue
                findings.append(DesignViolation(path.as_posix(), line_number, rule, line.strip()[:240]))
        findings.extend(_swiftui_violations(Path("."), path, content, lines))
    return findings


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, str)]
    return []


def audit_l10n(root: Path, paths: Sequence[str], locales: Sequence[str]) -> list[DesignViolation]:
    findings: list[DesignViolation] = []
    xcstrings = _audit_paths(root, paths, {".xcstrings"})
    source_paths = [path for path in _audit_paths(root, paths, SUPPORTED_SUFFIXES | {".m", ".mm", ".plist"}) if not _is_skipped_source(root, path)]
    registered: set[str] = set()
    for path in xcstrings:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            findings.append(DesignViolation(path.as_posix(), 0, "L10N-INVALID-XCSTRINGS", "invalid localization catalog"))
            continue
        for key, entry in document.get("strings", {}).items():
            registered.add(key)
            localizations = entry.get("localizations", {}) if isinstance(entry, dict) else {}
            missing = [locale for locale in locales if locale not in localizations]
            if missing:
                findings.append(DesignViolation(path.as_posix(), 0, "L10N-MISSING-LOCALE", f"{key}: missing {', '.join(missing)}"))
            source = localizations.get("en", {}).get("stringUnit", {}).get("value", key) if isinstance(localizations, dict) else key
            for locale, localized in localizations.items():
                value = localized.get("stringUnit", {}).get("value", "") if isinstance(localized, dict) else ""
                if "." in key and value == key:
                    findings.append(DesignViolation(path.as_posix(), 0, "L10N-RAW-KEY-LEAK", f"{key}: {locale}"))
                if FORMAT_SPECIFIER.findall(str(source)) != FORMAT_SPECIFIER.findall(str(value)):
                    findings.append(DesignViolation(path.as_posix(), 0, "L10N-FORMAT-MISMATCH", f"{key}: {locale}"))
    for path in source_paths:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix.casefold() == ".plist":
            localization_section = content.split("CFBundleLocalizations", 1)[1] if "CFBundleLocalizations" in content else ""
            if not localization_section or any(locale not in localization_section for locale in locales):
                findings.append(DesignViolation(path.as_posix(), 0, "L10N-INFOPLIST-LOCALES", f"expected {', '.join(locales)}"))
            continue
        for match in LOCALIZATION_CALL.finditer(content):
            key = match.group(1)
            if key and key not in registered:
                findings.append(DesignViolation(path.as_posix(), content.count("\n", 0, match.start()) + 1, "L10N-UNREGISTERED-KEY", key))
        for match in re.finditer(r"\b(?:Text|Label)\s*\(\s*[\"']([a-z0-9_]+(?:\.[a-z0-9_]+)+)[\"']", content, re.I):
            findings.append(DesignViolation(path.as_posix(), content.count("\n", 0, match.start()) + 1, "L10N-RAW-KEY-LEAK", match.group(1)))
    return findings


def _decode_png(data: bytes) -> tuple[int, int, bytes, int]:
    if len(data) < 29 or data[:8] != _PNG_SIGNATURE:
        raise ValueError("not a PNG")
    ihdr = _parse_ihdr(data[16:29])
    if ihdr is None:
        raise ValueError("invalid PNG IHDR")
    width, height, bit_depth, color_type, interlace = ihdr
    if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
        raise ValueError("unsupported PNG format")
    channels = 3 if color_type == 2 else 4
    expected = _png_image_byte_count(width, height, channels, bit_depth, interlace)
    if expected is None:
        raise ValueError("PNG image exceeds byte limit")
    raw = bytearray()
    offset = 8
    while offset < len(data):
        chunk = _png_chunk(data, offset)
        if chunk is None:
            raise ValueError("invalid PNG chunk")
        kind, chunk_data, offset = chunk
        if kind == b"IDAT":
            if len(raw) + len(chunk_data) > _MAX_PNG_IMAGE_BYTES:
                raise ValueError("PNG IDAT exceeds limit")
            raw.extend(chunk_data)
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(bytes(raw), expected + 1)
    if (
        len(decoded) != expected
        or decompressor.unconsumed_tail
        or decompressor.unused_data
        or not decompressor.eof
    ):
        raise ValueError("invalid PNG scanline payload")
    stride = width * channels
    rows: list[bytes] = []; cursor = 0; prior = bytearray(stride)
    for _ in range(height):
        filter_type = decoded[cursor]; cursor += 1; row = bytearray(decoded[cursor:cursor + stride]); cursor += stride
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0; up = prior[index]; upper = prior[index - channels] if index >= channels else 0
            if filter_type == 1: row[index] = (row[index] + left) & 255
            elif filter_type == 2: row[index] = (row[index] + up) & 255
            elif filter_type == 3: row[index] = (row[index] + (left + up) // 2) & 255
            elif filter_type == 4:
                estimate = left + up - upper; pa, pb, pc = abs(estimate-left), abs(estimate-up), abs(estimate-upper)
                row[index] = (row[index] + (left if pa <= pb and pa <= pc else up if pb <= pc else upper)) & 255
        rows.append(bytes(row)); prior = row
    return width, height, b"".join(rows), channels


def check_edge_clipping(path: Path, expected_width: Optional[str], scale: float, check_polarity: bool = False) -> list[str]:
    errors: list[str] = []
    images = [path] if path.is_file() else sorted(path.glob("*.png")) if path.is_dir() else []
    if not images: return [f"edge clipping path not found: {path}"]
    for image in images:
        try:
            width, height, pixels, channels = _decode_png(image.read_bytes())
            if expected_width is not None and width != round(float(expected_width) * scale):
                errors.append(f"{image}: EDGE_PIXEL_WIDTH expected {round(float(expected_width) * scale)}, got {width}")
            start, end = int(height * .14), max(int(height * .14) + 1, int(height * .86))
            def rgb(y: int, x: int) -> tuple[int, int, int]:
                base = (y * width + x) * channels; return tuple(pixels[base:base + 3])
            corners = [rgb(start, 0), rgb(start, width - 1), rgb(end - 1, 0), rgb(end - 1, width - 1)]
            background = tuple(sorted(channel[index] for channel in corners)[2] for index in range(3))
            left = sum(any(max(abs(rgb(y, x)[i] - background[i]) for i in range(3)) >= 28 for x in range(min(2, width))) for y in range(start, end)) / max(1, end - start)
            right = sum(any(max(abs(rgb(y, width - 1 - x)[i] - background[i]) for i in range(3)) >= 28 for x in range(min(2, width))) for y in range(start, end)) / max(1, end - start)
            if left >= .06: errors.append(f"{image}: EDGE_CLIPPING_LEFT")
            if right >= .06: errors.append(f"{image}: EDGE_CLIPPING_RIGHT")
            polarity = check_polarity or image.stem.casefold().endswith(("_light", "_dark"))
            if polarity:
                mean_luma = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in (tuple(pixels[index:index + 3]) for index in range(0, len(pixels), channels))) / max(1, width * height)
                stem = image.stem.casefold()
                if stem.endswith("_light") and mean_luma < 85:
                    errors.append(f"{image}: POLARITY_MISMATCH")
                if stem.endswith("_dark") and mean_luma > 170:
                    errors.append(f"{image}: POLARITY_MISMATCH")
        except (OSError, ValueError, struct.error, zlib.error) as error:
            errors.append(f"{image}: invalid PNG: {error}")
    return errors


def audit_geometry(path: Path, platform: str) -> list[str]:
    try: document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error: return [f"GEOM_INVALID: {error}"]
    viewport = float(document.get("viewportWidth", document.get("viewport", {}).get("width", 0)))
    nodes: list[dict[str, Any]] = []
    def visit(value: Any, parent: Optional[dict[str, Any]] = None) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("frame"), dict):
                item = dict(value); item["_parent"] = parent; nodes.append(item)
            for child in value.get("children", []): visit(child, value)
        elif isinstance(value, list):
            for child in value: visit(child, parent)
    visit(document)
    errors: list[str] = []
    for node in nodes:
        frame = node["frame"]; x, y = float(frame.get("minX", frame.get("x", 0))), float(frame.get("minY", frame.get("y", 0))); width, height = float(frame.get("width", 0)), float(frame.get("height", 0)); max_x, max_y = x + width, y + height
        if viewport and (x < 0 or max_x > viewport): errors.append("GEOM_VIEWPORT_OVERFLOW")
        text = str(node.get("text", node.get("label", "")))
        if node.get("numeric") and ("…" in text or "..." in text): errors.append("GEOM_NUMERIC_TRUNCATION")
        if node.get("interactive") and (width < (44 if platform == "mobile" else 28) or height < (44 if platform == "mobile" else 28)): errors.append("GEOM_HIT_TARGET_TOO_SMALL")
    for parent in {id(node.get("_parent")): node.get("_parent") for node in nodes if node.get("_parent")}.values():
        siblings = [node for node in nodes if node.get("_parent") is parent]
        for index, first in enumerate(siblings):
            a = first["frame"]; ax, ay = float(a.get("minX", a.get("x", 0))), float(a.get("minY", a.get("y", 0))); ar, ab = ax + float(a.get("width", 0)), ay + float(a.get("height", 0))
            for second in siblings[index + 1:]:
                b = second["frame"]; bx, by = float(b.get("minX", b.get("x", 0))), float(b.get("minY", b.get("y", 0))); br, bb = bx + float(b.get("width", 0)), by + float(b.get("height", 0))
                if min(ar, br) > max(ax, bx) and min(ab, bb) > max(ay, by): errors.append("GEOM_SIBLING_OVERLAP")
    def role(node: dict[str, Any], wanted: str) -> bool:
        return node.get("role") == wanted or node.get("kind") == wanted

    headers = [node for node in nodes if role(node, "tableHeader")]
    rows = [node for node in nodes if role(node, "tableRow")]
    def scope(node: dict[str, Any]) -> Any:
        return node.get("tableId", node.get("group", id(node.get("_parent"))))
    def column(node: dict[str, Any], index: int) -> Any:
        return next((node[key] for key in ("col", "columnIndex", "column") if key in node), index)
    header_groups: dict[Any, list[dict[str, Any]]] = {}
    row_groups: dict[Any, list[dict[str, Any]]] = {}
    for node in headers:
        header_groups.setdefault(scope(node), []).append(node)
    for node in rows:
        row_groups.setdefault(scope(node), []).append(node)
    for key, header_group in header_groups.items():
        row_group = row_groups.get(key, [])
        row_by_column = {column(node, index): node for index, node in enumerate(row_group)}
        for index, header in enumerate(header_group):
            row = row_by_column.get(column(header, index))
            if row is None:
                continue
            hf, rf = header["frame"], row["frame"]
            if abs(float(hf.get("minX", hf.get("x", 0))) - float(rf.get("minX", rf.get("x", 0)))) > 1 or abs(float(hf.get("width", 0)) - float(rf.get("width", 0))) > 1:
                errors.append("GEOM_COLUMN_MISALIGNED")

    bento = [node for node in nodes if node.get("role") == "bento"]
    for index, first in enumerate(bento):
        a = first["frame"]
        ay = float(a.get("minY", a.get("y", 0)))
        ab = ay + float(a.get("height", 0))
        for second in bento[index + 1:]:
            b = second["frame"]
            by = float(b.get("minY", b.get("y", 0)))
            same_group = first.get("row", first.get("group")) is not None and first.get("row", first.get("group")) == second.get("row", second.get("group"))
            if (same_group or abs(ay - by) <= 20.0) and abs(ab - (by + float(b.get("height", 0)))) > 1.0:
                errors.append("GEOM_BENTO_BOTTOM_MISALIGNED")
    return list(dict.fromkeys(errors))


def _jev_threshold_argument(value: str) -> float:
    score = _jev_score(value)
    if score is None:
        raise argparse.ArgumentTypeError(
            "Jev threshold must be finite and between 0 and 1"
        )
    return score


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit docs/design-contract.md and scan UI sources."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--contract",
        default="docs/design-contract.md",
        help="Path to design contract markdown (skipped if absent when standalone gate flags are used).",
    )
    parser.add_argument("--ui-path", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--screenshot-dir", type=Path, default=None)
    parser.add_argument("--require-state-matrix", action="store_true")
    parser.add_argument(
        "--jev-url",
        default=os.environ.get("DESIGN_CONTRACT_JEV_URL", ""),
    )
    parser.add_argument("--jev-threshold", type=_jev_threshold_argument, default=0.65)
    parser.add_argument(
        "--jev-mode", choices=("off", "advisory", "gate"), default="off"
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument(
        "--states", default="populated,empty,loading,error"
    )
    parser.add_argument("--appearances", default="light,dark")
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--expected-pixel-width")
    parser.add_argument("--audit-code", nargs="*", default=None, metavar="PATH")
    parser.add_argument("--cases-file", type=Path, default=None, metavar="JSON")
    parser.add_argument("--platform", choices=("desktop", "mobile", "web", "all"), default="desktop")
    parser.add_argument("--audit-l10n", nargs="?", const=".", default=None, metavar="PATH")
    parser.add_argument("--locales", default="en,zh-Hans")
    parser.add_argument("--check-edge-clipping", metavar="PNG_OR_DIR")
    parser.add_argument("--check-polarity", action="store_true")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--audit-geometry", metavar="GEOMETRY_JSON")
    return parser


def _snapshot_dir(root: Path, configured: Optional[Path]) -> Path:
    if configured is not None:
        return configured if configured.is_absolute() else root / configured
    artifacts = root / "artifacts" / "snapshots"
    return artifacts if artifacts.is_dir() else root / "snapshots"


def _parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_DIMENSION = 16384
_MAX_PNG_CHUNK_BYTES = 32 * 1024 * 1024
_MAX_PNG_IMAGE_BYTES = 64 * 1024 * 1024
_PNG_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_PNG_BIT_DEPTHS = {
    0: (1, 2, 4, 8, 16),
    2: (8, 16),
    3: (1, 2, 4, 8),
    4: (8, 16),
    6: (8, 16),
}
_ADAM7_PASSES = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def _png_width(path: Path) -> Optional[int]:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return _png_width_from_bytes(payload)


def _png_chunk(payload: bytes, offset: int) -> Optional[tuple[bytes, bytes, int]]:
    if len(payload) - offset < 12:
        return None
    length = struct.unpack_from(">I", payload, offset)[0]
    if length > _MAX_PNG_CHUNK_BYTES:
        return None
    data_end = offset + 8 + length
    crc_end = data_end + 4
    if crc_end > len(payload):
        return None
    chunk_type = payload[offset + 4 : offset + 8]
    data = payload[offset + 8 : data_end]
    expected = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    actual = struct.unpack_from(">I", payload, data_end)[0]
    if actual != expected:
        return None
    if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type) or chunk_type[2] & 0x20:
        return None
    return chunk_type, data, crc_end


def _parse_ihdr(data: bytes) -> Optional[tuple[int, int, int, int, int]]:
    if len(data) != 13:
        return None
    width, height, bit_depth, color_type, compression, filter_method, interlace = (
        struct.unpack(">IIBBBBB", data)
    )
    if (
        width < 1
        or height < 1
        or width > _MAX_PNG_DIMENSION
        or height > _MAX_PNG_DIMENSION
        or compression != 0
        or filter_method != 0
        or interlace not in (0, 1)
    ):
        return None
    allowed = _PNG_BIT_DEPTHS.get(color_type)
    if allowed is None or bit_depth not in allowed:
        return None
    return width, height, bit_depth, color_type, interlace


def _png_scanline_bytes(width: int, samples: int, bit_depth: int) -> int:
    return 1 + (width * samples * bit_depth + 7) // 8


def _png_image_byte_count(
    width: int, height: int, samples: int, bit_depth: int, interlace: int
) -> Optional[int]:
    if interlace == 0:
        total = height * _png_scanline_bytes(width, samples, bit_depth)
    elif interlace == 1:
        total = 0
        for origin_x, origin_y, step_x, step_y in _ADAM7_PASSES:
            if origin_x >= width or origin_y >= height:
                continue
            pass_width = (width - origin_x + step_x - 1) // step_x
            pass_height = (height - origin_y + step_y - 1) // step_y
            total += pass_height * _png_scanline_bytes(pass_width, samples, bit_depth)
    else:
        return None
    if total <= 0 or total > _MAX_PNG_IMAGE_BYTES:
        return None
    return total


def _png_scanlines_valid(
    payload: bytes,
    expected: int,
    ihdr: tuple[int, int, int, int, int],
) -> bool:
    decompressor = zlib.decompressobj()
    try:
        produced = decompressor.decompress(payload, expected + 1)
    except zlib.error:
        return False
    if (
        len(produced) != expected
        or decompressor.unconsumed_tail
        or decompressor.unused_data
        or not decompressor.eof
    ):
        return False
    width, height, bit_depth, color_type, interlace = ihdr
    samples = _PNG_SAMPLES[color_type]
    passes = ((0, 0, 1, 1),) if interlace == 0 else _ADAM7_PASSES
    offset = 0
    for origin_x, origin_y, step_x, step_y in passes:
        if origin_x >= width or origin_y >= height:
            continue
        pass_width = (width - origin_x + step_x - 1) // step_x
        pass_height = (height - origin_y + step_y - 1) // step_y
        row_bytes = _png_scanline_bytes(pass_width, samples, bit_depth)
        for _ in range(pass_height):
            if produced[offset] > 4:
                return False
            offset += row_bytes
    return offset == len(produced)


def _png_width_from_bytes(payload: bytes) -> Optional[int]:
    dimensions = _png_dimensions_from_bytes(payload)
    return dimensions[0] if dimensions is not None else None


def _png_dimensions_from_bytes(payload: bytes) -> Optional[tuple[int, int]]:
    if len(payload) < 8 or payload[:8] != _PNG_SIGNATURE:
        return None
    offset = 8
    ihdr: Optional[tuple[int, int, int, int, int]] = None
    idat = bytearray()
    idat_started = False
    idat_closed = False
    seen_plte = False
    while offset < len(payload):
        chunk = _png_chunk(payload, offset)
        if chunk is None:
            return None
        chunk_type, data, offset = chunk
        if ihdr is None:
            if chunk_type != b"IHDR":
                return None
            ihdr = _parse_ihdr(data)
            if ihdr is None:
                return None
            continue
        if chunk_type == b"IHDR":
            return None
        if chunk_type == b"IEND":
            if data or offset != len(payload) or not idat:
                return None
            width, height, bit_depth, color_type, interlace = ihdr
            samples = _PNG_SAMPLES[color_type]
            expected = _png_image_byte_count(
                width, height, samples, bit_depth, interlace
            )
            if expected is None or not _png_scanlines_valid(bytes(idat), expected, ihdr):
                return None
            return width, height
        if chunk_type == b"IDAT":
            if idat_closed or (ihdr[3] == 3 and not seen_plte):
                return None
            idat_started = True
            idat.extend(data)
            continue
        if idat_started:
            idat_closed = True
        if chunk_type == b"PLTE":
            bit_depth, color_type = ihdr[2:4]
            if (
                seen_plte
                or idat_started
                or color_type in (0, 4)
                or not data
                or len(data) % 3
                or len(data) > 768
                or (color_type == 3 and len(data) // 3 > 1 << bit_depth)
            ):
                return None
            seen_plte = True
            continue
        if chunk_type[0] & 0x20 == 0:
            return None
    return None


def _visual_audit(
    root: Path,
    states: Sequence[str],
    appearances: Sequence[str],
    snapshot_dir: Optional[Path],
    expected_pixel_width: Optional[str],
) -> list[str]:
    directory = _snapshot_dir(root, snapshot_dir)
    if not directory.is_dir():
        return [f"snapshot directory not found: {directory}"]
    expected: Optional[list[int]] = None
    if expected_pixel_width is not None:
        try:
            expected = [int(item) for item in _parse_csv(expected_pixel_width)]
        except ValueError:
            return [f"invalid expected pixel width: {expected_pixel_width}"]
        if not expected or any(width <= 0 for width in expected):
            return [f"invalid expected pixel width: {expected_pixel_width}"]

    snapshots = sorted(directory.glob("*.png"))
    errors: list[str] = []
    for state in states:
        for appearance in appearances:
            marker = re.compile(
                rf"(^|[-_]){re.escape(state)}[-_]{re.escape(appearance)}"
                rf"([-. _@]|$)",
                re.IGNORECASE,
            )
            matches = [path for path in snapshots if marker.search(path.stem)]
            label = f"{state}/{appearance}"
            if not matches:
                errors.append(f"missing snapshot: {label}")
                continue
            for path in matches:
                width = _png_width(path)
                if width is None:
                    errors.append(f"invalid PNG snapshot: {path}")
                elif expected is not None and width not in expected:
                    errors.append(
                        f"unexpected pixel width for {path.name}: "
                        f"{width} (expected {expected})"
                    )
    return errors


def _report(
    contract_path: Path,
    contract_errors: Sequence[str],
    violations: Sequence[DesignViolation],
    visual_errors: Sequence[str] = (),
    advisory_violations: Optional[Sequence[DesignViolation]] = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "ok": not contract_errors and not violations and not visual_errors,
        "contract": contract_path.as_posix(),
        "contract_errors": list(contract_errors),
        "violations": [asdict(violation) for violation in violations],
        "visual_errors": list(visual_errors),
    }
    if advisory_violations is not None:
        report["advisory_violations"] = [
            asdict(violation) for violation in advisory_violations
        ]
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the design-contract audit CLI and return a process status."""

    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    contract_arg = Path(args.contract)
    contract_path = (
        contract_arg.resolve() if contract_arg.is_absolute() else root / contract_arg
    )
    targeted = any(value is not None for value in (args.audit_code, args.audit_l10n, args.check_edge_clipping, args.audit_geometry))
    contract_errors = [] if targeted and args.contract == "docs/design-contract.md" and not contract_path.is_file() else audit_contract(contract_path)
    violations = (
        scan_ui_sources(root, args.ui_path, args.exclude) if args.ui_path else []
    )
    if args.audit_code is not None:
        audit_paths = _audit_paths(root, args.audit_code, SUPPORTED_SUFFIXES)
        cases_file = args.cases_file if args.cases_file is None or args.cases_file.is_absolute() else root / args.cases_file
        violations.extend(audit_code(audit_paths, args.platform, cases_file))
    if args.audit_l10n is not None:
        l10n_target = [args.audit_l10n] if args.audit_l10n != "." else []
        violations.extend(audit_l10n(root, l10n_target, _parse_csv(args.locales)))
    visual_errors: list[str] = []
    if args.check_edge_clipping:
        target = Path(args.check_edge_clipping)
        target = target if target.is_absolute() else root / target
        visual_errors.extend(check_edge_clipping(target, args.expected_pixel_width, args.scale, args.check_polarity))
    if args.audit_geometry:
        target = Path(args.audit_geometry)
        target = target if target.is_absolute() else root / target
        visual_errors.extend(audit_geometry(target, args.platform))
    if args.visual:
        visual_errors.extend(
            _visual_audit(
                root,
                _parse_csv(args.states),
                _parse_csv(args.appearances),
                args.snapshot_dir,
                args.expected_pixel_width,
            )
        )
    screenshot_paths: list[Path] = []
    advisory_violations: Optional[list[DesignViolation]] = None
    if args.screenshot_dir is not None:
        screenshot_paths, screenshot_violations = audit_screenshot_matrix(
            root,
            root / args.screenshot_dir
            if not args.screenshot_dir.is_absolute()
            else args.screenshot_dir,
            require_state_matrix=args.require_state_matrix,
        )
        violations.extend(screenshot_violations)
    elif args.require_state_matrix or args.jev_mode != "off":
        violations.append(
            DesignViolation(
                path=".",
                line=0,
                rule="SCREENSHOT_PATH_MISSING",
                snippet="--screenshot-dir is required for screenshot checks",
            )
        )

    if args.jev_mode != "off" and screenshot_paths:
        jev_violations, advisory_violations = scan_screenshots_with_jev(
            root,
            screenshot_paths,
            args.jev_url,
            jev_threshold=args.jev_threshold,
            jev_mode=args.jev_mode,
        )
        violations.extend(jev_violations)
    elif args.jev_mode == "advisory":
        advisory_violations = []

    report = _report(
        contract_path,
        contract_errors,
        violations,
        visual_errors,
        advisory_violations,
    )

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
        for error in visual_errors:
            sys.stderr.write(f"design contract: {error}\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
