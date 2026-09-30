"""Run the actual pre-push hook against hermetic Git repos and a marker verify."""
import os
import pathlib
import subprocess
import tempfile
import unittest

from fixture import REPO, environment


HOOK = REPO / "templates/githooks/pre-push"
SHA = "1" * 40
ZERO = "0" * 40
URL = "https://example.invalid/repo.git"


class PrePushGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="prepush repo ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = environment()
        self.git("init", "-q")
        self.marker = self.root / "verify-ran"
        self.verify = self.root / "scripts/verify"
        self.verify.parent.mkdir()
        self.verify.write_text("#!/usr/bin/env bash\nprintf 'verified\\n' > verify-ran\n",
                               encoding="utf-8")
        self.verify.chmod(0o755)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, env=self.env,
                              check=True, capture_output=True, text=True, timeout=20)

    def update(self, remote_ref, local_sha=SHA, local_ref="refs/heads/topic", remote_sha=SHA):
        return f"{local_ref} {local_sha} {remote_ref} {remote_sha}\n"

    def hook(self, lines="", remote="origin", hook=HOOK):
        self.marker.unlink(missing_ok=True)
        args = [] if remote is None else [remote, URL]
        return subprocess.run(["bash", str(hook), *args], input=lines, cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=20)

    def assert_allowed(self, result):
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertEqual("verified\n", self.marker.read_text(encoding="utf-8"))

    def assert_refused(self, result, branch="main"):
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr.startswith(
            f"[pre-push] direct pushes to {branch} are not allowed; open a PR\n"), result.stderr)
        self.assertFalse(self.marker.exists())

    def test_main_is_refused_with_safe_remediation(self):
        result = self.hook(self.update("refs/heads/main"))
        self.assert_refused(result)
        for message in ("git switch -c <topic-branch>", "git push -u origin <topic-branch>",
                        "gh pr create --fill", "git reset --hard origin/main", "optionally",
                        "preserving those commits", "saving uncommitted work",
                        "reset --hard discards local changes"):
            with self.subTest(message=message):
                self.assertIn(message, result.stderr)

    def test_feature_is_allowed(self):
        self.assert_allowed(self.hook(self.update("refs/heads/feature/x")))

    def test_mixed_refs_are_refused_in_either_order(self):
        feature = self.update("refs/heads/feature/x")
        main = self.update("refs/heads/main")
        for lines in (feature + main, main + feature):
            with self.subTest(lines=lines):
                self.assert_refused(self.hook(lines))

    def test_main_deletion_is_allowed_for_both_hash_lengths(self):
        for length in (40, 64):
            with self.subTest(length=length):
                self.assert_allowed(self.hook(self.update(
                    "refs/heads/main", local_sha="0" * length,
                    local_ref="(delete)", remote_sha="1" * length)))

    def test_zero_prefixed_non_deletion_is_refused(self):
        self.assert_refused(self.hook(self.update("refs/heads/main", local_sha="0" * 39 + "1")))

    def test_new_main_branch_is_refused(self):
        self.assert_refused(self.hook(self.update("refs/heads/main", remote_sha=ZERO)))

    def test_dynamic_default_protects_trunk_and_main(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        for branch in ("trunk", "main"):
            with self.subTest(branch=branch):
                self.assert_refused(self.hook(self.update("refs/heads/" + branch)), branch)
        self.assert_allowed(self.hook(self.update("refs/heads/feature/x")))
        self.assert_allowed(self.hook(self.update("refs/heads/trunk", local_sha=ZERO)))

    def test_default_lookup_uses_the_named_remote_and_preserves_slashes(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.git("symbolic-ref", "refs/remotes/upstream/HEAD", "refs/remotes/upstream/release/stable")
        self.assert_refused(self.hook(self.update("refs/heads/release/stable"), remote="upstream"),
                            "release/stable")
        self.assert_refused(self.hook(self.update("refs/heads/main"), remote="upstream"))
        self.assert_allowed(self.hook(self.update("refs/heads/trunk"), remote="upstream"))

    def test_missing_remote_head_falls_back_to_main(self):
        self.assert_refused(self.hook(self.update("refs/heads/main")))
        self.assert_allowed(self.hook(self.update("refs/heads/trunk")))

    def test_url_or_empty_remote_falls_back_to_main(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        for remote in (URL, "git@example.invalid:repo.git", "", None):
            with self.subTest(remote=remote):
                self.assert_refused(self.hook(self.update("refs/heads/main"), remote=remote))
                self.assert_allowed(self.hook(self.update("refs/heads/trunk"), remote=remote))

    def test_remote_head_outside_its_namespace_falls_back_to_main(self):
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/upstream/trunk")
        self.assert_refused(self.hook(self.update("refs/heads/main")))
        self.assert_allowed(self.hook(self.update("refs/heads/trunk")))

    def test_only_destination_branch_refs_are_protected(self):
        for ref in ("refs/tags/main", "refs/heads/main/topic", "refs/heads/feature/x"):
            with self.subTest(ref=ref):
                self.assert_allowed(self.hook(self.update(ref, local_ref="refs/heads/main")))

    def test_main_deletion_does_not_hide_a_later_protected_update(self):
        self.assert_refused(self.hook(self.update("refs/heads/main", local_sha=ZERO)
                                     + self.update("refs/heads/main")))

    def test_empty_stdin_runs_verify_without_arguments(self):
        self.assert_allowed(self.hook(remote=None))

    def test_verify_failure_is_propagated(self):
        with self.verify.open("a", encoding="utf-8") as script:
            script.write("exit 23\n")
        result = self.hook(self.update("refs/heads/feature/x"))
        self.assertEqual(23, result.returncode, result.stdout + result.stderr)
        self.assertEqual("verified\n", self.marker.read_text(encoding="utf-8"))

    def test_template_and_self_adopted_hook_are_identical_and_executable(self):
        adopted = REPO / ".githooks/pre-push"
        self.assertEqual(HOOK.read_bytes(), adopted.read_bytes())
        for hook in (HOOK, adopted):
            with self.subTest(hook=hook):
                self.assertEqual(0o111, hook.stat().st_mode & 0o111)
                self.assertTrue(os.access(hook, os.X_OK))
                self.assert_refused(self.hook(self.update("refs/heads/main"), hook=hook))
                self.assert_allowed(self.hook(hook=hook))


if __name__ == "__main__":
    unittest.main()
