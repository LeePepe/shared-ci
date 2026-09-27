"""Disposable Git repositories must not leave automatic writers at teardown."""
import json
import pathlib
import subprocess
import tempfile
import unittest

from fixture import ContractRepo


class FixtureLifecycleTests(unittest.TestCase):
    def fetch_with_auto_gc_due(self, automatic):
        repo = ContractRepo()
        self.addCleanup(repo.close)
        repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid",
                 "commit", "-qm", "base")
        head = repo.git("rev-parse", "HEAD").stdout.strip()
        repo.git("remote", "add", "origin", str(repo.root))
        # Keep the negative control synchronous: the regression must not itself
        # leave a detached writer racing TemporaryDirectory.cleanup().
        repo.git("config", "gc.autoDetach", "false")
        repo.git("config", "maintenance.autoDetach", "false")
        if automatic:
            repo.git("config", "maintenance.auto", "true")
        repo.git("config", "gc.auto", "1")
        # gc samples bucket 17. This real loose blob exceeds gc.auto=1's
        # per-bucket threshold without thousands of objects or timing guesses.
        repo.write("src/core/probe.py", "maintenance probe 80\n")
        repo.git("add", "src/core/probe.py")
        blob = repo.git("rev-parse", ":src/core/probe.py").stdout.strip()
        self.assertTrue(blob.startswith("17"), blob)
        with tempfile.TemporaryDirectory(prefix="fixture-trace-") as temp:
            trace = pathlib.Path(temp) / "trace.json"
            env = dict(repo.env, GIT_TRACE2_EVENT=str(trace))
            # Call Git as a descendant would, not through ContractRepo.git:
            # production review scripts run this exact local fetch shape.
            subprocess.run(
                ["git", "fetch", "--no-tags", "--depth=200", "origin", head, head],
                cwd=repo.root, env=env, capture_output=True, text=True,
                check=True, timeout=20)
            children = [event["argv"] for event in
                        (json.loads(line) for line in trace.read_text().splitlines())
                        if event["event"] == "child_start"]
        loose_exists = (repo.root / ".git" / "objects" / blob[:2] / blob[2:]).exists()
        repo.close()
        self.assertFalse(repo.root.exists())
        return children, loose_exists

    def test_fixture_fetch_leaves_no_automatic_git_writer(self):
        children, loose_exists = self.fetch_with_auto_gc_due(automatic=False)
        self.assertFalse(any("maintenance" in args or "gc" in args for args in children), children)
        self.assertTrue(loose_exists, "automatic gc unexpectedly packed the probe")

    def test_control_really_runs_auto_gc_when_enabled(self):
        children, loose_exists = self.fetch_with_auto_gc_due(automatic=True)
        self.assertTrue(any("maintenance" in args and "--auto" in args for args in children), children)
        self.assertTrue(any("repack" in args for args in children), children)
        self.assertFalse(loose_exists, "control did not actually pack the probe")


if __name__ == "__main__":
    unittest.main()
