"""Repository contract v1: one positive fixture and a failing fixture per item."""
import json
import unittest

from fixture import AGENTS, CI, ContractRepo, OTHER, PIN, REPO


class ContractPositiveTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)

    def test_compliant_repository_passes(self):
        status, findings, summary = self.repo.audit()
        self.assertEqual([], findings)
        self.assertEqual(0, status)
        self.assertTrue(summary["ok"])
        self.assertEqual(4, summary["classifications"]["leaf"])  # 2 sources + 2 leaf contexts

    def test_templates_are_self_consistent(self):
        # The published templates must themselves satisfy the section contract.
        contract = json.loads((REPO / "schemas/repo-contract-v1.json").read_text())["x-contract"]
        agents = (REPO / "templates/AGENTS.md").read_text()
        template = (REPO / "templates/pull_request_template.md").read_text()
        for title in contract["agents_sections"]:
            self.assertIn(f"## {title}", agents)
        for title in contract["pr_sections"]:
            self.assertIn(f"## {title}", template)
        self.assertLessEqual(len(agents.splitlines()), contract["agents_max_lines"])
        self.assertEqual(8, len(contract["items"]))


class ContractNegativeTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)

    def assertFinding(self, kind, fragment):
        findings = [f for f in self.repo.audit()[1] if f["kind"] == kind]
        self.assertTrue(any(fragment in f["detail"] for f in findings),
                        f"{kind}/{fragment!r} not in {findings}")
        self.assertTrue(all(f["layer"] == "contract" for f in findings))

    # 1 agents
    def test_agents_missing(self):
        self.repo.remove("AGENTS.md")
        self.assertFinding("contract_agents", "missing")

    def test_agents_too_long(self):
        text = (self.repo.root / "AGENTS.md").read_text()
        self.repo.write("AGENTS.md", text + "filler\n" * 150)
        self.assertFinding("contract_agents", "exceeds 150")

    def test_agents_pointer_missing(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace(f"LeePepe/shared-ci@{PIN}/ai/agent-protocol.md", "the protocol")
        self.repo.write("AGENTS.md", text)
        self.assertFinding("contract_agents", "missing protocol pointer")

    def test_agents_pointer_not_full_sha(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace(f"shared-ci@{PIN}/ai", "shared-ci@v1/ai")
        self.repo.write("AGENTS.md", text)
        self.assertFinding("contract_agents", "not a full 40-char SHA")

    def test_agents_pointer_differs_from_caller_pin(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace(f"shared-ci@{PIN}/ai", f"shared-ci@{OTHER}/ai")
        self.repo.write("AGENTS.md", text)
        self.assertFinding("contract_agents", "differs from workflow pins")

    def test_agents_section_missing(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace("## Red lines", "## Rules")
        self.repo.write("AGENTS.md", text)
        self.assertFinding("contract_agents", "'## Red lines'")

    # 2 agent_files
    def test_claude_md_must_defer_to_agents(self):
        self.repo.write("CLAUDE.md", "Claude rules live here.\n")
        self.assertFinding("contract_agent_files", "must defer to AGENTS.md")

    def test_claude_md_duplicates_required_checks(self):
        self.repo.write("CLAUDE.md", "Read AGENTS.md first.\nRequired: `quality / aggregate`\n")
        self.assertFinding("contract_agent_files", "duplicates required check")

    def test_claude_md_duplicates_pin(self):
        self.repo.write("CLAUDE.md", f"Read AGENTS.md first.\nLeePepe/shared-ci@{PIN}/ai/agent-protocol.md\n")
        self.assertFinding("contract_agent_files", "duplicates the shared-ci pin")

    # 3 ci
    def test_ci_missing(self):
        self.repo.remove(".github/workflows/ci.yml")
        self.assertFinding("contract_ci", "caller workflow is missing")

    def test_ci_tag_ref(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace(PIN, "v1"))
        self.assertFinding("contract_ci", "not pinned to a full 40-char SHA")

    def test_ci_branch_ref(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace(PIN, "main"))
        self.assertFinding("contract_ci", "not pinned to a full 40-char SHA")

    def test_ci_short_sha(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace(PIN, PIN[:12]))
        self.assertFinding("contract_ci", "not pinned to a full 40-char SHA")

    def test_ci_does_not_call_quality(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace("quality.yml", "other.yml"))
        self.assertFinding("contract_ci", "does not call")

    def test_ci_job_name_unstable(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace("  quality:\n", "  gate:\n"))
        self.assertFinding("contract_ci", "quality / aggregate")

    def test_ci_mixed_pins(self):
        self.repo.write(".github/workflows/review.yml",
                        f"on: pull_request_target\njobs:\n  r:\n    uses: LeePepe/shared-ci/.github/workflows/codex-review.yml@{OTHER}\n")
        self.assertFinding("contract_ci", "mixed shared-ci pins")

    # 4 verify
    def test_verify_missing(self):
        self.repo.remove("scripts/verify")
        self.assertFinding("contract_verify", "tracked and executable")

    def test_verify_not_executable(self):
        self.repo.git("update-index", "--chmod=-x", "scripts/verify")
        (self.repo.root / "scripts/verify").chmod(0o644)
        self.assertFinding("contract_verify", "tracked and executable")

    def test_hook_missing(self):
        self.repo.remove(".githooks/pre-push")
        self.assertFinding("contract_verify", "no .githooks")

    def test_hook_does_not_call_verify(self):
        self.repo.write(".githooks/pre-push", "#!/bin/sh\nswift test\n")
        self.assertFinding("contract_verify", "hooks do not invoke scripts/verify")

    def test_ci_does_not_call_verify(self):
        self.repo.write(".github/workflows/ci.yml", CI.replace("scripts/verify --all", "make test"))
        self.assertFinding("contract_verify", "CI does not invoke scripts/verify")

    # 5 ruleset (tree-visible part)
    def test_codeowners_missing(self):
        self.repo.remove(".github/CODEOWNERS")
        self.assertFinding("contract_ruleset", "CODEOWNERS is missing")

    def test_codeowners_incomplete(self):
        self.repo.write(".github/CODEOWNERS", "/.github/ @owner\n")
        self.assertFinding("contract_ruleset", "/AGENTS.md")

    # 6 pr_template
    def test_pr_template_missing(self):
        self.repo.remove(".github/pull_request_template.md")
        self.assertFinding("contract_pr_template", "PR template is missing")

    def test_pr_template_section_missing(self):
        text = (self.repo.root / ".github/pull_request_template.md").read_text()
        self.repo.write(".github/pull_request_template.md", text.replace("## Compatibility", "## Notes"))
        self.assertFinding("contract_pr_template", "Compatibility")

    # 7 dependencies
    def test_dependency_without_ai_pointer(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace(
            f" — https://github.com/LeePepe/shared-ci/blob/{PIN}/ai/", "")
        self.repo.write("AGENTS.md", text)
        self.assertFinding("contract_dependencies", "ai/ docs")

    def test_lockfile_pin_differs_from_declaration(self):
        text = (self.repo.root / "AGENTS.md").read_text().replace(
            "## Delivery", "- `shared-telemetry` `1.2.0` — https://example.invalid/1.2.0/ai/\n\n## Delivery")
        self.repo.write("AGENTS.md", text)
        self.repo.write("Package.resolved", json.dumps({"pins": [
            {"identity": "shared-telemetry", "state": {"version": "1.3.0", "revision": "a" * 40}}]}))
        self.repo.write("docs/architecture/tech-context.md",
                        (self.repo.root / "docs/architecture/tech-context.md").read_text()
                        .replace('"scripts/**"]', '"scripts/**", "Package.resolved"]'))
        self.assertFinding("contract_dependencies", "lockfile pins")

    def test_lockfile_pin_undeclared(self):
        self.repo.write("Package.resolved", json.dumps({"pins": [
            {"identity": "shared-design-system", "state": {"version": "0.4.0"}}]}))
        self.assertFinding("contract_dependencies", "not declared")

    # 8 identity
    def test_forbidden_home_path(self):
        self.repo.write("docs/setup.md", "Clone to " + "/Us" + "ers/someone/dev\n")
        self.assertFinding("contract_identity", "macOS home path")

    def test_forbidden_profile(self):
        self.repo.write("docs/setup.md", "export " + "GH_" + "CONFIG_DIR=x\n")
        self.assertFinding("contract_identity", "gh config override")

    def test_forbidden_identity_dir(self):
        self.repo.write("docs/setup.md", "github-" + "identity/profiles/x\n")
        self.assertFinding("contract_identity", "credential profile directory")


    def test_tool_attribution_is_not_an_identity_finding(self):
        # G8: tool attribution trailers and PR footers are allowed (agent-protocol §8).
        self.repo.write("docs/release.md", "Co-Authored-By: Claude <noreply@anthropic.com>\n"
                        "Co-authored-by: bot[bot] <1+bot[bot]@users.noreply.github.com>\n"
                        "Generated with [Claude Code](https://claude.com/claude-code)\n")
        self.assertNotIn("contract_identity", self.repo.kinds())


class LegacyFormatUnaffectedTests(unittest.TestCase):
    def test_legacy_context_tree_skips_contract(self):
        repo = ContractRepo()
        self.addCleanup(repo.close)
        repo.write("CONTEXT.md", "---\n" + json.dumps({
            "schema": 1, "kind": "index", "routes": [],
            "exclusions": [{"patterns": ["**"], "reason": "legacy caller"}]}) + "\n---\n")
        repo.remove("AGENTS.md")
        status, findings, _ = repo.audit()
        self.assertEqual((0, []), (status, findings))


class IndexContractTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)
        self.metadata = {"schema": 1, "guide": "docs/repository-guide.md", "shared_ci": PIN, "dependencies": {}}
        self.repo.write("docs/repository-guide.md", AGENTS)
        self.repo.write("AGENTS.md", "# Document index\n\n- Before editing: [Guide](docs/repository-guide.md)\n")
        self.repo.write(".github/CODEOWNERS", "/.github/ @owner\n/AGENTS.md @owner\n/docs/repository-guide.md @owner\n")
        self.write_metadata()

    def write_metadata(self):
        self.repo.write(".github/repo-contract.json", json.dumps(self.metadata))

    def finding(self, fragment):
        findings = self.repo.audit()[1]
        self.assertTrue(any(fragment in entry["detail"] for entry in findings), findings)

    def test_index_needs_no_inline_pin_rules_or_commands(self):
        self.assertEqual([], self.repo.audit()[1])

    def test_inline_policy_or_command_is_rejected(self):
        for text in ("Run scripts/verify before push.\n", "```sh\nscripts/verify\n```\n", "Owner approval is required.\n"):
            with self.subTest(text=text):
                self.repo.write("AGENTS.md", "# Index\n[Guide](docs/repository-guide.md)\n" + text)
                self.finding("index-only")

    def test_missing_route_target_is_rejected(self):
        self.repo.write("AGENTS.md", "# Index\n[Guide](docs/missing.md)\n")
        self.finding("route target")

    def test_pin_disagrees_with_workflow(self):
        self.metadata["shared_ci"] = OTHER
        self.write_metadata()
        self.finding("differs from workflow pins")

    def test_invalid_metadata_never_falls_back_to_valid_legacy_agents(self):
        self.repo.write("AGENTS.md", AGENTS)
        self.repo.write(".github/repo-contract.json", "{")
        self.finding("invalid repository metadata")

    def test_duplicate_pin_key_fails_closed(self):
        text = json.dumps(self.metadata).replace('"shared_ci":', '"shared_ci": "' + OTHER + '", "shared_ci":')
        self.repo.write(".github/repo-contract.json", text)
        self.finding("duplicate key")

    def test_guide_must_be_tracked_and_local(self):
        for path in ("docs/missing.md", "../outside.md", "/tmp/guide.md"):
            with self.subTest(path=path):
                self.metadata["guide"] = path
                self.write_metadata()
                self.finding("guide must")

    def test_guide_remains_owner_protected(self):
        self.repo.write(".github/CODEOWNERS", "/.github/ @owner\n/AGENTS.md @owner\n")
        self.finding("CODEOWNERS does not cover /docs/repository-guide.md")

    def test_later_ownerless_rule_cannot_unprotect_guide_or_metadata(self):
        for pattern in ("**/repository-guide.md", "**/repo-contract.json"):
            with self.subTest(pattern=pattern):
                self.repo.write(".github/CODEOWNERS", "/.github/ @owner\n/AGENTS.md @owner\n/docs/repository-guide.md @owner\n" + pattern + "\n")
                self.finding("unowned")

    def test_empty_primary_codeowners_does_not_use_root_fallback(self):
        self.repo.write("CODEOWNERS", "/.github/ @owner\n/AGENTS.md @owner\n/docs/repository-guide.md @owner\n")
        self.repo.write(".github/CODEOWNERS", "")
        self.finding("unowned")

    def test_required_check_duplication_is_read_from_guide(self):
        self.repo.write("CLAUDE.md", "Read AGENTS.md first.\nRequired: `quality / aggregate`\n")
        self.finding("duplicates required check")

    def test_dependency_pin_comes_from_metadata(self):
        self.metadata["dependencies"] = {"shared-telemetry": {"version": "1.2.0", "ai": "https://example.invalid/1.2.0/ai/"}}
        self.write_metadata()
        self.repo.write("Package.resolved", json.dumps({"pins": [
            {"identity": "shared-telemetry", "state": {"version": "1.3.0"}}]}))
        self.finding("lockfile pins")

    def test_shared_ci_has_one_metadata_authority(self):
        self.metadata["dependencies"]["shared-ci"] = {"version": PIN, "ai": f"https://example.invalid/{PIN}/ai/"}
        self.write_metadata()
        self.finding("not duplicated")

    def test_review_uses_guide_not_index_as_rules(self):
        workflow = f"on: pull_request_target\njobs:\n  review:\n    uses: LeePepe/shared-ci/.github/workflows/codex-review.yml@{PIN}\n"
        self.repo.write(".github/workflows/review.yml", workflow)
        self.finding("review rules-file")
        self.repo.write(".github/workflows/review.yml", workflow + "    with:\n      rules-file: docs/repository-guide.md\n")
        self.assertEqual([], self.repo.audit()[1])


if __name__ == "__main__":
    unittest.main()
