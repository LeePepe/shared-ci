"""Tests for the project design-contract audit and UI source gate."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
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


if __name__ == "__main__":
    unittest.main()
