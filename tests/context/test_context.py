"""Unit tests for topological wave planning and parallel wave gate execution."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
import unittest
from unittest import mock

from fixture import Fixture, PYTHON, layer_context


class TopologicalWavesTests(unittest.TestCase):
    def test_independent_layers_group_into_single_wave_preserving_order(self) -> None:
        layers = {
            "Core": {"dependencies": []},
            "Policy": {"dependencies": []},
            "Schemas": {"dependencies": []},
        }
        waves = layer_context._topological_waves(layers, ["Schemas", "Core", "Policy"])
        self.assertEqual([["Schemas", "Core", "Policy"]], waves)

    def test_diamond_dependency_graph_partitions_into_waves(self) -> None:
        layers = {
            "Core": {"dependencies": []},
            "UI": {"dependencies": ["Core"]},
            "Data": {"dependencies": ["Core"]},
            "App": {"dependencies": ["UI", "Data"]},
        }
        # Even when input order puts dependents first, waves follow strict topological levels.
        waves = layer_context._topological_waves(layers, ["App", "UI", "Data", "Core"])
        self.assertEqual([["Core"], ["UI", "Data"], ["App"]], waves)

    def test_transitive_dependencies_respected_when_intermediate_layer_omitted(self) -> None:
        layers = {
            "Core": SimpleNamespace(dependencies=()),
            "Domain": SimpleNamespace(dependencies=("Core",)),
            "App": SimpleNamespace(dependencies=("Domain",)),
        }
        waves = layer_context._topological_waves(layers, ["App", "Core"])
        self.assertEqual([["Core"], ["App"]], waves)

    def test_empty_and_deduplicated_orders(self) -> None:
        layers = {"Core": {"dependencies": []}}
        self.assertEqual([], layer_context._topological_waves(layers, []))
        self.assertEqual([["Core"]], layer_context._topological_waves(layers, ["Core", "Core"]))

    def test_unknown_layer_and_dependency_cycle_fail_closed(self) -> None:
        layers = {
            "A": {"dependencies": ["B"]},
            "B": {"dependencies": ["A"]},
        }
        with self.assertRaises(layer_context.ContextError):
            layer_context._topological_waves(layers, ["Missing"])
        with self.assertRaises(layer_context.ContextError) as ctx:
            layer_context._topological_waves(layers, ["B", "A"])
        self.assertEqual("dependency cycle involving A, B", str(ctx.exception))


class ParallelWaveExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def _setup_diamond_repo(self, *, fail_layer: str | None = None) -> None:
        self.fixture.write(
            "src/wave_probe.py",
            """import json
import os
from pathlib import Path
import sys
import time

layer = sys.argv[1]
mode = sys.argv[2]
peer = sys.argv[3] if len(sys.argv) > 3 else ""
marker_dir = Path("markers")
marker_dir.mkdir(exist_ok=True)
(marker_dir / f"{layer}.started").write_text("1", encoding="utf-8")

if mode == "parallel_peer":
    deadline = time.monotonic() + 2.0
    peer_started = marker_dir / f"{peer}.started"
    while time.monotonic() < deadline and not peer_started.exists():
        time.sleep(0.02)
    overlapped = peer_started.exists()
    (marker_dir / f"{layer}.done").write_text("1", encoding="utf-8")
    print(json.dumps({"layer": layer, "overlapped": overlapped}))
elif mode == "require_done":
    required = [item for item in peer.split(",") if item]
    missing = [item for item in required if not (marker_dir / f"{item}.done").exists()]
    (marker_dir / f"{layer}.done").write_text("1", encoding="utf-8")
    print(json.dumps({"layer": layer, "missing_prereqs": missing}))
    if missing:
        raise SystemExit(9)
elif mode == "fail":
    print(json.dumps({"layer": layer, "failing": True}))
    raise SystemExit(5)
""",
        )
        self.fixture.root_index([
            {"patterns": ["core/**"], "context": "core/CONTEXT.md"},
            {"patterns": ["net/**"], "context": "net/CONTEXT.md"},
            {"patterns": ["app/**"], "context": "app/CONTEXT.md"},
        ])
        probe = [PYTHON, "-I", "-B", "src/wave_probe.py"]
        core_cmd = (
            probe + ["Core", "fail"]
            if fail_layer == "Core"
            else probe + ["Core", "parallel_peer", "Net"]
        )
        net_cmd = (
            probe + ["Net", "fail"]
            if fail_layer == "Net"
            else probe + ["Net", "parallel_peer", "Core"]
        )
        app_cmd = probe + ["App", "require_done", "Core,Net"]
        self.fixture.leaf(
            path="core/CONTEXT.md",
            layer="Core",
            scope=["core/**"],
            dependents=["App"],
            gates=[{"id": "test", "kind": "test", "mode": "both", "command": core_cmd}],
        )
        self.fixture.leaf(
            path="net/CONTEXT.md",
            layer="Net",
            scope=["net/**"],
            dependents=["App"],
            gates=[{"id": "test", "kind": "test", "mode": "both", "command": net_cmd}],
        )
        self.fixture.leaf(
            path="app/CONTEXT.md",
            layer="App",
            scope=["app/**"],
            dependencies=["Core", "Net"],
            gates=[{"id": "test", "kind": "test", "mode": "both", "command": app_cmd}],
        )

    def test_independent_layers_run_in_parallel_and_dependent_waits_for_next_wave(self) -> None:
        self._setup_diamond_repo()
        result = self.fixture.cli("run", "App", "Net", "Core", "--jobs", "2")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payloads = [
            json.loads(line)
            for line in result.stdout.splitlines()
            if line.startswith("{")
        ]
        # Wave 0 preserves input order (Net then Core), Wave 1 runs App after both complete.
        self.assertEqual(["Net", "Core", "App"], [item["layer"] for item in payloads])
        self.assertTrue(payloads[0]["overlapped"], payloads)
        self.assertTrue(payloads[1]["overlapped"], payloads)
        self.assertEqual([], payloads[2]["missing_prereqs"])

    def test_failing_layer_in_wave_fails_closed_before_later_waves(self) -> None:
        self._setup_diamond_repo(fail_layer="Core")
        result = self.fixture.cli("run", "Core", "Net", "App", "--jobs", "2")
        self.assertEqual(5, result.returncode, result.stdout + result.stderr)
        self.assertFalse((self.fixture.root / "markers/App.started").exists())
        self.assertNotIn("App:test", result.stdout)
        finding = json.loads(result.stderr.splitlines()[-1])
        self.assertEqual("Core", finding["layer"])
        self.assertEqual("gate_failed", finding["kind"])

    def test_invalid_jobs_and_env_var_fail_closed(self) -> None:
        self._setup_diamond_repo()
        result = self.fixture.cli("run", "Core", "--jobs", "0")
        self.assertEqual(2, result.returncode)
        self.assertEqual("context_error", json.loads(result.stderr)["kind"])
        with mock.patch.dict(os.environ, {"SHARED_CI_JOBS": "invalid"}):
            with self.assertRaises(layer_context.ContextError):
                layer_context._resolve_max_jobs(None)


if __name__ == "__main__":
    unittest.main()
