"""Tests for the project design-contract audit and UI source gate."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import struct
import sys
import tempfile
import unittest
import zlib
from typing import Iterator
from unittest import mock


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "context" / "design_contract.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_design_contract", SCRIPT)
assert SPEC and SPEC.loader
design_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = design_contract
SPEC.loader.exec_module(design_contract)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _scanline_png(width: int, height: int, *, color_type: int, interlace: int) -> bytes:
    samples = {2: 3, 6: 4}[color_type]
    if interlace == 0:
        raw = b"".join(
            b"\x00" + (b"\x00" * (width * samples)) for _ in range(height)
        )
    else:
        raw = _adam7_raw(width, height, samples)
    return _png_with_idat(
        width,
        height,
        zlib.compress(raw),
        color_type=color_type,
        interlace=interlace,
        ancillary=True,
    )


def _png_with_idat(
    width: int,
    height: int,
    idat: bytes,
    *,
    color_type: int = 6,
    interlace: int = 0,
    ancillary: bool = False,
) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, interlace)
    chunks = [_png_chunk(b"IHDR", ihdr)]
    if ancillary:
        chunks.append(_png_chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)))
    chunks.append(_png_chunk(b"IDAT", idat))
    chunks.append(_png_chunk(b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def _adam7_raw(width: int, height: int, samples: int) -> bytes:
    """Uncompressed Adam7 image bytes, including each pass's filter byte."""

    passes = (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    )
    parts: list[bytes] = []
    for origin_x, origin_y, step_x, step_y in passes:
        if origin_x >= width or origin_y >= height:
            continue
        pass_width = (width - origin_x + step_x - 1) // step_x
        pass_height = (height - origin_y + step_y - 1) // step_y
        row = b"\x00" + (b"\x00" * (pass_width * samples))
        parts.append(row * pass_height)
    return b"".join(parts)


