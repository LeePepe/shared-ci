"""Actual reviewer wrappers must consume complete immutable base policy."""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from test_review import ContractRepo, PASS, REPO, REVIEW, STUB_CODEX, STUB_GH, render_prompt

KIMI = '''#!/bin/sh
prev=""
for a in "$@"; do [ "$prev" = "-p" ] && printf '%s' "$a" > "$STUB_OUT/prompt"; prev="$a"; done
printf '%s' "$STUB_VERDICT"
'''


class RulesInputTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        self.temp = tempfile.TemporaryDirectory(prefix="rules-input-")
        self.addCleanup(self.temp.cleanup)
        self.tools = pathlib.Path(self.temp.name)
        for name, body in (("gh", STUB_GH), ("codex", STUB_CODEX), ("kimi", KIMI)):
            path = self.tools / name
            path.write_text(body)
            path.chmod(0o755)
        self.provider = REPO

    def commit(self):
        self.repo.git("add", "-A")
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "fixture")
        return self.repo.git("rev-parse", "HEAD").stdout.strip()

    def revisions(self, path="docs/review rules.md", content=b"BASE POLICY\nEND POLICY\n\n", mode=None):
        target = self.repo.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            if mode == "symlink":
                target.symlink_to("../AGENTS.md")
            elif mode == "directory":
                target.mkdir()
                (target / "child").write_text("not a policy file")
            else:
                target.write_bytes(content)
        self.base = self.commit()
        self.repo.write("src/app/main.py", "Y = 3\n")
        self.head = self.commit()
        self.repo.git("checkout", "-q", "--detach", self.base)
        self.repo.git("remote", "add", "origin", str(self.repo.root))
        return target

    def run_wrapper(self, tool, path="docs/review rules.md"):
        for name in ("prompt", "comment"):
            (self.tools / name).unlink(missing_ok=True)
        env = dict(self.repo.env, PATH=f"{self.tools}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                   PR_NUMBER="7", BASE_SHA=self.base, HEAD_SHA=self.head, BASE_REPO="o/r",
                   SHARED_CI_DIR=str(self.provider), STUB_OUT=str(self.tools), STUB_VERDICT=json.dumps(PASS),
                   STUB_FAIL="", CODEX_REVIEW_HOME=str(self.tools / "home"))
        env.pop("REVIEW_RULES_FILE", None)
        if path is not None:
            env["REVIEW_RULES_FILE"] = path
        result = subprocess.run(["bash", str(REVIEW / (tool + "-review.sh"))], cwd=self.repo.root,
                                env=env, capture_output=True, text=True, timeout=30)
        comment = (self.tools / "comment").read_text() if (self.tools / "comment").exists() else ""
        prompt = (self.tools / "prompt").read_text() if (self.tools / "prompt").exists() else None
        return result, comment, prompt

    def rejected(self, path="docs/review rules.md"):
        for tool in ("codex", "kimi"):
            with self.subTest(tool=tool, path=path):
                result, comment, prompt = self.run_wrapper(tool, path)
                self.assertEqual(1 if tool == "codex" else 0, result.returncode, result.stderr)
                self.assertIn("unavailable", comment)
                self.assertIsNone(prompt, "model must not be invoked with invalid policy")

    def test_exact_base_bytes_ignore_worktree_and_head(self):
        target = self.revisions()
        self.repo.git("checkout", "-q", "--detach", self.head)
        target.write_text("HOSTILE HEAD RULES")
        self.head = self.commit()
        self.repo.git("checkout", "-q", "--detach", self.base)
        target.write_text("MUTABLE WORKTREE RULES")
        for tool in ("codex", "kimi"):
            result, comment, prompt = self.run_wrapper(tool)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("BASE POLICY\nEND POLICY\n\n", prompt)
            rules = prompt.split("## Trusted repository rules", 1)[1].split("## Trusted architecture", 1)[0]
            self.assertNotIn("HOSTILE HEAD RULES", rules)
            self.assertNotIn("MUTABLE WORKTREE RULES", rules)
        self.assertEqual(self.base, self.repo.git("rev-parse", "HEAD").stdout.strip())
        self.assertEqual("MUTABLE WORKTREE RULES", target.read_text())

    def test_missing_custom_never_falls_back_even_if_untracked_or_head_only(self):
        target = self.revisions(content=None)
        self.repo.git("checkout", "-q", "--detach", self.head)
        target.write_text("HEAD ONLY RULES")
        self.head = self.commit()
        self.repo.git("checkout", "-q", "--detach", self.base)
        target.write_text("UNTRACKED RULES")
        self.rejected()

    def test_default_agents_uses_base_not_mutable_worktree(self):
        self.revisions()
        expected = (self.repo.root / "AGENTS.md").read_text()
        (self.repo.root / "AGENTS.md").write_text("MUTABLE AGENTS")
        for tool in ("codex", "kimi"):
            result, _, prompt = self.run_wrapper(tool, None)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(expected, prompt)
            self.assertNotIn("MUTABLE AGENTS", prompt)

    def test_unsafe_paths(self):
        self.revisions()
        for path in ("/AGENTS.md", "../AGENTS.md", "docs/../AGENTS.md", "./AGENTS.md", "docs//review rules.md"):
            self.rejected(path)

    def test_symlink_and_directory(self):
        self.revisions(mode="symlink")
        self.rejected()
        self.rejected("docs")

    def test_invalid_and_oversized_payloads(self):
        self.revisions()
        for content in (b"", b" \n\t", b"bad\xff", b"bad\0text", b"bad\x01text", b"x" * 24001):
            self.repo.git("checkout", "-q", "--detach", self.base)
            (self.repo.root / "docs/review rules.md").write_bytes(content)
            self.base = self.commit()
            self.repo.write("src/app/main.py", "Y = 4\n")
            self.head = self.commit()
            self.repo.git("checkout", "-q", "--detach", self.base)
            self.rejected()

    def test_byte_limit_and_literal_special_filename(self):
        path = "docs/-rules [x]*.md"
        payload = ("é" * 11995 + "END POLICY").encode()
        self.assertEqual(24000, len(payload))
        self.revisions(path=path, content=payload)
        for tool in ("codex", "kimi"):
            result, _, prompt = self.run_wrapper(tool, path)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(payload.decode(), prompt)

    def test_no_diff_does_not_bypass_rules_admission(self):
        self.revisions(content=None)
        self.head = self.base
        self.rejected()

    def test_gitlink_and_symlink_ancestor_rejected(self):
        self.revisions()
        self.repo.git("checkout", "-q", "--detach", self.base)
        self.repo.git("update-index", "--add", "--cacheinfo", "160000," + self.base + ",submodule")
        self.repo.git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "gitlink")
        self.base = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.head = self.base
        self.rejected("submodule")
        self.rejected("submodule/AGENTS.md")
        (self.repo.root / "linked").symlink_to("docs")
        self.base = self.commit()
        self.head = self.base
        self.rejected("linked/review rules.md")

    def test_missing_default_and_noncommit_base_rejected(self):
        self.revisions()
        self.repo.git("checkout", "-q", "--detach", self.base)
        self.repo.git("rm", "AGENTS.md")
        self.base = self.commit()
        self.head = self.base
        self.rejected(None)
        self.base = self.repo.git("rev-parse", self.base + ":docs/review rules.md").stdout.strip()
        self.rejected()

    def test_git_replacement_cannot_change_selected_rules(self):
        self.revisions()
        self.repo.git("checkout", "-q", "--detach", self.head)
        (self.repo.root / "docs/review rules.md").write_text("REPLACEMENT POLICY")
        replacement = self.commit()
        self.repo.git("checkout", "-q", "--detach", self.base)
        original_blob = self.repo.git("rev-parse", self.base + ":docs/review rules.md").stdout.strip()
        replacement_blob = self.repo.git("rev-parse", replacement + ":docs/review rules.md").stdout.strip()
        self.repo.git("replace", original_blob, replacement_blob)
        for tool in ("codex", "kimi"):
            result, _, prompt = self.run_wrapper(tool)
            self.assertEqual(0, result.returncode, result.stderr)
            rules = prompt.split("## Trusted repository rules", 1)[1].split("## Trusted architecture", 1)[0]
            self.assertIn("BASE POLICY", rules)
            self.assertNotIn("REPLACEMENT POLICY", rules)

    def assert_provider_stays_clean(self, tool):
        self.revisions()
        self.provider = self.tools / "clean provider"
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(REPO), str(self.provider)],
                       env=self.repo.env, check=True, capture_output=True)
        # Include the current review implementation, even before an author commit.
        paths = subprocess.check_output(["git", "ls-files", "scripts/review"], cwd=REPO,
                                        env=self.repo.env, text=True).splitlines()
        for path in paths:
            shutil.copy2(REPO / path, self.provider / path)
        def provider_git(*args):
            return subprocess.check_output(["git", "-C", str(self.provider), *args],
                                           env=self.repo.env, text=True)
        provider_git("add", "scripts/review")
        provider_git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit",
                     "--allow-empty", "-qm", "review fixture")
        for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            self.repo.env.pop(key, None)
        before = self.repo.git("status", "--porcelain").stdout
        self.assertEqual("", provider_git("status", "--porcelain", "--ignored"))
        result, comment, prompt = self.run_wrapper(tool)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("unavailable", comment)
        self.assertIn("BASE POLICY\nEND POLICY\n\n", prompt)
        self.assertIn("src/app/main.py -> App", prompt)
        self.assertEqual("", provider_git("status", "--porcelain", "--ignored"))
        self.assertFalse(list(self.provider.rglob("__pycache__")))
        self.assertEqual(before, self.repo.git("status", "--porcelain").stdout)
        self.assertEqual(self.base, self.repo.git("rev-parse", "HEAD").stdout.strip())

    def test_codex_does_not_dirty_clean_provider(self):
        self.assert_provider_stays_clean("codex")

    def test_kimi_does_not_dirty_clean_provider(self):
        self.assert_provider_stays_clean("kimi")

    def test_rules_placeholder_required(self):
        template = (REVIEW / "review-prompt.md").read_text().replace("{{REPO_RULES}}", "")
        with self.assertRaises(ValueError):
            render_prompt.render(template, {})

    def test_wrappers_reject_missing_rules_placeholder(self):
        self.revisions()
        self.provider = self.tools / "provider"
        shutil.copytree(REVIEW, self.provider / "scripts/review")
        template = self.provider / "scripts/review/review-prompt.md"
        template.write_text(template.read_text().replace("{{REPO_RULES}}", ""))
        self.rejected()


if __name__ == "__main__":
    unittest.main()
