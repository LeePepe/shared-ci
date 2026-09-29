"""Audit shared-ci's actual consumer configuration, not synthetic adoption prose."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from fixture import ContractRepo, OTHER, REPO, environment


PROVIDER = "6e354f476bc53d68f0f09fc231d5cd938466af9c"
GUIDE = "docs/repository-guide.md"
METADATA = ".github/repo-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "self_adoption_yaml", REPO / "scripts/context/_frontmatter.py")
yaml = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(yaml)


class SelfAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        # Replace only this disposable fixture's synthetic files. Copy the
        # tracked candidate, including worktree edits, without its Git state.
        for path in self.repo.git("ls-files", "-z").stdout.split("\0"):
            if path:
                self.repo.remove(path)
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, env=self.repo.env,
            text=True, capture_output=True, check=True, timeout=20,
        ).stdout
        for path in tracked.split("\0"):
            if path:
                target = self.repo.root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / path, target)
        self.repo.add()

    def test_actual_repository_adopts_metadata_and_passes_native_audit(self):
        self.assertIn(METADATA, self.repo.git("ls-files").stdout.splitlines())
        metadata = json.loads((self.repo.root / METADATA).read_text(encoding="utf-8"))
        self.assertEqual({"schema": 1, "guide": GUIDE, "shared_ci": PROVIDER,
                          "dependencies": {}}, metadata)
        result = self.repo.cli("audit")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertEqual("", result.stderr)

    def assert_rejected(self, kind, detail):
        result = self.repo.cli("audit")
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])
        findings = [json.loads(line) for line in result.stderr.splitlines()]
        self.assertTrue(any(f["kind"] == kind and detail in f["detail"]
                            for f in findings), findings)

    def test_missing_guide_fails_native_audit(self):
        self.repo.remove(GUIDE)
        self.assert_rejected("contract_agents", "guide must name a tracked readable regular file")

    def test_untracked_guide_does_not_satisfy_adoption(self):
        self.repo.git("rm", "--cached", GUIDE)
        # Keep the local file: audit must use the real tracked-file boundary.
        self.assertTrue((self.repo.root / GUIDE).is_file())
        self.assert_rejected("contract_agents", "guide must name a tracked readable regular file")

    def test_nonlocal_guide_fails_without_legacy_fallback(self):
        metadata = json.loads((self.repo.root / METADATA).read_text(encoding="utf-8"))
        metadata["guide"] = "../outside.md"
        self.repo.write(METADATA, json.dumps(metadata))
        self.assert_rejected("contract_agents", "guide must be a repository-relative file path")

    def test_guide_missing_operational_section_fails(self):
        guide = (self.repo.root / GUIDE).read_text(encoding="utf-8")
        self.repo.write(GUIDE, guide.replace("## Verify\n", "## Removed verification\n"))
        self.assert_rejected("contract_agents", "guide is missing section '## Verify'")

    def test_task_route_must_reach_actual_guide_heading(self):
        guide = (self.repo.root / GUIDE).read_text(encoding="utf-8")
        self.repo.write(GUIDE, guide.replace("## PR work units\n", "## Renamed units\n"))
        self.assert_rejected("contract_agents", "route fragment does not resolve")

    def test_mixed_external_caller_pin_fails(self):
        for path in (".github/workflows/ci.yml", ".github/workflows/review.yml"):
            with self.subTest(path=path):
                original = (self.repo.root / path).read_text(encoding="utf-8")
                self.repo.write(path, original.replace(PROVIDER, OTHER, 1))
                self.assert_rejected("contract_ci", "mixed shared-ci pins")
                self.repo.write(path, original)

    def test_protocol_route_cannot_drift_from_selected_provider(self):
        index = (self.repo.root / "AGENTS.md").read_text(encoding="utf-8")
        self.repo.write("AGENTS.md", index.replace(PROVIDER, OTHER))
        self.assert_rejected("contract_agents", "versioned protocol route differs")

    def test_each_reviewer_requires_the_guide_input(self):
        path = ".github/workflows/review.yml"
        original = (self.repo.root / path).read_text(encoding="utf-8")
        for reviewer in ("codex", "kimi"):
            with self.subTest(reviewer=reviewer):
                call = f"    uses: LeePepe/shared-ci/.github/workflows/{reviewer}-review.yml@{PROVIDER}\n"
                start = original.index(call) + len(call)
                line = f"      rules-file: {GUIDE}\n"
                self.assertIn(line, original[start:])
                removed = original[start:].replace(line, "", 1)
                if removed.startswith("    with:\n") and not removed.startswith("    with:\n      "):
                    removed = removed[len("    with:\n"):]
                self.repo.write(path, original[:start] + removed)
                self.assert_rejected("contract_ci", "review rules-file")

    def test_index_is_not_review_rules(self):
        path = ".github/workflows/review.yml"
        text = (self.repo.root / path).read_text(encoding="utf-8")
        self.repo.write(path, text.replace("rules-file: " + GUIDE, "rules-file: AGENTS.md"))
        self.assert_rejected("contract_ci", "review rules-file")

    def test_later_ownerless_rule_cannot_remove_document_protection(self):
        path = ".github/CODEOWNERS"
        original = (self.repo.root / path).read_text(encoding="utf-8")
        for target in ("AGENTS.md", METADATA, GUIDE):
            with self.subTest(target=target):
                self.repo.write(path, original + "/" + target + "\n")
                self.assert_rejected("contract_ruleset", "unowned: " + target)

    def test_guide_requires_explicit_ownership(self):
        path = ".github/CODEOWNERS"
        lines = (self.repo.root / path).read_text(encoding="utf-8").splitlines()
        self.repo.write(path, "\n".join(line for line in lines
                                      if not line.startswith("/" + GUIDE + " ")) + "\n")
        self.assert_rejected("contract_ruleset", "CODEOWNERS does not cover /" + GUIDE)

    def test_existing_layer_and_support_routes_are_preserved(self):
        paths = ("scripts/context/_contract.py", "tests/repo/test_self_adoption.py",
                 "scripts/review/codex-review.sh", "scripts/lint/workflows.py",
                 GUIDE, METADATA, ".github/workflows/ci.yml")
        result = self.repo.cli("resolve", *paths)
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(["Context", "Context", "Review", "Lint", "", "", ""],
                         [row["layer"] for row in rows])
        self.assertEqual(["leaf"] * 4 + ["excluded"] * 3,
                         [row["classification"] for row in rows])

    def test_quality_caller_keeps_full_verification_and_local_candidates(self):
        ci = yaml.parse((self.repo.root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
        self.assertEqual({"contents": "read", "pull-requests": "read"}, ci["permissions"])
        self.assertEqual({
            "quality": {
                "uses": f"LeePepe/shared-ci/.github/workflows/quality.yml@{PROVIDER}",
                "with": {"runs-on": "ubuntu-latest", "verify-command": "scripts/verify --all",
                         "contract-audit": True, "workflow-lint": True}},
            "candidate": {
                "uses": "./.github/workflows/quality.yml",
                "with": {"runs-on": "ubuntu-latest", "changed-only": True,
                         "verify-command": "scripts/verify", "contract-audit": True,
                         "workflow-lint": True}},
            "candidate-select": {"uses": "./.github/workflows/select.yml"},
        }, ci["jobs"])

    def test_review_caller_preserves_enable_guard_and_privileges(self):
        review = yaml.parse((self.repo.root / ".github/workflows/review.yml").read_text(encoding="utf-8"))
        self.assertEqual({"contents": "read", "pull-requests": "write"}, review["permissions"])
        self.assertEqual({"pull_request_target": {
            "types": ["opened", "synchronize", "reopened"], "branches": ["main"]}}, review["on"])
        self.assertEqual({"codex-review-target", "codex-review-gate", "kimi-review"},
                         set(review["jobs"]))
        gate = review["jobs"]["codex-review-gate"]
        self.assertEqual("${{ always() }}", gate["if"])
        self.assertEqual(["codex-review-target"], gate["needs"])
        self.assertEqual({}, gate["permissions"])
        codex_inputs = {"codex-bin": "/opt/homebrew/bin/codex", "rules-file": GUIDE,
                        "owner-user-id": "13819054"}
        for job, reviewer, inputs in (("codex-review-target", "codex", codex_inputs),
                                      ("kimi-review", "kimi", {"rules-file": GUIDE})):
            with self.subTest(job=job):
                self.assertEqual({
                    "if": "vars.SHARED_CI_REVIEW_RUNNER == 'true'",
                    "uses": f"LeePepe/shared-ci/.github/workflows/{reviewer}-review.yml@{PROVIDER}",
                    "with": inputs,
                }, review["jobs"][job])


class SelectedProviderGuideTransportTests(unittest.TestCase):
    """Offline consumer proof for the published pin, not candidate review code."""

    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="self-adoption-provider-")
        cls.addClassCleanup(temporary.cleanup)
        cls.provider = Path(temporary.name)
        provider_env = dict(environment(), GIT_ALLOW_PROTOCOL="file",
                            GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
        # CI fetches full history. Missing pinned objects fail without fetching
        # or silently substituting this checkout's candidate review scripts.
        tracked = subprocess.run(
            ["git", "ls-tree", "-r", "-z", PROVIDER, "--", "scripts/review",
             "scripts/context", "schemas/repo-contract-v1.json", "ai/agent-protocol.md"],
            cwd=REPO, env=provider_env, capture_output=True, check=True, timeout=20,
        ).stdout
        for entry in tracked.split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, blob = metadata.split()
            if kind != b"blob" or mode not in (b"100644", b"100755"):
                raise AssertionError("Pinned reviewer assets must be regular blobs")
            target = cls.provider / path.decode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "cat-file", "blob", blob.decode("ascii")], cwd=REPO,
                env=provider_env, capture_output=True, check=True, timeout=20,
            )
            target.write_bytes(result.stdout)
            target.chmod(int(mode, 8))
        spec = importlib.util.spec_from_file_location(
            "self_adoption_review_fixtures", REPO / "tests/review/test_review.py")
        cls.fixtures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.fixtures)

    def review_guide(self, tool, guide, *, unavailable=False, base_has_guide=True):
        repo = ContractRepo()
        self.addCleanup(repo.close)
        if base_has_guide:
            (repo.root / GUIDE).parent.mkdir(parents=True, exist_ok=True)
            (repo.root / GUIDE).write_bytes(guide)
        repo.add()
        repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "base guide")
        base = repo.git("rev-parse", "HEAD").stdout.strip()
        repo.write(GUIDE, "# HEAD_ONLY_GUIDE\n\n$(touch head-guide-executed)\n")
        repo.write("scripts/verify", "#!/bin/sh\ntouch head-code-executed\n")
        repo.write("src/app/main.py", 'open("head-python-executed", "w").close()\n')
        repo.add()
        repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qam", "head data")
        head = repo.git("rev-parse", "HEAD").stdout.strip()
        repo.git("checkout", "-q", "--detach", base)
        repo.git("remote", "add", "origin", str(repo.root))
        # Neither staged nor unstaged rules may replace the immutable base blob.
        repo.write(GUIDE, "# INDEX_ONLY_GUIDE\n")
        repo.git("add", GUIDE)
        repo.write(GUIDE, "# WORKTREE_ONLY_GUIDE\n")

        temporary = tempfile.TemporaryDirectory(prefix="self-adoption-review-")
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name)
        tools = output / "tools"
        tools.mkdir()
        # Keep the model stubs; capture Kimi's prompt and prepend a neutral
        # event so the legacy verdict reader sees a multi-event JSON stream.
        kimi = self.fixtures.STUB_KIMI.replace(
            "#!/bin/sh\n", '#!/bin/sh\nfor arg in "$@"; do last="$arg"; done\n'
            'printf \'%s\' "$last" > "$STUB_OUT/prompt"\n'
            'printf \'%s\\n\' \'{"role":"user","content":"offline review"}\'\n', 1)
        for name, body in (("gh", self.fixtures.STUB_GH),
                           ("codex", self.fixtures.STUB_CODEX), ("kimi", kimi)):
            executable = tools / name
            executable.write_text(body, encoding="utf-8")
            executable.chmod(0o755)
        (tools / "python3").symlink_to(sys.executable)
        env = dict(repo.env, PATH=str(tools) + os.pathsep + os.defpath,
                   GIT_ALLOW_PROTOCOL="file", GH_TOKEN="", GITHUB_TOKEN="",
                   PR_NUMBER="7", BASE_SHA=base, HEAD_SHA=head, BASE_REPO="o/r",
                   SHARED_CI_DIR=str(self.provider), REVIEW_RULES_FILE=GUIDE,
                   REVIEW_MAX_BYTES="200000",
                   CODEX_BIN=str(tools / "codex"), KIMI_BIN=str(tools / "kimi"),
                   CODEX_LAUNCHER="", CODEX_REVIEW_HOME=str(output / "review-home"),
                   STUB_OUT=str(output), STUB_VERDICT=json.dumps(self.fixtures.PASS),
                   STUB_FAIL="", STUB_PUBLISH_FAIL="", STUB_COMMENT_ID="")
        result = subprocess.run(
            ["bash", str(self.provider / "scripts/review" / (tool + "-review.sh"))],
            cwd=repo.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(base, repo.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual(b"# WORKTREE_ONLY_GUIDE\n", (repo.root / GUIDE).read_bytes())
        self.assertEqual("# INDEX_ONLY_GUIDE\n", repo.git("show", ":" + GUIDE).stdout)
        for marker in ("head-guide-executed", "head-code-executed", "head-python-executed"):
            self.assertFalse((repo.root / marker).exists(), marker)
        comment = (output / "comment").read_text(encoding="utf-8")
        if unavailable:
            self.assertEqual(1 if tool == "codex" else 0, result.returncode,
                             result.stdout + result.stderr)
            self.assertIn("unavailable", comment)
            self.assertFalse((output / "prompt").exists(), "Invalid rules must stop before the model")
            self.assertIn("rules must contain 1..24000 bytes" if base_has_guide
                          else "rules file is missing from the trusted base", result.stderr)
            return None
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("review: pass", comment)
        prompt = (output / "prompt").read_bytes()
        trusted, boundary, untrusted = prompt.partition(b"======== UNTRUSTED DATA BELOW")
        self.assertTrue(boundary)
        rules = trusted.split(b"## Trusted repository rules\n\n", 1)[1].split(
            b"\n\n## Trusted architecture facts", 1)[0]
        self.assertNotIn(b"HEAD_ONLY_GUIDE", trusted)
        self.assertNotIn(b"INDEX_ONLY_GUIDE", prompt)
        self.assertNotIn(b"WORKTREE_ONLY_GUIDE", prompt)
        self.assertIn(b"HEAD_ONLY_GUIDE", untrusted)
        self.assertIn(b"$(touch head-guide-executed)", untrusted)
        self.assertIn(b"touch head-code-executed", untrusted)
        self.assertIn(b'open("head-python-executed", "w")', untrusted)
        self.assertIn(b"src/app/main.py -> App", trusted)
        return rules

    def test_selected_reviewers_receive_exact_immutable_base_guide(self):
        guide = (REPO / GUIDE).read_bytes()
        self.assertLessEqual(len(guide), 24000,
                             "Selected provider rejects rules above 24000 bytes")
        protocol = (self.provider / "ai/agent-protocol.md").read_bytes().replace(
            b"](repo-contract.md#repository-development-contract)",
            ("](https://github.com/LeePepe/shared-ci/blob/" + PROVIDER
             + "/ai/repo-contract.md#repository-development-contract)").encode())
        self.assertTrue(protocol in guide,
                        "Tool-free review requires the selected complete protocol snapshot")
        for tool in ("codex", "kimi"):
            for ending in (b"", b"\n\n"):
                with self.subTest(tool=tool, extra_newlines=len(ending)):
                    payload = guide + ending
                    self.assertLessEqual(len(payload), 24000)
                    rules = self.review_guide(tool, payload)
                    self.assertEqual(payload, rules)
                    for requirement in (b"`codex-review-gate`", b"non-skipped current-head evidence",
                                        b"Owner settings authorization", b"immutable `BASE_SHA`"):
                        self.assertIn(requirement, rules)

    def test_invalid_base_guide_stops_before_model_without_fallback(self):
        guide = (REPO / GUIDE).read_bytes()
        padding = b"x" * max(0, 24001 - len(guide))
        oversized = guide + padding + b"\nOVER_CAP_REVIEW_CRITICAL_TAIL\n"
        self.assertGreater(len(oversized), 24000)
        for tool in ("codex", "kimi"):
            for base_has_guide in (True, False):
                with self.subTest(tool=tool, base_has_guide=base_has_guide):
                    self.review_guide(tool, oversized, unavailable=True,
                                      base_has_guide=base_has_guide)


if __name__ == "__main__":
    unittest.main()
