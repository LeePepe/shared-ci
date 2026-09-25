"""Index routes through the real audit CLI, without implicitly staging inputs."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from fixture import AGENTS, ContractRepo, PIN


class IndexRouteTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        self.guide = "docs/repository-guide.md"
        self.repo.write(self.guide, AGENTS)
        self.repo.write(".github/repo-contract.json", json.dumps({
            "schema": 1, "guide": self.guide, "shared_ci": PIN, "dependencies": {}}))
        self.repo.write(".github/CODEOWNERS", "/.github/ @owner\n/AGENTS.md @owner\n/" + self.guide + " @owner\n")
        self.index = f"# Document index\n\n- Before editing: [Guide]({self.guide})\n"
        self.repo.write("AGENTS.md", self.index)
        self.repo.add()

    def route(self, target):
        self.repo.write("AGENTS.md", self.index + f"- For details: [Reference]({target})\n")

    def audit(self, status, path=None):
        # ContractRepo.audit() calls add -A: that would erase the untracked case
        # and replace staged modes with worktree modes before the CLI sees them.
        result = self.repo.cli("audit")
        self.assertEqual(status, result.returncode, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(status == 0, summary["ok"])
        findings = [json.loads(line) for line in result.stderr.splitlines()]
        if status == 0:
            self.assertEqual([], findings)
        if path:
            self.assertTrue(any(f["kind"] == "contract_agents" and f["path"] == path
                                for f in findings), findings)
        return findings

    def test_valid_index(self):
        self.audit(0)

    def test_conventional_terminal_punctuation(self):
        for prefix, suffix in (("- Before editing: ", "."), ("* ", ";"), ("1. Read first: ", ".")):
            with self.subTest(prefix=prefix, suffix=suffix):
                self.repo.write("AGENTS.md", f"# Index\n{prefix}[Guide]({self.guide}){suffix}\n")
                self.audit(0)

    def test_trailing_instructions_are_still_rejected(self):
        self.repo.write("AGENTS.md", self.index.rstrip() + ". Run commands here.\n")
        self.audit(1, "AGENTS.md:3")

    def test_untracked_route_fails_until_explicitly_staged(self):
        self.repo.write("docs/local.md", "# Local\n")
        self.route("docs/local.md")
        self.assertNotIn("docs/local.md", self.repo.git("ls-files").stdout.splitlines())
        self.audit(1, "AGENTS.md:4")
        self.repo.git("add", "docs/local.md")
        self.audit(0)

    def test_ignored_local_route_is_not_admitted(self):
        self.repo.write(".gitignore", "docs/local.md\n")
        self.repo.write("docs/local.md", "# Local\n")
        self.route("docs/local.md")
        self.audit(1, "AGENTS.md:4")

    def test_tracked_executable_regular_document_is_allowed(self):
        self.repo.git("update-index", "--chmod=+x", self.guide)
        self.audit(0)

    def test_missing_and_directory_targets_fail(self):
        for target in ("docs/missing.md", "docs"):
            with self.subTest(target=target):
                self.route(target)
                self.audit(1, "AGENTS.md:4")

    def test_tracked_file_replaced_by_directory_fails(self):
        target = self.repo.root / self.guide
        target.unlink()
        target.mkdir()
        self.audit(1, ".github/repo-contract.json")

    def test_tracked_file_replaced_by_fifo_fails_without_reading(self):
        self.repo.write("docs/pipe.md", "# File\n")
        self.repo.git("add", "docs/pipe.md")
        target = self.repo.root / "docs/pipe.md"
        target.unlink()
        os.mkfifo(target)
        self.route("docs/pipe.md")
        self.audit(1, "AGENTS.md:4")

    def test_unmerged_index_entry_is_not_a_regular_route(self):
        blob = self.repo.git("rev-parse", ":" + self.guide).stdout.strip()
        # Index-info is data for Git, not a staged version of the working file.
        subprocess.run(["git", "update-index", "--index-info"], cwd=self.repo.root, env=self.repo.env,
                       input=f"0 {'0' * 40}\tdocs/conflict.md\n100644 {blob} 2\tdocs/conflict.md\n",
                       text=True, capture_output=True, check=True, timeout=20)
        self.repo.write("docs/conflict.md", "# Local resolution\n")
        self.route("docs/conflict.md")
        self.audit(1, "AGENTS.md:4")

    def test_staged_symlink_mode_is_not_a_regular_route(self):
        target = self.repo.root / "docs/alias.md"
        target.symlink_to("repository-guide.md")
        self.repo.git("add", "docs/alias.md")
        target.unlink()
        target.write_text("# Looks regular locally\n", encoding="utf-8")
        self.route("docs/alias.md")
        self.audit(1, "AGENTS.md:4")

    def test_worktree_symlink_and_loop_are_rejected(self):
        self.repo.write("docs/alias.md", "# Tracked\n")
        self.repo.git("add", "docs/alias.md")
        target = self.repo.root / "docs/alias.md"
        for destination in ("repository-guide.md", "alias.md"):
            with self.subTest(destination=destination):
                target.unlink()
                target.symlink_to(destination)
                self.route("docs/alias.md")
                self.audit(1, "AGENTS.md:4")

    def test_internal_ancestor_symlink_is_rejected(self):
        self.repo.write("docs/route/page.md", "# Tracked\n")
        self.repo.git("add", "docs/route/page.md")
        directory = self.repo.root / "docs/route"
        directory.rename(self.repo.root / "docs/moved")
        directory.symlink_to("moved", target_is_directory=True)
        self.route("docs/route/page.md")
        self.audit(1, "AGENTS.md:4")

    def test_external_ancestor_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="shared-ci-route-outside-") as outside:
            self.repo.write("docs/route/page.md", "# Tracked\n")
            self.repo.git("add", "docs/route/page.md")
            directory = self.repo.root / "docs/route"
            (directory / "page.md").unlink()
            directory.rmdir()
            (Path(outside) / "page.md").write_text("# Outside\n", encoding="utf-8")
            directory.symlink_to(outside, target_is_directory=True)
            self.route("docs/route/page.md#outside")
            self.audit(1, "AGENTS.md:4")

    def test_guide_ancestor_symlink_is_rejected_as_metadata(self):
        directory = self.repo.root / "docs"
        directory.rename(self.repo.root / "moved-docs")
        directory.symlink_to("moved-docs", target_is_directory=True)
        self.audit(1, ".github/repo-contract.json")

    def test_missing_heading_fragment_fails(self):
        self.route(self.guide + "#does-not-exist")
        self.audit(1, "AGENTS.md:4")

    def test_standard_heading_fragments(self):
        self.repo.write("docs/headings.md", """# Plain heading
