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
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
        )
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


if __name__ == "__main__":
    unittest.main()
