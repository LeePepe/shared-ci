"""Disposable Git repositories must not leave automatic writers at teardown."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fixture import ContractRepo, run_bounded


class BoundedRunnerTests(unittest.TestCase):
    def test_capture_input_exit_status_and_check(self):
        args = [sys.executable, "-I", "-B", "-c",
                'import sys; print(sys.stdin.read()); print("error", file=sys.stderr); sys.exit(7)']
        result = run_bounded(args, input="hello", timeout=5)
        self.assertEqual((7, "hello\n", "error\n"),
                         (result.returncode, result.stdout, result.stderr))
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            run_bounded(args, input="hello", check=True, timeout=5)
        self.assertEqual((7, "hello\n", "error\n"),
                         (caught.exception.returncode, caught.exception.stdout, caught.exception.stderr))

    def test_timeout_kills_shell_and_descendant(self):
        self.assert_group_cleanup()

    def test_interruption_kills_shell_and_descendant(self):
        self.assert_group_cleanup(interrupt=True)

    def assert_group_cleanup(self, interrupt=False):
        communicate = subprocess.Popen.communicate
        pids = []
        drained = []

        def capture(process, *args, **kwargs):
            try:
                output = communicate(process, *args, **kwargs)
                drained.append(output[0])
                return output
            except subprocess.TimeoutExpired as error:
                pids.extend(int(pid) for pid in error.output.split())
                if interrupt:
                    raise KeyboardInterrupt("interrupted while waiting") from error
                raise

        # The descendant inherits captured pipes and outlives a direct-child kill.
        # A finite sleep keeps a broken regression from leaving permanent orphans.
        with patch.object(subprocess.Popen, "communicate", capture):
            with self.assertRaises(KeyboardInterrupt if interrupt else subprocess.TimeoutExpired):
                run_bounded(
                    ["bash", "-c", 'bash -c "sleep 5; echo survived" & '
                     'printf "%s %s\\n" "$$" "$!"; wait'], timeout=0.5)
        self.assertNotIn("survived", "".join(drained), "descendant survived the timeout")
        self.assertEqual(2, len(pids), "shell must start its descendant before timeout")
        deadline = time.monotonic() + 2
        for pid in pids:
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() >= deadline:
                    self.fail(f"runner left process {pid} alive after cleanup")
                time.sleep(0.01)


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
