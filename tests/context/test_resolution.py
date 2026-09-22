"""Generic ownership tests adapted from the pinned AIDash context tests.

Source: LeePepe/AIDash 30092ed0d09e2b6e7a4a9f49d7cd64627fbf898e,
scripts/context/tests/test_context.py, blob 414fc541bd912a25bb4b667ad2bffbc78ebc52fe.
No product repository assertions are included.
"""
import json
import pathlib
import re
import unittest
from unittest import mock

from fixture import Fixture, REPO, layer_context


class ContextAuditNegativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def assert_kind(self, expected: str) -> None:
        kinds = {finding.kind for finding in self.fixture.findings()}
        self.assertIn(expected, kinds, kinds)

    def test_unmapped_path_is_rejected(self) -> None:
        self.fixture.root_index([])
        self.fixture.write("orphan.txt")
        self.fixture.git("add", "orphan.txt", "CONTEXT.md")
        self.assert_kind("unmapped_path")

    def test_untracked_path_is_not_audited(self) -> None:
        self.fixture.root_index([])
        self.fixture.git("add", "CONTEXT.md")
        self.fixture.write("arbitrary-untracked.txt")
        findings, counts = self.fixture.audit()
        self.assertFalse(any(finding.path == "arbitrary-untracked.txt" for finding in findings))
        self.assertEqual(1, counts["total"])

    def test_sibling_overlap_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"},
            {"patterns": ["src/*.py"], "context": "other/CONTEXT.md"},
        ])
        self.fixture.leaf()
        self.fixture.leaf(path="other/CONTEXT.md", layer="Other", scope=["src/*.py"])
        self.fixture.write("src/a.py")
        self.fixture.git("add", "src/a.py")
        self.assert_kind("sibling_overlap")

    def test_test_path_sibling_overlap_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "test_paths": ["tests/shared.py"],
             "context": "src/CONTEXT.md"},
            {"patterns": ["other/**"], "test_paths": ["tests/shared.py"],
             "context": "other/CONTEXT.md"},
        ])
        self.fixture.leaf(test_paths=["tests/shared.py"])
        self.fixture.leaf(path="other/CONTEXT.md", layer="Other", scope=["other/**"],
                          test_paths=["tests/shared.py"])
        self.fixture.write("tests/shared.py")
        self.fixture.git("add", "tests/shared.py")
        self.assert_kind("sibling_overlap")

    def test_context_cycle_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "child/CONTEXT.md"}])
        self.fixture.context("child/CONTEXT.md", {
            "schema": 1, "kind": "index",
            "routes": [{"patterns": ["src/**"], "context": "../CONTEXT.md"}],
            "exclusions": [],
        })
        self.fixture.write("src/a.py")
        self.assert_kind("cycle")

    def test_missing_context_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "missing/CONTEXT.md"}])
        self.fixture.write("src/a.py")
        self.assert_kind("missing_context")

    def test_parent_leaf_mismatch_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}])
        self.fixture.leaf(parent="wrong/CONTEXT.md")
        self.fixture.write("src/a.py")
        self.assert_kind("parent_leaf_mismatch")

    def test_parent_leaf_test_paths_mismatch_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "test_paths": ["tests/source.py"],
             "context": "src/CONTEXT.md"},
        ])
        self.fixture.leaf(test_paths=["tests/different.py"])
        self.assert_kind("parent_leaf_mismatch")

    def test_duplicate_layer_id_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"},
            {"patterns": ["other/**"], "context": "other/CONTEXT.md"},
        ])
        self.fixture.leaf()
        self.fixture.leaf(path="other/CONTEXT.md", layer="Source", scope=["other/**"])
        self.assert_kind("duplicate_layer_id")

    def test_invalid_gate_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}])
        self.fixture.leaf(gates=[{"id": "bad", "kind": "magic", "mode": "sometimes", "command": []}])
        self.assert_kind("invalid_gate")

    def test_missing_dependency_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}])
        self.fixture.leaf(dependencies=["Ghost"])
        self.assert_kind("missing_dependency")

    def test_reciprocal_dependency_drift_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"},
            {"patterns": ["base/**"], "context": "base/CONTEXT.md"},
        ])
        self.fixture.leaf(dependencies=["Base"])
        self.fixture.leaf(path="base/CONTEXT.md", layer="Base", scope=["base/**"])
        self.assert_kind("reciprocal_dependency_drift")

    def test_dependency_cycle_is_rejected(self) -> None:
        self.fixture.root_index([
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"},
            {"patterns": ["base/**"], "context": "base/CONTEXT.md"},
        ])
        self.fixture.leaf(dependencies=["Base"], dependents=["Base"])
        self.fixture.leaf(path="base/CONTEXT.md", layer="Base", scope=["base/**"],
                          dependencies=["Source"], dependents=["Source"])
        self.assert_kind("dependency_cycle")

    def test_package_manifest_dependency_drift_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}])
        self.fixture.write("src/Package.swift", '.package(path: "../Ghost")\n')
        self.fixture.leaf(manifest={
            "kind": "swift-package", "path": "src/Package.swift", "local_dependencies": []
        })
        self.assert_kind("manifest_dependency_drift")

    def test_project_manifest_dependency_drift_is_rejected(self) -> None:
        self.fixture.root_index([{"patterns": ["src/**"], "context": "src/CONTEXT.md"}])
        self.fixture.write("src/project.yml", "targets:\n  App:\n    dependencies:\n      - package: Core\n")
        self.fixture.leaf(manifest={
            "kind": "xcodegen-target", "path": "src/project.yml", "target": "App",
            "local_dependencies": [],
        })
        self.assert_kind("manifest_dependency_drift")

class NestedLeafOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.fixture.root_index([
            {"patterns": ["Packages/**"], "context": "Packages/CONTEXT.md"},
        ])
        self.fixture.context("Packages/CONTEXT.md", {
            "schema": 1,
            "kind": "index",
            "routes": [{
                "patterns": ["Core/**"],
                "test_paths": ["Tests/test_core.py"],
                "context": "Core/CONTEXT.md",
            }],
            "exclusions": [{"patterns": ["CONTEXT.md"], "reason": "metadata"}],
        })
        self.fixture.leaf(
            path="Packages/Core/CONTEXT.md",
            layer="Core",
            parent="Packages/CONTEXT.md",
            scope=["Core/**"],
            test_paths=["Tests/test_core.py"],
        )

    def tearDown(self) -> None:
        self.fixture.close()

    def test_nested_leaf_scope_is_relative_to_parent_index(self) -> None:
        result = layer_context.resolve(self.fixture.root, "Packages/Core/source.py")
        self.assertEqual("Core", result.layer)
        self.assertEqual("Packages/Core/CONTEXT.md", result.context)

    def test_nested_leaf_test_path_is_relative_to_parent_index(self) -> None:
        result = layer_context.resolve(self.fixture.root, "Packages/Tests/test_core.py")
        self.assertEqual("Core", result.layer)
        self.assertEqual("Packages/Core/CONTEXT.md", result.context)


class ContainmentAndSchemaTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.outside = Fixture()
        self.addCleanup(self.fixture.close)
        self.addCleanup(self.outside.close)
        self.fixture.root_index()
        self.fixture.leaf()

    def test_positive_unique_mapping_and_justified_exclusion(self):
        self.fixture.write("src/a.py")
        self.fixture.git("add", "CONTEXT.md", "src")
        findings, counts = self.fixture.audit()
        self.assertEqual([], findings)
        self.assertEqual({"leaf": 2, "excluded": 1, "total": 3}, counts)
        result = layer_context.resolve(self.fixture.root, "CONTEXT.md")
        self.assertEqual("excluded", result.classification)
        self.assertEqual("routing metadata", result.reason)

    def test_absolute_inside_path_and_internal_symlink(self):
        self.fixture.write("src/a.py")
        (self.fixture.root / "src/link.py").symlink_to("a.py")
        for raw in (str(self.fixture.root / "src/a.py"), "./src/a.py", "src/link.py"):
            with self.subTest(raw=raw):
                self.assertEqual("Source", layer_context.resolve(self.fixture.root, raw).layer)
        result = layer_context.resolve(self.fixture.root, str(self.fixture.root / "src/link.py"))
        self.assertEqual("src/a.py", result.path)

    def test_escape_paths_rejected_before_outside_stat_or_read(self):
        original_stat = pathlib.Path.lstat
        original_read = pathlib.Path.read_text
        outside = self.outside.root

        def guarded_stat(path, *args, **kwargs):
            self.assertFalse(path == outside or outside in path.parents, str(path))
            return original_stat(path, *args, **kwargs)

        def guarded_read(path, *args, **kwargs):
            self.assertFalse(path == outside or outside in path.parents, str(path))
            return original_read(path, *args, **kwargs)

        self.outside.write("secret.py", "do not read")
        (self.fixture.root / "src/escape.py").symlink_to(outside / "secret.py")
        (self.fixture.root / "src/escape-dir").symlink_to(outside, target_is_directory=True)
        raw_paths = ["src/../../outside", str(outside / "secret.py"),
                     "src/escape.py", "src/escape-dir/secret.py",
                     "src/escape-dir/../src/a.py"]
        with mock.patch.object(pathlib.Path, "lstat", guarded_stat), \
                mock.patch.object(pathlib.Path, "read_text", guarded_read):
            for raw in raw_paths:
                with self.subTest(raw=raw), self.assertRaises(layer_context.ContextError):
                    layer_context.resolve(self.fixture.root, raw)

    def test_normalized_spelling_after_internal_symlink_cannot_escape(self):
        self.fixture.write("safe/inside.txt")
        (self.fixture.root / "src/link").symlink_to("../safe", target_is_directory=True)
        (self.fixture.root / "src/CONTEXT.md").unlink()
        (self.fixture.root / "src/CONTEXT.md").symlink_to(self.outside.root / "CONTEXT.md")
        # Raw traversal reaches the safe root context; collapsed spelling names
        # src/CONTEXT.md. That second target must also be checked before opening.
        with self.assertRaises(layer_context.ContextError):
            layer_context.parse_context(self.fixture.root, "src/link/../CONTEXT.md")

    def test_manifest_read_error_is_structured(self):
        self.fixture.write("src/manifest")
        self.fixture.leaf(manifest={"kind": "swift-package", "path": "src/manifest"})
        original = pathlib.Path.read_text

        def denied(path, *args, **kwargs):
            if path == self.fixture.root / "src/manifest":
                raise PermissionError("synthetic denied read")
            return original(path, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "read_text", denied), \
                mock.patch.object(layer_context, "tracked_files", return_value=[]):
            findings, _ = layer_context.audit(self.fixture.root)
        self.assertEqual(["invalid_manifest"], [item.kind for item in findings])
        self.assertIn("synthetic denied read", findings[0].detail)

    def test_escaped_routes_and_symlinked_contexts_are_not_read(self):
        self.outside.context("CONTEXT.md", {"kind": "index"})
        outside = self.outside.root / "CONTEXT.md"
        original = pathlib.Path.read_text

        def guarded_read(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), outside)
            return original(path, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "read_text", guarded_read):
            for target in ("src/../../" + self.outside.root.name + "/CONTEXT.md", str(outside)):
                self.fixture.root_index([{"patterns": ["src/**"], "context": target}])
                with self.assertRaises(layer_context.ContextError):
                    layer_context.resolve(self.fixture.root, "src/a.py")
                _, findings = layer_context.discover_contexts(self.fixture.root)
                self.assertIn("unsafe_path", [item.kind for item in findings])
            self.fixture.root_index()
            leaf = self.fixture.root / "src/CONTEXT.md"
            leaf.unlink()
            leaf.symlink_to(outside)
            _, findings = layer_context.discover_contexts(self.fixture.root)
            self.assertIn("unsafe_path", [item.kind for item in findings])
            root_context = self.fixture.root / "CONTEXT.md"
            root_context.unlink()
            root_context.symlink_to(outside)
            _, findings = layer_context.discover_contexts(self.fixture.root)
            self.assertIn("unsafe_path", [item.kind for item in findings])

    def test_manifest_escapes_never_read(self):
        self.outside.write("manifest", "outside")
        outside = self.outside.root / "manifest"
        (self.fixture.root / "src/manifest").symlink_to(outside)
        original = pathlib.Path.read_text

        def guarded_read(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), outside)
            return original(path, *args, **kwargs)

        for raw in (str(outside), "src/manifest", "src/../../manifest"):
            self.fixture.leaf(manifest={"kind": "swift-package", "path": raw})
            # Patch tracked_files, not process environment, for in-process I/O proof.
            with mock.patch.object(pathlib.Path, "read_text", guarded_read), \
                    mock.patch.object(layer_context, "tracked_files", return_value=[]):
                findings, _ = layer_context.audit(self.fixture.root)
            self.assertIn("unsafe_path", [item.kind for item in findings])

    def test_tracked_symlink_is_an_audit_finding(self):
        self.outside.write("secret.py")
        (self.fixture.root / "src/escape.py").symlink_to(self.outside.root / "secret.py")
        self.fixture.git("add", "src/escape.py")
        findings = self.fixture.findings()
        self.assertTrue(any(item.path == "src/escape.py" and "outside" in item.detail
                            for item in findings))

    def test_schema_versions_and_recognized_types_fail(self):
        valid = self.fixture.data()
        cases = [("schema", 2), ("schema", True), ("schema", "1"), ("schema", None),
                 ("layer", []), ("group", 3), ("scope", "src/**"),
                 ("dependencies", [4]), ("dependents", None), ("red_lines", [""]),
                 ("test_paths", [False]), ("gates", {}), ("manifest", []),
                 ("kind", []), ("parent", "../outside")]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.fixture.context("src/CONTEXT.md", dict(valid, **{key: value}))
                with self.assertRaises(layer_context.ContextError):
                    layer_context.parse_context(self.fixture.root, "src/CONTEXT.md")

    def test_legacy_missing_schema_and_extensible_metadata(self):
        data = self.fixture.data()
        del data["schema"]
        data["project_metadata"] = {"answer": 42}
        self.fixture.context("src/CONTEXT.md", data)
        result = self.fixture.cli("field", "Source", "project_metadata.answer")
        self.assertEqual((0, "42\n"), (result.returncode, result.stdout))

    def test_unjustified_exclusion_is_invalid_even_if_untracked(self):
        self.fixture.root_index([], [{"patterns": ["ignored/**"], "reason": " "}])
        self.assertIn("invalid_context", [f.kind for f in self.fixture.findings()])

    def test_malformed_frontmatter_and_missing_leaf_fields(self):
        for text in ("not frontmatter", "---\n{\n---\n", "---\n[]\n---\n",
                     "---\n" + json.dumps({"kind": "leaf", "layer": "Source"}) + "\n---\n"):
            self.fixture.write("src/CONTEXT.md", text)
            with self.assertRaises(layer_context.ContextError):
                layer_context.parse_context(self.fixture.root, "src/CONTEXT.md")

    def test_external_dependency_policy_is_explicit_and_exact(self):
        self.fixture.write("src/project.yml",
                           "targets:\n  Tool:\n    dependencies:\n"
                           "      - package: NeutralVendor\n      - package: Core\n")
        manifest = {"kind": "xcodegen-target", "path": "src/project.yml",
                    "target": "Tool", "local_dependencies": ["Core"]}
        self.fixture.leaf(manifest=manifest)
        self.assertIn("manifest_dependency_drift", [f.kind for f in self.fixture.findings()])
        manifest["external_dependencies"] = ["NeutralVendor"]
        self.fixture.leaf(manifest=manifest)
        self.assertEqual([], self.fixture.findings())
        manifest["external_dependencies"] = ["Neutral*"]
        self.fixture.leaf(manifest=manifest)
        self.assertIn("manifest_dependency_drift", [f.kind for f in self.fixture.findings()])

    def test_positive_package_manifest_dependencies(self):
        self.fixture.write("src/Package.swift", '.package(path: "../Core")\n')
        self.fixture.leaf(manifest={"kind": "swift-package", "path": "src/Package.swift",
                                    "local_dependencies": ["Core"]})
        self.assertEqual([], self.fixture.findings())

    def test_absolute_aliases_accept_inside_files_contexts_and_manifests(self):
        alias = self.outside.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        chained = self.outside.root / "chained-alias"
        chained.symlink_to("repo-alias", target_is_directory=True)
        self.fixture.write("src/a.py")
        (self.fixture.root / "src/internal.py").symlink_to("a.py")
        for prefix in (alias, chained):
            for name, expected in (("a.py", "src/a.py"), ("internal.py", "src/a.py"),
                                   ("not-created.py", "src/not-created.py")):
                with self.subTest(prefix=prefix, name=name):
                    result = layer_context.resolve(self.fixture.root, str(prefix / "src" / name))
                    self.assertEqual(("Source", expected), (result.layer, result.path))
            parsed = layer_context.parse_context(self.fixture.root, str(prefix / "src/CONTEXT.md"))
            self.assertEqual("src/CONTEXT.md", parsed["_context_path"])
        file_alias = self.outside.root / "file-alias"
        file_alias.symlink_to(self.fixture.root / "src/a.py")
        self.assertEqual("src/a.py", layer_context.resolve(self.fixture.root, str(file_alias)).path)
        self.fixture.write("src/Package.swift", '.package(path: "../Core")\n')
        self.fixture.leaf(manifest={"kind": "swift-package",
                                    "path": str(alias / "src/Package.swift"),
                                    "local_dependencies": ["Core"]})
        self.assertEqual([], self.fixture.findings())

    def test_host_tmp_alias_accepts_canonical_inside_path(self):
        # No host alias is created or changed: use the existing OS ancestor alias.
        if pathlib.Path("/tmp").resolve() != pathlib.Path("/private/tmp"):
            self.skipTest("host does not expose the macOS /tmp ancestor alias")
        fixture = Fixture(nested=True, directory="/tmp")
        self.addCleanup(fixture.close)
        fixture.root_index()
        fixture.leaf()
        alias = pathlib.Path("/tmp") / fixture.root.parent.name / fixture.root.name
        result = layer_context.resolve(fixture.root, str(alias / "src/a.py"))
        self.assertEqual(("Source", "src/a.py"), (result.layer, result.path))

    def test_outside_alias_refused_before_any_file_content_read(self):
        self.outside.write("payload", "synthetic outside content")
        alias = self.outside.root / "outside-alias"
        alias.symlink_to(self.outside.root, target_is_directory=True)
        paths = [str(alias / "payload"), str(alias / "missing"),
                 str(self.outside.root / "payload")]
        with mock.patch.object(pathlib.Path, "read_text") as read, \
                mock.patch.object(layer_context.subprocess, "run") as child:
            for raw in paths:
                for operation in (layer_context.resolve, layer_context.parse_context,
                                  layer_context._manifest_text):
                    with self.subTest(raw=raw, operation=operation.__name__):
                        with self.assertRaises(layer_context.ContextError):
                            operation(self.fixture.root, raw)
            read.assert_not_called()
            child.assert_not_called()

    def test_inside_alias_cannot_escape_or_reenter_via_parent_or_symlink(self):
        alias = self.outside.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        (self.fixture.root / "src/outside").symlink_to(self.outside.root, target_is_directory=True)
        for raw in (str(alias / "../outside"), str(alias / "src/../../outside"),
                    str(alias / "src/outside/payload"),
                    str(alias / "src/outside/repo-alias/src/a.py")):
            with self.subTest(raw=raw), mock.patch.object(pathlib.Path, "read_text") as read:
                with self.assertRaises(layer_context.ContextError):
                    layer_context.resolve(self.fixture.root, raw)
                read.assert_not_called()

    def test_absolute_alias_cycle_is_bounded_without_content_access(self):
        alias = self.outside.root / "cycle"
        alias.symlink_to("cycle", target_is_directory=True)
        with mock.patch.object(pathlib.Path, "read_text") as read:
            with self.assertRaisesRegex(layer_context.ContextError, "symlink cycle"):
                layer_context.resolve(self.fixture.root, str(alias / "payload"))
            read.assert_not_called()


