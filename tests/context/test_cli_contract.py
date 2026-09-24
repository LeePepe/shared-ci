"""Subprocess contracts for all six public entrypoints; synthetic roots only."""
import concurrent.futures
import json
import os
import pathlib
import unittest

from fixture import Fixture, REPO, isolated_environment


class CLIContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)
        self.fixture.root_index([
            {"patterns": ["src/**"], "context": "src/CONTEXT.md"},
            {"patterns": ["docs/**"], "context": "docs/CONTEXT.md"},
        ])
        self.fixture.leaf(layer="ZSource")
        self.fixture.leaf(path="docs/CONTEXT.md", layer="ADocs", scope=["docs/**"])
        data = self.fixture.data()
        data.update(group="synthetic", custom={"value": "hello", "list": [2, 1]})
        self.fixture.context("src/CONTEXT.md", data)

    def test_resolve_json_text_and_mixed_failure(self):
        result = self.fixture.cli("resolve", "src/a.py", "orphan", "docs/a.md")
        self.assertEqual(1, result.returncode)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(["ZSource", "ADocs"], [item["layer"] for item in records])
        self.assertEqual({
            "path": "src/a.py", "classification": "leaf", "layer": "ZSource",
            "context": "src/CONTEXT.md", "chain": ["CONTEXT.md", "src/CONTEXT.md"],
            "reason": "",
        }, records[0])
        self.assertEqual("resolve_failed", json.loads(result.stderr)["kind"])
        self.assertEqual("ZSource\n\n", self.fixture.cli(
            "resolve", "src/a.py", "CONTEXT.md", "--format", "layer").stdout)
        self.assertEqual("src/CONTEXT.md\n", self.fixture.cli(
            "resolve", "src/a.py", "--format", "context").stdout)

    def test_audit_stdout_stderr_and_status(self):
        self.fixture.git("add", "CONTEXT.md", "src", "docs")
        result = self.fixture.cli("audit")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual({"ok": True, "findings": 0,
                          "classifications": {"leaf": 2, "excluded": 1, "total": 3}},
                         json.loads(result.stdout))
        self.fixture.write("orphan")
        self.fixture.git("add", "orphan")
        result = self.fixture.cli("audit")
        self.assertEqual(1, result.returncode)
        self.assertFalse(json.loads(result.stdout)["ok"])
        self.assertEqual("unmapped_path", json.loads(result.stderr)["kind"])

    def test_layers_sort_deduplicate_stdin_and_json(self):
        result = self.fixture.cli("layers", "src/a.py", "docs/b.md", "src/c.py")
        self.assertEqual((0, "ADocs\nZSource\n"), (result.returncode, result.stdout))
        result = self.fixture.cli("layers", "src/a.py", "--stdin", "--json",
                                  input="docs/b.md\nsrc/a.py\n\n")
        self.assertEqual(["ADocs", "ZSource"], json.loads(result.stdout))
        result = self.fixture.cli("layers", "CONTEXT.md", "--json")
        self.assertEqual((0, []), (result.returncode, json.loads(result.stdout)))
        result = self.fixture.cli("layers", "src/a.py", "orphan", "--json")
        self.assertEqual((1, ["ZSource"]), (result.returncode, json.loads(result.stdout)))
        self.assertEqual("resolve_failed", json.loads(result.stderr)["kind"])

    def test_all_and_group_formats(self):
        self.assertEqual("ADocs\nZSource\n", self.fixture.cli("layers", "--all").stdout)
        self.assertEqual({"ADocs": "docs/CONTEXT.md", "ZSource": "src/CONTEXT.md"},
                         json.loads(self.fixture.cli("layers", "--all", "--json").stdout))
        self.assertEqual("ZSource\n", self.fixture.cli(
            "layers", "--group", "synthetic").stdout)
        self.assertEqual(["ZSource"], json.loads(self.fixture.cli(
            "layers", "--group", "synthetic", "--json").stdout))

    def test_conflicting_or_empty_layers_options(self):
        for args in ((), ("--all", "src/a.py"), ("--all", "--stdin"),
                     ("--group", "synthetic", "--all"), ("--group", "synthetic", "--stdin"),
                     ("--group", "synthetic", "src/a.py"), ("--group", "missing"),
                     ("--stdin",)):
            with self.subTest(args=args):
                result = self.fixture.cli("layers", *args, input="")
                self.assertEqual(2, result.returncode)
                self.assertEqual("context_error", json.loads(result.stderr)["kind"])

    def test_field_representation_and_errors(self):
        self.assertEqual("hello\n", self.fixture.cli(
            "field", "ZSource", "custom.value").stdout)
        self.assertEqual("[\n  2,\n  1\n]\n", self.fixture.cli(
            "field", "ZSource", "custom.list").stdout)
        for args in (("ZSource", "custom.absent"), ("Missing", "layer")):
            result = self.fixture.cli("field", *args)
            self.assertEqual(2, result.returncode)
            self.assertEqual("context_error", json.loads(result.stderr)["kind"])

    def test_contexts_chain_headings_and_error(self):
        self.assertEqual("CONTEXT.md\nsrc/CONTEXT.md\n",
                         self.fixture.cli("contexts", "src/a.py").stdout)
        self.assertEqual("src/a.py:\nCONTEXT.md\nsrc/CONTEXT.md\n"
                         "docs/a.md:\nCONTEXT.md\ndocs/CONTEXT.md\n",
                         self.fixture.cli("contexts", "src/a.py", "docs/a.md").stdout)
        result = self.fixture.cli("contexts", "orphan")
        self.assertEqual(2, result.returncode)
        self.assertEqual("context_error", json.loads(result.stderr)["kind"])

    def test_argparse_retains_usage_errors(self):
        for command, args in (("resolve", ()), ("resolve", ("src/a.py", "--format", "bad")),
                              ("run", ("ZSource", "--mode", "bad")), ("field", ("ZSource",))):
            with self.subTest(command=command, args=args):
                result = self.fixture.cli(command, *args)
                self.assertEqual(2, result.returncode)
                self.assertIn("usage: scripts/context/" + command, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_all_executable_wrappers(self):
        data = self.fixture.data()
        data["gates"] = [{"id": "probe", "kind": "test", "mode": "both",
                          "command": self.fixture.probe() + ["exit", "0"]}]
        self.fixture.context("src/CONTEXT.md", data)
        for command, args in (("audit", ()), ("resolve", ("src/a.py",)),
                              ("layers", ("--all",)), ("field", ("ZSource", "layer")),
                              ("contexts", ("src/a.py",)), ("run", ("ZSource",))):
            with self.subTest(command=command):
                result = self.fixture.cli(command, *args, wrapper=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(os.access(REPO / "scripts/context" / command, os.X_OK))


class FixtureIsolationTests(unittest.TestCase):
    def test_git_overrides_removed_in_children_only(self):
        outer = Fixture()
        self.addCleanup(outer.close)
        outer.write("sentinel", "unchanged")
        outer.git("add", "sentinel")
        index_before = (outer.root / ".git/index").read_bytes()
        before = os.environ.copy()
        polluted = dict(before)
        for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY",
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE",
                    "GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_EXEC_PATH",
                    "GIT_TEMPLATE_DIR", "GIT_INDEX_FILE"):
            polluted[key] = str(outer.root / ".git")
        polluted.update(GIT_INDEX_FILE=str(outer.root / ".git/index"),
                        GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.worktree",
                        GIT_CONFIG_VALUE_0=str(outer.root), GIT_CONFIG_PARAMETERS="'bad=true'")
        fixture = Fixture(polluted)
        self.addCleanup(fixture.close)
        fixture.root_index()
        fixture.leaf()
        fixture.write("src/inner.py")
        fixture.git("add", "src", "CONTEXT.md")
        self.assertEqual(str(fixture.root), fixture.git("rev-parse", "--show-toplevel").stdout.strip())
        self.assertEqual(0, fixture.cli("audit").returncode)
        self.assertEqual(index_before, (outer.root / ".git/index").read_bytes())
        self.assertEqual("sentinel\n", outer.git("ls-files").stdout)
        self.assertEqual(before, dict(os.environ))
        clean = isolated_environment(polluted)
        self.assertEqual({"GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
                          "GIT_ATTR_NOSYSTEM"}, {key for key in clean if key.startswith("GIT_")})

    def test_concurrent_roots_have_disjoint_index_context_and_execution(self):
        def work(name):
            fixture = Fixture()
            root = fixture.root
            try:
                fixture.root_index()
                fixture.leaf(layer=name, gates=[{
                    "id": "probe", "kind": "test", "mode": "both",
                    "command": fixture.probe() + ["args", name],
                }])
                fixture.write("src/" + name + ".py")
                fixture.git("add", "src", "CONTEXT.md")
                result = fixture.cli("run", name)
                self.assertEqual(0, result.returncode, result.stderr)
                probe = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual({"cwd": str(root), "args": [name]}, probe)
                self.assertEqual(name + "\n", fixture.cli("layers", "--all").stdout)
                return root, fixture.git("ls-files").stdout
            finally:
                fixture.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(work, ["North", "South"]))
        self.assertNotEqual(first[0], second[0])
        self.assertIn("src/North.py", first[1])
        self.assertNotIn("src/South.py", first[1])
        self.assertIn("src/South.py", second[1])
        self.assertFalse(first[0].exists())
        self.assertFalse(second[0].exists())
