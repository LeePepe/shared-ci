"""Committed contract discovery. The sole public Interface is the CLI.

External tool/distribution/byte admission precedes execution. Internal checks
are consistency checks, not authentication. Runtime dependencies are stdlib only.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


_USAGE = "usage: resolve.py --git ABSOLUTE_GIT --revision FULL_SHA --entry ENTRY_ID"
_OPTIONS = ("--git", "--revision", "--entry")
_ID = r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*"
_OID = r"(?!0{40}$)[0-9a-f]{40}"
_POINTER = r"(?:/[A-Za-z0-9_$.-]+)*"
_REGISTRY = "ai/registry.json"
_SCHEMA = "schemas/ai-registry-v1.schema.json"
_SOURCE = "scripts/contracts/resolve.py"
_COMMANDS = ("audit", "contexts", "field", "layers", "resolve", "run")
_PROVIDER = {"repository_id": "1380829073", "library": "shared-ci", "unit": "git-source"}
_ERRORS = {
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


class _Failure(Exception):
    def __init__(self, kind):
        self.kind = kind


def _require(condition, kind="registry_invalid"):
    if not condition:
        raise _Failure(kind)


def _matches(pattern, value):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys.split()))


def _json(raw, kind):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, kind)
            result[key] = value
        return result

    def constant(_):
        raise _Failure(kind)

    def scalar(value):
        if type(value) is str:
            value.encode("utf-8", "strict")
        elif type(value) is dict:
            for key, item in value.items():
                scalar(key)
                scalar(item)
        elif type(value) is list:
            for item in value:
                scalar(item)

    try:
        _require(not raw.startswith(b"\xef\xbb\xbf"), kind)
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                           parse_constant=constant)
        scalar(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise _Failure(kind) from None


def _path(value):
    return (type(value) is str and bool(value)
            and not any(part in ("", ".", "..") for part in value.split("/"))
            and not any(c in "\\#?" or ord(c) < 32 or 127 <= ord(c) <= 159 for c in value))


def _ref(value, typ):
    keys = {"document": "type path anchor", "source": "type path",
            "schema": "type path pointer", "example": "type path scope"}
    _closed(value, keys[typ])
    _require(value["type"] == typ and type(value["path"]) is str)
    if typ == "document":
        _require(value["anchor"] is None or type(value["anchor"]) is str)
    if typ == "schema":
        _require(type(value["pointer"]) is str)
    if typ == "example":
        _require(value["scope"] in ("synthetic-test-source", "isolated-distribution-consumer"))


def _ref_key(ref):
    return (ref["path"], ref["type"],
            ref.get("anchor") or ref.get("pointer") or ref.get("scope") or "")


def _references(entry):
    if entry["kind"] == "document":
        return [entry["resource"]]
    if entry["kind"] == "task":
        return []
    interface = entry["interface"]
    sources = ([interface["wrapper"], interface["direct"]["source"]]
               if interface["kind"] == "context" else [interface["source"]])
    return sources + entry["schemas"] + entry["examples"]


def _shape(registry):
    _require(type(registry) is dict)
    version = registry.get("schema")
    _require(type(version) is int)
    _require(version == 1, "registry_schema_unsupported")
    _closed(registry, "schema provider revision_binding entries compatibility release_notes")
    _require(registry["provider"] == _PROVIDER)
    _require(registry["revision_binding"] == "containing-commit")
    _require(registry["compatibility"] == {"declared": "doc.compatibility", "tested": "doc.evidence"})
    _require(registry["release_notes"] is None)
    entries = registry["entries"]
    _require(type(entries) is list and len(entries) == 31)
    for entry in entries:
        _require(type(entry) is dict and _matches(_ID, entry.get("id")))
        kind = entry.get("kind")
        _require(kind in ("document", "task", "capability"))
        if kind == "document":
            _closed(entry, "id kind resource")
            _ref(entry["resource"], "document")
        elif kind == "task":
            _closed(entry, "id kind documents")
            _require(type(entry["documents"]) is list and bool(entry["documents"]))
            _require(all(_matches(_ID, item) for item in entry["documents"]))
        else:
            _closed(entry, "id kind interface contract schemas examples")
            _require(_matches(_ID, entry["contract"]))
            for field, typ in (("schemas", "schema"), ("examples", "example")):
                _require(type(entry[field]) is list and bool(entry[field]))
                for ref in entry[field]:
                    _ref(ref, typ)
                keys = [_ref_key(ref) for ref in entry[field]]
                _require(keys == sorted(set(keys)))
            interface = entry["interface"]
            _require(type(interface) is dict)
            ikind = interface.get("kind")
            if ikind == "context":
                _closed(interface, "kind wrapper direct")
                _ref(interface["wrapper"], "source")
                _closed(interface["direct"], "source command")
                _ref(interface["direct"]["source"], "source")
                _require(interface["direct"]["command"] in _COMMANDS)
            elif ikind == "function":
                _closed(interface, "kind source symbol parameters returns dependencies")
                _ref(interface["source"], "source")
                _require(interface["symbol"] in ("evaluate_policy", "aggregate_6dq"))
                _require(interface["returns"] == "dict")
                params = interface["parameters"]
                _require(type(params) is list and bool(params))
                for param in params:
                    _closed(param, "name annotation kind required")
                    _require(param["name"] in ("baseline", "candidate", "approvals", "observation", "expectation", "evidence"))
                    _require(param["annotation"] in ("dict", "list"))
                    _require(param["kind"] == "keyword-only" and param["required"] is True)
                deps = interface["dependencies"]
                _require(type(deps) is list and all(_matches(_ID, dep) for dep in deps))
                _require(deps == sorted(set(deps)))
            elif ikind == "resolver":
                _closed(interface, "kind source python_flags required_options")
                _ref(interface["source"], "source")
                _require(interface["python_flags"] == ["-I", "-S", "-B"])
                _require(interface["required_options"] == list(_OPTIONS))
            else:
                raise _Failure("registry_invalid")
    ids = [entry["id"] for entry in entries]
    _require(ids == sorted(_expected()))
    return {entry["id"]: entry for entry in entries}


def _expected():
    """Frozen public inventory, independent of the loaded registry."""
    documents = {
        "architecture": ("docs/architecture.md", None),
        "compatibility": ("docs/integration-and-migration.md", "compatibility"),
        "context": ("docs/context-cli-contract.md", None),
        "evidence": ("docs/integration-and-migration.md", "existing-fixtures-and-evidence"),
        "examples": ("docs/integration-and-migration.md", "existing-fixtures-and-evidence"),
        "failure.context": ("docs/context-cli-contract.md", "commands-and-outputs"),
        "failure.policy": ("docs/policy-validation-contract.md", "deterministic-failure-order-and-kinds"),
        "failure.quality": ("docs/quality-aggregation-contract.md", "exact-state-machine-and-findings"),
        "failure.registry": ("docs/registry-resolution-contract.md", "errors"),
        "index": ("README.md", None),
        "integration": ("docs/integration-and-migration.md", "fixed-checkout-surfaces"),
        "migration": ("docs/integration-and-migration.md", "migration-and-rollback"),
        "policy": ("docs/policy-validation-contract.md", None),
        "quality": ("docs/quality-aggregation-contract.md", None),
        "recovery": ("docs/disaster-recovery.md", None),
        "registry": ("docs/registry-resolution-contract.md", None),
        "registry.example": ("docs/registry-resolution-contract.md", "offline-consumer-example"),
        "usage": ("docs/ai-usage.md", None),
    }
    tasks = {
        "integrate": "integration registry registry.example context policy quality",
        "change": "architecture registry context policy quality examples",
        "upgrade": "compatibility migration",
        "diagnose": "failure.registry failure.context failure.policy failure.quality recovery",
    }
    entries = {}
    for name, (path, anchor) in documents.items():
        key = "doc." + name
        entries[key] = {"id": key, "kind": "document", "resource": {
            "type": "document", "path": path, "anchor": anchor}}
    for name, docs in tasks.items():
        key = "task." + name
        entries[key] = {"id": key, "kind": "task", "documents": ["doc." + d for d in docs.split()]}

    def source(path):
        return {"type": "source", "path": path}

    def schema(name, pointer=""):
        return {"type": "schema", "path": "schemas/" + name + ".schema.json", "pointer": pointer}

    def example(path, scope="synthetic-test-source"):
        return {"type": "example", "path": path, "scope": scope}

    def capability(key, interface, contract, schemas, examples):
        entries[key] = {"id": key, "kind": "capability", "interface": interface,
                        "contract": contract, "schemas": sorted(schemas, key=_ref_key),
                        "examples": sorted(examples, key=_ref_key)}

    context_examples = {"audit": "fixture test_resolution", "resolve": "test_cli_contract test_resolution",
                        "layers": "test_cli_contract", "field": "test_cli_contract",
                        "contexts": "test_cli_contract", "run": "test_fixture_hooks test_runner"}
    for command in _COMMANDS:
        capability("cap.context." + command, {
            "kind": "context", "wrapper": source("scripts/context/" + command),
            "direct": {"source": source("scripts/context/_context.py"), "command": command}},
            "doc.context", [schema("context-v1"), schema("finding-v1")],
            [example("tests/context/" + name + ".py") for name in context_examples[command].split()])
    for key, path, symbol, params, deps, contract, schemas, test in (
        ("cap.policy.evaluate", "policy/validate", "evaluate_policy",
         (("baseline", "dict"), ("candidate", "dict"), ("approvals", "list"), ("observation", "dict")),
         [], "policy", ("finding-v1", "policy-input-v1", "policy-exception-v1"), "policy/test_validation"),
        ("cap.quality.aggregate", "quality/aggregate", "aggregate_6dq",
         (("expectation", "dict"), ("evidence", "dict")), ["cap.policy.evaluate"],
         "quality", ("finding-v1", "quality-input-v1", "quality-result-v1"), "quality/test_aggregation"),
    ):
        capability(key, {"kind": "function", "source": source("scripts/" + path + ".py"),
                        "symbol": symbol, "parameters": [
                            {"name": name, "annotation": annotation, "kind": "keyword-only", "required": True}
                            for name, annotation in params], "returns": "dict", "dependencies": deps},
                   "doc." + contract, [schema(name) for name in schemas], [example("tests/" + test + ".py")])
    capability("cap.contract.resolve", {
        "kind": "resolver", "source": source(_SOURCE), "python_flags": ["-I", "-S", "-B"],
        "required_options": list(_OPTIONS)}, "doc.registry",
        [schema("ai-registry-v1", "/$defs/" + name) for name in ("stored", "result", "finding")]
        + [schema("finding-v1")],
        [example("examples/contracts/resolve-from-caller.sh", "isolated-distribution-consumer")]
        + [example("tests/contracts/" + name + ".py") for name in
           ("test_resolution", "test_registry_consistency", "test_isolation")])
    return entries


def _graph(entries):
    for key, entry in entries.items():
        _require(key.startswith({"document": "doc.", "task": "task.", "capability": "cap."}[entry["kind"]]))
        for ref in _references(entry):
            _require(_path(ref["path"]), "contract_reference_invalid")
            if ref["type"] == "document":
                _require(ref["anchor"] is None or _matches(r"[a-z0-9]+(?:-[a-z0-9]+)*", ref["anchor"]),
                         "contract_reference_invalid")
            if ref["type"] == "schema":
                _require(_matches(_POINTER, ref["pointer"]), "contract_reference_invalid")
        for linked in _links(entry):
            _require(linked in entries, "contract_reference_invalid")
            expected_kind = "capability" if linked.startswith("cap.") else "document"
            _require(entries[linked]["kind"] == expected_kind, "contract_reference_invalid")
        if entry["kind"] == "task":
            _require(all(d.startswith("doc.") for d in entry["documents"]), "contract_reference_invalid")
        if entry["kind"] == "capability":
            _require(entry["contract"].startswith("doc."), "contract_reference_invalid")
            _require(all(d.startswith("cap.") for d in entry["interface"].get("dependencies", [])),
                     "contract_reference_invalid")
    for key in entries:
        _closure(entries, key)


def _links(entry):
    if entry["kind"] == "task":
        return entry["documents"]
    if entry["kind"] == "capability":
        return [entry["contract"]] + entry["interface"].get("dependencies", [])
    return []


def _closure(entries, selected):
    visited, active = set(), set()

    def visit(key):
        _require(key not in active, "contract_reference_invalid")
        if key in visited:
            return
        active.add(key)
        for link in _links(entries[key]):
            visit(link)
        active.remove(key)
        visited.add(key)

    visit(selected)
    return sorted(visited)


class _Git:
    def __init__(self, executable, root):
        self.root = root
        self.directory = root / ".git"
        self.executable = executable
        self.environment = {
            "LC_ALL": "C", "PATH": "", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": "", "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "", "PAGER": "",
        }
        self.trees = {}
        self.blobs = {}

    def call(self, *args, kind="contract_missing", plain=False, allow_failure=False):
        prefix = [] if plain else ["--git-dir=" + str(self.directory), "--work-tree=" + str(self.root),
                                  "-c", "protocol.allow=never", "-c", "core.hooksPath=/dev/null"]
        try:
            result = subprocess.run([self.executable, "--no-pager", *prefix, *args],
                                    cwd=self.root, env=self.environment, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise _Failure("provider_tool_unavailable") from None
        _require(allow_failure or result.returncode == 0, kind)
        return result

    def eligible(self):
        kind = "provider_distribution_unsupported"
        d = self.directory
        _require(d.is_dir() and not d.is_symlink(), kind)
        # Metadata/storage indirection is unsupported, even with cached objects.
        for base, dirs, files in os.walk(d, followlinks=False):
            _require(not any((Path(base) / name).is_symlink() for name in dirs + files), kind)
        for name in ("commondir", "shallow", "objects/info/alternates", "objects/info/http-alternates"):
            _require(not (d / name).exists(), kind)
        _require(not any((d / "objects/pack").glob("*.promisor")), kind)
        config = self.call("config", "--local", "--no-includes", "--null", "--list", kind=kind).stdout
        for row in config.split(b"\0"):
            if not row:
                continue
            key, _, value = row.partition(b"\n")
            key, value = key.lower(), value.lower()
            _require(not (key.startswith((b"include.", b"includeif."))
                          or key in (b"core.worktree", b"extensions.worktreeconfig", b"extensions.partialclone")
                          or key.endswith((b".promisor", b".partialclonefilter"))), kind)
            if key == b"extensions.objectformat":
                _require(value == b"sha1", kind)
        _require(self.call("rev-parse", "--is-bare-repository", kind=kind).stdout == b"false\n", kind)
        _require(self.call("rev-parse", "--show-object-format", kind=kind).stdout == b"sha1\n", kind)
        _require(self.call("rev-parse", "--is-shallow-repository", kind=kind).stdout == b"false\n", kind)

    def bind(self, revision, executing):
        kind = "provider_revision_mismatch"
        head = (self.directory / "HEAD").read_bytes()
        _require(head == revision.encode("ascii") + b"\n", kind)
        _require(self.call("cat-file", "-t", revision, kind=kind).stdout == b"commit\n", kind)
        self.tree = self.call("rev-parse", "--verify", revision + "^{tree}", kind=kind).stdout.decode("ascii").strip()
        _require(_matches(_OID, self.tree), kind)
        mark, raw = self.resource(_SOURCE)
        _require(executing.read_bytes() == raw, kind)
        return mark

    def resource(self, path):
        tree = self.tree
        parts = path.split("/")
        for index, part in enumerate(parts):
            if tree not in self.trees:
                raw = self.call("ls-tree", "-z", tree).stdout
                rows = {}
                for row in raw.split(b"\0"):
                    if row:
                        meta, name = row.split(b"\t", 1)
                        mode, typ, oid = meta.decode("ascii").split()
                        rows[name] = (mode, typ, oid)
                self.trees[tree] = rows
            row = self.trees[tree].get(part.encode("utf-8"))
            _require(row is not None, "contract_missing")
            mode, typ, oid = row
            if index < len(parts) - 1:
                _require(mode == "040000" and typ == "tree", "contract_reference_invalid")
                tree = oid
            else:
                _require(mode in ("100644", "100755") and typ == "blob", "contract_reference_invalid")
                if oid not in self.blobs:
                    self.blobs[oid] = self.call("cat-file", "blob", oid).stdout
                raw = self.blobs[oid]
                return {"blob": oid, "mode": mode, "sha256": hashlib.sha256(raw).hexdigest()}, raw


def _pointer(document, pointer):
    _require(_matches(_POINTER, pointer), "contract_reference_invalid")
    value = document
    for key in pointer.split("/")[1:]:
        _require(type(value) is dict and key in value, "contract_reference_invalid")
        value = value[key]
    return value


def _schema(raw, registry=False):
    kind = "contract_reference_invalid"
    document = _json(raw, kind)

    def strings(value):
        # Establish hashability/comparability before either deduplication or the
        # registry's later closed-property comparison. Never leak a TypeError.
        _require(type(value) is list and all(type(item) is str for item in value), kind)
        _require(len(set(value)) == len(value), kind)

    def number(value):
        _require(type(value) in (int, float), kind)
        _require(type(value) is int or -float("inf") < value < float("inf"), kind)

    # Definition-shape checks only, not instance validation or a metaschema
    # engine. Traverse actual schema positions and explicit local reference
    # targets; const/default/enum/examples and unknown annotations are data.
    schema_maps = ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas")
    schema_values = ("additionalProperties", "items", "contains", "propertyNames", "not",
                     "if", "then", "else", "unevaluatedProperties", "unevaluatedItems", "contentSchema")
    schema_arrays = ("allOf", "anyOf", "oneOf", "prefixItems")
    type_names = ("null", "boolean", "object", "array", "number", "string", "integer")
    nodes, pending, seen = [], [document], set()
    while pending:
        value = pending.pop()
        _require(type(value) in (dict, bool), kind)
        if type(value) is bool or id(value) in seen:
            continue
        seen.add(id(value))
        nodes.append(value)
        for key, item in value.items():
            if key in schema_maps:
                _require(type(item) is dict, kind)
                pending.extend(item.values())
            elif key in schema_values:
                pending.append(item)
            elif key in schema_arrays:
                _require(type(item) is list and bool(item), kind)
                pending.extend(item)
            elif key == "type":
                if type(item) is list:
                    strings(item)
                    _require(bool(item) and all(name in type_names for name in item), kind)
                else:
                    _require(type(item) is str and item in type_names, kind)
            elif key == "required":
                strings(item)
            elif key == "dependentRequired":
                _require(type(item) is dict, kind)
                for names in item.values():
                    strings(names)
            elif key in ("$ref", "$dynamicRef", "$recursiveRef"):
                _require(type(item) is str and item.startswith("#"), kind)
                pending.append(_pointer(document, item[1:]))
            elif key == "$id":
                _require(type(item) is str and item.startswith("#"), kind)
            elif key in ("$schema", "$comment", "$anchor", "$dynamicAnchor", "title", "description",
                         "pattern", "format", "contentEncoding", "contentMediaType"):
                _require(type(item) is str, kind)
            elif key == "$vocabulary":
                _require(type(item) is dict and all(type(flag) is bool for flag in item.values()), kind)
            elif key in ("uniqueItems", "readOnly", "writeOnly", "deprecated", "$recursiveAnchor"):
                _require(type(item) is bool, kind)
            elif key in ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties",
                         "minContains", "maxContains"):
                number(item)
                _require(item >= 0 and item % 1 == 0, kind)
            elif key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
                number(item)
                _require(key != "multipleOf" or item > 0, kind)
            elif key == "enum":
                _require(type(item) is list, kind)
            elif key == "examples":
                _require(type(item) is list, kind)
    if registry:
        _require(type(document) is dict and document.get("$schema") == "https://json-schema.org/draft/2020-12/schema", kind)
        _require(document.get("$ref") == "#/$defs/stored", kind)
        for name in ("stored", "result", "finding"):
            _require(type(_pointer(document, "/$defs/" + name)) is dict, kind)
        fields = {
            "stored": "schema provider revision_binding entries compatibility release_notes",
            "result": "schema provider revision tree basis selected entries resources",
            "provider": "repository_id library unit", "mark": "blob mode sha256",
            "document": "id kind resource", "task": "id kind documents",
            "capability": "id kind interface contract schemas examples",
            "documentRef": "type path anchor", "sourceRef": "type path",
            "schemaRef": "type path pointer", "exampleRef": "type path scope",
            "parameter": "name annotation kind required",
            "contextInterface": "kind wrapper direct",
            "functionInterface": "kind source symbol parameters returns dependencies",
            "resolverInterface": "kind source python_flags required_options",
        }
        for name, required in fields.items():
            definition = _pointer(document, "/$defs/" + name)
            _require(type(definition) is dict and definition.get("type") == "object", kind)
            _require(type(definition.get("properties")) is dict
                     and set(definition["properties"]) == set(required.split()), kind)
        _require(_pointer(document, "/$defs/version") == {"type": "integer", "const": 1}, kind)
        finding = _pointer(document, "/$defs/finding")
        _require(type(finding.get("oneOf")) is list and len(finding["oneOf"]) == len(_ERRORS), kind)
        expected_findings = []
        for code, (detail, anchor) in _ERRORS.items():
            expected_findings.append({"layer": "contracts", "path": _SOURCE if code.startswith("provider_") else _REGISTRY,
                                      "kind": code, "detail": detail + " Repair: docs/registry-resolution-contract.md#" + anchor,
                                      "red_lines": []})
        actual_findings = []
        for variant in finding["oneOf"]:
            _require(type(variant) is dict and variant.get("type") == "object"
                     and type(variant.get("properties")) is dict, kind)
            props = variant["properties"]
            _require(set(props) == {"layer", "path", "kind", "detail", "red_lines"}
                     and all(type(v) is dict and set(v) == {"const"} for v in props.values()), kind)
            actual_findings.append({key: value["const"] for key, value in props.items()})
        _require(actual_findings == expected_findings, kind)
        # Only actual schema positions participate in the closed-object rule.
        # Their required elements were validated before sorting/deduplication.
        for value in nodes:
            declared_type = value.get("type")
            if declared_type == "object" or (type(declared_type) is list and "object" in declared_type):
                _require(value.get("additionalProperties") is False, kind)
                _require(type(value.get("properties")) is dict and "required" in value, kind)
                _require(sorted(value["properties"]) == sorted(value["required"]), kind)
        _require(_pointer(document, "/$defs/pointer") == {
            "type": "string", "pattern": r"^(?:/[A-Za-z0-9_$.-]+)*$(?![\s\S])"}, kind)
    return document


def _anchors(text):
    anchors, fence, width = [], None, 0
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            token, rest = match.groups()
            if fence is None:
                fence, width = token[0], len(token)
            elif token[0] == fence and len(token) >= width and not rest.strip():
                fence = None
            continue
        if fence is not None:
            continue
        match = re.match(r"^ {0,3}#{1,6}(?: +|$)(.*)$", line)
        if match:
            title = re.sub(r" +#+ *$", "", match.group(1))
            title = title.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))
            title = re.sub(r"[^\w -]", "", title, flags=re.ASCII)
            title = title.replace("_", "")
            anchors.append(re.sub(r" +", "-", title).strip(" -"))
    return anchors


def _resources(git, entries):
    references = {_ref_key(ref): ref for entry in entries.values() for ref in _references(entry)}
    result, bodies = {}, {}
    for key in sorted(references):
        ref = references[key]
        mark, raw = git.resource(ref["path"])
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeError:
            raise _Failure("contract_reference_invalid") from None
        bodies[ref["path"]] = (mark, text)
        if ref["type"] == "document" and ref["anchor"] is not None:
            _require(_anchors(text).count(ref["anchor"]) == 1, "contract_reference_invalid")
        if ref["type"] == "schema":
            _pointer(_schema(raw), ref["pointer"])
        result[key] = {"ref": ref, "object": mark, "text": text if ref["type"] == "document" else None}
    return result, bodies


def _parity(entries, bodies):
    kind = "contract_api_drift"
    expected = _expected()
    for key in sorted(entries):
        _require(entries[key] == expected[key], kind if key.startswith("cap.") else "contract_reference_invalid")
    for command in _COMMANDS:
        mark, text = bodies["scripts/context/" + command]
        _require(mark["mode"] == "100755", kind)
        _require(text == '#!/bin/sh\nexec python3 "$(dirname "$0")/_context.py" ' + command + ' "$@"\n', kind)
    _require(bodies["examples/contracts/resolve-from-caller.sh"][0]["mode"] == "100755", kind)
    try:
        context = ast.parse(bodies["scripts/context/_context.py"][1])
        functions = {node.name: node for node in context.body if isinstance(node, ast.FunctionDef)}
        parser = functions["parser_for"]
        _require(len(parser.body) == 3 and isinstance(parser.body[0], ast.Assign)
                 and isinstance(parser.body[-1], ast.Return)
                 and isinstance(parser.body[-1].value, ast.Name)
                 and parser.body[-1].value.id == "parser", kind)
        init = ast.parse('parser = argparse.ArgumentParser(prog=f"scripts/context/{command_name}")').body[0]
        _require(ast.dump(parser.body[0]) == ast.dump(init), kind)
        branch = next(node for node in parser.body if isinstance(node, ast.If))
        declarations = {}
        while isinstance(branch, ast.If):
            test = branch.test
            _require(isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                     and test.left.id == "command_name" and len(test.ops) == 1
                     and isinstance(test.ops[0], ast.Eq), kind)
            command = ast.literal_eval(test.comparators[0])
            arguments, handlers = [], []
            for statement in branch.body:
                _require(isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call), kind)
                call = statement.value
                _require(isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                         and call.func.value.id == "parser", kind)
                if call.func.attr == "add_argument":
                    arguments.append(([ast.literal_eval(arg) for arg in call.args],
                                      {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}))
                else:
                    _require(call.func.attr == "set_defaults" and not call.args and len(call.keywords) == 1, kind)
                    kw = call.keywords[0]
                    _require(kw.arg == "handler" and isinstance(kw.value, ast.Name), kind)
                    handlers.append(kw.value.id)
            _require(command not in declarations and handlers == ["command_" + command], kind)
            _require("command_" + command in functions, kind)
            declarations[command] = arguments
            _require(len(branch.orelse) == 1, kind)
            branch = branch.orelse[0]
        _require(isinstance(branch, ast.Raise), kind)
        _require(declarations == {
            "audit": [], "resolve": [(["paths"], {"nargs": "+"}), (["--format"], {"choices": ("json", "layer", "context"), "default": "json"})],
            "layers": [(["paths"], {"nargs": "*"}), (["--stdin"], {"action": "store_true"}),
                       (["--all"], {"action": "store_true"}), (["--group"], {}), (["--json"], {"action": "store_true"})],
            "field": [(["layer"], {}), (["field"], {})], "contexts": [(["paths"], {"nargs": "+"})],
            "run": [(["layer"], {}), (["--gate"], {}), (["--mode"], {"choices": ("local", "ci"), "default": "local"}), (["--path"], {})]}, kind)
        # Freeze supported direct-dispatch wiring structurally, not by importing.
        dispatch = '''def main() -> int:
    command_name = pathlib.Path(sys.argv[0]).name
    try:
        if command_name == "_context.py":
            if len(sys.argv) < 2:
                raise ContextError("missing context command")
            command_name = sys.argv.pop(1)
        root = repo_root()
        parser = parser_for(command_name)
        args = parser.parse_args()
        return args.handler(args, root)
    except ContextError as error:
        Finding("context", ROOT_CONTEXT, "context_error", str(error)).emit()
        return 2
'''
        _require(ast.dump(functions["main"]) == ast.dump(ast.parse(dispatch).body[0]), kind)
        for key in ("cap.policy.evaluate", "cap.quality.aggregate"):
            interface = entries[key]["interface"]
            module = ast.parse(bodies[interface["source"]["path"]][1])
            public = [n for n in module.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")]
            _require(len(public) == 1 and isinstance(public[0], ast.FunctionDef), kind)
            function = public[0]
            _require(function.name == interface["symbol"] and not function.decorator_list, kind)
            args = function.args
            _require(not (args.posonlyargs or args.args or args.vararg or args.kwarg or args.defaults), kind)
            _require(all(default is None for default in args.kw_defaults), kind)
            _require([(arg.arg, ast.dump(arg.annotation)) for arg in args.kwonlyargs]
                     == [(p["name"], ast.dump(ast.Name(id=p["annotation"], ctx=ast.Load()))) for p in interface["parameters"]], kind)
            _require(ast.dump(function.returns) == ast.dump(ast.Name(id="dict", ctx=ast.Load())), kind)
            if key == "cap.quality.aggregate":
                imports = [n for n in module.body if isinstance(n, ast.ImportFrom)]
                _require(len(imports) == 1 and imports[0].module == "scripts.policy.validate"
                         and imports[0].level == 0 and len(imports[0].names) == 1
                         and imports[0].names[0].name == "evaluate_policy", kind)
                alias = imports[0].names[0].asname or "evaluate_policy"
                _require(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id == alias for n in ast.walk(function)), kind)
    except (SyntaxError, ValueError, TypeError, KeyError, StopIteration, AttributeError):
        raise _Failure(kind) from None


def _arguments(tokens):
    if tokens in (["-h"], ["--help"]):
        return None
    values = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        option, equal, value = token.partition("=")
        if option not in _OPTIONS:
            raise ValueError("unknown or positional argument")
        if option in values:
            raise ValueError("repeated option")
        if not equal:
            index += 1
            if index == len(tokens) or tokens[index].startswith("--") or tokens[index] == "-h":
                raise ValueError("missing option value")
            value = tokens[index]
        if not value:
            raise ValueError("missing option value")
        values[option] = value
        index += 1
    for option in _OPTIONS:
        if option not in values:
            raise ValueError("missing required option " + option)
    if not os.path.isabs(values["--git"]) or "\0" in values["--git"]:
        raise ValueError("invalid value for --git")
    if not _matches(_OID, values["--revision"]):
        raise ValueError("invalid value for --revision")
    if not _matches(_ID, values["--entry"]):
        raise ValueError("invalid value for --entry")
    return values


def _resolve(options):
    executing = Path(__file__).resolve(strict=True)
    root = executing.parents[2]
    git = _Git(options["--git"], root)
    git.call("--version", plain=True, kind="provider_tool_unavailable")
    git.eligible()
    resolver_mark = git.bind(options["--revision"], executing)
    registry_mark, raw = git.resource(_REGISTRY)
    entries = _shape(_json(raw, "registry_invalid"))
    schema_mark, raw = git.resource(_SCHEMA)
    _schema(raw, registry=True)
    _graph(entries)
    resources, bodies = _resources(git, entries)
    _parity(entries, bodies)
    selected = options["--entry"]
    _require(selected in entries, "contract_entry_unknown")
    closure = [entries[key] for key in _closure(entries, selected)]
    keys = {_ref_key(ref) for entry in closure for ref in _references(entry)}
    return {"schema": 1, "provider": dict(_PROVIDER), "revision": options["--revision"], "tree": git.tree,
            "basis": {"registry": registry_mark, "schema": schema_mark, "resolver": resolver_mark},
            "selected": selected, "entries": closure, "resources": [resources[key] for key in sorted(keys)]}


def _emit(value, stream):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    stream.buffer.write(raw)
    stream.buffer.flush()


def main():
    try:
        options = _arguments(sys.argv[1:])
    except ValueError as error:
        sys.stderr.write(_USAGE + "\nerror: " + str(error) + "\n")
        return 2
    if options is None:
        sys.stdout.write(_USAGE + "\nResolve one committed registry entry; tools and distribution require external admission.\n")
        return 0
    try:
        result = _resolve(options)
    except _Failure as error:
        kind = error.kind
    except (OSError, UnicodeError, ValueError, RecursionError):
        kind = "provider_distribution_unsupported"
    else:
        _emit(result, sys.stdout)
        return 0
    detail, anchor = _ERRORS[kind]
    _emit({"layer": "contracts", "path": _SOURCE if kind.startswith("provider_") else _REGISTRY,
           "kind": kind, "detail": detail + " Repair: docs/registry-resolution-contract.md#" + anchor,
           "red_lines": []}, sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
