"""Shell entry points must not depend on pipe-backed here-documents."""
import re
import subprocess
import unittest

from fixture import ContractRepo, REPO, environment, run_bounded


HEREDOC = re.compile(r"(?<!<)<<(?!<)")
SHELL_SHEBANG = re.compile(r"^#![^\n]*\b(?:sh|bash)(?:\s|$)")


class ShellEntrypointTests(unittest.TestCase):
    def test_tracked_shell_scripts_have_no_heredocs(self):
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, env=environment(),
            capture_output=True, text=True, check=True, timeout=20)
        violations = []
        for name in tracked.stdout.split("\0"):
            if not name:
                continue
            source = (REPO / name).read_bytes().decode("utf-8", errors="replace")
            if not (name.endswith(".sh") or SHELL_SHEBANG.match(source)):
                continue
            for number, line in enumerate(source.splitlines(), 1):
                if HEREDOC.search(line):
                    violations.append(f"{name}:{number}")
        self.assertEqual([], violations,
                         "No here-documents in shell entry points: bash >=5.1 pipe "
                         "heredocs can deadlock on macOS above 512 bytes; use a "
                         "single-quoted Python program with python3 -I -B -c. "
                         + ", ".join(violations))

    def test_heredoc_guard_includes_tab_stripping_but_not_here_strings(self):
        for source in ("cat <<EOF", "cat <<-EOF", "cat 3<<'EOF'"):
            with self.subTest(source=source):
                self.assertIsNotNone(HEREDOC.search(source))
        self.assertIsNone(HEREDOC.search('cat <<< "$value"'))

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