def matches_documented_schema(value, schema, document):
    """Test-only evaluator for the exact keywords used in these two documents.

    This is deliberately not a general JSON Schema validator. Unknown assertion
    keywords fail the test so added schema rules cannot silently go untested.
    """
    supported = {"$schema", "$defs", "$ref", "title", "description", "type", "const",
                 "enum", "required", "properties", "additionalProperties", "allOf",
                 "anyOf", "not", "if", "then", "items", "minItems", "maxItems",
                 "minLength", "pattern"}
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


class SchemaDocumentTests(unittest.TestCase):
    def test_context_document_and_runtime_agree_on_recognized_shapes(self):
        schema = json.loads((REPO / "schemas/context-v1.schema.json").read_text())
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        base = {"schema": 1, "kind": "leaf", "layer": "Unit", "parent": "CONTEXT.md", "scope": ["src/**"]}
        valid = [base, {k: v for k, v in base.items() if k != "schema"}, {"kind": "index"},
                 dict(base, custom={"arbitrary": [1, False]}),
                 dict(base, gates=[{"id": "t", "kind": "test", "mode": "both", "command": ["tool"]}])]
        invalid = []
        for field in ("scope", "test_paths", "dependencies", "dependents", "red_lines"):
            invalid.extend(dict(base, **{field: value}) for value in (None, {}, "bad", [1], [" "], ["\0"]))
        for field in ("layer", "parent", "group"):
            invalid.extend(dict(base, **{field: value}) for value in (None, [], 1, "", " "))
        invalid.extend(dict(base, schema=value) for value in (0, 2, "1", True, None))
        invalid.extend([
            dict(base, routes=[]), dict(base, exclusions=[]), dict(base, gates={}),
            dict(base, manifest={"kind": "unknown", "path": "file"}),
            dict(base, manifest={"kind": "xcodegen-target", "path": "file"}),
            dict(base, manifest={"kind": "swift-package", "path": "file", "local_dependencies": [1]}),
            {"kind": "index", "layer": "Bad"},
            {"kind": "index", "routes": [{"patterns": ["src/**"]}]},
            {"kind": "index", "exclusions": [{"patterns": ["src/**"], "reason": " "}]},
            {"kind": "leaf", "layer": "Unit", "parent": "CONTEXT.md"},
        ])
        for expected, cases in ((True, valid), (False, invalid)):
            for data in cases:
                with self.subTest(data=data):
                    self.assertEqual(expected, matches_documented_schema(data, schema, schema))
                    if expected:
                        layer_context.validate_context(data, "synthetic")
                    else:
                        with self.assertRaises(layer_context.ContextError):
                            layer_context.validate_context(data, "synthetic")

    def test_finding_document_matches_real_cli_failure(self):
        fixture = Fixture()
        self.addCleanup(fixture.close)
        fixture.root_index()
        fixture.leaf()
        schema = json.loads((REPO / "schemas/finding-v1.schema.json").read_text())
        finding = json.loads(fixture.cli("resolve", "orphan").stderr)
        self.assertTrue(matches_documented_schema(finding, schema, schema))
        for key in finding:
            invalid = dict(finding)
            del invalid[key]
            self.assertFalse(matches_documented_schema(invalid, schema, schema))
        self.assertFalse(matches_documented_schema(dict(finding, red_lines="bad"), schema, schema))
        self.assertFalse(matches_documented_schema(dict(finding, extra=True), schema, schema))
