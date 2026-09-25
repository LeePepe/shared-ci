"""Metadata/index contract adoption through the real audit CLI."""
import json
import unittest

from fixture import AGENTS, ContractRepo, OTHER, PIN


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