@contextlib.contextmanager
def captured_output() -> Iterator[tuple[io.StringIO, io.StringIO]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield stdout, stderr


class DesignContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix=".design-contract-", dir=REPO)
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def _write(self, relative: str, content: str) -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _valid_contract(self) -> str:
        return """# Contract

## Design system & version
Package: DesignSystem 1.2.3. Platforms: iOS. Modes: light and dark.

## Semantic token profile
Brand, surface, and text roles use semantic tokens only.

## Required view states
populated, empty, loading, error

## Redlines & CI gate
No raw colors.
"""

    def _write_png(
        self, relative: str, width: int = 2, height: int = 3
    ) -> pathlib.Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_scanline_png(width, height, color_type=6, interlace=0))
        return path

    def test_template_passes_contract_audit(self) -> None:
        errors = design_contract.audit_contract(REPO / "templates/design-contract.md")
        self.assertEqual([], errors)

    def test_missing_sections_and_states_are_reported(self) -> None:
        contract = self._write(
            "docs/design-contract.md",
            "## Design system & version\nlight\n",
        )
        errors = design_contract.audit_contract(contract)
        self.assertIn("missing required section: ## Semantic token profile", errors)
        self.assertIn("missing required view state: populated", errors)
        self.assertIn("missing required appearance mode: dark", errors)

    def test_scanner_detects_swift_tsx_and_css_and_honors_skips(self) -> None:
        self._write(
            "Sources/Screen.swift",
            'let color = Color(red: 1, green: 0, blue: 0)\n'
            'let accent = "#FF00AA"\n',
        )
        self._write(
            "Sources/Component.tsx",
            "const style = { color: #123456 };\n"
            "const shadow = rgba(0, 0, 0, 0.5);\n"
            'const old = "#ABCDEF"; // design-contract-allow: legacy\n',
        )
        self._write("Sources/Generated/Colors.swift", 'let value = "#FFFFFF"\n')
        self._write("Sources/TokenPalette.ts", "const value = rgba(0, 0, 0, 1)\n")

        findings = design_contract.scan_ui_sources(self.root, ["Sources"])
        self.assertEqual(
            {
                ("Sources/Screen.swift", 1, "RAW_RGB_COLOR"),
                ("Sources/Screen.swift", 2, "RAW_HEX_COLOR"),
                ("Sources/Component.tsx", 1, "RAW_HEX_COLOR"),
                ("Sources/Component.tsx", 2, "RAW_RGB_COLOR"),
            },
            {(item.path, item.line, item.rule) for item in findings},
        )

    def test_scanner_does_not_skip_production_names_containing_test(self) -> None:
        self._write(
            "UI/LatestView.swift",
            "let color = Color(red: 1, green: 0, blue: 0)\n",
        )
        self._write(
            "UI/ContestScreen.tsx",
            "const color = rgba(0, 0, 0, 0.5);\n",
        )
        self._write(
            "UI/Contests/Screen.tsx",
            'const accent = "#112233";\n',
        )

        findings = design_contract.scan_ui_sources(self.root, ["UI"])

        self.assertEqual(
            {
                ("UI/LatestView.swift", 1, "RAW_RGB_COLOR"),
                ("UI/ContestScreen.tsx", 1, "RAW_RGB_COLOR"),
                ("UI/Contests/Screen.tsx", 1, "RAW_HEX_COLOR"),
            },
            {(item.path, item.line, item.rule) for item in findings},
        )

    def test_scanner_detects_multiline_rgb_constructors(self) -> None:
        self._write(
            "UI/Multiline.swift",
            "let color = Color(\n"
            "    red: 1.0,\n"
            "    green: 0.0,\n"
            "    blue: 0.0\n"
            ")\n",
        )
        self._write(
            "UI/Multiline.tsx",
            "const color = rgba(\n"
            "    0, 0, 0, 0.5\n"
            ");\n",
        )

        findings = design_contract.scan_ui_sources(self.root, ["UI"])

        self.assertEqual(
            {
                ("UI/Multiline.swift", 1, "RAW_RGB_COLOR"),
                ("UI/Multiline.tsx", 1, "RAW_RGB_COLOR"),
            },
            {(item.path, item.line, item.rule) for item in findings},
        )

    def test_cli_json_reports_success_and_failure_status(self) -> None:
        self._write("docs/design-contract.md", self._valid_contract())
        self._write("UI/View.tsx", 'const style = { color: "#123456" };\n')

        with captured_output() as (stdout, stderr):
            success = design_contract.main(
                ["--root", str(self.root), "--ui-path", "UI", "--json"]
            )
        self.assertEqual(1, success)
        self.assertEqual("", stderr.getvalue())
        failure_report = json.loads(stdout.getvalue())
        self.assertFalse(failure_report["ok"])
        self.assertEqual("RAW_HEX_COLOR", failure_report["violations"][0]["rule"])

        self._write("UI/View.tsx", "// design-contract-allow: legacy\n")
        with captured_output() as (stdout, stderr):
            success = design_contract.main(
                ["--root", str(self.root), "--ui-path", "UI", "--json"]
            )
        self.assertEqual(0, success)
        self.assertEqual("", stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["ok"])

    def test_v1_contract_uses_seven_numbered_sections(self) -> None:
        sections = "\n".join(f"## {number}. Section {number}" for number in range(1, 8))
        contract = self._write(
            "docs/design.md",
            "---\nschema: agent-design-doc/v1\n---\n"
            f"{sections}\n"
            "populated empty loading error light dark\n",
        )
        self.assertEqual([], design_contract.audit_contract(contract))

    def test_scanner_detects_new_static_rules(self) -> None:
        self._write(
            "UI/View.swift",
            "let a = hsl(20, 50%, 50%)\n"
            "let b = hsla(20, 50%, 50%, 0.5)\n"
            ".frame(width: 380).padding(16)\n"
            ".padding(16).frame(width: 380)\n"
            ".font(.system(size: 7.5))\n"
            ".minimumScaleFactor(0.55)\n",
        )
        findings = design_contract.scan_ui_sources(self.root, ["UI"])
        rules = [item.rule for item in findings]
        self.assertEqual(2, rules.count("raw-hsl-color"))
        self.assertIn("frame-before-padding", rules)
        self.assertIn("micro-font-size", rules)
        self.assertIn("excessive-scale-factor", rules)
        self.assertEqual(
            0,
            sum(item.rule == "frame-before-padding" and ".padding(16).frame" in item.snippet
                for item in findings),
        )

    def test_scanner_detects_multiline_swiftui_layout_and_font_rules(self) -> None:
        self._write(
            "UI/Layout.swift",
            "Text(\"Bad\")\n"
            "    .frame(width: 380)\n"
            "    .padding(16)\n"
            "Text(\"Good\")\n"
            "    .padding(16)\n"
            "    .frame(width: 380)\n"
            "Text(\"Micro\")\n"
            "    .font(.system(size:\n"
            "        7.5))\n"
            "Text(\"Scale\")\n"
            "    .minimumScaleFactor(\n"
            "        0.55)\n"
            "Text(\"Readable\")\n"
            "    .font(.system(size:\n"
            "        12))\n"
            "    .minimumScaleFactor(\n"
            "        0.9)\n"
            "Text(\"Allowed\")\n"
            "    .frame(width: 380) // design-contract-allow: legacy\n"
            "    .padding(16)\n"
            "    .font(.system(size:\n"
            "        8)) // design-contract-allow: legacy\n",
        )
        findings = design_contract.scan_ui_sources(self.root, ["UI"])
        self.assertEqual(
            {
                ("UI/Layout.swift", 2, "frame-before-padding"),
                ("UI/Layout.swift", 8, "micro-font-size"),
                ("UI/Layout.swift", 11, "excessive-scale-factor"),
            },
            {(item.path, item.line, item.rule) for item in findings},
        )
        snippets = {item.line: item.snippet for item in findings}
        self.assertIn(".frame(width: 380)", snippets[2])
        self.assertIn(".system(size:", snippets[8])
        self.assertIn(".minimumScaleFactor(", snippets[11])

    def test_visual_audit_checks_matrix_and_png_width(self) -> None:
        snapshots = self.root / "snapshots"
        snapshots.mkdir()
        png = _scanline_png(380, 2, color_type=6, interlace=0)
        for state in ("populated", "empty", "loading", "error"):
            for appearance in ("light", "dark"):
                (snapshots / f"screen-{state}-{appearance}.png").write_bytes(png)
        errors = design_contract._visual_audit(
            self.root,
            ("populated", "empty", "loading", "error"),
            ("light", "dark"),
            None,
            "380,760",
        )
        self.assertEqual([], errors)

    def test_visual_audit_rejects_truncated_snapshots(self) -> None:
        snapshots = self.root / "snapshots"
        snapshots.mkdir()
        complete = _scanline_png(380, 1, color_type=6, interlace=0)
        partial_ihdr = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">IIBBBBB", 380, 100, 8, 6, 0, 0, 0)
        )
        self.assertEqual(29, len(partial_ihdr))
        ihdr = struct.pack(">IIBBBBB", 380, 1, 8, 6, 0, 0, 0)
        header_only = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
        fabricated = (
            header_only
            + _png_chunk(b"IDAT", b"not-image-data")
            + _png_chunk(b"IEND", b"")
        )
        bad_crc = bytearray(header_only)
        bad_crc[-1] ^= 0xFF
        scanlines = b"\x00" + (b"\x00" * (380 * 4))
        compressed = zlib.compress(scanlines)
        self.assertGreater(len(compressed), 6)
        trailer_removed = _png_with_idat(380, 1, compressed[:-4])
        intact = self.root / "intact.png"
        intact.write_bytes(_png_with_idat(380, 1, compressed))
        self.assertEqual(380, design_contract._png_width(intact))
        truncated = {
            "partial-ihdr": partial_ihdr,
            "ihdr-only": header_only,
            "cut-idat": complete[: len(complete) // 2],
            "missing-iend": complete[: complete.rfind(b"IEND") - 4],
            "truncated-crc": complete[:-1],
            "fabricated-idat": fabricated,
            "bad-ihdr-crc": bytes(bad_crc),
            "zlib-trailer": trailer_removed,
        }
        for name, payload in truncated.items():
            path = snapshots / f"screen-populated-light-{name}.png"
            path.write_bytes(payload)
            self.assertIsNone(design_contract._png_width(path), name)

        wide = snapshots / "screen-populated-light.png"
        wide.write_bytes(complete)
        narrow = snapshots / "screen-empty-light.png"
        narrow.write_bytes(_scanline_png(100, 1, color_type=2, interlace=0))
        interlaced = _adam7_raw(8, 8, 3)
        self.assertEqual(207, len(interlaced))
        adam7 = snapshots / "screen-loading-light.png"
        adam7.write_bytes(_scanline_png(8, 8, color_type=2, interlace=1))
        self.assertEqual(8, design_contract._png_width(adam7))
        self.assertEqual(380, design_contract._png_width(wide))

        errors = design_contract._visual_audit(
            self.root,
            ("populated", "empty", "loading", "error"),
            ("light", "dark"),
            None,
            "380,760",
        )
        self.assertTrue(errors)
        self.assertTrue(
            any(
                error.startswith("invalid PNG snapshot:") and "zlib-trailer" in error
                for error in errors
            )
        )
        self.assertTrue(
            any("unexpected pixel width" in error and "100" in error for error in errors)
        )
        self.assertTrue(any("missing snapshot: populated/dark" in error for error in errors))
        self.assertFalse(
            any("screen-populated-light.png" in error and "invalid PNG" in error for error in errors)
        )

    def test_screenshot_matrix_validates_pngs_and_required_combinations(self) -> None:
        self._write_png("screenshots/workout_populated_light.png")
        self._write_png("screenshots/workout_populated_dark.png")
        self._write("screenshots/workout_empty_light.png", "not a png")

        paths, findings = design_contract.audit_screenshot_matrix(
            self.root,
            self.root / "screenshots",
            require_state_matrix=True,
        )

        self.assertEqual(2, len(paths))
        self.assertIn(
            ("screenshots/workout_empty_light.png", "INVALID_SCREENSHOT_PNG"),
            {(item.path, item.rule) for item in findings},
        )
        missing = [item for item in findings if item.rule == "MISSING_STATE_SCREENSHOT"]
        self.assertEqual(6, len(missing))

    def test_screenshot_matrix_rejects_directory_outside_root(self) -> None:
        paths, findings = design_contract.audit_screenshot_matrix(
            self.root,
            pathlib.Path(tempfile.gettempdir()),
        )

        self.assertEqual([], paths)
        self.assertEqual("SCREENSHOT_PATH_OUTSIDE_ROOT", findings[0].rule)

    def test_screenshot_matrix_rejects_symlink_outside_root(self) -> None:
        outside = pathlib.Path(tempfile.mkdtemp(prefix=".outside-design-contract-"))
        target = outside / "secret.png"
        target.write_bytes(_scanline_png(2, 3, color_type=6, interlace=0))
        self.addCleanup(lambda: (target.unlink(), outside.rmdir()))
        link = self.root / "screenshots" / "outside.png"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

        paths, findings = design_contract.audit_screenshot_matrix(
            self.root, self.root / "screenshots"
        )

        self.assertEqual([], paths)
        self.assertEqual("SCREENSHOT_PATH_OUTSIDE_ROOT", findings[0].rule)

    def test_screenshot_matrix_rejects_truncated_png(self) -> None:
        path = self.root / "screenshots" / "truncated.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + (2).to_bytes(4, "big")
            + (3).to_bytes(4, "big")
        )

        paths, findings = design_contract.audit_screenshot_matrix(
            self.root, self.root / "screenshots"
        )

        self.assertEqual([], paths)
        self.assertEqual("INVALID_SCREENSHOT_PNG", findings[0].rule)

    def test_screenshot_matrix_rejects_invalid_png_structures(self) -> None:
        signature = b"\x89PNG\r\n\x1a\n"
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 3, 8, 6, 0, 0, 0))
        raw = (b"\x00" + b"\x00" * 8) * 3
        compressed = zlib.compress(raw)
        idat = _png_chunk(b"IDAT", compressed)
        iend = _png_chunk(b"IEND", b"")
        malformed = {
            "empty-scanlines": ihdr + _png_chunk(b"IDAT", zlib.compress(b"")) + iend,
            "short-scanlines": ihdr + _png_chunk(b"IDAT", zlib.compress(raw[:-1])) + iend,
            "extra-scanlines": ihdr + _png_chunk(b"IDAT", zlib.compress(raw + b"\x00")) + iend,
            "invalid-filter": ihdr + _png_chunk(b"IDAT", zlib.compress(b"\x05" + raw[1:])) + iend,
            "duplicate-ihdr": ihdr + ihdr + idat + iend,
            "duplicate-iend": ihdr + idat + iend + iend,
            "early-iend": ihdr + iend + idat + iend,
            "idat-first": idat + ihdr + iend,
            "split-idat": (
                ihdr + _png_chunk(b"IDAT", compressed[:4])
                + _png_chunk(b"tEXt", b"key\x00value")
                + _png_chunk(b"IDAT", compressed[4:]) + iend
            ),
            "unknown-critical": ihdr + _png_chunk(b"ABCD", b"") + idat + iend,
            "reserved-bit": ihdr + _png_chunk(b"abca", b"") + idat + iend,
            "extra-zlib-stream": ihdr + _png_chunk(b"IDAT", compressed * 2) + iend,
        }
        for color_type, depth in ((2, 4), (3, 16), (4, 1), (6, 2), (1, 8)):
            header = struct.pack(">IIBBBBB", 2, 3, depth, color_type, 0, 0, 0)
            malformed[f"color-{color_type}-depth-{depth}"] = (
                _png_chunk(b"IHDR", header) + idat + iend
            )
        for name, chunks in malformed.items():
            with self.subTest(name=name):
                path = self.root / "screenshots" / f"populated_light_{name}.png"
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(signature + chunks)
                self.assertIsNone(design_contract.read_png_dimensions(path))

        paths, findings = design_contract.audit_screenshot_matrix(
            self.root, self.root / "screenshots", require_state_matrix=True
        )
        self.assertEqual([], paths)
        self.assertEqual(len(malformed), sum(
            item.rule == "INVALID_SCREENSHOT_PNG" for item in findings
        ))
        self.assertEqual(8, sum(
            item.rule == "MISSING_STATE_SCREENSHOT" for item in findings
        ))

    def test_png_dimensions_accept_legal_depths_and_validate_palettes(self) -> None:
        signature = b"\x89PNG\r\n\x1a\n"
        path = self.root / "image.png"
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                  4: (8, 16), 6: (8, 16)}
        samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
        for color_type, allowed in depths.items():
            for depth in allowed:
                with self.subTest(color_type=color_type, depth=depth):
                    header = _png_chunk(b"IHDR", struct.pack(
                        ">IIBBBBB", 3, 5, depth, color_type, 0, 0, 0
                    ))
                    palette = _png_chunk(b"PLTE", b"\x00\x00\x00") if color_type == 3 else b""
                    row_bytes = (3 * samples[color_type] * depth + 7) // 8
                    raw = b"".join(bytes([filter_type]) + b"\x00" * row_bytes
                                   for filter_type in range(5))
                    compressed = zlib.compress(raw)
                    # Contiguous IDAT chunks and ancillary metadata are legal.
                    image = (header + palette + _png_chunk(b"IDAT", compressed[:4])
                             + _png_chunk(b"IDAT", compressed[4:])
                             + _png_chunk(b"tEXt", b"key\x00value") + _png_chunk(b"IEND", b""))
                    path.write_bytes(signature + image)
                    self.assertEqual((3, 5), design_contract.read_png_dimensions(path))

        indexed_header = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 1, 3, 0, 0, 0))
        idat = _png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        iend = _png_chunk(b"IEND", b"")
        for palette in (b"", _png_chunk(b"PLTE", b""), _png_chunk(b"PLTE", b"\x00"),
                        _png_chunk(b"PLTE", b"\x00" * 9),
                        _png_chunk(b"PLTE", b"\x00" * 3) * 2):
            with self.subTest(palette=palette):
                path.write_bytes(signature + indexed_header + palette + idat + iend)
                self.assertIsNone(design_contract.read_png_dimensions(path))

    def test_png_dimensions_validate_adam7_scanlines(self) -> None:
        path = self.root / "interlaced.png"
        for width, height in ((1, 1), (2, 3), (8, 8)):
            with self.subTest(width=width, height=height):
                raw = _adam7_raw(width, height, 3)
                path.write_bytes(_scanline_png(width, height, color_type=2, interlace=1))
                self.assertEqual((width, height), design_contract.read_png_dimensions(path))
                for invalid in (raw[:-1], raw + b"\x00", b"\x05" + raw[1:]):
                    path.write_bytes(_png_with_idat(
                        width, height, zlib.compress(invalid), color_type=2, interlace=1
                    ))
                    self.assertIsNone(design_contract.read_png_dimensions(path))

    def test_jev_uses_box_only_when_noul_clears_threshold(self) -> None:
        screenshot = self._write_png("screenshots/workout_populated_dark.png")
        response_body = {
            "answers": {
                "has_text_truncation": {"value": 0.84},
                "truncation_box": {"boxes": [412, 118, 446, 360]},
                "has_control_collision": 0.2,
                "collision_box": {"box": [1, 2, 3, 4]},
                "has_unreadable_contrast": {"value": 0.7},
                "contrast_box": {"box": [5, 6, 7, 8]},
            }
        }
        response = mock.Mock(status=200)
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=False)
        response.read = mock.Mock(
            return_value=json.dumps(response_body).encode("utf-8")
        )

        with mock.patch.object(
            design_contract.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            violations, advisory = design_contract.scan_screenshots_with_jev(
                self.root, [screenshot], "http://jev.test/v1/systemone"
            )

        self.assertEqual([], advisory)
        self.assertEqual(
            {"UI_TEXT_TRUNCATION_BOX", "UI_UNREADABLE_CONTRAST_BOX"},
            {item.rule for item in violations},
        )
        request = urlopen.call_args.args[0]
        self.assertEqual("POST", request.get_method())
        payload = json.loads(request.data)
        self.assertTrue(payload["state"]["image"].startswith("data:image/png;base64,"))

    def test_jev_advisory_failure_is_reported_without_changing_ok(self) -> None:
        self._write("docs/design-contract.md", self._valid_contract())
        self._write_png("screenshots/workout_populated_dark.png")

        with mock.patch.object(
            design_contract.urllib.request,
            "urlopen",
            side_effect=OSError("service unavailable"),
        ):
            with captured_output() as (stdout, stderr):
                status = design_contract.main(
                    [
                        "--root",
                        str(self.root),
                        "--screenshot-dir",
                        "screenshots",
                        "--jev-url",
                        "http://jev.test/v1/systemone",
                        "--jev-mode",
                        "advisory",
                        "--json",
                    ]
                )

        self.assertEqual(0, status)
        self.assertEqual("", stderr.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(
            "JEV_VISION_UNAVAILABLE",
            report["advisory_violations"][0]["rule"],
        )

    def test_jev_rejects_missing_nonfinite_and_out_of_range_scores(self) -> None:
        screenshot = self._write_png("screenshots/workout_populated_dark.png")
        for invalid in (None, {"value": float("nan")}, {"value": float("inf")},
                        {"value": -0.1}, {"value": 1.1}):
            response_body = {"answers": {
                "has_text_truncation": invalid,
                "has_control_collision": 0.2,
                "has_unreadable_contrast": 0.2,
            }}
            response = mock.Mock(status=200)
            response.__enter__ = mock.Mock(return_value=response)
            response.__exit__ = mock.Mock(return_value=False)
            response.read = mock.Mock(
                return_value=json.dumps(response_body, allow_nan=True).encode("utf-8")
            )
            with mock.patch.object(
                design_contract.urllib.request, "urlopen", return_value=response
            ):
                violations, advisory = design_contract.scan_screenshots_with_jev(
                    self.root, [screenshot], "http://jev.test/v1/systemone"
                )

            self.assertEqual([], advisory)
            self.assertEqual("JEV_VISION_UNAVAILABLE", violations[0].rule)
            self.assertIn("invalid score for has_text_truncation", violations[0].snippet)

    def test_jev_rejects_invalid_thresholds_before_requests(self) -> None:
        screenshot = self._write_png("screenshots/workout_populated_dark.png")
        for threshold in (float("nan"), float("inf"), -float("inf"), -0.1, 1.1):
            for mode in ("gate", "advisory"):
                for paths in ([screenshot], []):
                    with self.subTest(threshold=threshold, mode=mode, paths=paths):
                        with mock.patch.object(design_contract.urllib.request, "urlopen") as request:
                            with self.assertRaisesRegex(ValueError, "jev_threshold must be finite"):
                                design_contract.scan_screenshots_with_jev(
                                    self.root, paths, "http://jev.test/v1/systemone",
                                    jev_threshold=threshold, jev_mode=mode,
                                )
                            request.assert_not_called()

        for threshold in ("nan", "inf", "-inf", "-0.1", "1.1"):
            with self.subTest(cli_threshold=threshold):
                with captured_output() as (stdout, stderr):
                    with self.assertRaises(SystemExit) as exit_status:
                        design_contract.main([f"--jev-threshold={threshold}"])
                self.assertEqual(2, exit_status.exception.code)
                self.assertEqual("", stdout.getvalue())
                self.assertIn("Jev threshold must be finite and between 0 and 1", stderr.getvalue())

    def test_new_audit_code_gate_has_positive_and_negative_results(self) -> None:
        self._write("UI/Good.swift", "Text(\"ok\")\n")
        with captured_output() as (stdout, _):
            self.assertEqual(0, design_contract.main(["--root", str(self.root), "--audit-code", "UI", "--platform", "desktop", "--json"]))
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        self._write("UI/Bad.swift", "Text(\"bad\").hoverEffect()\n")
        with captured_output() as (stdout, _):
            self.assertEqual(1, design_contract.main(["--root", str(self.root), "--audit-code", "UI", "--platform", "desktop", "--json"]))
        self.assertIn("HIG-MACOS-HOVER-EFFECT", stdout.getvalue())

    def test_new_audit_l10n_gate_has_positive_and_negative_results(self) -> None:
        self._write("Localizable.xcstrings", json.dumps({"strings": {"screen.title": {"localizations": {"en": {"stringUnit": {"value": "Hello"}}, "zh-Hans": {"stringUnit": {"value": "你好"}}}}}}))
        self._write("UI/View.swift", 'Text(localized: "screen.title")\n')
        self.assertEqual([], design_contract.audit_l10n(self.root, [], ["en", "zh-Hans"]))
        self._write("UI/View.swift", 'Text(localized: "missing.title")\n')
        self.assertIn("L10N-UNREGISTERED-KEY", {item.rule for item in design_contract.audit_l10n(self.root, [], ["en"])})

    def test_new_edge_clipping_gate_has_positive_and_negative_results(self) -> None:
        image = self._write_png("shots/clean.png", width=12, height=12)
        self.assertEqual([], design_contract.check_edge_clipping(image, "12", 1.0))
        self.assertIn("edge clipping path not found", design_contract.check_edge_clipping(self.root / "missing.png", None, 1.0)[0])

    def test_new_geometry_gate_has_positive_and_negative_results(self) -> None:
        good = self._write("good.json", json.dumps({"viewportWidth": 200, "children": [{"role": "button", "interactive": True, "frame": {"x": 0, "y": 0, "width": 44, "height": 44}}]}))
        self.assertEqual([], design_contract.audit_geometry(good, "mobile"))
        bad = self._write("bad.json", json.dumps({"viewportWidth": 100, "children": [{"numeric": True, "text": "12...", "interactive": True, "frame": {"x": 98, "y": 0, "width": 5, "height": 5}}]}))
        self.assertEqual({"GEOM_VIEWPORT_OVERFLOW", "GEOM_NUMERIC_TRUNCATION", "GEOM_HIT_TARGET_TOO_SMALL"}, set(design_contract.audit_geometry(bad, "mobile")))

    def test_audit_code_loads_cases_skips_sources_and_honors_allow_comments(self) -> None:
        self._write("UI/Bad.swift", "let value = Marker()\n")
        self._write("Tests/Bad.swift", "let value = Marker()\n")
        self._write("UI/Allowed.swift", "let value = Marker() // design-contract-allow: CASE-001\n")
        cases = self._write("cases.json", json.dumps({"rules": [{"id": "CASE-001", "title": "marker", "severity": "P1", "platforms": ["desktop"], "regex": r"Marker\(", "remediation": "remove marker"}]}))
        findings = design_contract.audit_code([self.root / "UI/Bad.swift", self.root / "Tests/Bad.swift", self.root / "UI/Allowed.swift"], "desktop", cases)
        self.assertEqual({"CASE-001"}, {item.rule for item in findings})
        self.assertTrue(findings[0].path.endswith("/UI/Bad.swift"))

    def test_audit_code_fails_closed_on_missing_or_invalid_cases_file(self) -> None:
        source = self._write("UI/Good.swift", "Text(\"ok\")\n")
        missing_findings = design_contract.audit_code([source], "desktop", self.root / "missing-cases.json")
        self.assertEqual(["INVALID_CASES_FILE"], [item.rule for item in missing_findings])
        broken = self._write("broken-cases.json", "{not-json")
        broken_findings = design_contract.audit_code([source], "desktop", broken)
        self.assertEqual(["INVALID_CASES_FILE"], [item.rule for item in broken_findings])
        bad_regex = self._write("bad-regex.json", json.dumps({"rules": [{"id": "CASE-BAD", "platforms": ["desktop"], "regex": "("}]}))
        regex_findings = design_contract.audit_code([source], "desktop", bad_regex)
        self.assertEqual(["INVALID_CASES_FILE"], [item.rule for item in regex_findings])

    def test_l10n_detects_raw_keys_only_in_ui_and_supports_localization_calls(self) -> None:
        self._write("Localizable.xcstrings", json.dumps({"strings": {"dashboard.metric.title": {"localizations": {"en": {"stringUnit": {"value": "dashboard.metric.title"}}}}}}))
        self._write("UI/View.swift", 'Text("dashboard.metric.title")\nString(localized: "dashboard.metric.title")\nNSLocalizedString("dashboard.metric.title", comment: "")\nFooL10n.format("dashboard.metric.title")\nlet arbitrary = "not.a.ui.key"\n')
        self._write("Tests/View.swift", 'Text("test.raw.key")\n')
        findings = design_contract.audit_l10n(self.root, [], ["en"])
        raw = [item for item in findings if item.rule == "L10N-RAW-KEY-LEAK"]
        self.assertEqual(2, len(raw))
        self.assertEqual(0, sum(item.rule == "L10N-UNREGISTERED-KEY" for item in findings))

    def test_l10n_requires_infoplist_locales_when_key_is_missing_or_incomplete(self) -> None:
        plist = self._write("Info.plist", "<plist><dict><key>CFBundleName</key><string>App</string></dict></plist>")
        self.assertIn("L10N-INFOPLIST-LOCALES", {item.rule for item in design_contract.audit_l10n(self.root, ["Info.plist"], ["en"])})
        plist.write_text("<key>CFBundleLocalizations</key><array><string>en</string></array>", encoding="utf-8")
        self.assertEqual([], design_contract.audit_l10n(self.root, ["Info.plist"], ["en"]))

    def test_geometry_matches_columns_by_index_and_aligns_only_bento_rows(self) -> None:
        geometry = self._write("geometry.json", json.dumps({"viewportWidth": 300, "children": [
            {"role": "tableHeader", "tableId": "t", "col": 0, "frame": {"x": 0, "y": 0, "width": 100, "height": 20}},
            {"role": "tableHeader", "tableId": "t", "col": 1, "frame": {"x": 100, "y": 0, "width": 100, "height": 20}},
            {"role": "tableRow", "tableId": "t", "col": 0, "frame": {"x": 0, "y": 30, "width": 100, "height": 20}},
            {"role": "tableRow", "tableId": "t", "col": 1, "frame": {"x": 100, "y": 30, "width": 100, "height": 20}},
            {"role": "tableHeader", "group": "other", "frame": {"x": 0, "y": 80, "width": 50, "height": 20}},
            {"role": "tableRow", "group": "other-row", "frame": {"x": 50, "y": 110, "width": 50, "height": 20}},
            {"role": "bento", "row": 1, "frame": {"x": 0, "y": 150, "width": 50, "height": 40}},
            {"role": "bento", "row": 1, "frame": {"x": 60, "y": 150, "width": 50, "height": 30}},
            {"role": "tableHeader", "group": "headers", "frame": {"x": 0, "y": 200, "width": 50, "height": 10}},
            {"role": "tableRow", "group": "headers", "frame": {"x": 0, "y": 220, "width": 50, "height": 10}},
        ]}))
        errors = set(design_contract.audit_geometry(geometry, "desktop"))
        self.assertEqual({"GEOM_BENTO_BOTTOM_MISALIGNED"}, errors)

    def test_edge_clipping_checks_filename_polarity(self) -> None:
        dark_light = self._write_png("shots/home_light.png")
        self.assertTrue(any("POLARITY_MISMATCH" in error for error in design_contract.check_edge_clipping(dark_light, None, 1.0)))
        normal = self._write_png("shots/home.png")
        self.assertNotIn("POLARITY_MISMATCH", design_contract.check_edge_clipping(normal, None, 1.0))

    def test_composable_gate_invocation_matches_tech_context_shape(self) -> None:
        self._write("UI/View.swift", "Text(\"ok\")\n")
        with captured_output() as (stdout, _):
            status = design_contract.main(["--root", str(self.root), "--audit-code", "UI", "--platform", "mobile", "--audit-l10n", str(self.root), "--json"])
        self.assertEqual(0, status)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])

    def test_jev_threshold_probability_boundaries_detect_defects(self) -> None:
        screenshot = self._write_png("screenshots/workout_populated_dark.png")
        response = {"answers": {
            "has_text_truncation": {"value": 1.0},
            "truncation_box": {"box": [1, 2, 3, 4]},
            "has_control_collision": 0.0,
            "has_unreadable_contrast": 0.0,
        }}
        for threshold in (0.0, 1.0):
            with self.subTest(threshold=threshold):
                self.assertEqual(threshold, design_contract._build_parser().parse_args(
                    ["--jev-threshold", str(threshold)]
                ).jev_threshold)
                with mock.patch.object(design_contract, "_jev_request", return_value=response):
                    violations, advisory = design_contract.scan_screenshots_with_jev(
                        self.root, [screenshot], "http://jev.test/v1/systemone",
                        jev_threshold=threshold,
                    )
                self.assertEqual([], advisory)
                self.assertIn("UI_TEXT_TRUNCATION_BOX", {item.rule for item in violations})


if __name__ == "__main__":
    unittest.main()
