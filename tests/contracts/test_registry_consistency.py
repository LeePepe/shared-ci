"""Separately cleared offline schema-engine entry; NOT RUN at authoring.

No ambient dependency discovery, installation, .pth processing or retrieval.
The externally prepared frozen validator closure is a separate admission input.
"""

import copy
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import types


def source_module(name, filename):
    path = Path(__file__).resolve().with_name(filename)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    # Reviewed stdlib-only declaration sources; no __main__ and no collection.
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def validator(options, run):
    root = Path(options.validator_root)
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        raise ValueError("validator root must be admitted canonical directory")
    admitted = run.record["validator"]
    if str(root) != admitted["root"] or options.validator_version != admitted["version"]:
        raise ValueError("validator selection mismatch")
    observed = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.suffix in (".pth", ".pyc", ".pyo") or path.name == "__pycache__":
            raise ValueError("validator closure is not frozen bytecode-free source")
        if path.is_file():
            observed[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != admitted["files"]:
        raise ValueError("validator dependency manifest mismatch")
    if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        raise ValueError("isolated bytecode-free interpreter required")
    # -I -S established the stdlib paths; reject unexpected package search paths.
    if any(not p or "site-packages" in Path(p).parts or "dist-packages" in Path(p).parts for p in sys.path):
        raise ValueError("ambient dependency search path refused")
    original_path = list(sys.path)
    before = set(sys.modules)
    sys.path.append(str(root))
    try:
        engine = importlib.import_module("jsonschema")
        referencing = importlib.import_module("referencing")
        specifications = importlib.import_module("jsonschema_specifications")
        if importlib.metadata.version("jsonschema") != options.validator_version:
            raise ValueError("validator version mismatch")
        for name in set(sys.modules) - before:
            module = sys.modules[name]
            origin = getattr(module, "__file__", None)
            if origin:
                path = Path(origin).resolve()
                permitted = [root] + [Path(p).resolve() for p in original_path if Path(p).is_dir()]
                if not any(path == p or p in path.parents for p in permitted):
                    raise ValueError("unadmitted module origin")
        def deny(_uri):
            raise ValueError("offline schema retrieval refused")
        resources = referencing.Registry(retrieve=deny).combine(specifications.REGISTRY)
        # Keep this explicit path only for the lifetime of this isolated test
        # process so reviewed lazy imports remain within the frozen closure.
        return engine.Draft202012Validator, resources
    except BaseException:
        sys.path[:] = original_path
        raise


def main():
    fixture = source_module("reviewed_fixture", "fixture.py")
    options = fixture.arguments("schema").parse_args()
    run = fixture.Run(options, "schema")
    return fixture.guarded(run, lambda: exercise(run, fixture, options))


def exercise(run, fixture, options):
    run.create()
    distribution = fixture.Distribution(run)
    expectations = source_module("reviewed_expectations", "test_resolution.py")
    engine, resources = validator(options, run)
    schema = json.loads(distribution.mark("schemas/ai-registry-v1.schema.json")[1])
    engine.check_schema(schema)
    # Independent definition conformance is separate from resolver subprocess
    # behavior. Only the already admitted local metaschema registry is used.
    definitions = engine(engine.META_SCHEMA, registry=resources)
    for definition in expectations.INVALID_SCHEMA_DEFINITIONS:
        assert list(definitions.iter_errors(definition)), definition
        malformed = copy.deepcopy(schema)
        malformed["$defs"]["id"] = definition
        assert list(definitions.iter_errors(malformed)), definition
    for required in ([None, "schema"], ["schema", {}], ["schema", ["nested"]]):
        malformed = copy.deepcopy(schema)
        malformed["$defs"]["stored"]["required"] = required
        assert list(definitions.iter_errors(malformed)), required
    annotated = copy.deepcopy(schema)
    for index, definition in enumerate(expectations.VALID_SCHEMA_DEFINITIONS):
        assert not list(definitions.iter_errors(definition)), definition
        annotated["$defs"]["shape-probe-" + str(index)] = definition
    assert not list(definitions.iter_errors(annotated))
    stored = json.loads(distribution.mark("ai/registry.json")[1])
    assert stored["entries"] == expectations.EXPECTED_ENTRIES
    assert len(stored["entries"]) == 31
    assert {kind: sum(e["kind"] == kind for e in stored["entries"]) for kind in ("document", "task", "capability")} == {
        "document": 18, "task": 4, "capability": 9}

    def check(target, value, valid=True):
        selected = dict(schema, **{"$ref": "#/$defs/" + target})
        errors = list(engine(selected, registry=resources).iter_errors(value))
        assert (not errors) == valid, (target, valid)

    check("stored", stored)
    for entry in expectations.EXPECTED_ENTRIES:
        response = distribution.resolve(entry["id"])
        assert response.returncode == 0 and response.stderr == b""
        result = json.loads(response.stdout)
        assert result == expectations.expected_result(distribution, entry["id"])
        check("result", result)
    for kind in expectations.ERRORS:
        check("finding", expectations.finding(kind))
    # Closed variants, required nullable fields, primitive spelling and coupling.
    positives = {"stored": stored, "result": expectations.expected_result(distribution, "task.upgrade"),
                 "finding": expectations.finding("registry_invalid")}
    for target, value in positives.items():
        extra = copy.deepcopy(value)
        extra["extra"] = None
        check(target, extra, False)
        for key in value:
            missing = copy.deepcopy(value)
            del missing[key]
            check(target, missing, False)
        # Every nested wire object is closed and every field is required, not
        # just the outer envelope. Paths into arrays retain declaration order.
        def objects(current, path=()):
            if isinstance(current, dict):
                yield path, current
                for key, child in current.items():
                    yield from objects(child, path + (key,))
            elif isinstance(current, list):
                for index, child in enumerate(current):
                    yield from objects(child, path + (index,))
        for path, original in objects(value):
            for field in (None, *original):
                mutated = copy.deepcopy(value)
                nested = mutated
                for part in path:
                    nested = nested[part]
                if field is None:
                    nested["unexpected"] = None
                else:
                    del nested[field]
                check(target, mutated, False)
    for value in (True, "1", None, 2):
        mutated = copy.deepcopy(stored)
        mutated["schema"] = value
        check("stored", mutated, False)
    # JSON Schema mathematical integer admits 1.0; lexical runtime rejection is
    # asserted separately by test_resolution, never claimed as engine semantics.
    mathematical = copy.deepcopy(stored)
    mathematical["schema"] = 1.0
    check("stored", mathematical)
    for pointer in ("", "/$defs/stored", "/$defs/result", "/$defs/finding", "/A_.$-9"):
        check("pointer", pointer)
    for pointer in ("$defs/stored", "/", "//x", "/a~1b", "/a b", "/a%20b", "/a\n"):
        check("pointer", pointer, False)
    for path in ("a", "docs/space name.md", "文档/百分比%25.md"):
        check("path", path)
    for path in ("", "/x", "x/", "x//y", "./x", "../x", "x/../y", "x\\y", "x#y", "x?y", "x\n", "x\x85y"):
        check("path", path, False)
    for oid in ("0" * 40, "A" * 40, "1" * 39, "1" * 40 + "\n"):
        check("oid", oid, False)
    for field, replacement in (("path", "caller/private"), ("detail", "arbitrary detail"), ("red_lines", ["x"]), ("kind", "unknown")):
        mutated = expectations.finding("registry_invalid")
        mutated[field] = replacement
        check("finding", mutated, False)
    result = copy.deepcopy(positives["result"])
    result["resources"][0]["text"] = None
    check("result", result, False)
    # Retrieval is denied rather than falling through to a network loader.
    try:
        list(engine({"$ref": "https://example.invalid/never"}, registry=resources).iter_errors({}))
    except Exception:
        pass
    else:
        raise AssertionError("external retrieval was not refused")
    distribution.check_files(distribution.source)
    run.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
