"""Metadata/index contract adoption through the real audit CLI."""
import json
import re
import unittest

from fixture import AGENTS, ContractRepo, OTHER, PIN, REPO


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

    def test_review_call_spellings_enforce_guide_and_pin(self):
        for reviewer in ("codex", "kimi"):
            for spelling in ("plain", "quoted", "flow"):
                for guide, pin, expected in ((None, PIN, "review rules-file"),
                                              ("AGENTS.md", PIN, "review rules-file"),
                                              (self.metadata["guide"], OTHER, "mixed shared-ci pins"),
                                              (self.metadata["guide"], "main", "not pinned"),
                                              (self.metadata["guide"], PIN, None)):
                    with self.subTest(reviewer=reviewer, spelling=spelling, guide=guide, pin=pin):
                        uses = f"LeePepe/shared-ci/.github/workflows/{reviewer}-review.yml@{pin}"
                        if spelling == "flow":
                            inputs = f", with: {{rules-file: {guide}}}" if guide else ""
                            job = f"  review: {{uses: {uses}{inputs}}}\n"
                        else:
                            key = '"uses"' if spelling == "quoted" else "uses"
                            job = f"  review:\n    {key}: {uses}\n"
                            if guide:
                                job += f"    with:\n      rules-file: {guide}\n"
                        self.repo.write(".github/workflows/review.yml", "on: pull_request_target\njobs:\n" + job)
                        if expected:
                            self.finding(expected)
                        else:
                            self.assertEqual([], self.repo.audit()[1])

    def test_uninterpretable_workflows_fail_closed(self):
        for jobs in ("[]", "{review: []}", "{review: {uses: []}}", "{review: &call {uses: ignored}}",
                     '{review: {"uses": "x", with: []}}', '{review: {steps: {}}}',
                     '{review: {steps: [null]}}', '{review: {uses: x, uses: y}}',
                     '{review: {uses: LeePepe/shared-ci/invalid}}', '{review.bad: {uses: x}}'):
            with self.subTest(jobs=jobs):
                self.repo.write(".github/workflows/review.yml", "on: pull_request_target\njobs: " + jobs + "\n")
                self.finding("cannot resolve workflow calls")

    def test_quality_job_is_discovered_from_structure(self):
        for job_id in ("quality", "gate"):
            with self.subTest(job_id=job_id):
                self.repo.write(".github/workflows/ci.yml", f"""on: pull_request
jobs:
  {job_id}: {{"uses": "LeePepe/shared-ci/.github/workflows/quality.yml@{PIN}", with: {{verify-command: scripts/verify --all}}}}
""")
                if job_id == "quality":
                    self.assertEqual([], self.repo.audit()[1])
                else:
                    self.finding("quality / aggregate")

    def test_workflow_symlink_is_not_silently_ignored(self):
        self.repo.write("docs/review.yml", "jobs: {review: {uses: ignored}}\n")
        (self.repo.root / ".github/workflows/review.yml").symlink_to("../../docs/review.yml")
        self.finding("cannot resolve workflow calls")

    def test_script_text_is_not_a_workflow_call(self):
        self.repo.write(".github/workflows/review.yml", """on: pull_request_target
jobs:
  script:
    runs-on: ubuntu-latest
    steps:
      - run: |
          uses: LeePepe/shared-ci/.github/workflows/codex-review.yml@main
""")
        self.assertEqual([], self.repo.audit()[1])

    def test_invalid_owner_tokens_fail_closed(self):
        for token in ("not-an-owner", "@", "@org/", "@org/team/extra", "owner@", "@bad_name",
                      "@bad--name", "@" + "a" * 40, "a..b@example.invalid", "@owner invalid"):
            with self.subTest(token=token):
                self.repo.write(".github/CODEOWNERS", "".join(
                    f"{path} {token}\n" for path in ("/.github/", "/AGENTS.md", "/docs/repository-guide.md")))
                self.finding("invalid CODEOWNERS owner")

    def test_supported_owners_and_ownerless_override(self):
        for token in ("@owner", "@org/team-name", "owner@example.invalid", "a.b@foo--bar.invalid"):
            with self.subTest(token=token):
                owners = "".join(f"{path} {token}\n" for path in (
                    "/.github/", "/AGENTS.md", "/docs/repository-guide.md"))
                self.repo.write(".github/CODEOWNERS", owners)
                self.assertEqual([], self.repo.audit()[1])
                self.repo.write(".github/CODEOWNERS", owners + "**/repository-guide.md\n")
                self.finding("unowned")

    def test_exact_versions_agree_with_schema(self):
        schema = json.loads((REPO / "schemas/repo-metadata-v1.json").read_text())
        pattern = schema["properties"]["dependencies"]["additionalProperties"]["properties"]["version"]["pattern"]
        valid = ("0.0.0", "v1.2.3", "1.2.3-rc.1+build.7", "1.2.3+001", "1.2.3-0.a-1", PIN)
        invalid = ("01.2.3", "1.02.3", "1.2.03", "1.2.3-bad_identifier", "1.2.3-é",
                   "1.2.3-01", "1.2.3-a..b", "1.2.3+", "1.2.3+a..b", "1.2.3\n", "１.2.3", "A" * 40, "main")
        for version in valid + invalid:
            with self.subTest(version=version):
                expected = version in valid
                self.metadata["dependencies"] = {"shared-telemetry": {
                    "version": version, "ai": f"https://example.invalid/{version}/ai/"}}
                self.write_metadata()
                findings = self.repo.audit()[1]
                accepted = not any("version must be exact semver" in f["detail"] for f in findings)
                self.assertEqual(expected, accepted, findings)
                self.assertEqual(expected, re.search(pattern, version) is not None)


if __name__ == "__main__":
    unittest.main()
