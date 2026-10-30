"""Regression tests for the stdlib-only Apple shard planner."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "select" / "apple_shards.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_apple_shards", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
apple_shards = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apple_shards)


def _swift_fixture(count: int) -> str:
    methods = "\n".join(f"    func testGenerated{index}() {{}}" for index in range(count))
    return f"""import XCTest

final class GeneratedTests: XCTestCase {{
{methods}
    func testLiveSmoke() {{
        XCTSkipUnless(ProcessInfo.processInfo.environment["RUN_LIVE_SMOKE"] == "1")
    }}
}}
"""


class AppleShardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-apple-shards-")
        self.root = pathlib.Path(self.temp.name)
        self.ui = self.root / "AppUITests"
        self.ui.mkdir()
        (self.ui / "Generated.swift").write_text(_swift_fixture(30), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_discovery_is_ordered_and_excludes_opt_in_live_methods(self) -> None:
        (self.ui / "A.swift").write_text(
            """import XCTest
final class FirstTests: XCTestCase {
    func testFirst() {}
}
""",
            encoding="utf-8",
        )
        self.assertEqual(
            apple_shards.discover_xcuitests(self.root),
            [
                "AppUITests/FirstTests/testFirst",
                *[f"AppUITests/GeneratedTests/testGenerated{index}" for index in range(30)],
            ],
        )
        self.assertNotIn("AppUITests/GeneratedTests/testLiveSmoke", apple_shards.discover_xcuitests(self.root))

    def test_plan_balances_methods_and_puts_units_on_first_shard(self) -> None:
        plan = apple_shards.plan_apple_shards(self.root, max_per_shard=5)
        self.assertEqual(plan["shard_count_per_device"], 6)
        self.assertEqual(len(plan["shards"]), 12)
        for device in apple_shards.DEFAULT_DEVICES:
            device_shards = [shard for shard in plan["shards"] if shard["device"] == device]
            self.assertEqual(
                [len(shard["only_test_targets"].split(",")) - (6 if shard["shard_index"] == 0 else 0)
                 for shard in device_shards],
                [5, 5, 5, 5, 5, 5],
            )
            self.assertTrue(device_shards[0]["only_test_targets"].startswith("SearchTelemetryTests,"))
            self.assertEqual(device_shards[0]["shard_total"], 6)

        (self.ui / "Generated.swift").write_text(_swift_fixture(31), encoding="utf-8")
        self.assertEqual(
            apple_shards.plan_apple_shards(self.root, max_per_shard=5)["shard_count_per_device"],
            7,
        )

    def test_skip_all_and_skipping_every_target_emit_no_shards(self) -> None:
        self.assertEqual(
            apple_shards.plan_apple_shards(self.root, skip_all=True),
            {
                "skip_all_apple_tests": True,
                "max_per_shard": 5,
                "ui_tests": [],
                "shard_count_per_device": 0,
                "shards": [],
            },
        )
        skipped = apple_shards.plan_apple_shards(
            self.root,
            skip_targets=[*apple_shards.DEFAULT_UNIT_TARGETS, "AppUITests"],
        )
        self.assertTrue(skipped["skip_all_apple_tests"])
        self.assertEqual(skipped["shards"], [])

    def test_cli_writes_github_outputs(self) -> None:
        with tempfile.NamedTemporaryFile() as output:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(SCRIPT),
                    "--root",
                    str(self.root),
                    "--max-per-shard",
                    "5",
                    "--github-output",
                    output.name,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            lines = dict(line.split("=", 1) for line in output.read().decode().splitlines())
            self.assertEqual(lines["skip_all_apple_tests"], "0")
            self.assertEqual(json.loads(lines["shards_matrix"]), {"include": plan["shards"]})


if __name__ == "__main__":
    unittest.main()
