"""Selected-provider repository audit transport regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fixture import REPO, environment, run_bounded


AUDIT_SELECTED = REPO / "scripts/context/audit-selected"
METADATA = ".github/repo-contract.json"


class SelectedProviderAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix=".selected-provider-", dir=REPO / "tests/repo")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = environment()
        self.git("init", "-q")
        self.git("config", "maintenance.auto", "false")
        self.write(
            "scripts/context/_context.py",
            """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
IDENTITY = (root / "scripts/context/helper.py").read_text().split('"')[1]
schema = json.loads((root / "schemas/repo-contract-v1.json").read_text())
if IDENTITY != "provider" or schema != {"identity": "provider"}:
    raise SystemExit(91)
marker = os.environ.get("AUDIT_MARKER")
if marker:
    Path(marker).write_text(IDENTITY, encoding="utf-8")
raise SystemExit(int(os.environ.get("AUDIT_STATUS", "0")))
""",
        )
        self.write("scripts/context/helper.py", 'IDENTITY = "provider"\n')
        self.write("schemas/repo-contract-v1.json", '{"identity":"provider"}\n')
        (self.root / "scripts/context/_context.py").chmod(0o755)
        self.git("add", "-A")
        self.git("update-index", "--chmod=+x", "scripts/context/_context.py")
        self.commit("provider")
        self.provider = self.git("rev-parse", "HEAD").stdout.strip()

        self.write("AGENTS.md", self.legacy(self.provider))
        self.write(METADATA, json.dumps({
            "schema": 1,
            "guide": "docs/repository-guide.md",
            "shared_ci": self.provider,
            "dependencies": {},
        }) + "\n")
        self.write("scripts/context/_context.py", self.decoy("candidate"))
        self.write("scripts/context/helper.py", 'IDENTITY = "candidate"\n')
        self.write("schemas/repo-contract-v1.json", '{"identity":"candidate"}\n')
        self.git("add", "-A")
        self.commit("consumer")
        self.marker = self.root / "audit-marker"

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def git(self, *args):
        return run_bounded(
            ["git", *args], cwd=self.root, env=self.env, check=True, timeout=20)

    def commit(self, message):
        self.git(
            "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", message)

    @staticmethod
    def legacy(pin):
        return (
            "# AGENTS.md\n\n"
            "Follow https://github.com/LeePepe/shared-ci/blob/"
            f"{pin}/ai/agent-protocol.md\n"
        )

    @staticmethod
    def decoy(identity):
        return (
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            f"Path({identity!r} + '-runtime-executed').write_text('bad')\n"
            "raise SystemExit(92)\n"
        )

    def run_audit(self, *, env=None):
        selected_env = dict(self.env, AUDIT_MARKER=str(self.marker))
        if env:
            selected_env.update(env)
        return run_bounded(
            [str(AUDIT_SELECTED)], cwd=self.root, env=selected_env, timeout=30)

    def replace_metadata(self, text):
        self.write(METADATA, text)

    def assert_closed(self, result):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / "legacy-runtime-executed").exists())
        self.assertFalse((self.root / ".shared-ci").exists())

    def install_git_wrapper(self, body):
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        wrapper = tools / "git"
        wrapper.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        wrapper.chmod(0o755)
        return str(tools) + os.pathsep + os.defpath

    def network_rejecting_git(self):
        real_git = shutil.which("git")
        return self.install_git_wrapper(
            f"""case "$1" in
fetch|clone)
  : > "$FORBIDDEN_GIT_MARKER"
  exit 99
  ;;
esac
exec {real_git} "$@"
""")

    def test_accepts_live_legacy_configuration(self):
        self.git("rm", "-q", METADATA)
        self.commit("legacy consumer")
        result = self.run_audit()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))

    def test_uses_exact_commit_runtime_and_schema_despite_worktree_and_index_decoys(self):
        self.write("scripts/context/_context.py", self.decoy("index"))
        self.write("scripts/context/helper.py", 'IDENTITY = "index"\n')
        self.write("schemas/repo-contract-v1.json", '{"identity":"index"}\n')
        self.git("add", "scripts/context", "schemas/repo-contract-v1.json")
        self.write("scripts/context/_context.py", self.decoy("worktree"))
        self.write("scripts/context/helper.py", 'IDENTITY = "worktree"\n')
        self.write("schemas/repo-contract-v1.json", '{"identity":"worktree"}\n')
        result = self.run_audit()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))
        for identity in ("candidate", "index", "worktree"):
            self.assertFalse((self.root / f"{identity}-runtime-executed").exists())

    def test_malformed_metadata_has_no_legacy_fallback(self):
        self.replace_metadata("{")
        self.assert_closed(self.run_audit())

    def test_duplicate_metadata_has_no_legacy_fallback(self):
        self.replace_metadata(
            '{"schema":1,"schema":1,"guide":"docs/repository-guide.md",'
            f'"shared_ci":"{self.provider}","dependencies":{{}}}}\n')
        self.assert_closed(self.run_audit())

    def test_non_object_metadata_has_no_legacy_fallback(self):
        self.replace_metadata("[]\n")
        self.assert_closed(self.run_audit())

    def test_untracked_metadata_has_no_legacy_fallback(self):
        content = (self.root / METADATA).read_text(encoding="utf-8")
        self.git("rm", "-q", METADATA)
        self.commit("remove metadata")
        self.write(METADATA, content)
        self.assert_closed(self.run_audit())

    def test_symlink_metadata_has_no_legacy_fallback(self):
        content = (self.root / METADATA).read_text(encoding="utf-8")
        self.git("rm", "-q", METADATA)
        self.write(".github/elsewhere.json", content)
        (self.root / METADATA).symlink_to("elsewhere.json")
        self.git("add", "-A")
        self.assert_closed(self.run_audit())

    def test_non_commit_provider_pin_does_not_fetch_cache_or_fallback(self):
        blob = self.git("hash-object", "AGENTS.md").stdout.strip()
        self.replace_metadata((self.root / METADATA).read_text().replace(self.provider, blob))
        forbidden = self.root / "forbidden-git"
        result = self.run_audit(env={
            "PATH": self.network_rejecting_git(),
            "FORBIDDEN_GIT_MARKER": str(forbidden),
        })
        self.assert_closed(result)
        self.assertFalse(forbidden.exists())

    def test_missing_provider_object_does_not_fetch_cache_or_fallback(self):
        missing = "f" * 40
        self.replace_metadata((self.root / METADATA).read_text().replace(self.provider, missing))
        forbidden = self.root / "forbidden-git"
        result = self.run_audit(env={
            "PATH": self.network_rejecting_git(),
            "FORBIDDEN_GIT_MARKER": str(forbidden),
        })
        self.assert_closed(result)
        self.assertFalse(forbidden.exists())

    def test_archive_command_failure_fails_closed(self):
        real_git = shutil.which("git")
        path = self.install_git_wrapper(
            f'if [ "$1" = archive ]; then exit 42; fi\nexec {real_git} "$@"\n')
        self.assert_closed(self.run_audit(env={"PATH": path}))

    def test_incomplete_or_invalid_runtime_materialization_fails_closed(self):
        real_git = shutil.which("git")
        path = self.install_git_wrapper(
            f"""if [ "$1" = archive ]; then
  exec {real_git} archive "$3" -- scripts/context/_context.py schemas/repo-contract-v1.json
fi
exec {real_git} "$@"
""")
        self.assert_closed(self.run_audit(env={"PATH": path}))

    def test_exact_nonzero_provider_status_is_propagated(self):
        result = self.run_audit(env={"AUDIT_STATUS": "73"})
        self.assertEqual(73, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
