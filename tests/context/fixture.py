"""Synthetic, child-environment-isolated fixtures (Python 3.9+, stdlib only).

Fixture shape adapted from LeePepe/AIDash at
30092ed0d09e2b6e7a4a9f49d7cd64627fbf898e, scripts/context/tests/test_context.py
(blob 414fc541bd912a25bb4b667ad2bffbc78ebc52fe). No product commands are reused.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from types import SimpleNamespace


REPO = pathlib.Path(__file__).resolve().parents[2]
MODULE = REPO / "scripts/context/_context.py"
SPEC = importlib.util.spec_from_file_location("layer_context", MODULE)
assert SPEC and SPEC.loader
layer_context = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = layer_context
SPEC.loader.exec_module(layer_context)
PYTHON = "/usr/bin/python3"


def isolated_environment(inherited=None):
    # Strip ALL Git inputs, including numbered config entries, future routing
    # flags and executable/template overrides. Never mutate the parent process.
    environment = {key: value for key, value in
                   (os.environ if inherited is None else inherited).items()
                   if not key.startswith(("GIT_", "PYTHON"))}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_ATTR_NOSYSTEM": "1",
        "PATH": "/usr/bin:/bin", "LC_ALL": "C",
    })
    return environment


class Fixture:
    def __init__(self, environment=None, *, nested=False, directory=None):
        self.temp = tempfile.TemporaryDirectory(prefix="shared-context-fixture-", dir=directory)
        self.root = pathlib.Path(self.temp.name).resolve()
        if nested:
            # Own the parent as well as the repo for traversal regressions.
            # Never place sentinels in a shared temp or real checkout parent.
            self.root = self.root / "repo"
            self.root.mkdir()
        self.environment = isolated_environment(environment)
        try:
            self.write("empty-template/.keep", "")
            self.git("init", "-q", "--template=" + str(self.root / "empty-template"))
        except BaseException:
            self.close()
            raise

    def close(self):
        # TemporaryDirectory removes only this instance's unique, owned root.
        self.temp.cleanup()

    def write(self, path, content="fixture\n"):
        target = self.root / path
        target.relative_to(self.root)
        if ".." in pathlib.Path(path).parts:
            raise ValueError("fixture write must remain inside its root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *arguments):
        return subprocess.run(
            ["/usr/bin/git", *arguments],
            cwd=self.root, env=self.environment, check=True, text=True,
            capture_output=True, timeout=10,
        )

    def cli(self, command, *arguments, input=None, wrapper=False):
        assert command in {"audit", "resolve", "layers", "field", "contexts", "run"}
        argv = ([str(REPO / "scripts/context" / command)] if wrapper else
                [PYTHON, "-I", "-B", str(MODULE), command])
        return subprocess.run(
            argv + list(arguments), cwd=self.root, env=self.environment,
            input=input, text=True, capture_output=True, timeout=10,
        )

    def context(self, path, data):
        self.write(path, "---\n" + json.dumps(data, indent=2) + "\n---\n\n# Synthetic context\n")

    def data(self, path="src/CONTEXT.md"):
        data = layer_context.parse_context(self.root, path)
        del data["_context_path"]
        return data

    def leaf(self, *, path="src/CONTEXT.md", layer="Source", parent="CONTEXT.md",
             scope=None, test_paths=None, dependencies=None, dependents=None,
             gates=None, manifest=None):
        data = {
            "schema": 1, "kind": "leaf", "layer": layer, "parent": parent,
            "scope": ["src/**"] if scope is None else scope,
            "dependencies": dependencies or [], "dependents": dependents or [],
            "red_lines": ["synthetic boundary"], "gates": gates or [],
        }
        if test_paths is not None:
            data["test_paths"] = test_paths
        if manifest is not None:
            data["manifest"] = manifest
        self.context(path, data)

    def root_index(self, routes=None, exclusions=None):
        self.context("CONTEXT.md", {
            "schema": 1, "kind": "index",
            "routes": ([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}]
                       if routes is None else routes),
            "exclusions": ([{"patterns": ["CONTEXT.md"], "reason": "routing metadata"}]
                           if exclusions is None else exclusions),
        })

    def audit(self):
        result = self.cli("audit")
        if result.returncode not in (0, 1):
            raise AssertionError(result.stderr)
        findings = [SimpleNamespace(**json.loads(line)) for line in result.stderr.splitlines()]
        return findings, json.loads(result.stdout)["classifications"]

    def findings(self):
        return self.audit()[0]

    def probe(self):
        # This is the normal gate payload used by real subprocess tests.
        # The traversal regression also owns a unique-parent sentinel.
        # It can print synthetic arguments, exit, or signal its own process only.
        self.write("src/probe.py", """import json
import os
import signal
import sys
if sys.argv[1] == "exit":
    raise SystemExit(int(sys.argv[2]))
if sys.argv[1] == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
print(json.dumps({"cwd": os.getcwd(), "args": sys.argv[2:]}))
""")
        return [PYTHON, "-I", "-B", "src/probe.py"]
