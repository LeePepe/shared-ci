"""The versioned documentation bundle stays navigable and examples stay real."""
import json
import re
import sys
import unittest

from fixture import ContractRepo, REPO, environment, run_bounded


BUNDLE = ("USAGE", "INTEGRATION", "COMPATIBILITY", "MIGRATION")


class AIBundleTests(unittest.TestCase):
    def test_plan_references_resolve_at_their_own_provider_versions(self):
        migration = (REPO / "ai/MIGRATION.md").read_text()
        link = "repo-contract.md#task-plans-and-versioned-guides"
        self.assertIn(link, re.findall(r"\[[^\]]+\]\(([^)]+)\)", migration))
        path, _ = link.split("#")
        contract = (REPO / "ai" / path).read_text()
        self.assertIn("### Task plans and versioned guides", contract)

        # Generate the template pointer with the actually selected provider,
        # not the candidate contract. Older pins must retain a valid route.
        pin = json.loads((REPO / ".github/repo-contract.json").read_text())["shared_ci"]
        template = (REPO / "templates/repository-guide.md").read_text()
        prefix, snapshot = template.split("## Complete shared protocol snapshot\n", 1)
        dependencies = prefix.split("## Dependencies\n", 1)[1].split("\n## ", 1)[0]
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", dependencies)
        self.assertEqual(1, len(links), "One authority pointer, not a second policy copy")
        selected_url = links[0].replace("<40-char-sha>", pin)
        target = re.fullmatch(
            r"https://github.com/[^/]+/shared-ci/blob/([0-9a-f]{40})/(ai/repo-contract\.md)#([a-z-]+)",
            selected_url)
        self.assertIsNotNone(target, selected_url)
        revision, path, fragment = target.groups()
        self.assertEqual(pin, revision)
        selected = run_bounded(["git", "show", f"{revision}:{path}"], cwd=REPO,
                               env=environment(), timeout=10, check=True).stdout
        headings = re.findall(r"^#{1,6} +(.+)$", selected, re.M)
        self.assertIn(fragment, [heading.lower().replace(" ", "-") for heading in headings])
        self.assertIn("clarification only if present at that SHA", " ".join(dependencies.split()))
        baseline = run_bounded(["git", "show", f"{pin}:templates/repository-guide.md"], cwd=REPO,
                               env=environment(), timeout=10, check=True).stdout
        self.assertEqual(baseline.split("## Complete shared protocol snapshot\n", 1)[1], snapshot)

    def test_plan_guidance_keeps_existing_process_and_separate_responsibilities(self):
        # Text-contract guards, not proof of an agent's planning behavior.
        text = (REPO / "ai/repo-contract.md").read_text()
        section = text.split("### Task plans and versioned guides\n", 1)[1].split("\n### ", 1)[0]
        section = " ".join(section.split())
        for rule in (
                "Where the repository's existing process uses a task plan",
                "task and its version, dependency versions and update order, completion conditions and next actions",
                "Reuse a sufficiently concrete existing plan",
                "check it against current code, dependencies and verification",
                "fill gaps instead of rewriting the same plan",
                "Existing spec/plan review and required approvals still apply",
                "adds no plan requirement or exemption",
                "`AGENTS.md` → repository guide → shared contract at the selected immutable version",
                "General update/migration rules belong in the repository guide or versioned shared documentation",
                "the plan references the applicable immutable versions instead of maintaining duplicate policy",
                "a source candidate does not replace the contract at the selected pin"):
            with self.subTest(rule=rule):
                self.assertIn(rule, section)

    def test_bundle_links_and_anchors(self):
        for name in BUNDLE:
            source = REPO / "ai" / (name + ".md")
            text = source.read_text(encoding="utf-8")
            links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
            self.assertTrue(links, name)
            for link in links:
                with self.subTest(source=name, link=link):
                    # This bundle uses same-commit relative links, not floating URLs.
                    self.assertNotIn("://", link)
                    path, _, anchor = link.partition("#")
                    target = (source.parent / path).resolve() if path else source
                    self.assertTrue(target.is_relative_to(REPO))
                    self.assertTrue(target.exists(), link)
                    if anchor:
                        headings = re.findall(r"^#{1,6} +(.+)$",
                                              target.read_text(encoding="utf-8"), re.M)
                        anchors = [re.sub(r" +", "-", re.sub(r"[^a-z0-9 -]", "",
                                   heading.lower())).strip("-") for heading in headings]
                        self.assertIn(anchor, anchors, link)

    def test_existing_registry_routes_remain_compatible(self):
        registry = json.loads((REPO / "ai/registry.json").read_text())
        docs = {entry["id"]: entry["resource"] for entry in registry["entries"]
                if entry["kind"] == "document"}
        self.assertEqual("docs/ai-usage.md", docs["doc.usage"]["path"])
        for name, anchor in (("integration", "fixed-checkout-surfaces"),
                             ("compatibility", "compatibility"),
                             ("migration", "migration-and-rollback")):
            self.assertEqual({"type": "document", "path": "docs/integration-and-migration.md",
                              "anchor": anchor}, docs["doc." + name])
        for path in ("README.md", "docs/ai-usage.md", "docs/integration-and-migration.md"):
            self.assertIn("ai/USAGE.md", (REPO / path).read_text())

    def test_integration_example_on_synthetic_caller(self):
        text = (REPO / "ai/INTEGRATION.md").read_text()
        blocks = re.findall(r"```sh\n(.*?)```", text, re.S)
        self.assertEqual(1, len(blocks))
        caller = ContractRepo()
        self.addCleanup(caller.close)
        env = dict(caller.env, ADMITTED_PYTHON=sys.executable, PROVIDER_DIR=str(REPO))
        result = run_bounded(["/bin/sh", "-eu", "-c", blocks[0]], cwd=caller.root,
                             env=env, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        # Run the exact documented command with a missing required caller artifact.
        caller.remove("AGENTS.md")
        result = run_bounded(["/bin/sh", "-eu", "-c", blocks[0]], cwd=caller.root,
                             env=env, timeout=30)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("contract_agents", result.stderr)


if __name__ == "__main__":
    unittest.main()