## Verify: `scripts/verify` & **tests**! ##
### Café 中文
Setext heading
==============
## Repeat
## Repeat
## Repeat-1
## _Emphasis_ and [links](https://example.invalid)
## Code `<Node>` and `_identifier_`
""")
        self.repo.git("add", "docs/headings.md")
        for fragment in ("plain-heading", "verify-scriptsverify--tests", "caf%C3%A9-%E4%B8%AD%E6%96%87",
                         "setext-heading", "repeat", "repeat-1", "repeat-1-1", "emphasis-and-links",
                         "code-node-and-_identifier_"):
            with self.subTest(fragment=fragment):
                self.route("docs/headings.md#" + fragment)
                self.audit(0)

    def test_explicit_anchors_and_encoded_path(self):
        self.repo.write("docs/anchor page.md", '<a id="Exact-ID"></a>\n<a name=legacy></a>\n'
                        "<span id='with&amp;entity'></span>\n")
        self.repo.git("add", "docs/anchor page.md")
        for fragment in ("Exact-ID", "legacy", "with%26entity"):
            with self.subTest(fragment=fragment):
                self.route("docs/anchor%20page.md#" + fragment)
                self.audit(0)
        self.route("docs/anchor%20page.md#exact-id")
        self.audit(1, "AGENTS.md:4")

    def test_fragment_only_route_resolves_to_index(self):
        self.route("#document-index")
        self.audit(0)
        self.route("#missing")
        self.audit(1, "AGENTS.md:4")

    def test_code_and_comments_do_not_create_anchors(self):
        self.repo.write("docs/examples.md", """```markdown
# Fenced
<a id="fenced-anchor"></a>
```
~~~
Tilde fence
===========
~~~
    # Indented
    <a id="indented-anchor"></a>
`<a id="inline-code"></a>`
<!--
# Commented
<a id="comment-anchor"></a>
-->
""")
        self.repo.git("add", "docs/examples.md")
        for fragment in ("fenced", "fenced-anchor", "tilde-fence", "indented", "indented-anchor",
                         "inline-code", "commented", "comment-anchor"):
            with self.subTest(fragment=fragment):
                self.route("docs/examples.md#" + fragment)
                self.audit(1, "AGENTS.md:4")

    def test_non_markdown_fragment_cannot_pass_without_validation(self):
        self.route(".github/repo-contract.json#schema")
        self.audit(1, "AGENTS.md:4")

    def test_comment_syntax_in_code_does_not_hide_real_headings(self):
        self.repo.write("docs/code.md", "```html\n<!-- unfinished example\n```\n\n"
                        "## After example\n\n## Code `<!--`\n\n    <!-- indented example\n\n"
                        "## Still visible\n")
        self.repo.git("add", "docs/code.md")
        for fragment in ("after-example", "code---", "still-visible"):
            with self.subTest(fragment=fragment):
                self.route("docs/code.md#" + fragment)
                self.audit(0)

    def test_html_blocks_and_frontmatter_do_not_manufacture_headings(self):
        self.repo.write("docs/blocks.md", """---
