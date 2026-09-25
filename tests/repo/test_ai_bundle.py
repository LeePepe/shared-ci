"""The versioned documentation bundle stays navigable and examples stay real."""
import json
import re
import subprocess
import sys
import unittest

from fixture import ContractRepo, REPO


BUNDLE = ("USAGE", "INTEGRATION", "COMPATIBILITY", "MIGRATION")


class AIBundleTests(unittest.TestCase):
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
        result = subprocess.run(["/bin/sh", "-eu", "-c", blocks[0]], cwd=caller.root,
                                env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        # Run the exact documented command with a missing required caller artifact.
        caller.remove("AGENTS.md")
        result = subprocess.run(["/bin/sh", "-eu", "-c", blocks[0]], cwd=caller.root,
                                env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("contract_agents", result.stderr)


if __name__ == "__main__":
    unittest.main()
