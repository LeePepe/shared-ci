"""Resolver support for the repo-kit tech-context layer map."""
import json
import unittest

from fixture import APP, ContractRepo, CORE, PIN, REPO, ROOT_CONTEXT


class TechContextResolverTests(unittest.TestCase):
    def setUp(self):
        self.repo = ContractRepo()
        self.addCleanup(self.repo.close)

    def run_cli(self, *args):
        self.repo.add()
        return self.repo.cli(*args)

    def test_resolve_leaf_support_and_root(self):
        result = self.run_cli("resolve", "src/core/model.py", "README.md",
                              "docs/architecture/tech-context.md")
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(("leaf", "Core", "src/core/tech-context.md"),
                         (rows[0]["classification"], rows[0]["layer"], rows[0]["context"]))
        self.assertEqual(["docs/architecture/tech-context.md", "src/core/tech-context.md"], rows[0]["chain"])
        self.assertEqual(("excluded", "support files"), (rows[1]["classification"], rows[1]["reason"]))
        self.assertEqual("excluded", rows[2]["classification"])

    def test_layers_field_contexts_and_run(self):
        result = self.run_cli("layers", "src/app/main.py", "src/core/model.py")
        self.assertEqual("App\nCore\n", result.stdout)
        self.assertEqual('[\n  "Core"\n]\n', self.run_cli("field", "App", "dependencies").stdout)
        self.assertEqual(["wiring only"], json.loads(self.run_cli("field", "App", "red_lines").stdout))
        chain = self.run_cli("contexts", "src/app/main.py").stdout.splitlines()
        self.assertEqual(["docs/architecture/tech-context.md", "src/app/tech-context.md"], chain)
        run = self.run_cli("run", "Core", "--gate", "test")
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertIn("[context/run] Core:test", run.stdout)

    def test_block_and_flow_gate_forms_are_equivalent(self):
        for layer in ("Core", "App"):
            gates = json.loads(self.run_cli("field", layer, "gates").stdout)
            self.assertEqual([{"id": "test", "kind": "test", "mode": "both",
                               "command": ["python3", "-c", "pass"]}], gates)

    def test_unmapped_path(self):
        self.repo.write("lib/orphan.py", "")
        self.assertIn("unmapped_path", self.repo.kinds())
        self.assertEqual(1, self.run_cli("resolve", "lib/orphan.py").returncode)

    def test_overlapping_owners(self):
        self.repo.write("src/app/tech-context.md", APP.replace("owns: [src/app/**]", "owns: [src/**]"))
        self.assertIn("sibling_overlap", self.repo.kinds())

    def test_table_drift_and_unlisted_leaf(self):
        self.repo.write("docs/architecture/tech-context.md", ROOT_CONTEXT.replace("| wiring | `src/app/tech-context.md` | Core |", "| wiring | `src/app/tech-context.md` | (none) |"))
        self.repo.write("src/core/sub/tech-context.md", CORE.replace("layer: Core", "layer: Sub").replace("src/core/**", "src/core/sub/**"))
        kinds = self.repo.kinds()
        self.assertIn("layer_table_drift", kinds)
        self.assertIn("unlisted_layer_context", kinds)

    def test_missing_dependency_and_cycle(self):
        self.repo.write("src/core/tech-context.md", CORE.replace("depends_on: []", "depends_on: [App]"))
        self.repo.write("docs/architecture/tech-context.md",
                        ROOT_CONTEXT.replace("| types | `src/core/tech-context.md` | (none) |", "| types | `src/core/tech-context.md` | App |"))
        self.assertIn("dependency_cycle", self.repo.kinds())
        self.repo.write("src/core/tech-context.md", CORE.replace("depends_on: []", "depends_on: [Ghost]"))
        self.assertIn("missing_dependency", self.repo.kinds())

    def test_invalid_leaf_frontmatter(self):
        self.repo.write("src/core/tech-context.md", CORE.replace("owns: [src/core/**]\n", ""))
        self.assertIn("invalid_leaf", self.repo.kinds())
        self.repo.write("src/core/tech-context.md", "no frontmatter\n")
        self.assertIn("invalid_context", self.repo.kinds())

    def test_json_frontmatter_leaf_is_accepted(self):
        self.repo.write("src/core/tech-context.md", "---\n" + json.dumps({
            "layer": "Core", "owns": ["src/core/**"], "depends_on": [],
            "gate": {"test": ["python3", "-c", "pass"]}, "red_lines": []}) + "\n---\n")
        self.assertEqual(set(), self.repo.kinds())

    def test_root_without_table_is_an_error(self):
        self.repo.write("docs/architecture/tech-context.md", "---\nlayer: _root\n---\n# nothing\n")
        self.assertIn("invalid_context", self.repo.kinds())

    def use_published_templates(self):
        agents = (REPO / "templates/AGENTS.md").read_text(encoding="utf-8")
        self.repo.write("AGENTS.md", agents.replace("<40-char-sha>", PIN)
                        .replace("<Repository>", "Synthetic"))
        root = (REPO / "templates/tech-context.root.md").read_text(encoding="utf-8")
        root = root.replace("Packages/Core", "src/core").replace("Packages/App", "src/app")
        self.repo.write("docs/architecture/tech-context.md", root)
        core = (REPO / "templates/tech-context.leaf.md").read_text(encoding="utf-8")
        self.repo.write("src/core/tech-context.md", core.replace("Packages/Core", "src/core"))
        self.repo.write("docs/development.md",
                        (REPO / "templates/development.md").read_text(encoding="utf-8"))

    def test_published_templates_keep_tests_with_implementation(self):
        self.use_published_templates()
        self.repo.write("src/core/tests/test_model.py", "assert 1 == 1\n")
        self.assertEqual(set(), self.repo.kinds())
        result = self.run_cli("resolve", "src/core/model.py", "src/core/tests/test_model.py",
                              "docs/development.md", ".github/workflows/ci.yml")
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(["Core", "Core"], [row["layer"] for row in rows[:2]])
        self.assertEqual(["excluded", "excluded"], [row["classification"] for row in rows[2:]])

    def test_published_root_requires_an_owner_for_new_script(self):
        self.use_published_templates()
        self.repo.write("scripts/new_tool.py", "VALUE = 1\n")
        self.assertIn("unmapped_path", self.repo.kinds())
        core = (self.repo.root / "src/core/tech-context.md").read_text(encoding="utf-8")
        self.repo.write("src/core/tech-context.md",
                        core.replace("owns: [src/core/**]",
                                     "owns: [src/core/**, scripts/new_tool.py]"))
        self.assertEqual(set(), self.repo.kinds())
        self.assertEqual("Core\n", self.run_cli("resolve", "scripts/new_tool.py",
                                               "--format", "layer").stdout)


if __name__ == "__main__":
    unittest.main()
