"""Selected-provider repository audit transport regressions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

from fixture import REPO, environment, run_bounded


AUDIT_SELECTED = REPO / "scripts/context/audit-selected"
METADATA = ".github/repo-contract.json"
RUNTIME_CLOSURE = (
    "scripts/context/audit",
    "scripts/context/_context.py",
    "scripts/context/_techcontext.py",
    "scripts/context/_frontmatter.py",
    "scripts/context/_contract.py",
    "scripts/context/helper.py",
    "schemas/repo-contract-v1.json",
)


class SelectedProviderAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix=".selected-provider-", dir=REPO / "tests/repo")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = environment()
        self.real_git = shutil.which("git")
        self.git("init", "-q")
        self.git("config", "maintenance.auto", "false")
        self.write("scripts/context/audit", "#!/bin/sh\n# provider audit entry\nexit 0\n")
        self.write(
            "scripts/context/_context.py",
            """#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import stat

root = Path(__file__).resolve().parents[2]
paths = (
    "scripts/context/audit",
    "scripts/context/_context.py",
    "scripts/context/_techcontext.py",
    "scripts/context/_frontmatter.py",
    "scripts/context/_contract.py",
    "scripts/context/helper.py",
    "schemas/repo-contract-v1.json",
)
for path in paths[:-1]:
    if "provider" not in (root / path).read_text(encoding="utf-8"):
        raise SystemExit(91)
if json.loads((root / paths[-1]).read_text()) != {"identity": "provider"}:
    raise SystemExit(91)
evidence = {}
for path in paths:
    target = root / path
    content = target.read_bytes()
    digest = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\\0" + content).hexdigest()
    mode = "100755" if stat.S_IMODE(target.stat().st_mode) & 0o111 else "100644"
    evidence[path] = {"mode": mode, "blob": digest}
Path(os.environ["AUDIT_EVIDENCE"]).write_text(json.dumps(evidence), encoding="utf-8")
Path(os.environ["AUDIT_MARKER"]).write_text("provider", encoding="utf-8")
raise SystemExit(int(os.environ.get("AUDIT_STATUS", "0")))
""",
        )
        self.write("scripts/context/_techcontext.py", 'IDENTITY = "provider techcontext"\n')
        self.write("scripts/context/_frontmatter.py", 'IDENTITY = "provider frontmatter"\n')
        self.write("scripts/context/_contract.py", 'IDENTITY = "provider contract"\n')
        self.write("scripts/context/helper.py", 'IDENTITY = "provider helper"\n')
        self.write("schemas/repo-contract-v1.json", '{"identity":"provider"}\n')
        for path in ("scripts/context/audit", "scripts/context/_context.py"):
            (self.root / path).chmod(0o755)
        self.git("add", "-A")
        for path in ("scripts/context/audit", "scripts/context/_context.py"):
            self.git("update-index", "--chmod=+x", path)
        self.commit("provider")
        self.provider = self.git("rev-parse", "HEAD").stdout.strip()
        self.provider_evidence = self.selected_evidence(self.provider)

        self.write("AGENTS.md", self.legacy(self.provider))
        self.write(".gitignore", ".shared-ci/\n")
        self.write(METADATA, json.dumps({
            "schema": 1,
            "guide": "docs/repository-guide.md",
            "shared_ci": self.provider,
            "dependencies": {},
        }) + "\n")
        self.install_runtime("candidate")
        self.git("add", "-A")
        self.commit("consumer")
        self.install_runtime_decoy("legacy")
        self.install_runtime_decoy("cache-decoy", cache=True)
        evidence_directory = tempfile.TemporaryDirectory(
            prefix=".selected-provider-evidence-", dir=REPO / "tests/repo")
        self.addCleanup(evidence_directory.cleanup)
        self.evidence_root = Path(evidence_directory.name)
        self.marker = self.evidence_root / "audit-marker"
        self.evidence = self.evidence_root / "audit-evidence"
        self.network_marker = self.evidence_root / "network-attempt"
        self.archive_marker = self.evidence_root / "archive-attempt"
        self.install_command_guards()

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

    def install_runtime(self, identity):
        self.write("scripts/context/audit", f"#!/bin/sh\n# {identity} audit\nexit 92\n")
        self.write("scripts/context/_context.py", self.decoy(identity))
        for name in ("_techcontext.py", "_frontmatter.py", "_contract.py", "helper.py"):
            self.write(f"scripts/context/{name}", f'IDENTITY = "{identity} {name}"\n')
        self.write("schemas/repo-contract-v1.json", json.dumps({"identity": identity}) + "\n")

    def install_runtime_decoy(self, identity, *, cache=False):
        directory = ".shared-ci/scripts/context" if cache else f"runtime-decoys/{identity}"
        self.write(
            f"{directory}/_context.py",
            self.decoy(identity),
        )
        (self.root / directory / "_context.py").chmod(0o755)

    def selected_evidence(self, commit):
        result = self.git("ls-tree", "-r", commit, "--", *RUNTIME_CLOSURE)
        evidence = {}
        for row in result.stdout.splitlines():
            metadata, path = row.split("\t", 1)
            mode, kind, blob = metadata.split()
            self.assertEqual("blob", kind)
            evidence[path] = {"mode": mode, "blob": blob}
        self.assertEqual(set(RUNTIME_CLOSURE), set(evidence))
        return evidence

    def install_command_guards(self):
        tools = self.root / "tools"
        tools.mkdir()
        git_wrapper = tools / "git"
        git_wrapper.write_text(
            f"""#!/bin/sh
