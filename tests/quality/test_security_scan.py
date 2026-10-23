"""Unit and integration tests for scripts/quality/security_scan.py and .githooks/pre-commit."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "quality" / "security_scan.py"
TEMPLATE_PRECOMMIT = REPO / "templates" / "githooks" / "pre-commit"
ADOPTED_PRECOMMIT = REPO / ".githooks" / "pre-commit"

SPEC = importlib.util.spec_from_file_location("shared_ci_security_scan", SCRIPT)
assert SPEC and SPEC.loader
security_scan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = security_scan
SPEC.loader.exec_module(security_scan)


class SecurityScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-sec-scan-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.bins = self.root / "bins"
        self.bins.mkdir(parents=True, exist_ok=True)

    def _run_cli(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = security_scan.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def _git(self, *args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
        target = cwd or self.repo
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_")
        }
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["HOME"] = str(self.root)
        return subprocess.run(
            ["git", *args],
            cwd=target,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def _write_exec(self, name: str, content: str) -> pathlib.Path:
        path = self.bins / name
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def test_clean_worktree_passes(self) -> None:
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text("VALUE = 42\n", encoding="utf-8")
        code, stdout, stderr = self._run_cli(
            "--root",
            str(self.repo),
            "--gitleaks-bin",
            "nonexistent-gitleaks-bin",
            "--osv-bin",
            "nonexistent-osv-bin",
        )
        self.assertEqual(0, code, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("worktree", report["mode"])
        self.assertEqual("pass", report["scanners"]["identity"]["status"])
        self.assertEqual("skipped", report["scanners"]["gitleaks"]["status"])
        self.assertEqual("skipped", report["scanners"]["osv"]["status"])
        self.assertEqual([], report["findings"])

    def test_detects_forbidden_identity_and_secret_patterns(self) -> None:
        forbidden_samples = (
            ("credential profile directory", "dir = '" + "github" + "-identity'\n"),
            ("gh config override", "export " + "GH_" + "CONFIG_DIR=/opt/gh\n"),
            ("macOS home path", "path = '" + "/" + "Users" + "/alice/work'\n"),
            ("personal profile path", "cfg = '" + "profiles" + "/LeePepe'\n"),
            ("GitHub personal access token", "tok = 'ghp_" + ("A" * 38) + "'\n"),
            ("AWS access key ID", "aws = 'AKIA" + ("B" * 16) + "'\n"),
            ("API secret key token", "key = 'sk-proj-" + ("C" * 28) + "'\n"),
        )
        for expected_rule, line in forbidden_samples:
            with self.subTest(rule=expected_rule):
                (self.repo / "sample.txt").write_text(line, encoding="utf-8")
                code, stdout, _ = self._run_cli(
                    "--root",
                    str(self.repo),
                    "--gitleaks-bin",
                    "missing-gitleaks",
                    "--osv-bin",
                    "missing-osv",
                )
                self.assertEqual(1, code)
                report = json.loads(stdout)
                self.assertFalse(report["ok"])
                self.assertEqual("fail", report["scanners"]["identity"]["status"])
                rules = {item["rule"] for item in report["findings"]}
                self.assertIn(expected_rule, rules)

    def test_staged_mode_scans_only_staged_index_and_ignores_unstaged_edits(self) -> None:
        self._git("init", "-q")
        clean_file = self.repo / "clean.py"
        clean_file.write_text("X = 1\n", encoding="utf-8")
        self._git("add", "clean.py")
        # Write forbidden pattern only to unstaged worktree copy and untracked file.
        bad_home = "/" + "Users" + "/leak/path"
        clean_file.write_text(f"X = '{bad_home}'\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text(f"leak = '{bad_home}'\n", encoding="utf-8")

        code, stdout, stderr = self._run_cli(
            "--root",
            str(self.repo),
            "--staged",
            "--gitleaks-bin",
            "missing-gitleaks",
            "--osv-bin",
            "missing-osv",
        )
        self.assertEqual(0, code, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("staged", report["mode"])
        self.assertEqual([], report["findings"])

        # Now stage the forbidden modification and verify --staged fails closed.
        self._git("add", "clean.py")
        code2, stdout2, _ = self._run_cli(
            "--root",
            str(self.repo),
            "--staged",
            "--gitleaks-bin",
            "missing-gitleaks",
            "--osv-bin",
            "missing-osv",
        )
        self.assertEqual(1, code2)
        report2 = json.loads(stdout2)
        self.assertFalse(report2["ok"])
        self.assertEqual("clean.py", report2["findings"][0]["path"])

    def test_require_gitleaks_fails_closed_when_missing_and_parses_report(self) -> None:
        (self.repo / "app.py").write_text("X = 1\n", encoding="utf-8")
        code, stdout, _ = self._run_cli(
            "--root",
            str(self.repo),
            "--require-gitleaks",
            "--gitleaks-bin",
            "nonexistent-gitleaks-binary",
            "--osv-bin",
            "nonexistent-osv-binary",
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("missing", report["scanners"]["gitleaks"]["status"])
        self.assertEqual("scanner_missing", report["findings"][0]["kind"])

        stub_pass = self._write_exec(
            "gitleaks-pass",
            "#!/bin/sh\n"
            "prev=''\n"
            "for a in \"$@\"; do [ \"$prev\" = \"--report-path\" ] && printf '[]' > \"$a\"; prev=\"$a\"; done\n"
            "exit 0\n",
        )
        code_ok, stdout_ok, stderr_ok = self._run_cli(
            "--root",
            str(self.repo),
            "--require-gitleaks",
            "--gitleaks-bin",
            str(stub_pass),
            "--osv-bin",
            "nonexistent-osv-binary",
        )
        self.assertEqual(0, code_ok, stderr_ok)
        self.assertEqual("pass", json.loads(stdout_ok)["scanners"]["gitleaks"]["status"])

        stub_fail = self._write_exec(
            "gitleaks-fail",
            "#!/bin/sh\n"
            "prev=''\n"
            "for a in \"$@\"; do\n"
            "  if [ \"$prev\" = \"--report-path\" ]; then\n"
            "    printf '[{\"File\":\"app.py\",\"StartLine\":1,\"RuleID\":\"generic-api-key\",\"Description\":\"Generic API Key\"}]' > \"$a\"\n"
            "  fi\n"
            "  prev=\"$a\"\n"
            "done\n"
            "exit 1\n",
        )
        code_fail, stdout_fail, _ = self._run_cli(
            "--root",
            str(self.repo),
            "--require-gitleaks",
            "--gitleaks-bin",
            str(stub_fail),
            "--osv-bin",
            "nonexistent-osv-binary",
        )
        self.assertEqual(1, code_fail)
        fail_report = json.loads(stdout_fail)
        self.assertFalse(fail_report["ok"])
        self.assertEqual("fail", fail_report["scanners"]["gitleaks"]["status"])
        self.assertEqual("generic-api-key", fail_report["findings"][0]["rule"])

    def test_require_osv_fails_closed_when_missing_and_audits_discovered_lockfiles(self) -> None:
        for lock_name in (
            "Package.resolved",
            "package-lock.json",
            "pnpm-lock.yaml",
            "bun.lock",
            "bun.lockb",
            "Cargo.lock",
            "uv.lock",
            "poetry.lock",
            "requirements.txt",
            "go.sum",
        ):
            (self.repo / lock_name).write_text("{}\n", encoding="utf-8")

        code_missing, stdout_missing, _ = self._run_cli(
            "--root",
            str(self.repo),
            "--require-osv",
            "--gitleaks-bin",
            "nonexistent-gitleaks",
            "--osv-bin",
            "nonexistent-osv",
        )
        self.assertEqual(1, code_missing)
        missing_report = json.loads(stdout_missing)
        self.assertEqual("missing", missing_report["scanners"]["osv"]["status"])
        self.assertEqual(10, len(missing_report["scanners"]["osv"]["lockfiles"]))

        stub_osv_pass = self._write_exec(
            "osv-pass",
            "#!/bin/sh\nprintf '{\"results\":[]}'\nexit 0\n",
        )
        code_pass, stdout_pass, stderr_pass = self._run_cli(
            "--root",
            str(self.repo),
            "--require-osv",
            "--gitleaks-bin",
            "nonexistent-gitleaks",
            "--osv-bin",
            str(stub_osv_pass),
        )
        self.assertEqual(0, code_pass, stderr_pass)
        self.assertEqual("pass", json.loads(stdout_pass)["scanners"]["osv"]["status"])

        stub_osv_vuln = self._write_exec(
            "osv-vuln",
            "#!/bin/sh\n"
            "printf '{\"results\":[{\"source\":{\"path\":\"package-lock.json\"},"
            "\"packages\":[{\"vulnerabilities\":[{\"id\":\"GHSA-1234-5678-9012\","
            "\"summary\":\"Prototype pollution\"}]}]}]}'\n"
            "exit 1\n",
        )
        code_vuln, stdout_vuln, _ = self._run_cli(
            "--root",
            str(self.repo),
            "--require-osv",
            "--gitleaks-bin",
            "nonexistent-gitleaks",
            "--osv-bin",
            str(stub_osv_vuln),
        )
        self.assertEqual(1, code_vuln)
        vuln_report = json.loads(stdout_vuln)
        self.assertFalse(vuln_report["ok"])
        self.assertEqual("fail", vuln_report["scanners"]["osv"]["status"])
        self.assertEqual("GHSA-1234-5678-9012", vuln_report["findings"][0]["rule"])

    def test_rejects_symlinks_and_unsafe_config_paths_with_exit_2(self) -> None:
        (self.repo / "real.txt").write_text("ok\n", encoding="utf-8")
        symlink_root = self.root / "symlink-repo"
        symlink_root.symlink_to(self.repo)
        code_root, _, err_root = self._run_cli("--root", str(symlink_root))
        self.assertEqual(2, code_root)
        self.assertEqual("symlink_target", json.loads(err_root)["code"])

        for bad_cfg in ("../outside.toml", "/etc/passwd"):
            with self.subTest(bad_cfg=bad_cfg):
                code_cfg, _, err_cfg = self._run_cli(
                    "--root", str(self.repo), "--gitleaks-config", bad_cfg
                )
                self.assertEqual(2, code_cfg)
                self.assertEqual("unsafe_target", json.loads(err_cfg)["code"])

        (self.repo / "link.txt").symlink_to(self.repo / "real.txt")
        code_link, _, err_link = self._run_cli("--root", str(self.repo))
        self.assertEqual(2, code_link)
        self.assertEqual("symlink_target", json.loads(err_link)["code"])

    def test_precommit_hook_template_and_adopted_hook_snapshot_behavior(self) -> None:
        self.assertEqual(TEMPLATE_PRECOMMIT.read_bytes(), ADOPTED_PRECOMMIT.read_bytes())
        for hook in (TEMPLATE_PRECOMMIT, ADOPTED_PRECOMMIT):
            self.assertEqual(0o111, hook.stat().st_mode & 0o111)
            self.assertTrue(os.access(hook, os.X_OK))

        self._git("init", "-q")
        (self.repo / "clean.py").write_text("A = 1\n", encoding="utf-8")
        self._git("add", "clean.py")
        self._git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=1+test@users.noreply.github.com",
            "commit",
            "-qm",
            "init",
        )

        # Stage a clean modification while leaving an unstaged forbidden pattern in worktree.
        (self.repo / "clean.py").write_text("A = 2\n", encoding="utf-8")
        self._git("add", "clean.py")
        bad_home = "/" + "Users" + "/alice/secret"
        (self.repo / "clean.py").write_text(f"A = '{bad_home}'   \n", encoding="utf-8")

        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["SHARED_CI"] = str(REPO)
        pass_res = subprocess.run(
            ["bash", str(TEMPLATE_PRECOMMIT)],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(0, pass_res.returncode, pass_res.stdout + pass_res.stderr)

        # Staging the forbidden modification causes pre-commit to fail closed.
        (self.repo / "clean.py").write_text(f"A = '{bad_home}'\n", encoding="utf-8")
        self._git("add", "clean.py")
        fail_res = subprocess.run(
            ["bash", str(TEMPLATE_PRECOMMIT)],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(0, fail_res.returncode)


if __name__ == "__main__":
    unittest.main()
