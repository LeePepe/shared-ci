"""Regression and compatibility tests for test reachability declarations.

Covers US2-A (T101 Schemas + T102 Context normalization):
- Closed test_reachability schema and adapter definitions
- Legacy gate compatibility (string and string-list)
- Object gate normalization and reaches adapter validation
- Leaf test_paths in tech-context.md
- Root test_reachability in both CONTEXT.md and tech-context.md
- Fail-closed behavior for malformed or unknown fields
"""

import json
import re
import unittest

from fixture import Fixture, REPO, layer_context


def matches_documented_schema(value, schema, document):
    """Test-only evaluator for the exact keywords used in context schema.

    Supports uniqueItems for required_gates uniqueness validation.
    """
    supported = {"$schema", "$defs", "$ref", "title", "description", "type", "const",
                 "enum", "required", "properties", "additionalProperties", "allOf",
                 "anyOf", "not", "if", "then", "items", "minItems", "maxItems",
                 "minLength", "pattern", "uniqueItems"}
    assert not set(schema) - supported, set(schema) - supported
    if "$ref" in schema:
        return matches_documented_schema(value, document["$defs"][schema["$ref"].split("/")[-1]], document)
    kind = schema.get("type")
    checks = {"object": lambda: isinstance(value, dict),
              "array": lambda: isinstance(value, list),
              "string": lambda: isinstance(value, str),
              "integer": lambda: type(value) is int}
    if kind is not None and not checks[kind]():
        return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        if any(key not in value for key in schema.get("required", [])):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if any(not matches_documented_schema(value[key], child, document)
               for key, child in properties.items() if key in value):
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            return False
        if schema.get("uniqueItems") is True:
            serialized = [json.dumps(x, sort_keys=True) for x in value]
            if len(serialized) != len(set(serialized)):
                return False
        if "items" in schema and any(not matches_documented_schema(item, schema["items"], document)
                                     for item in value):
            return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
    if any(not matches_documented_schema(value, child, document) for child in schema.get("allOf", [])):
        return False
    if "anyOf" in schema and not any(matches_documented_schema(value, child, document)
                                     for child in schema["anyOf"]):
        return False
    if "not" in schema and matches_documented_schema(value, schema["not"], document):
        return False
    if "if" in schema and matches_documented_schema(value, schema["if"], document):
        if not matches_documented_schema(value, schema.get("then", {}), document):
            return False
    return True


class ReachabilityDeclarationSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads((REPO / "schemas/context-v1.schema.json").read_text(encoding="utf-8"))

    def test_schema_accepts_valid_root_test_reachability(self) -> None:
        valid_reachability = {
            "version": 1,
            "inventory": {
                "defaults": "default-v1",
                "include": ["custom_tests/**/*.py"],
            },
            "required_gates": [
                {
                    "layer": "Quality",
                    "gate": "unit",
                    "aggregate_lane": "verify",
                }
            ],
            "non_tests": [
                {
                    "patterns": ["scripts/quality/test_integrity.py"],
                    "reason": "Quality engine tool, not a test suite.",
                }
            ],
            "exclusions": [
                {
                    "patterns": ["tests/contracts/**"],
                    "reason": "Deliberately excluded contract fixtures.",
                }
            ],
        }
        root_data = {
            "schema": 1,
            "kind": "index",
            "test_reachability": valid_reachability,
            "routes": [{"patterns": ["src/**"], "context": "src/CONTEXT.md"}],
            "exclusions": [{"patterns": ["CONTEXT.md"], "reason": "metadata"}],
        }
        self.assertTrue(matches_documented_schema(root_data, self.schema, self.schema))
        layer_context.validate_context(root_data, "CONTEXT.md")

    def test_schema_accepts_minimal_root_test_reachability(self) -> None:
        root_data = {
            "kind": "index",
            "test_reachability": {
                "version": 1,
                "inventory": {
                    "defaults": "default-v1",
                },
            },
        }
        self.assertTrue(matches_documented_schema(root_data, self.schema, self.schema))
        layer_context.validate_context(root_data, "CONTEXT.md")

    def test_schema_rejects_invalid_test_reachability_shapes(self) -> None:
        base = {
            "schema": 1,
            "kind": "index",
            "test_reachability": {
                "version": 1,
                "inventory": {
                    "defaults": "default-v1",
                },
            },
        }
        invalid_cases = [
            {"version": 2, "inventory": {"defaults": "default-v1"}},
            {"version": "1", "inventory": {"defaults": "default-v1"}},
            {"version": 1},  # missing inventory
            {"version": 1, "inventory": {}},  # missing defaults
            {"version": 1, "inventory": {"defaults": "other"}},  # non-default-v1
            {"version": 1, "inventory": {"defaults": "default-v1", "include": [1]}},
            {"version": 1, "inventory": {"defaults": "default-v1"}, "extra": True},
            {"version": 1, "inventory": {"defaults": "default-v1", "extra": True}},
            {
                "version": 1,
                "inventory": {"defaults": "default-v1"},
                "required_gates": [{"layer": "L", "gate": "G"}],  # missing aggregate_lane
            },
            {
                "version": 1,
                "inventory": {"defaults": "default-v1"},
                "non_tests": [{"patterns": []}],  # missing reason, empty patterns
            },
            {
                "version": 1,
                "inventory": {"defaults": "default-v1"},
                "exclusions": [{"patterns": ["tests/**"], "reason": ""}],  # empty reason
            },
            None,  # test_reachability: null explicitly supplied
        ]
        for invalid_reach in invalid_cases:
            with self.subTest(invalid_reach=invalid_reach):
                data = dict(base, test_reachability=invalid_reach)
                self.assertFalse(matches_documented_schema(data, self.schema, self.schema))
                with self.assertRaises(layer_context.ContextError):
                    layer_context.validate_context(data, "CONTEXT.md")

    def test_schema_and_runtime_reject_duplicate_required_gates(self) -> None:
        duplicate_gates_reachability = {
            "version": 1,
            "inventory": {"defaults": "default-v1"},
            "required_gates": [
                {"layer": "Quality", "gate": "unit", "aggregate_lane": "verify"},
                {"layer": "Quality", "gate": "unit", "aggregate_lane": "verify"},
            ],
        }
        root_data = {
            "schema": 1,
            "kind": "index",
            "test_reachability": duplicate_gates_reachability,
            "routes": [{"patterns": ["src/**"], "context": "src/CONTEXT.md"}],
            "exclusions": [{"patterns": ["CONTEXT.md"], "reason": "metadata"}],
        }
        self.assertFalse(matches_documented_schema(root_data, self.schema, self.schema))
        with self.assertRaises(layer_context.ContextError) as cm:
            layer_context.validate_context(root_data, "CONTEXT.md")
        self.assertIn("duplicate", str(cm.exception))

    def test_schema_and_runtime_reject_test_reachability_in_nested_index(self) -> None:
        nested_index_data = {
            "schema": 1,
            "kind": "index",
            "test_reachability": {
                "version": 1,
                "inventory": {"defaults": "default-v1"},
            },
            "routes": [{"patterns": ["Core/**"], "context": "Core/CONTEXT.md"}],
            "exclusions": [{"patterns": ["CONTEXT.md"], "reason": "metadata"}],
        }
        with self.assertRaises(layer_context.ContextError) as cm:
            layer_context.validate_context(nested_index_data, "Packages/CONTEXT.md")
        self.assertIn("root context index", str(cm.exception))

    def test_schema_forbids_test_reachability_in_leaf(self) -> None:
        leaf_data = {
            "schema": 1,
            "kind": "leaf",
            "layer": "Source",
            "parent": "CONTEXT.md",
            "scope": ["src/**"],
            "test_reachability": {
                "version": 1,
                "inventory": {"defaults": "default-v1"},
            },
        }
        self.assertFalse(matches_documented_schema(leaf_data, self.schema, self.schema))
        with self.assertRaises(layer_context.ContextError):
            layer_context.validate_context(leaf_data, "src/CONTEXT.md")

    def test_schema_accepts_all_reach_adapters(self) -> None:
        adapters = [
            {"adapter": "swiftpm-v1", "package_path": "Packages/Core"},
            {"adapter": "swiftpm-v1"},
            {"adapter": "xcodegen-v1", "project": "project.yml", "scheme": "AppTests"},
            {"adapter": "python-unittest-v1", "start_directory": "tests/unit", "pattern": "test_*.py"},
            {"adapter": "python-unittest-v1"},
            {"adapter": "pytest-v1", "root": "tests", "python_files": ["*_test.py"]},
            {"adapter": "node-test-v1", "patterns": ["tests/**/*.test.mjs"]},
            {"adapter": "vitest-v1", "include": ["tests/**/*.test.ts"], "exclude": ["tests/e2e/**"], "config": "vitest.config.ts"},
            {"adapter": "ruby-v1", "patterns": ["spec/**/*_spec.rb"]},
            {"adapter": "shell-v1", "patterns": ["tests/**/*.sh"]},
            {"adapter": "declared-glob-v1", "patterns": ["tests/**"], "source": "scripts/test-manifest.json", "reason": "custom runner"},
        ]
        for adapter in adapters:
            with self.subTest(adapter=adapter):
                leaf = {
                    "schema": 1,
                    "kind": "leaf",
                    "layer": "TestLayer",
                    "parent": "CONTEXT.md",
                    "scope": ["src/**"],
                    "test_paths": ["tests/**"],
                    "gates": [
                        {
                            "id": "unit",
                            "kind": "test",
                            "mode": "ci",
                            "command": ["tool", "test"],
                            "reaches": [adapter],
                        }
                    ],
                }
                self.assertTrue(matches_documented_schema(leaf, self.schema, self.schema))
                layer_context.validate_context(leaf, "src/CONTEXT.md")

    def test_schema_rejects_invalid_reach_adapter_shapes(self) -> None:
        invalid_adapters = [
            {"adapter": "unknown-v1"},
            {"adapter": "swiftpm-v1", "unknown_field": True},
            {"adapter": "swiftpm-v1", "package_path": ""},
            {"adapter": "xcodegen-v1", "project": 123},
            {"adapter": "python-unittest-v1", "start_directory": ""},
            {"adapter": "pytest-v1", "python_files": "not-a-list"},
            {"adapter": "node-test-v1", "patterns": []},
            {"adapter": "vitest-v1", "include": [1]},
            {"adapter": "declared-glob-v1", "patterns": ["tests/**"], "source": "scripts/manifest.json"},  # missing reason
            {"adapter": "declared-glob-v1", "reason": "reason only", "source": "scripts/manifest.json"},  # missing patterns
            {"adapter": "declared-glob-v1", "patterns": ["tests/**"], "reason": "reason only"},  # missing source
            {"adapter": "declared-glob-v1", "patterns": ["tests/**"], "reason": "reason only", "source": ""},  # empty source
            {"adapter": "declared-glob-v1", "patterns": ["tests/**"], "reason": "reason only", "source": 123},  # non-string source
        ]
        for invalid_adapter in invalid_adapters:
            with self.subTest(invalid_adapter=invalid_adapter):
                leaf = {
                    "schema": 1,
                    "kind": "leaf",
                    "layer": "TestLayer",
                    "parent": "CONTEXT.md",
                    "scope": ["src/**"],
                    "gates": [
                        {
                            "id": "unit",
                            "kind": "test",
                            "mode": "ci",
                            "command": ["tool", "test"],
                            "reaches": [invalid_adapter],
                        }
                    ],
                }
                self.assertFalse(matches_documented_schema(leaf, self.schema, self.schema))
                with self.assertRaises(layer_context.ContextError):
                    layer_context.validate_context(leaf, "src/CONTEXT.md")

    def test_schema_rejects_reaches_on_non_test_or_local_gates(self) -> None:
        cases = [
            # kind: check with reaches
            {"id": "c", "kind": "check", "mode": "ci", "command": ["tool"],
             "reaches": [{"adapter": "python-unittest-v1"}]},
            # kind: build with reaches
            {"id": "b", "kind": "build", "mode": "both", "command": ["tool"],
             "reaches": [{"adapter": "swiftpm-v1"}]},
            # mode: local with reaches
            {"id": "t", "kind": "test", "mode": "local", "command": ["tool"],
             "reaches": [{"adapter": "python-unittest-v1"}]},
        ]
        for gate in cases:
            with self.subTest(gate=gate):
                leaf = {
                    "schema": 1,
                    "kind": "leaf",
                    "layer": "TestLayer",
                    "parent": "CONTEXT.md",
                    "scope": ["src/**"],
                    "gates": [gate],
                }
                self.assertFalse(matches_documented_schema(leaf, self.schema, self.schema))
                with self.assertRaises(layer_context.ContextError):
                    layer_context.validate_context(leaf, "src/CONTEXT.md")


class TechContextNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def test_legacy_string_gate_normalizes_and_preserves_behavior(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            gate={"unit": "python3 -m unittest discover -s tests/quality"},
        )
        layers = layer_context.layer_map(self.fixture.root)
        data = layers["Quality"]
        self.assertEqual("Quality", data["layer"])
        self.assertEqual([], data["test_paths"])
        gates = data["gates"]
        self.assertEqual(1, len(gates))
        self.assertEqual("unit", gates[0]["id"])
        self.assertEqual("check", gates[0]["kind"])
        self.assertEqual("both", gates[0]["mode"])
        self.assertEqual(["python3", "-m", "unittest", "discover", "-s", "tests/quality"], gates[0]["command"])
        self.assertNotIn("reaches", gates[0])

    def test_legacy_string_list_gate_normalizes(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            gate={"test": ["python3", "-m", "unittest"]},
        )
        layers = layer_context.layer_map(self.fixture.root)
        data = layers["Quality"]
        gates = data["gates"]
        self.assertEqual(1, len(gates))
        self.assertEqual("test", gates[0]["id"])
        self.assertEqual("test", gates[0]["kind"])
        self.assertEqual("both", gates[0]["mode"])
        self.assertEqual(["python3", "-m", "unittest"], gates[0]["command"])

    def test_object_form_gate_with_reaches_normalizes_and_validates(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            test_paths=["tests/quality/**"],
            gate={
                "unit": {
                    "kind": "test",
                    "mode": "ci",
                    "command": ["python3", "-I", "-B", "-m", "unittest", "discover", "-s", "tests/quality"],
                    "reaches": [
                        {"adapter": "python-unittest-v1"}
                    ],
                }
            },
        )
        layers = layer_context.layer_map(self.fixture.root)
        data = layers["Quality"]
        self.assertEqual(["tests/quality/**"], data["test_paths"])
        gates = data["gates"]
        self.assertEqual(1, len(gates))
        self.assertEqual("unit", gates[0]["id"])
        self.assertEqual("test", gates[0]["kind"])
        self.assertEqual("ci", gates[0]["mode"])
        self.assertEqual(["python3", "-I", "-B", "-m", "unittest", "discover", "-s", "tests/quality"], gates[0]["command"])
        self.assertEqual([{"adapter": "python-unittest-v1"}], gates[0]["reaches"])

    def test_object_form_gate_with_string_command_normalizes(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            test_paths=["tests/quality/**"],
            gate={
                "unit": {
                    "kind": "test",
                    "mode": "ci",
                    "command": "python3 -m unittest discover -s tests/quality",
                    "reaches": [{"adapter": "python-unittest-v1"}],
                }
            },
        )
        layers = layer_context.layer_map(self.fixture.root)
        data = layers["Quality"]
        self.assertEqual(["python3", "-m", "unittest", "discover", "-s", "tests/quality"], data["gates"][0]["command"])

    def test_root_tech_context_with_test_reachability_loads_and_audits(self) -> None:
        self.fixture.tech_root(
            rows=[{"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}],
            support=[{"patterns": ["empty-template/**"], "reason": "template"}],
            test_reachability={
                "version": 1,
                "inventory": {
                    "defaults": "default-v1",
                    "include": ["custom_tests/**"],
                },
                "required_gates": [
                    {
                        "layer": "Quality",
                        "gate": "unit",
                        "aggregate_lane": "verify",
                    }
                ],
                "non_tests": [
                    {
                        "patterns": ["scripts/quality/test_integrity.py"],
                        "reason": "Quality tool.",
                    }
                ],
                "exclusions": [
                    {
                        "patterns": ["tests/contracts/**"],
                        "reason": "Separate admission.",
                    }
                ],
            },
        )
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
        )
        self.fixture.write("scripts/quality/tool.py")
        self.fixture.git("add", ".")
        findings, counts = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertEqual([], findings)
        self.assertEqual(0, len(findings))
        model = layer_context._techcontext().load(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertEqual(1, model["test_reachability"]["version"])

    def test_invalid_test_reachability_in_root_tech_context_emits_finding(self) -> None:
        self.fixture.tech_root(
            rows=[{"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}],
            support=[{"patterns": ["empty-template/**"], "reason": "template"}],
            test_reachability={
                "version": 999,  # invalid version
                "inventory": {"defaults": "default-v1"},
            },
        )
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
        )
        self.fixture.write("scripts/quality/tool.py")
        self.fixture.git("add", ".")
        findings, counts = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_test_declaration" for f in findings))

    def test_leaf_tech_context_with_invalid_reaches_gate_fails_load(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            gate={
                "unit": {
                    "kind": "check",  # non-test with reaches
                    "command": "python3 -m unittest",
                    "reaches": [{"adapter": "python-unittest-v1"}],
                }
            },
        )
        self.fixture.git("add", ".")
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_test_declaration" and "reaches" in f.detail for f in findings))

    def test_tech_context_declared_glob_adapter_requires_source(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        # Valid declared-glob-v1 with source
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            test_paths=["tests/**"],
            gate={
                "custom": {
                    "kind": "test",
                    "mode": "ci",
                    "command": ["python3", "runner.py"],
                    "reaches": [
                        {
                            "adapter": "declared-glob-v1",
                            "patterns": ["tests/**"],
                            "source": "scripts/manifest.json",
                            "reason": "Custom runner manifest.",
                        }
                    ],
                }
            },
        )
        layers = layer_context.layer_map(self.fixture.root)
        reaches = layers["Quality"]["gates"][0]["reaches"]
        self.assertEqual("scripts/manifest.json", reaches[0]["source"])

        # Invalid declared-glob-v1 missing source
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            test_paths=["tests/**"],
            gate={
                "custom": {
                    "kind": "test",
                    "mode": "ci",
                    "command": ["python3", "runner.py"],
                    "reaches": [
                        {
                            "adapter": "declared-glob-v1",
                            "patterns": ["tests/**"],
                            "reason": "Missing source.",
                        }
                    ],
                }
            },
        )
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_test_declaration" and "source" in f.detail for f in findings))

    def test_tech_context_object_gate_rejects_unknown_fields(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            gate={
                "unit": {
                    "kind": "test",
                    "mode": "ci",
                    "command": ["python3", "-m", "unittest"],
                    "unknown_field": True,
                }
            },
        )
        self.fixture.git("add", ".")
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_gate" and "unknown fields" in f.detail for f in findings))

    def test_tech_context_rejects_explicit_null_test_reachability(self) -> None:
        self.fixture.tech_root(
            rows=[{"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}],
            test_reachability=None,  # will omit or if we put explicit None in frontmatter:
        )
        # Manually write frontmatter with explicit test_reachability: null
        content = "---\ntest_reachability: null\n---\n\n# Layer Map\n\n| Layer | tech-context | Depends on |\n| --- | --- | --- |\n| Quality | scripts/quality/tech-context.md | none |\n"
        self.fixture.write("docs/architecture/tech-context.md", content)
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
        )
        self.fixture.git("add", ".")
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_test_declaration" and "must be an object" in f.detail for f in findings))

    def test_tech_context_leaf_rejects_explicit_null_test_paths(self) -> None:
        self.fixture.tech_root([
            {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []}
        ])
        content = "---\nlayer: Quality\nowns: [scripts/quality/**]\ntest_paths: null\n---\n\n# Leaf\n"
        self.fixture.write("scripts/quality/tech-context.md", content)
        self.fixture.git("add", ".")
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "invalid_leaf" and "test_paths" in f.detail for f in findings))

    def test_tech_context_test_paths_participates_in_layer_ownership_and_overlap(self) -> None:
        self.fixture.tech_root(
            rows=[
                {"layer": "Quality", "path": "scripts/quality/tech-context.md", "depends_on": []},
                {"layer": "Policy", "path": "scripts/policy/tech-context.md", "depends_on": []},
            ],
            support=[{"patterns": ["empty-template/**"], "reason": "template"}],
        )
        self.fixture.tech_leaf(
            path="scripts/quality/tech-context.md",
            layer="Quality",
            owns=["scripts/quality/**"],
            test_paths=["tests/quality/**"],
        )
        self.fixture.tech_leaf(
            path="scripts/policy/tech-context.md",
            layer="Policy",
            owns=["scripts/policy/**"],
            test_paths=["tests/policy/**"],
        )
        self.fixture.write("scripts/quality/tool.py")
        self.fixture.write("tests/quality/test_gate.py")
        self.fixture.write("scripts/policy/check.py")
        self.fixture.write("tests/policy/test_val.py")
        self.fixture.git("add", ".")

        # Resolve tracked test path owned only through test_paths
        res = layer_context._techcontext().resolve(layer_context, self.fixture.root, "docs/architecture/tech-context.md", "tests/quality/test_gate.py")
        self.assertEqual("Quality", res.layer)
        self.assertEqual("leaf", res.classification)
        self.assertEqual("scripts/quality/tech-context.md", res.context)

        # Audit should find 0 findings for tracked tests owned via test_paths
        findings, counts = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertEqual([], findings)
        self.assertEqual(6, counts["leaf"])

        # Test sibling overlap between test_paths and another layer's owns or test_paths
        self.fixture.tech_leaf(
            path="scripts/policy/tech-context.md",
            layer="Policy",
            owns=["scripts/policy/**"],
            test_paths=["tests/quality/**"],  # Overlaps Quality's test_paths
        )
        findings, _ = layer_context._techcontext().audit(layer_context, self.fixture.root, "docs/architecture/tech-context.md")
        self.assertTrue(any(f.kind == "sibling_overlap" and "tests/quality/test_gate.py" in f.path for f in findings))