case "$1" in
fetch|clone|pull|remote|ls-remote|submodule)
  : > "$NETWORK_ATTEMPT_MARKER"
  exit 99
  ;;
archive)
  if [ -n "${{ARCHIVE_ATTEMPT_MARKER:-}}" ]; then
    printf invoked > "$ARCHIVE_ATTEMPT_MARKER"
  fi
  if [ "${{FAIL_ARCHIVE:-}}" = 1 ]; then
    exit 42
  fi
  ;;
esac
exec {self.real_git} "$@"
""",
            encoding="utf-8",
        )
        git_wrapper.chmod(0o755)
        for command in ("curl", "wget", "ssh", "scp", "nc"):
            wrapper = tools / command
            wrapper.write_text(
                '#!/bin/sh\n: > "$NETWORK_ATTEMPT_MARKER"\nexit 99\n',
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
        self.env.update({
            "PATH": str(tools) + os.pathsep + os.defpath,
            "NETWORK_ATTEMPT_MARKER": str(self.network_marker),
        })

    def repository_snapshot(self):
        index = self.git("write-tree").stdout.strip()
        status = self.git(
            "status", "--porcelain=v1", "-z", "--untracked-files=all",
        ).stdout
        staged = self.git("diff", "--cached", "--binary", "--no-ext-diff").stdout
        worktree = self.git("diff", "--binary", "--no-ext-diff").stdout
        tracked = {
            path for path in self.git("ls-files", "-z").stdout.split("\0") if path
        }
        untracked = []
        for directory, directories, filenames in os.walk(
                self.root, topdown=True, followlinks=False):
            relative_directory = Path(directory).relative_to(self.root)
            if relative_directory == Path("."):
                directories[:] = [name for name in directories if name != ".git"]
            entries = [(name, True) for name in directories]
            entries.extend((name, False) for name in filenames)
            for name, is_directory in entries:
                target = Path(directory) / name
                relative = target.relative_to(self.root).as_posix()
                if relative in tracked:
                    continue
                info = target.lstat()
                if stat.S_ISREG(info.st_mode):
                    kind = "file"
                    content = hashlib.sha256(target.read_bytes()).hexdigest()
                elif stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                    content = hashlib.sha256(
                        os.readlink(target).encode("utf-8", "surrogateescape"),
                    ).hexdigest()
                    if is_directory:
                        directories.remove(name)
                elif stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                    content = None
                else:
                    kind = "other"
                    content = None
                untracked.append(
                    (relative, kind, stat.S_IMODE(info.st_mode), content),
                )
        return index, status, staged, worktree, tuple(sorted(untracked))

    def assert_snapshot_tracks_untracked_identity(self):
        target = self.root / "untracked-identity-proof"
        target.write_bytes(b"original")
        target.chmod(0o600)
        baseline = self.repository_snapshot()
        mutations = (
            ("content", lambda: target.write_bytes(b"modified")),
            ("mode", lambda: target.chmod(0o700)),
            ("type", lambda: (target.unlink(), target.symlink_to("original"))),
        )
        for label, mutate in mutations:
            with self.subTest(untracked_identity=label):
                if target.is_symlink():
                    target.unlink()
                target.write_bytes(b"original")
                target.chmod(0o600)
                mutate()
                self.assertNotEqual(baseline, self.repository_snapshot())
        target.unlink()

    def persistent_artifacts(self):
        return sorted(
            str(path.relative_to(self.root))
            for path in self.root.rglob("*")
            if (path.name == "__pycache__"
                or path.suffix in (".pyc", ".pyo")
                or path.name.startswith(".audit-selected."))
        )

    def run_audit(self, *, env=None):
        selected_env = dict(
            self.env,
            AUDIT_MARKER=str(self.marker),
            AUDIT_EVIDENCE=str(self.evidence),
        )
        if env:
            selected_env.update(env)
        archive_attempt = selected_env.get("ARCHIVE_ATTEMPT_MARKER")
        if archive_attempt:
            Path(archive_attempt).write_text("", encoding="utf-8")
        before = self.repository_snapshot()
        artifacts_before = self.persistent_artifacts()
        result = run_bounded(
            [str(AUDIT_SELECTED)], cwd=self.root, env=selected_env, timeout=30)
        result.repository_before = before
        result.repository_after = self.repository_snapshot()
        result.artifacts_before = artifacts_before
        result.artifacts_after = self.persistent_artifacts()
        return result

    def replace_metadata(self, text):
        self.write(METADATA, text)

    def assert_closed(self, result):
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.evidence.exists())
        self.assertFalse(self.network_marker.exists())
        self.assertIn(
            ".shared-ci/scripts/context/_context.py",
            {identity[0] for identity in result.repository_before[-1]},
        )
        for identity in ("candidate", "index", "worktree", "legacy", "cache-decoy"):
            self.assertFalse((self.root / f"{identity}-runtime-executed").exists())
        self.assertEqual(result.repository_before, result.repository_after)
        self.assertEqual(result.artifacts_before, result.artifacts_after)

    def test_accepts_live_tracked_four_key_metadata_configuration(self):
        result = self.run_audit()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))

    def test_uses_exact_commit_runtime_and_schema_despite_worktree_and_index_decoys(self):
        self.install_runtime("index")
        self.git("add", "scripts/context", "schemas/repo-contract-v1.json")
        self.install_runtime("worktree")
        result = self.run_audit()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))
        self.assertEqual(
            self.provider_evidence,
            json.loads(self.evidence.read_text(encoding="utf-8")),
        )
        for identity in ("candidate", "index", "worktree", "legacy", "cache-decoy"):
            self.assertFalse((self.root / f"{identity}-runtime-executed").exists())

    def test_malformed_metadata_has_no_legacy_fallback(self):
        self.assert_snapshot_tracks_untracked_identity()
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

    def test_missing_or_untracked_metadata_has_no_legacy_fallback(self):
        content = (self.root / METADATA).read_text(encoding="utf-8")
        self.git("rm", "-q", METADATA)
        self.commit("remove metadata")
        self.assert_closed(self.run_audit())
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
        self.assert_closed(self.run_audit())

    def test_missing_provider_object_does_not_fetch_cache_or_fallback(self):
        missing = "f" * 40
        self.replace_metadata((self.root / METADATA).read_text().replace(self.provider, missing))
        self.assert_closed(self.run_audit())

    def test_archive_command_failure_fails_closed(self):
        result = self.run_audit(env={
            "ARCHIVE_ATTEMPT_MARKER": str(self.archive_marker),
            "FAIL_ARCHIVE": "1",
        })
        self.assert_closed(result)
        self.assertEqual("invoked", self.archive_marker.read_text(encoding="utf-8"))

    def test_incomplete_or_invalid_runtime_fails_before_archive_or_provider_execution(self):
        metadata = (self.root / METADATA).read_text()
        required = "scripts/context/_contract.py"
        cases = ("missing", "symlink")
        for case in cases:
            with self.subTest(required_asset=case):
                self.git("rm", "-q", required)
                if case == "symlink":
                    (self.root / required).symlink_to("_context.py")
                    self.git("add", required)
                self.commit(f"provider required runtime is {case}")
                invalid = self.git("rev-parse", "HEAD").stdout.strip()
                self.replace_metadata(metadata.replace(self.provider, invalid))
                result = self.run_audit(env={
                    "ARCHIVE_ATTEMPT_MARKER": str(self.archive_marker),
                })
                self.assert_closed(result)
                self.assertEqual("", self.archive_marker.read_text(encoding="utf-8"))
                if case != cases[-1]:
                    self.git("checkout", self.provider, "--", required)
                    self.commit("restore required runtime")

    def test_exact_nonzero_provider_status_is_propagated(self):
        result = self.run_audit(env={"AUDIT_STATUS": "73"})
        self.assertEqual(73, result.returncode, result.stdout + result.stderr)
        self.assertEqual("provider", self.marker.read_text(encoding="utf-8"))
        self.assertFalse(self.network_marker.exists())
        for identity in ("candidate", "index", "worktree", "legacy", "cache-decoy"):
            self.assertFalse((self.root / f"{identity}-runtime-executed").exists())
        self.assertEqual(result.repository_before, result.repository_after)
        self.assertEqual(result.artifacts_before, result.artifacts_after)


if __name__ == "__main__":
    unittest.main()
