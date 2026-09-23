"""Explicit public subprocess assertions; NOT RUN at authoring.

External D1 acceptance and content admission must precede this separate entry.
No unittest discovery, resolver imports, ambient packages or product workloads.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import types


# Frozen r2 table expectations, not derived from candidate discovery. Later
# certification must retain independently controlled expectations outside C1.
EXPECTED_ENTRIES = json.loads(r'''[{"id":"cap.context.audit","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/audit"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"audit"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/fixture.py","scope":"synthetic-test-source"},{"type":"example","path":"tests/context/test_resolution.py","scope":"synthetic-test-source"}]},{"id":"cap.context.contexts","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/contexts"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"contexts"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/test_cli_contract.py","scope":"synthetic-test-source"}]},{"id":"cap.context.field","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/field"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"field"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/test_cli_contract.py","scope":"synthetic-test-source"}]},{"id":"cap.context.layers","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/layers"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"layers"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/test_cli_contract.py","scope":"synthetic-test-source"}]},{"id":"cap.context.resolve","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/resolve"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"resolve"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/test_cli_contract.py","scope":"synthetic-test-source"},{"type":"example","path":"tests/context/test_resolution.py","scope":"synthetic-test-source"}]},{"id":"cap.context.run","kind":"capability","interface":{"kind":"context","wrapper":{"type":"source","path":"scripts/context/run"},"direct":{"source":{"type":"source","path":"scripts/context/_context.py"},"command":"run"}},"contract":"doc.context","schemas":[{"type":"schema","path":"schemas/context-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/context/test_fixture_hooks.py","scope":"synthetic-test-source"},{"type":"example","path":"tests/context/test_runner.py","scope":"synthetic-test-source"}]},{"id":"cap.contract.resolve","kind":"capability","interface":{"kind":"resolver","source":{"type":"source","path":"scripts/contracts/resolve.py"},"python_flags":["-I","-S","-B"],"required_options":["--git","--revision","--entry"]},"contract":"doc.registry","schemas":[{"type":"schema","path":"schemas/ai-registry-v1.schema.json","pointer":"/$defs/finding"},{"type":"schema","path":"schemas/ai-registry-v1.schema.json","pointer":"/$defs/result"},{"type":"schema","path":"schemas/ai-registry-v1.schema.json","pointer":"/$defs/stored"},{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"examples/contracts/resolve-from-caller.sh","scope":"isolated-distribution-consumer"},{"type":"example","path":"tests/contracts/test_isolation.py","scope":"synthetic-test-source"},{"type":"example","path":"tests/contracts/test_registry_consistency.py","scope":"synthetic-test-source"},{"type":"example","path":"tests/contracts/test_resolution.py","scope":"synthetic-test-source"}]},{"id":"cap.policy.evaluate","kind":"capability","interface":{"kind":"function","source":{"type":"source","path":"scripts/policy/validate.py"},"symbol":"evaluate_policy","parameters":[{"name":"baseline","annotation":"dict","kind":"keyword-only","required":true},{"name":"candidate","annotation":"dict","kind":"keyword-only","required":true},{"name":"approvals","annotation":"list","kind":"keyword-only","required":true},{"name":"observation","annotation":"dict","kind":"keyword-only","required":true}],"returns":"dict","dependencies":[]},"contract":"doc.policy","schemas":[{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/policy-exception-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/policy-input-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/policy/test_validation.py","scope":"synthetic-test-source"}]},{"id":"cap.quality.aggregate","kind":"capability","interface":{"kind":"function","source":{"type":"source","path":"scripts/quality/aggregate.py"},"symbol":"aggregate_6dq","parameters":[{"name":"expectation","annotation":"dict","kind":"keyword-only","required":true},{"name":"evidence","annotation":"dict","kind":"keyword-only","required":true}],"returns":"dict","dependencies":["cap.policy.evaluate"]},"contract":"doc.quality","schemas":[{"type":"schema","path":"schemas/finding-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/quality-input-v1.schema.json","pointer":""},{"type":"schema","path":"schemas/quality-result-v1.schema.json","pointer":""}],"examples":[{"type":"example","path":"tests/quality/test_aggregation.py","scope":"synthetic-test-source"}]},{"id":"doc.architecture","kind":"document","resource":{"type":"document","path":"docs/architecture.md","anchor":null}},{"id":"doc.compatibility","kind":"document","resource":{"type":"document","path":"docs/integration-and-migration.md","anchor":"compatibility"}},{"id":"doc.context","kind":"document","resource":{"type":"document","path":"docs/context-cli-contract.md","anchor":null}},{"id":"doc.evidence","kind":"document","resource":{"type":"document","path":"docs/integration-and-migration.md","anchor":"existing-fixtures-and-evidence"}},{"id":"doc.examples","kind":"document","resource":{"type":"document","path":"docs/integration-and-migration.md","anchor":"existing-fixtures-and-evidence"}},{"id":"doc.failure.context","kind":"document","resource":{"type":"document","path":"docs/context-cli-contract.md","anchor":"commands-and-outputs"}},{"id":"doc.failure.policy","kind":"document","resource":{"type":"document","path":"docs/policy-validation-contract.md","anchor":"deterministic-failure-order-and-kinds"}},{"id":"doc.failure.quality","kind":"document","resource":{"type":"document","path":"docs/quality-aggregation-contract.md","anchor":"exact-state-machine-and-findings"}},{"id":"doc.failure.registry","kind":"document","resource":{"type":"document","path":"docs/registry-resolution-contract.md","anchor":"errors"}},{"id":"doc.index","kind":"document","resource":{"type":"document","path":"README.md","anchor":null}},{"id":"doc.integration","kind":"document","resource":{"type":"document","path":"docs/integration-and-migration.md","anchor":"fixed-checkout-surfaces"}},{"id":"doc.migration","kind":"document","resource":{"type":"document","path":"docs/integration-and-migration.md","anchor":"migration-and-rollback"}},{"id":"doc.policy","kind":"document","resource":{"type":"document","path":"docs/policy-validation-contract.md","anchor":null}},{"id":"doc.quality","kind":"document","resource":{"type":"document","path":"docs/quality-aggregation-contract.md","anchor":null}},{"id":"doc.recovery","kind":"document","resource":{"type":"document","path":"docs/disaster-recovery.md","anchor":null}},{"id":"doc.registry","kind":"document","resource":{"type":"document","path":"docs/registry-resolution-contract.md","anchor":null}},{"id":"doc.registry.example","kind":"document","resource":{"type":"document","path":"docs/registry-resolution-contract.md","anchor":"offline-consumer-example"}},{"id":"doc.usage","kind":"document","resource":{"type":"document","path":"docs/ai-usage.md","anchor":null}},{"id":"task.change","kind":"task","documents":["doc.architecture","doc.registry","doc.context","doc.policy","doc.quality","doc.examples"]},{"id":"task.diagnose","kind":"task","documents":["doc.failure.registry","doc.failure.context","doc.failure.policy","doc.failure.quality","doc.recovery"]},{"id":"task.integrate","kind":"task","documents":["doc.integration","doc.registry","doc.registry.example","doc.context","doc.policy","doc.quality"]},{"id":"task.upgrade","kind":"task","documents":["doc.compatibility","doc.migration"]}]''')
USAGE = b"usage: resolve.py --git ABSOLUTE_GIT --revision FULL_SHA --entry ENTRY_ID\n"
ERRORS = {
    "provider_tool_unavailable": ("Required admitted tool is unavailable.", "tool-admission"),
    "provider_distribution_unsupported": ("Provider distribution is unsupported.", "distribution"),
    "provider_revision_mismatch": ("Provider and resolver revision binding failed.", "revision-binding"),
    "registry_invalid": ("Stored registry is invalid.", "stored-registry"),
    "registry_schema_unsupported": ("Registry schema version is unsupported.", "stored-registry"),
    "contract_missing": ("Required committed resource is unavailable.", "resources"),
    "contract_reference_invalid": ("Contract reference is invalid.", "resources"),
    "contract_api_drift": ("Public capability inventory differs from committed source.", "capability-parity"),
    "contract_entry_unknown": ("Requested entry is unknown.", "cli"),
}

# Definition-shape regressions are data, shared with the separately admitted
# schema-engine stage. No resolver implementation is imported by either stage.
INVALID_SCHEMA_DEFINITIONS = (
    {"type": "not-a-json-schema-type"},
    {"type": None},
    {"type": []},
    {"type": ["string", None]},
    {"type": ["string", "string"]},
    {"properties": []},
    {"properties": {"name": None}},
    {"$defs": []},
    {"$defs": {"broken": 1}},
    {"oneOf": {}},
    {"oneOf": []},
    {"oneOf": [{"type": "string"}, None]},
    {"anyOf": [False, {"properties": []}]},
    {"allOf": [{"required": ["name", {}]}]},
    {"required": "name"},
    {"required": [None, "schema"]},
    {"required": ["name", {}]},
    {"required": ["name", ["nested"]]},
    {"required": ["name", "name"]},
    {"additionalProperties": []},
    {"items": [{"type": "string"}]},
    {"not": 1},
    {"if": {"type": "invalid"}},
    {"then": None},
    {"else": []},
    {"propertyNames": {"type": "invalid"}},
    {"minItems": -1},
    {"maxLength": 1.5},
    {"minimum": True},
    {"maximum": "1"},
    {"uniqueItems": "true"},
    {"pattern": []},
    {"enum": {}},
    {"examples": {}},
)

VALID_SCHEMA_DEFINITIONS = (
    True,
    False,
    {},
    {"type": ["string", "null"]},
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    {"properties": {"type": {"const": "data"}, "$ref": {"type": "string"},
                    "required": True, "oneOf": False}},
    {"allOf": [True, {"anyOf": [{"type": "string"}, {"type": "null"}]}],
     "oneOf": [False, {"not": False}], "if": True, "then": {}, "else": False},
    {"items": {"type": "integer"}, "minItems": 0.0, "uniqueItems": True},
    {"propertyNames": {"pattern": "^[a-z]+$"}, "additionalProperties": {"type": "string"}},
    {"enum": []},
    # These schema-looking values are instances/annotations, not schema positions.
    {"const": {"type": "invalid", "properties": [], "required": [None, "schema"]},
     "default": {"$ref": "https://example.invalid/inert", "$id": "https://example.invalid/inert"},
     "enum": [{"oneOf": [None]}], "examples": [{"$defs": []}],
     "x-annotation": {"type": "object", "required": [None, "schema"], "properties": []}},
)


def load_fixture():
    source = Path(__file__).resolve().with_name("fixture.py")
    module = types.ModuleType("reviewed_contract_fixture")
    module.__file__ = str(source)
    exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
    return module


def wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def finding(kind):
    detail, anchor = ERRORS[kind]
    return {"layer": "contracts", "path": "scripts/contracts/resolve.py" if kind.startswith("provider_") else "ai/registry.json",
            "kind": kind, "detail": detail + " Repair: docs/registry-resolution-contract.md#" + anchor, "red_lines": []}


def failure(result, kind):
    assert (result.returncode, result.stdout, result.stderr) == (1, b"", wire(finding(kind)))


def expected_result(distribution, selected):
    entries = {entry["id"]: entry for entry in EXPECTED_ENTRIES}
    closure = set()

    def visit(key):
        if key in closure:
            return
        closure.add(key)
        entry = entries[key]
        if entry["kind"] == "task":
            for doc in entry["documents"]:
                visit(doc)
        if entry["kind"] == "capability":
            visit(entry["contract"])
            for dependency in entry["interface"].get("dependencies", []):
                visit(dependency)

    visit(selected)
    selected_entries = [entries[key] for key in sorted(closure)]
    references = []
    for entry in selected_entries:
        if entry["kind"] == "document":
            references.append(entry["resource"])
        if entry["kind"] == "capability":
            interface = entry["interface"]
            references += ([interface["wrapper"], interface["direct"]["source"]]
                           if interface["kind"] == "context" else [interface["source"]])
            references += entry["schemas"] + entry["examples"]
    unique = {}
    for ref in references:
        key = (ref["path"], ref["type"], ref.get("anchor") or ref.get("pointer") or ref.get("scope") or "")
        unique[key] = ref
    resources = []
    for key, ref in sorted(unique.items()):
        mark, raw = distribution.mark(ref["path"])
        resources.append({"ref": ref, "object": mark, "text": raw.decode("utf-8") if ref["type"] == "document" else None})
    tree = distribution.run.git(distribution.root, "rev-parse", distribution.revision + "^{tree}").stdout.decode().strip()
    return {"schema": 1, "provider": {"repository_id": "1380829073", "library": "shared-ci", "unit": "git-source"},
            "revision": distribution.revision, "tree": tree, "basis": {
                key: distribution.mark(path)[0] for key, path in (
                    ("registry", "ai/registry.json"), ("schema", "schemas/ai-registry-v1.schema.json"),
                    ("resolver", "scripts/contracts/resolve.py"))},
            "selected": selected, "entries": selected_entries, "resources": resources}


def positive(distribution):
    for entry in EXPECTED_ENTRIES:
        result = distribution.resolve(entry["id"])
        assert (result.returncode, result.stdout, result.stderr) == (0, wire(expected_result(distribution, entry["id"])), b"")
    failure(distribution.resolve("doc.unknown"), "contract_entry_unknown")


def cli(distribution):
    base = ["--git", distribution.run.options.git, "--revision", distribution.revision, "--entry", "task.upgrade"]
    cases = [([], "missing required option --git"),
             (["--revision", distribution.revision], "missing required option --git"),
             (base[:2], "missing required option --revision"),
             (base[:4], "missing required option --entry")]
    for token in ("positional", "--unknown", "--rev", "-h", "--help"):
        cases.append((base + [token], "unknown or positional argument"))
    for option in ("--git", "--revision", "--entry"):
        cases += [(base + [option, "value"], "repeated option"), ([option], "missing option value"),
                  ([option + "="], "missing option value"), ([option, "--unknown"], "missing option value")]
    for index, values in ((1, ["git", "relative/git"]), (3, ["0" * 40, "A" * 40, "a" * 39, "main", "1.0"]),
                          (5, ["Task.upgrade", "task..upgrade", "task/upgrade", "*", "task-upgrade-"])):
        for value in values:
            tokens = base.copy()
            tokens[index] = value
            cases.append((tokens, "invalid value for " + base[index - 1]))
    for tokens, message in cases:
        result = distribution.resolve(tokens=tokens)
        assert (result.returncode, result.stdout, result.stderr) == (2, b"", USAGE + ("error: " + message + "\n").encode())
    for help_token in ("-h", "--help"):
        result = distribution.resolve(tokens=[help_token])
        assert (result.returncode, result.stdout, result.stderr) == (
            0, USAGE + b"Resolve one committed registry entry; tools and distribution require external admission.\n", b"")
    equal = [base[i] + "=" + base[i + 1] for i in (0, 2, 4)]
    assert distribution.resolve(tokens=equal).stdout == wire(expected_result(distribution, "task.upgrade"))
    failure(distribution.resolve(revision="1" * 40), "provider_revision_mismatch")
    bad_git = base.copy()
    bad_git[1] = str(distribution.run.root / "tools/absent")
    failure(distribution.resolve(tokens=bad_git), "provider_tool_unavailable")


def negatives(distribution):
    serial = 0

    def candidate(edit, kind, entry="task.upgrade"):
        nonlocal serial
        serial += 1
        root, pin = distribution.negative(str(serial), edit)
        failure(distribution.resolve(entry, root=root, revision=pin), kind)
        return root, pin

    def registry(change):
        def edit(root):
            path = root / "ai/registry.json"
            data = json.loads(path.read_bytes())
            change(data)
            path.write_text(json.dumps(data), encoding="utf-8")
        return edit

    def replace(path, before, after):
        def edit(root):
            target = root / path
            raw = target.read_bytes()
            assert before in raw
            target.write_bytes(raw.replace(before, after, 1))
        return edit

    def raw_registry(raw):
        return lambda root: (root / "ai/registry.json").write_bytes(raw)

    for value in (True, 1.0, "1", None):
        candidate(registry(lambda d, v=value: d.update(schema=v)), "registry_invalid")
    candidate(registry(lambda d: d.update(schema=2, unexpected=True)), "registry_schema_unsupported")
    for raw in (b'\xef\xbb\xbf{}', b'{"schema":1,"schema":1}', b'{"schema":NaN}', b'{} trailing',
                b'{"schema":1,"x":"\\ud800"}', b'\xff', b'{"schema":Infinity}',
                b'{"schema":1,"nested":{"x":1,"x":2}}'):
        candidate(raw_registry(raw), "registry_invalid")
    for change in (lambda d: d.update(extra=None), lambda d: d["provider"].update(repository_id="1"),
                   lambda d: d["entries"].reverse(), lambda d: d["entries"].append(d["entries"][0]),
                   lambda d: d["entries"].__setitem__(1, d["entries"][0]),
                   lambda d: d.update(release_notes="README.md")):
        candidate(registry(change), "registry_invalid")
    for kind in ("document", "task", "capability"):
        candidate(registry(lambda d, k=kind: d["entries"].remove(next(e for e in d["entries"] if e["kind"] == k))), "registry_invalid")
    candidate(registry(lambda d: d["entries"][0].update(kind="task")), "registry_invalid")
    for path in ("../README.md", "/README.md", "docs//x", "docs/./x", "docs/x?y", "docs/x#y", "docs\\x", "docs/\x85x"):
        candidate(registry(lambda d, p=path: next(e for e in d["entries"] if e["id"] == "doc.index")["resource"].update(path=p)), "contract_reference_invalid")
    for pointer in ("$defs/stored", "/$defs/", "/$defs~1stored", "/$defs/missing", "/entries/0"):
        def change_pointer(data, p=pointer):
            schemas = next(e for e in data["entries"] if e["id"] == "cap.contract.resolve")["schemas"]
            schemas[0]["pointer"] = p
            schemas.sort(key=lambda ref: (ref["path"], ref["pointer"]))
        candidate(registry(change_pointer), "contract_reference_invalid")
    candidate(registry(lambda d: next(e for e in d["entries"] if e["id"] == "task.upgrade")["documents"].append("doc.absent")), "contract_reference_invalid")
    candidate(registry(lambda d: next(e for e in d["entries"] if e["id"] == "cap.quality.aggregate")["interface"].update(dependencies=["cap.quality.aggregate"])), "contract_reference_invalid")
    for path in ("docs/disaster-recovery.md", "schemas/context-v1.schema.json", "tests/context/test_runner.py", "scripts/context/audit"):
        candidate(lambda root, p=path: (root / p).unlink(), "contract_missing")
    for path in ("scripts/context/audit", "examples/contracts/resolve-from-caller.sh"):
        candidate(lambda root, p=path: (root / p).chmod(0o644), "contract_api_drift")
    candidate(replace("scripts/context/audit", b'_context.py" audit', b'_context.py" changed'), "contract_api_drift")
    candidate(replace("scripts/context/_context.py", b'command_name == "audit"', b'command_name == "changed"'), "contract_api_drift")
    candidate(replace("scripts/context/_context.py", b'default="json"', b'default="layer"'), "contract_api_drift")
    for before, after in ((b'*, baseline: dict', b'*, added: dict, baseline: dict'),
                          (b'observation: dict) -> dict', b'observation: dict = None) -> dict'),
                          (b'*, baseline: dict', b'baseline: dict, *')):
        candidate(replace("scripts/policy/validate.py", before, after), "contract_api_drift")
    for before, after in ((b'*, expectation: dict', b'*, added: dict, expectation: dict'),
                          (b'evidence: dict) -> dict', b'evidence: dict = None) -> dict'),
                          (b'*, expectation: dict', b'expectation: dict, *')):
        candidate(replace("scripts/quality/aggregate.py", before, after), "contract_api_drift")
    candidate(replace("scripts/quality/aggregate.py", b'from scripts.policy.validate import evaluate_policy', b'from scripts.policy.validate import missing_policy'), "contract_api_drift")
    candidate(replace("docs/integration-and-migration.md", b'## Compatibility', b'## Changed compatibility'), "contract_reference_invalid")
    candidate(replace("docs/integration-and-migration.md", b'## Compatibility', b'## Compatibility\n\n## Compatibility'), "contract_reference_invalid")
    candidate(replace("docs/integration-and-migration.md", b'## Compatibility', b'```markdown\n## Compatibility\n```'), "contract_reference_invalid")
    candidate(lambda root: (root / "docs/integration-and-migration.md").write_bytes(b'\xff'), "contract_reference_invalid")
    candidate(lambda root: (root / "schemas/context-v1.schema.json").write_text('{"$ref":"https://example.invalid/schema"}'), "contract_reference_invalid")
    candidate(lambda root: (root / "schemas/ai-registry-v1.schema.json").write_text('{}'), "contract_reference_invalid")
    candidate(lambda root: (root / "schemas/context-v1.schema.json").write_text('{"$ref":"#/$defs/absent"}'), "contract_reference_invalid")

    def symlink(root):
        (root / "docs/disaster-recovery.md").unlink()
        (root / "docs/disaster-recovery.md").symlink_to("architecture.md")
    candidate(symlink, "contract_reference_invalid")
    def directory(root):
        target = root / "docs/disaster-recovery.md"
        target.unlink()
        target.mkdir()
        (target / "nested").write_text("synthetic")
    candidate(directory, "contract_reference_invalid")
    # Gitlink is created in the isolated index only, never through submodule I/O.
    root = distribution.materialize("provider/gitlink")
    distribution.run.git(root, "update-index", "--add", "--cacheinfo", "160000," + distribution.revision + ",docs/disaster-recovery.md")
    distribution.run.git(root, "commit", "-m", "synthetic gitlink")
    pin = distribution.run.git(root, "rev-parse", "HEAD").stdout.decode().strip()
    failure(distribution.resolve(root=root, revision=pin), "contract_reference_invalid")
    # Pairwise precedence; unknown selection never conceals global breakage.
    candidate(raw_registry(b'{}'), "registry_invalid", "doc.unknown")
    def missing_and_drift(root):
        (root / "docs/disaster-recovery.md").unlink()
        (root / "scripts/context/audit").chmod(0o644)
    candidate(missing_and_drift, "contract_missing")
    root, pin = candidate(raw_registry(b'{}'), "registry_invalid")
    failure(distribution.resolve(root=root, revision=distribution.revision), "provider_revision_mismatch")
    # Full document content, not an anchor excerpt or normalized newline stream.
    root, pin = distribution.negative("text-preservation", lambda root: (root / "README.md").write_bytes("# Synthetic\r\nUnicode 文本\r\nno final newline".encode()))
    alternate = copy.copy(distribution)
    alternate.root, alternate.revision = root, pin
    result = alternate.resolve("doc.index")
    assert (result.returncode, result.stdout, result.stderr) == (0, wire(expected_result(alternate, "doc.index")), b"")
    # Mixed resolvers from two existing committed pins fail before registry work.
    root, pin = distribution.negative("resolver-successor", lambda root: (root / "scripts/contracts/resolve.py").write_bytes(
        (root / "scripts/contracts/resolve.py").read_bytes() + b"\n# distinct committed resolver\n"))
    (root / "scripts/contracts/resolve.py").write_bytes((distribution.root / "scripts/contracts/resolve.py").read_bytes())
    failure(distribution.resolve(root=root, revision=pin), "provider_revision_mismatch")


def schema_definitions(distribution):
    """Exact public-CLI shape failures, precedence and schema-position controls."""
    def malformed(label, edit):
        root, pin = distribution.negative("schema-" + label, edit)
        for selected in ("task.upgrade", "doc.unknown"):
            # Includes exact status, empty stdout and the single fixed finding:
            # neither a traceback nor provider_distribution_unsupported is valid.
            failure(distribution.resolve(selected, root=root, revision=pin), "contract_reference_invalid")

    for index, definition in enumerate(INVALID_SCHEMA_DEFINITIONS):
        def referenced(root, value=definition):
            (root / "schemas/context-v1.schema.json").write_text(json.dumps(value), encoding="utf-8")

        def registry(root, value=definition):
            path = root / "schemas/ai-registry-v1.schema.json"
            schema = json.loads(path.read_bytes())
            schema["$defs"]["id"] = value
            path.write_text(json.dumps(schema), encoding="utf-8")

        malformed("referenced-" + str(index), referenced)
        malformed("registry-id-" + str(index), registry)

    # Exact Standards P1 location: a mixed null/string required list in stored.
    # Include unhashable members to guard both sorting and deduplication paths.
    for index, required in enumerate(([None, "schema"], ["schema", {}], ["schema", ["nested"]])):
        def stored_required(root, value=required):
            path = root / "schemas/ai-registry-v1.schema.json"
            schema = json.loads(path.read_bytes())
            schema["$defs"]["stored"]["required"] = value
            path.write_text(json.dumps(schema), encoding="utf-8")
        malformed("stored-required-" + str(index), stored_required)

    # An explicit reference target is a schema position even when its original
    # location is an otherwise inert annotation. Local cycles must terminate.
    def bad_target(root):
        (root / "schemas/context-v1.schema.json").write_text(json.dumps({
            "$ref": "#/default", "default": {"type": "invalid"}}), encoding="utf-8")
    malformed("referenced-target", bad_target)

    def valid(root):
        path = root / "schemas/ai-registry-v1.schema.json"
        schema = json.loads(path.read_bytes())
        for index, definition in enumerate(VALID_SCHEMA_DEFINITIONS):
            schema["$defs"]["shape-probe-" + str(index)] = definition
        schema["$defs"]["shape-cycle"] = {"$ref": "#/$defs/shape-cycle"}
        path.write_text(json.dumps(schema), encoding="utf-8")
        (root / "schemas/context-v1.schema.json").write_text(json.dumps({
            "$defs": {"node": {"$ref": "#/$defs/node"}},
            "allOf": list(VALID_SCHEMA_DEFINITIONS), "$ref": "#/$defs/node"}), encoding="utf-8")

    root, pin = distribution.negative("schema-valid-positions", valid)
    alternate = copy.copy(distribution)
    alternate.root, alternate.revision = root, pin
    for selected in ("task.upgrade", "cap.contract.resolve", "cap.context.resolve"):
        result = alternate.resolve(selected)
        assert (result.returncode, result.stdout, result.stderr) == (
            0, wire(expected_result(alternate, selected)), b"")
    failure(alternate.resolve("doc.unknown"), "contract_entry_unknown")


def distributions(distribution):
    run = distribution.run
    for label, edit in (
        ("shallow", lambda root: (root / ".git/shallow").write_text(distribution.revision + "\n")),
        ("alternates", lambda root: (root / ".git/objects/info/alternates").write_text("/nonexistent\n")),
        ("promisor", lambda root: (root / ".git/objects/pack/synthetic.promisor").write_text("")),
        ("partial", lambda root: (root / ".git/config").write_text((root / ".git/config").read_text() + '\n[extensions]\npartialClone = synthetic\n')),
    ):
        root = distribution.materialize("provider/" + label)
        edit(root)
        failure(distribution.resolve(root=root), "provider_distribution_unsupported")
    archive = run.target("provider/archive")
    archive.mkdir()
    for path in run.record["source"]["files"]:
        target = archive / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((distribution.root / path).read_bytes())
    failure(distribution.resolve(root=archive), "provider_distribution_unsupported")
    linked = run.target("provider/linked")
    run.git(distribution.root, "worktree", "add", "--detach", str(linked), distribution.revision)
    failure(distribution.resolve(root=linked), "provider_distribution_unsupported")
    run.git(distribution.root, "worktree", "remove", str(linked))
    # An independently materialized negative commit creates a unique loose blob;
    # removing exactly that object cannot fall back to an existing pack copy.
    root, pin = distribution.negative("absent-object", lambda root: (root / "docs/disaster-recovery.md").write_text("unique absent-object probe\n"))
    mark, _ = distribution.mark("docs/disaster-recovery.md", root, pin)
    (root / ".git/objects" / mark["blob"][:2] / mark["blob"][2:]).unlink()
    failure(distribution.resolve(root=root, revision=pin), "contract_missing")
    # Attached HEAD, same pin, is a v1 revision mismatch (not authentication).
    root = distribution.materialize("provider/attached")
    run.git(root, "checkout", "-b", "synthetic-attached")
    failure(distribution.resolve(root=root), "provider_revision_mismatch")
    # Minimal source-bearing unsupported distributions, with no checkout fallback.
    for label, args in (("bare", ["--bare", "--object-format=sha1"]),
                        ("sha256", ["--object-format=sha256"])):
        root = run.target("provider/" + label)
        run.git(run.root, "init", "--template=", *args, str(root))
        target = root / "scripts/contracts/resolve.py"
        target.parent.mkdir(parents=True)
        target.write_bytes((distribution.root / "scripts/contracts/resolve.py").read_bytes())
        failure(distribution.resolve(root=root), "provider_distribution_unsupported")


def journey(distribution):
    run = distribution.run
    expected = wire(expected_result(distribution, "task.upgrade"))
    reference = run.write("caller/reference.json", json.dumps({"provider": str(distribution.root), "revision": distribution.revision}))
    old = reference.read_bytes()
    argv = [run.options.shell, str(distribution.root / "examples/contracts/resolve-from-caller.sh"),
            "--python", run.options.python, "--git", run.options.git, str(distribution.root), distribution.revision, "task.upgrade"]
    result = run.call(argv, cwd=distribution.caller)
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b"")
    for wrong in (argv[1:2], argv[1:3], [argv[1], "--python", "relative", "--git", run.options.git,
                                       str(distribution.root), distribution.revision, "task.upgrade"]):
        refused = run.call([run.options.shell] + wrong, cwd=distribution.caller)
        assert refused.returncode == 2 and refused.stdout == b"" and refused.stderr
    # Use a run-owned producer to demonstrate independence without renaming or
    # removing the externally admitted original source checkout.
    producer = distribution.materialize("provider/bundle-producer")
    second_bundle = run.root / "cache/independent.bundle"
    assert run.git(producer, "rev-parse", "HEAD").stdout.decode().strip() == distribution.revision
    run.git(producer, "bundle", "create", str(second_bundle), "HEAD")
    producer.rename(run.root / "provider/producer-unavailable")
    original_bundle = distribution.bundle
    distribution.bundle = second_bundle
    independent = distribution.materialize("provider/independent")
    distribution.bundle = original_bundle
    assert not producer.exists()
    assert distribution.resolve(root=independent).stdout == expected
    reference.write_text(json.dumps({"provider": str(distribution.root), "revision": "1" * 40}))
    failure(distribution.resolve(revision="1" * 40), "provider_revision_mismatch")
    dirty_doc = distribution.root / "docs/integration-and-migration.md"
    original = dirty_doc.read_bytes()
    dirty_doc.write_bytes(b"dirty provider document\r\n")
    assert distribution.resolve().stdout == expected
    dirty_doc.write_bytes(original)
    resolver = distribution.root / "scripts/contracts/resolve.py"
    original = resolver.read_bytes()
    resolver.write_bytes(original + b"\n# mixed revision probe\n")
    failure(distribution.resolve(), "provider_revision_mismatch")
    resolver.write_bytes(original)
    # All hostile inputs point inside this run; none references real user state.
    decoys = run.root / "cache/decoys"
    decoys.mkdir()
    run.write("cache/decoys/sitecustomize.py", "raise RuntimeError('must not load')\n")
    run.write("cache/decoys/json.py", "raise RuntimeError('must not load')\n")
    for tool in ("git", "python3"):
        run.write("cache/decoys/" + tool, "#!/bin/sh\nexit 99\n").chmod(0o755)
    environment = run.environment()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_EXEC_PATH", "GIT_TRACE", "GIT_NAMESPACE"):
        environment[key] = str(decoys)
    environment.update(PATH=str(decoys), PYTHONPATH=str(decoys), GIT_CONFIG_COUNT="1",
                       GIT_CONFIG_KEY_0="core.bare", GIT_CONFIG_VALUE_0="true")
    assert distribution.resolve(environment=environment).stdout == expected
    # Replacement refs are ignored even when a valid substitute object exists.
    replacement = run.git(distribution.root, "hash-object", "-w", "--stdin", input=b"replacement decoy\n").stdout.decode().strip()
    mark, _ = distribution.mark("docs/integration-and-migration.md")
    run.git(distribution.root, "update-ref", "refs/replace/" + mark["blob"], replacement)
    assert distribution.resolve().stdout == expected
    reference.write_bytes(old)
    restored = json.loads(reference.read_bytes())
    assert distribution.resolve(root=Path(restored["provider"]), revision=restored["revision"]).stdout == expected


def context_parity(distribution):
    # Both invocation forms are checked against explicit outputs, independently.
    mapped = {"path": "src/example.py", "classification": "leaf", "layer": "Source", "context": "src/CONTEXT.md",
              "chain": ["CONTEXT.md", "src/CONTEXT.md"], "reason": ""}
    scenarios = [
        ("audit", [], 0, {"ok": True, "classifications": {"leaf": 2, "excluded": 4, "total": 6}, "findings": 0}, None),
        ("resolve", ["src/example.py"], 0, mapped, None),
        ("resolve", ["src/example.py", "--format", "layer"], 0, b"Source\n", None),
        ("resolve", ["src/example.py", "--format", "context"], 0, b"src/CONTEXT.md\n", None),
        ("resolve", ["CONTEXT.md", "--format", "layer"], 0, b"\n", None),
        ("layers", ["src/example.py", "--json"], 0, ["Source"], None),
        ("layers", ["--stdin", "--json"], 0, ["Source"], b"src/example.py\n"),
        ("layers", ["--all", "--json"], 0, {"Source": "src/CONTEXT.md"}, None),
        ("layers", ["--group", "core", "--json"], 0, ["Source"], None),
        ("field", ["Source", "group"], 0, b"core\n", None),
        ("field", ["Source", "scope"], 0, ["src/**"], None),
        ("contexts", ["src/example.py"], 0, b"CONTEXT.md\nsrc/CONTEXT.md\n", None),
        ("contexts", ["src/example.py", "CONTEXT.md"], 0, b"src/example.py:\nCONTEXT.md\nsrc/CONTEXT.md\nCONTEXT.md:\nCONTEXT.md\n", None),
    ]
    for wrapper in (False, True):
        for command, args, status, expected, input in scenarios:
            result = distribution.context_call(command, *args, wrapper=wrapper, input=input)
            assert result.returncode == status and result.stderr == b""
            assert (result.stdout if isinstance(expected, bytes) else json.loads(result.stdout)) == expected
        for command, args in (("layers", ["--all", "src/example.py"]), ("layers", ["--group", "unknown"]),
                              ("layers", ["--group", "core", "--stdin"]), ("field", ["Missing", "scope"]),
                              ("field", ["Source", "missing"]), ("run", ["Source"]), ("run", ["Source", "--gate", "unknown"])):
            result = distribution.context_call(command, *args, wrapper=wrapper)
            assert result.returncode == 2 and result.stdout == b""
            assert json.loads(result.stderr)["kind"] == "context_error"
        result = distribution.context_call("resolve", "src/example.py", "unmapped", wrapper=wrapper)
        assert result.returncode == 1 and json.loads(result.stdout) == mapped
        assert json.loads(result.stderr)["kind"] == "resolve_failed"
        result = distribution.context_call("contexts", "src/example.py", "unmapped", wrapper=wrapper)
        assert result.returncode == 2 and result.stdout == b"src/example.py:\nCONTEXT.md\nsrc/CONTEXT.md\n"
        assert json.loads(result.stderr)["kind"] == "context_error"
    # Audit ownership failure is generated only in the separate caller index.
    distribution.run.write("caller/unmapped", "synthetic\n")
    distribution.run.git(distribution.caller, "add", "--", "unmapped")
    for wrapper in (False, True):
        result = distribution.context_call("audit", wrapper=wrapper)
        assert result.returncode == 1
        assert json.loads(result.stdout) == {"ok": False, "classifications": {"leaf": 2, "excluded": 4, "total": 7}, "findings": 1}
        assert json.loads(result.stderr)["kind"] == "unmapped_path"
    distribution.run.git(distribution.caller, "rm", "--", "unmapped")
    probe = distribution.run.write("caller/src/probe.py", "import pathlib,sys\npathlib.Path('src/executed').write_text('owned')\nprint('synthetic gate')\nraise SystemExit(int(sys.argv[1]))\n")
    for wrapper in (False, True):
        for mode in ("local", "ci"):
            for exitcode in (0, 7):
                gates = [{"id": "probe", "kind": "test", "mode": mode,
                          "command": [distribution.run.options.python, "-I", "-S", "-B", "src/probe.py", str(exitcode)]}]
                distribution.leaf["gates"] = gates
                distribution.context("src/CONTEXT.md", distribution.leaf)
                result = distribution.context_call("run", "Source", "--mode", mode, "--gate", "probe", wrapper=wrapper)
                assert result.returncode == exitcode and b"synthetic gate\n" in result.stdout
                if exitcode:
                    assert json.loads(result.stderr)["kind"] == "gate_failed"
                else:
                    assert result.stderr == b""
        result = distribution.context_call("run", "Source", "--mode", "local", "--gate", "probe", wrapper=wrapper)
        assert result.returncode == 2 and result.stdout == b""
        assert json.loads(result.stderr)["kind"] == "context_error"
        executed = distribution.caller / "src/executed"
        executed.unlink()
        distribution.leaf["gates"] = [
            {"id": "safe", "kind": "test", "mode": "both", "command": [distribution.run.options.python, "-I", "-S", "-B", "src/probe.py", "0"]},
            {"id": "unsafe", "kind": "test", "mode": "both", "command": [distribution.run.options.python, "../escape.py"]}]
        distribution.context("src/CONTEXT.md", distribution.leaf)
        result = distribution.context_call("run", "Source", wrapper=wrapper)
        assert result.returncode == 2 and result.stdout == b"" and not executed.exists()
        assert json.loads(result.stderr)["kind"] == "context_error"
    distribution.leaf["gates"] = []
    distribution.context("src/CONTEXT.md", distribution.leaf)


def fixture_local_hook(distribution):
    """Behavior-only regression: fresh fixture Git honors its own local hook."""
    run = distribution.run
    parent_environment, parent_cwd = dict(os.environ), Path.cwd()
    distribution.check_files(distribution.source)
    repo = run.target("provider/hook-regression")
    assert not repo.exists()
    run.git(run.root, "init", "--template=", "--object-format=sha1", str(repo))
    config_before = (repo / ".git/config").read_bytes()
    head_before = (repo / ".git/HEAD").read_bytes()
    absent = run.git(repo, "config", "--local", "--get", "core.hooksPath", check=False)
    assert (absent.returncode, absent.stdout, absent.stderr) == (1, b"", b"")
    parent_sentinel = run.write("cache/hook-parent-sentinel", "parent unchanged\n")
    marker = repo / "hook-marker"
    assert not marker.exists()
    # The executable hook uses the admitted shell, not a PATH lookup or an
    # installed hook. Reject a shell spelling that cannot form a POSIX shebang.
    shell = run.options.shell
    if any(character.isspace() for character in shell):
        raise ValueError("admitted hook shell needs a shebang-safe absolute path")
    hook = run.write("provider/hook-regression/.git/hooks/post-index-change", (
        "#!" + shell + "\n"
        '[ "$(pwd -P)" = ' + shlex.quote(str(repo)) + ' ] || exit 1\n'
        "printf '%s\\n' 'fixture-local-hook' > " + shlex.quote(str(marker)) + "\n"))
    hook.chmod(0o700)
    run.write("provider/hook-regression/tracked.txt", "synthetic index entry\n")
    result = run.git(repo, "add", "--", "tracked.txt")
    assert result.args == [run.options.git, "--no-pager", "-c", "protocol.allow=never",
                           "-C", str(repo), "add", "--", "tracked.txt"]
    assert marker.read_bytes() == b"fixture-local-hook\n"
    assert run.git(repo, "ls-files").stdout == b"tracked.txt\n"
    assert (repo / ".git/config").read_bytes() == config_before
    assert (repo / ".git/HEAD").read_bytes() == head_before
    assert parent_sentinel.read_bytes() == b"parent unchanged\n"
    assert not (run.root / "hook-marker").exists()
    assert dict(os.environ) == parent_environment and Path.cwd() == parent_cwd
    distribution.check_files(distribution.source)


def main():
    fixture = load_fixture()
    options = fixture.arguments("behavior").parse_args()
    run = fixture.Run(options, "behavior")
    return fixture.guarded(run, lambda: exercise(run, fixture))


def exercise(run, fixture):
    run.create()
    # Failures deliberately retain the exact owned root for independent review.
    distribution = fixture.Distribution(run)
    positive(distribution)
    cli(distribution)
    negatives(distribution)
    schema_definitions(distribution)
    distributions(distribution)
    context_parity(distribution)
    journey(distribution)
    fixture_local_hook(distribution)
    distribution.check_files(distribution.source)
    run.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
