"""Synthetic repo-kit repositories for contract/audit tests (stdlib only)."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
CONTEXT = REPO / "scripts" / "context" / "_context.py"
PIN = "1" * 40
OTHER = "2" * 40
PYTHON = sys.executable


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull, "LC_ALL": "C.UTF-8"})
    return env


AGENTS = f"""# AGENTS.md — Synthetic

Synthetic repository.

## Read first

1. docs/architecture/tech-context.md

## Protocol

Follow `LeePepe/shared-ci@{PIN}/ai/agent-protocol.md`.

## Verify

scripts/verify

## Required checks

- `quality / aggregate`
- `codex-review-target / codex-review`

## Red lines

- none beyond the protocol

## Dependencies

- `shared-ci` `{PIN}` — https://github.com/LeePepe/shared-ci/blob/{PIN}/ai/

## Delivery

One PR per task.
"""

ROOT_CONTEXT = """---
layer: _root
support:
  - patterns: ["*.md", "docs/**", ".github/**", ".githooks/**", "scripts/**"]
    reason: support files
---

# Synthetic

| Layer | Responsibility | tech-context | depends_on |
|---|---|---|---|
| Core | types | `src/core/tech-context.md` | (none) |
| App | wiring | `src/app/tech-context.md` | Core |
"""

CORE = """---
layer: Core
owns: [src/core/**]
depends_on: []
gate: {test: "python3 -c pass"}
red_lines: ["no imports of App"]
---
# Core
"""

APP = """---
layer: App
owns: [src/app/**]
depends_on: [Core]
gate:
  test: python3 -c pass
red_lines:
  - wiring only
---
# App
"""

CI = f"""name: ci
on:
  pull_request:
jobs:
  quality:
    uses: LeePepe/shared-ci/.github/workflows/quality.yml@{PIN}
    with:
      verify-command: scripts/verify --all
"""

PR_TEMPLATE = (REPO / "templates" / "pull_request_template.md").read_text(encoding="utf-8")
CODEOWNERS = "/.github/ @owner\n/AGENTS.md @owner\n"
HOOK = "#!/bin/sh\nexec scripts/verify\n"
VERIFY = "#!/bin/sh\necho ok\n"


class ContractRepo:
    """A git repo satisfying every contract item; tests then break one item."""

    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-contract-")
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = environment()
        self.git("init", "-q")
        files = {
            "AGENTS.md": AGENTS, "docs/architecture/tech-context.md": ROOT_CONTEXT,
            "src/core/tech-context.md": CORE, "src/core/model.py": "X = 1\n",
            "src/app/tech-context.md": APP, "src/app/main.py": "Y = 2\n",
            ".github/workflows/ci.yml": CI, ".github/pull_request_template.md": PR_TEMPLATE,
            ".github/CODEOWNERS": CODEOWNERS, ".githooks/pre-push": HOOK, "scripts/verify": VERIFY,
            "CLAUDE.md": "Read AGENTS.md first.\n",
        }
        for path, content in files.items():
            self.write(path, content)
        for path in (".githooks/pre-push", "scripts/verify"):
            (self.root / path).chmod(0o755)
        self.add()

    def close(self) -> None:
        self.temp.cleanup()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def remove(self, path: str) -> None:
        self.git("rm", "-q", "--cached", path)
        (self.root / path).unlink()

    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True, timeout=20)

    def add(self) -> None:
        self.git("add", "-A")
        # Preserve executable bits deterministically, independent of core.filemode.
        for path in (".githooks/pre-push", "scripts/verify"):
            if (self.root / path).exists() and os.access(self.root / path, os.X_OK):
                self.git("update-index", "--chmod=+x", path)

    def cli(self, command: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([PYTHON, "-I", "-B", str(CONTEXT), command, *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=30)

    def audit(self) -> tuple[int, list[dict], dict]:
        self.add()
        result = self.cli("audit")
        findings = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
        summary = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, findings, summary

    def kinds(self) -> set[str]:
        return {finding["kind"] for finding in self.audit()[1]}
