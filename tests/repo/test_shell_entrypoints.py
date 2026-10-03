"""Runtime regression coverage for the macOS pipe-heredoc deadlock."""
import unittest

from fixture import ContractRepo, REPO, run_bounded


class ShellEntrypointTests(unittest.TestCase):
    def test_template_pin_extraction_completes_with_path_bash(self):
        repo = ContractRepo()
        self.addCleanup(repo.close)
        # A valid legacy pin reaches path validation without fetching a provider.
        # This executes the actual >512-byte pin program with whichever Bash is on PATH.
        result = run_bounded(
            ["bash", str(REPO / "templates/scripts/verify"), "--all"],
            cwd=repo.root, env=dict(repo.env, SHARED_CI=str(repo.root / "absent")), timeout=30)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("", result.stdout)
        self.assertEqual("[verify] supplied SHARED_CI must already exist at the declared pin\n",
                         result.stderr)


if __name__ == "__main__":
    unittest.main()
