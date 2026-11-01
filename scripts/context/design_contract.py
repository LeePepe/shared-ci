#!/usr/bin/env python3
"""Validate a project design contract and scan UI sources for raw colors."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit docs/design-contract.md and scan UI sources."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--contract", default="docs/design-contract.md")
    parser.add_argument("--ui-path", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument(
        "--states", default="populated,empty,loading,error"
    )
    parser.add_argument("--appearances", default="light,dark")
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--expected-pixel-width")
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
    if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
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


def _zlib_exact(payload: bytes, expected: int) -> bool:
    decompressor = zlib.decompressobj()
    try:
        produced = decompressor.decompress(payload, expected)
    except zlib.error:
        return False
    if len(produced) != expected or decompressor.unconsumed_tail:
        return False
    try:
        remainder = decompressor.flush()
    except zlib.error:
        return False
    return (
        remainder == b""
        and not decompressor.unused_data
        and decompressor.eof
    )


def _png_width_from_bytes(payload: bytes) -> Optional[int]:
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
            if expected is None or not _zlib_exact(bytes(idat), expected):
                return None
            return width
        if chunk_type == b"IDAT":
            if idat_closed:
                return None
            idat_started = True
            idat.extend(data)
            continue
        if idat_started:
            idat_closed = True
        if chunk_type == b"PLTE":
            if seen_plte or idat_started:
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
) -> dict[str, object]:
    return {
        "ok": not contract_errors and not violations and not visual_errors,
        "contract": contract_path.as_posix(),
        "contract_errors": list(contract_errors),
        "violations": [asdict(violation) for violation in violations],
        "visual_errors": list(visual_errors),
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
    visual_errors = (
        _visual_audit(
            root,
            _parse_csv(args.states),
            _parse_csv(args.appearances),
            args.snapshot_dir,
            args.expected_pixel_width,
        )
        if args.visual
        else []
    )
    report = _report(contract_path, contract_errors, violations, visual_errors)

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
    return 0 if not contract_errors and not violations and not visual_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
