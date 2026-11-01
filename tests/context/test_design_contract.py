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
from typing import Iterator


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "context" / "design_contract.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_design_contract", SCRIPT)
assert SPEC and SPEC.loader
design_contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = design_contract
SPEC.loader.exec_module(design_contract)


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

    def test_visual_audit_checks_matrix_and_png_width(self) -> None:
        snapshots = self.root / "snapshots"
        snapshots.mkdir()
        png = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">IIBBBBB", 380, 100, 8, 6, 0, 0, 0)
        )
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


if __name__ == "__main__":
    unittest.main()
