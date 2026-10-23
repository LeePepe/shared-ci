"""Unit and integration tests for scripts/quality/release_sync.py."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import http.server
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import typing
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "quality" / "release_sync.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_release_sync", SCRIPT)
assert SPEC and SPEC.loader
release_sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_sync
SPEC.loader.exec_module(release_sync)

SAMPLE_SHA = "a" * 40
OTHER_SHA = "b" * 40


class _LiveHandler(http.server.BaseHTTPRequestHandler):
    status_code: int = 200
    response_body: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: typing.Any) -> None:  # noqa: A002
        return


class ReleaseSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-release-sync-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()

    def _run_cli(self, *args: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = release_sync.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def _make_polyglot_repo(self, version: str = "1.2.3") -> pathlib.Path:
        repo = self.root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        (repo / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        (repo / "package.json").write_text(
            json.dumps({"name": "root-pkg", "version": version, "private": True}, indent=2) + "\n",
            encoding="utf-8",
        )
        pkg_web = repo / "packages" / "web"
        pkg_web.mkdir(parents=True, exist_ok=True)
        (pkg_web / "package.json").write_text(
            json.dumps({"name": "@scope/web", "version": version}, indent=2) + "\n",
            encoding="utf-8",
        )
        app_cli = repo / "apps" / "cli"
        app_cli.mkdir(parents=True, exist_ok=True)
        (app_cli / "package.json").write_text(
            json.dumps({"name": "@scope/cli", "version": version}, indent=2) + "\n",
            encoding="utf-8",
        )
        (repo / "Cargo.toml").write_text(
            f'[package]\nname = "demo"\nversion = "{version}"\nedition = "2021"\n\n'
            f'[dependencies]\nserde = {{ version = "1.0.197", features = ["derive"] }}\n',
            encoding="utf-8",
        )
        (repo / "project.yml").write_text(
            f"name: DemoApp\nsettings:\n  base:\n    MARKETING_VERSION: {version}\n",
            encoding="utf-8",
        )
        xcodeproj = repo / "DemoApp.xcodeproj"
        xcodeproj.mkdir(parents=True, exist_ok=True)
        (xcodeproj / "project.pbxproj").write_text(
            f"// !$*UTF8*$!\n{{\n\tbuildSettings = {{\n\t\tMARKETING_VERSION = {version};\n\t}};\n}}\n",
            encoding="utf-8",
        )
        return repo

    def test_version_sync_check_passes_when_all_targets_match(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        code, stdout, stderr = self._run_cli("version-sync", "--root", str(repo), "--check")
        self.assertEqual(0, code, stderr)
        report = json.loads(stdout)
        self.assertTrue(report["ok"])
        self.assertEqual("1.2.3", report["version"])
        self.assertEqual(0, report["drifted_count"])
        self.assertEqual([], report["findings"])
        discovered = {t["path"] for t in report["targets"]}
        self.assertEqual(
            {
                "VERSION",
                "package.json",
                "Cargo.toml",
                "project.yml",
                "DemoApp.xcodeproj/project.pbxproj",
                "packages/web/package.json",
                "apps/cli/package.json",
            },
            discovered,
        )

    def test_version_sync_check_detects_drift(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        (repo / "packages/web/package.json").write_text(
            json.dumps({"name": "@scope/web", "version": "1.2.2"}, indent=2) + "\n",
            encoding="utf-8",
        )
        code, stdout, _ = self._run_cli(
            "version-sync", "--root", str(repo), "--version", "1.2.3", "--check"
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual(1, report["drifted_count"])
        self.assertEqual(1, len(report["findings"]))
        self.assertEqual("version_mismatch", report["findings"][0]["kind"])
        self.assertEqual("packages/web/package.json", report["findings"][0]["path"])

    def test_version_sync_apply_and_semver_bumps_across_all_manifests(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        for bump_kind, expected in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")):
            with self.subTest(bump=bump_kind):
                code, stdout, stderr = self._run_cli(
                    "version-sync", "--root", str(repo), "--bump", bump_kind, "--apply"
                )
                self.assertEqual(0, code, stderr)
                report = json.loads(stdout)
                self.assertTrue(report["ok"])
                self.assertEqual(expected, report["version"])
                # Dependency version in Cargo.toml must remain untouched.
                cargo_text = (repo / "Cargo.toml").read_text(encoding="utf-8")
                self.assertIn(f'version = "{expected}"', cargo_text)
                self.assertIn('serde = { version = "1.0.197"', cargo_text)
                # Subsequent --check confirms 0 drift.
                chk_code, chk_out, _ = self._run_cli(
                    "version-sync", "--root", str(repo), "--version", expected, "--check"
                )
                self.assertEqual(0, chk_code, chk_out)

    def test_version_sync_stale_version_detection(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        (repo / "README.md").write_text("Install release v1.2.3 from GitHub.\n", encoding="utf-8")
        code, stdout, _ = self._run_cli(
            "version-sync",
            "--root",
            str(repo),
            "--version",
            "1.3.0",
            "--apply",
            "--check-stale",
            "README.md",
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertTrue(any(f["kind"] == "stale_version" and f["path"] == "README.md" for f in report["findings"]))

        # Updating README.md clears the stale version finding.
        (repo / "README.md").write_text("Install release v1.3.0 from GitHub.\n", encoding="utf-8")
        code2, stdout2, stderr2 = self._run_cli(
            "version-sync",
            "--root",
            str(repo),
            "--version",
            "1.3.0",
            "--check",
            "--previous-version",
            "1.2.3",
            "--check-stale",
            "README.md",
        )
        self.assertEqual(0, code2, stderr2)
        self.assertTrue(json.loads(stdout2)["ok"])

    def test_version_sync_atomic_apply_aborts_before_any_write_on_invalid_manifest(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        (repo / "packages/web/package.json").write_text("{malformed json", encoding="utf-8")
        code, stdout, stderr = self._run_cli(
            "version-sync", "--root", str(repo), "--version", "2.0.0", "--apply"
        )
        self.assertEqual(2, code)
        self.assertEqual("", stdout)
        self.assertFalse(json.loads(stderr)["ok"])
        # VERSION and root package.json must remain at 1.2.3 (atomic rollback/no partial writes).
        self.assertEqual("1.2.3\n", (repo / "VERSION").read_text(encoding="utf-8"))
        self.assertEqual(
            "1.2.3",
            json.loads((repo / "package.json").read_text(encoding="utf-8"))["version"],
        )

    def test_version_sync_atomic_apply_rolls_back_on_mid_batch_replace_failure(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        target_rels = release_sync.discover_version_targets(repo)
        originals = {rel: (repo / rel).read_bytes() for rel in target_rels}
        real_replace = os.replace
        call_count = 0

        def flaky_replace(src: os.PathLike[str] | str, dst: os.PathLike[str] | str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("simulated mid-batch os.replace failure")
            real_replace(src, dst)

        with mock.patch("os.replace", side_effect=flaky_replace):
            code, stdout, stderr = self._run_cli(
                "version-sync", "--root", str(repo), "--version", "2.0.0", "--apply"
            )

        self.assertEqual(2, code)
        self.assertEqual("", stdout)
        err_payload = json.loads(stderr)
        self.assertFalse(err_payload["ok"])
        self.assertEqual("write_failed", err_payload["code"])
        for rel, orig_bytes in originals.items():
            self.assertEqual(orig_bytes, (repo / rel).read_bytes(), f"{rel} was not rolled back")
        leftover_temps = list(repo.rglob("*.tmp-*")) + list(repo.rglob(".*.tmp-*"))
        self.assertEqual([], leftover_temps)

    def test_version_sync_atomic_apply_cleans_staged_temps_on_stage_failure(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        target_rels = release_sync.discover_version_targets(repo)
        originals = {rel: (repo / rel).read_bytes() for rel in target_rels}
        real_stage = release_sync._stage_sibling_temp
        stage_calls = 0

        def flaky_stage(target_path: pathlib.Path, payload: bytes, mode: int) -> pathlib.Path:
            nonlocal stage_calls
            stage_calls += 1
            if stage_calls == 2:
                raise OSError("simulated disk full during staging")
            return real_stage(target_path, payload, mode)

        with mock.patch.object(release_sync, "_stage_sibling_temp", side_effect=flaky_stage):
            code, stdout, stderr = self._run_cli(
                "version-sync", "--root", str(repo), "--version", "2.0.0", "--apply"
            )

        self.assertEqual(2, code)
        self.assertEqual("", stdout)
        err_payload = json.loads(stderr)
        self.assertFalse(err_payload["ok"])
        self.assertEqual("write_failed", err_payload["code"])
        for rel, orig_bytes in originals.items():
            self.assertEqual(orig_bytes, (repo / rel).read_bytes(), f"{rel} was modified")
        leftover_temps = list(repo.rglob("*.tmp-*")) + list(repo.rglob(".*.tmp-*"))
        self.assertEqual([], leftover_temps)

    def test_symlinked_ancestor_rejected_in_check_and_apply_without_external_writes(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        external = self.root / "external-pkg"
        external.mkdir(parents=True, exist_ok=True)
        sentinel = external / "package.json"
        sentinel.write_text(
            json.dumps({"name": "external", "version": "1.2.3"}, indent=2) + "\n",
            encoding="utf-8",
        )
        # Replace packages/web with a symlink to external-pkg.
        (repo / "packages/web/package.json").unlink()
        (repo / "packages/web").rmdir()
        (repo / "packages/web").symlink_to(external, target_is_directory=True)

        for mode_flag in ("--check", "--apply"):
            with self.subTest(mode=mode_flag):
                code, stdout, stderr = self._run_cli(
                    "version-sync", "--root", str(repo), "--version", "9.9.9", mode_flag
                )
                self.assertEqual(2, code)
                self.assertEqual("", stdout)
                err_payload = json.loads(stderr)
                self.assertFalse(err_payload["ok"])
                self.assertIn(err_payload["code"], ("symlink_target", "unsafe_target"))
                self.assertEqual(
                    "1.2.3",
                    json.loads(sentinel.read_text(encoding="utf-8"))["version"],
                )
                self.assertEqual("1.2.3\n", (repo / "VERSION").read_text(encoding="utf-8"))

    def test_readback_live_endpoint_pass_mismatch_and_http_error(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        server = http.server.HTTPServer(("127.0.0.1", 0), _LiveHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        live_url = f"http://127.0.0.1:{port}/api/live"

        # 1. Matching version and SHA -> exit 0
        _LiveHandler.status_code = 200
        _LiveHandler.response_body = json.dumps(
            {"version": "1.2.3", "sha": SAMPLE_SHA, "status": "ok"}
        ).encode("utf-8")
        code, stdout, stderr = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--expected-sha",
            SAMPLE_SHA,
            "--live-url",
            live_url,
        )
        self.assertEqual(0, code, stderr)
        self.assertTrue(json.loads(stdout)["ok"])

        # 2. Mismatched version -> exit 1
        _LiveHandler.response_body = json.dumps(
            {"version": "1.2.2", "sha": SAMPLE_SHA}
        ).encode("utf-8")
        code, stdout, _ = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--expected-sha",
            SAMPLE_SHA,
            "--live-url",
            live_url,
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("live_version_mismatch", report["findings"][0]["kind"])

        # 3. Mismatched SHA -> exit 1
        _LiveHandler.response_body = json.dumps(
            {"version": "1.2.3", "commit": OTHER_SHA}
        ).encode("utf-8")
        code, stdout, _ = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--expected-sha",
            SAMPLE_SHA,
            "--live-url",
            live_url,
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("live_sha_mismatch", report["findings"][0]["kind"])

        # 4. HTTP 500 failure -> exit 1
        _LiveHandler.status_code = 500
        _LiveHandler.response_body = b'{"error":"internal"}'
        code, stdout, _ = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--live-url",
            live_url,
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("live_http_error", report["findings"][0]["kind"])

        # 5. Disallowed URL scheme -> exit 2
        code, _, stderr = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--live-url",
            "file:///etc/passwd",
        )
        self.assertEqual(2, code)
        self.assertEqual("unsafe_target", json.loads(stderr)["code"])

    def test_readback_checksums_and_release_json_verification(self) -> None:
        repo = self._make_polyglot_repo("1.2.3")
        dist = repo / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        artifact = dist / "demo-1.2.3.tar.gz"
        payload = b"binary-release-artifact-content"
        artifact.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()

        checksums = repo / "SHA256SUMS"
        checksums.write_text(f"{digest}  dist/demo-1.2.3.tar.gz\n", encoding="utf-8")

        release_json = repo / "release.json"
        release_json.write_text(
            json.dumps(
                {
                    "tag_name": "v1.2.3",
                    "draft": False,
                    "assets": [
                        {"name": "demo-1.2.3.tar.gz", "size": len(payload), "state": "uploaded"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        # Pass case
        code, stdout, stderr = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--checksums-file",
            "SHA256SUMS",
            "--artifact",
            "dist/demo-1.2.3.tar.gz",
            "--release-json",
            "release.json",
        )
        self.assertEqual(0, code, stderr)
        self.assertTrue(json.loads(stdout)["ok"])

        # Tampered artifact -> checksum_mismatch (exit 1)
        artifact.write_bytes(b"tampered-bytes")
        code, stdout, _ = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--checksums-file",
            "SHA256SUMS",
            "--artifact",
            "dist/demo-1.2.3.tar.gz",
        )
        self.assertEqual(1, code)
        report = json.loads(stdout)
        self.assertFalse(report["ok"])
        self.assertEqual("checksum_mismatch", report["findings"][0]["kind"])

        # Restore artifact; test draft release & zero-size asset failure
        artifact.write_bytes(payload)
        release_json.write_text(
            json.dumps(
                {
                    "tag_name": "v1.2.2",
                    "draft": True,
                    "assets": [{"name": "demo-1.2.3.tar.gz", "size": 0}],
                }
            ),
            encoding="utf-8",
        )
        code, stdout, _ = self._run_cli(
            "readback",
            "--root",
            str(repo),
            "--expected-version",
            "1.2.3",
            "--release-json",
            "release.json",
        )
        self.assertEqual(1, code)
        kinds = {f["kind"] for f in json.loads(stdout)["findings"]}
        self.assertEqual({"release_tag_mismatch", "release_is_draft", "release_asset_empty"}, kinds)

    def test_reusable_release_workflow_and_template_docs_exist(self) -> None:
        workflow_path = REPO / ".github" / "workflows" / "release.yml"
        self.assertTrue(workflow_path.is_file())
        workflow_text = workflow_path.read_text(encoding="utf-8")
        self.assertNotIn("job.workflow_repository", workflow_text)
        self.assertNotIn("job.workflow_sha", workflow_text)
        dev_template = (REPO / "templates" / "development.md").read_text(encoding="utf-8")
        self.assertIn("## Release and live readback", dev_template)

        fm_spec = importlib.util.spec_from_file_location(
            "shared_ci_frontmatter", REPO / "scripts" / "context" / "_frontmatter.py"
        )
        assert fm_spec and fm_spec.loader
        fm = importlib.util.module_from_spec(fm_spec)
        fm_spec.loader.exec_module(fm)
        parsed = fm.parse(workflow_text)
        steps = parsed["jobs"]["release"]["steps"]
        provider_step = next(s for s in steps if s.get("id") == "provider")

        caller = self.root / "caller-repo"
        caller.mkdir(parents=True, exist_ok=True)
        (caller / ".github").mkdir(parents=True, exist_ok=True)
        (caller / ".github" / "repo-contract.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "guide": "docs/repository-guide.md",
                    "shared_ci": SAMPLE_SHA,
                    "dependencies": {},
                }
            ),
            encoding="utf-8",
        )
        git_env = {
            k: os.environ[k]
            for k in ("PATH", "HOME", "TMPDIR")
            if k in os.environ
        }
        git_env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
        )
        subprocess.run(["git", "init", "-q"], cwd=caller, env=git_env, check=True)
        subprocess.run(
            ["git", "add", ".github/repo-contract.json"],
            cwd=caller,
            env=git_env,
            check=True,
        )

        gh_out = self.root / "github_output.txt"
        run_env = dict(
            git_env,
            GITHUB_OUTPUT=str(gh_out),
            INPUT_REPOSITORY="LeePepe/shared-ci",
            INPUT_SHA="",
        )
        res = subprocess.run(
            ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", provider_step["run"]],
            cwd=caller,
            env=run_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertEqual(
            f"repository=LeePepe/shared-ci\nsha={SAMPLE_SHA}\n",
            gh_out.read_text(encoding="utf-8"),
        )

        # Mismatched INPUT_SHA vs .github/repo-contract.json must fail closed.
        gh_out.write_text("", encoding="utf-8")
        bad_env = dict(run_env, INPUT_SHA=OTHER_SHA)
        bad_res = subprocess.run(
            ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", provider_step["run"]],
            cwd=caller,
            env=bad_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, bad_res.returncode)
        self.assertIn("does not match repository contract pin", bad_res.stdout + bad_res.stderr)


if __name__ == "__main__":
    unittest.main()