title: Metadata
---
<div>
# Not Markdown
</div>

<!-- unfinished comment
# Also hidden
""")
        self.repo.git("add", "docs/blocks.md")
        for fragment in ("title-metadata", "--title-metadata", "not-markdown", "also-hidden"):
            with self.subTest(fragment=fragment):
                self.route("docs/blocks.md#" + fragment)
                self.audit(1, "AGENTS.md:4")

    def test_escaped_html_is_not_an_explicit_anchor(self):
        self.repo.write("docs/escaped.md", '\\<a id="not-an-anchor"></a>\n')
        self.repo.git("add", "docs/escaped.md")
        self.route("docs/escaped.md#not-an-anchor")
        self.audit(1, "AGENTS.md:4")

    def test_malformed_routes_fail_deterministically(self):
        for target in ("../outside.md", "docs/../AGENTS.md", "docs/%2e%2e/AGENTS.md", "/AGENTS.md",
                       "docs/missing%00.md", "docs/%FF.md", self.guide + "#%XX", self.guide + "#",
                       self.guide + "?query=1#verify", "docs\\repository-guide.md"):
            with self.subTest(target=target):
                self.route(target)
                first = self.audit(1, "AGENTS.md:4")
                self.assertEqual(first, self.audit(1, "AGENTS.md:4"))

    def test_untracked_metadata_does_not_fall_back_to_legacy(self):
        self.repo.write("AGENTS.md", AGENTS)
        self.repo.git("rm", "--cached", ".github/repo-contract.json")
        self.audit(1, ".github/repo-contract.json")

    def test_generic_git_filenames_do_not_relax_route_syntax(self):
        for name, encoded in (("tab\tname.md", "tab%09name.md"),
                              ("newline\nname.md", "newline%0Aname.md"),
                              ("back\\slash.md", "back%5Cslash.md")):
            with self.subTest(name=name):
                path = "docs/" + name
                self.repo.write(path, "# Document\n")
                self.repo.git("add", path)
                self.route("docs/" + encoded)
                self.audit(1, "AGENTS.md:4")

    def test_generic_git_filenames_do_not_relax_metadata_guide_syntax(self):
        metadata = json.loads((self.repo.root / ".github/repo-contract.json").read_text())
        for name in ("tab\tname.md", "newline\nname.md", "back\\slash.md"):
            with self.subTest(name=name):
                path = "docs/" + name
                self.repo.write(path, AGENTS)
                self.repo.git("add", path)
                metadata["guide"] = path
                self.repo.write(".github/repo-contract.json", json.dumps(metadata))
                self.audit(1, ".github/repo-contract.json")

    def test_dangling_metadata_symlink_does_not_fall_back_to_legacy(self):
        self.repo.write("AGENTS.md", AGENTS)
        self.repo.remove(".github/repo-contract.json")
        (self.repo.root / ".github/repo-contract.json").symlink_to("missing.json")
        self.audit(1, ".github/repo-contract.json")

    def test_metadata_and_guide_staged_symlinks_do_not_use_regular_local_files(self):
        for path in (".github/repo-contract.json", self.guide):
            with self.subTest(path=path):
                target = self.repo.root / path
                original = target.read_text(encoding="utf-8")
                target.unlink()
                target.symlink_to("missing")
                self.repo.git("add", path)
                target.unlink()
                target.write_text(original, encoding="utf-8")
                self.audit(1, ".github/repo-contract.json")
                self.repo.git("add", path)
                self.audit(0)

    def test_unsafe_lockfile_cannot_hide_dependency_pin_mismatch(self):
        metadata = json.loads((self.repo.root / ".github/repo-contract.json").read_text())
        metadata["dependencies"] = {"shared-telemetry": {
            "version": "1.2.0", "ai": "https://example.invalid/1.2.0/ai/"}}
        self.repo.write(".github/repo-contract.json", json.dumps(metadata))
        self.repo.write("docs/pins/package-lock.json", json.dumps({"packages": {
            "node_modules/shared-telemetry": {"version": "1.3.0"}}}))
        self.repo.git("add", "docs/pins/package-lock.json")
        self.assertTrue(any(f["kind"] == "contract_dependencies" for f in self.audit(1)))
        directory = self.repo.root / "docs/pins"
        directory.rename(self.repo.root / "docs/saved-pins")
        directory.symlink_to("saved-pins", target_is_directory=True)
        self.assertTrue(any(f["kind"] == "contract_dependencies" for f in self.audit(1)))


if __name__ == "__main__":
    unittest.main()
