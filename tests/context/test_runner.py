"""Gate preflight and real synthetic subprocess exit/argument contracts."""
import json
import io
import pathlib
import shlex
import signal
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from fixture import Fixture, PYTHON, layer_context


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)
        self.fixture.root_index()
        self.command = self.fixture.probe()
        self.fixture.leaf()

    def gate(self, ident="probe", mode="both", command=None):
        return {"id": ident, "kind": "test", "mode": mode,
                "command": self.command + ["args", ident] if command is None else command}

    def run_gates(self, gates, *args):
        self.fixture.leaf(gates=gates)
        return self.fixture.cli("run", "Source", *args)

    def assert_context_error(self, result):
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("context_error", json.loads(result.stderr)["kind"])
        self.assertEqual("", result.stdout)  # All preflight occurs before execution.

    def test_local_ci_and_both_selection_order(self):
        gates = [self.gate("local", "local"), self.gate("ci", "ci"), self.gate("both")]
        for mode, expected in (("local", ["local", "both"]), ("ci", ["ci", "both"])):
            result = self.run_gates(gates, "--mode", mode)
            self.assertEqual(0, result.returncode, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            self.assertEqual(expected, [item["args"][0] for item in records])
        result = self.run_gates(gates, "--gate", "both")
        self.assertEqual(0, result.returncode)
        self.assertEqual(["both"], json.loads(result.stdout.splitlines()[-1])["args"])

    def test_no_declared_selected_or_mode_compatible_gates_fail_closed(self):
        for gates, args in (([], ()), ([self.gate(mode="ci")], ()),
                            ([self.gate()], ("--gate", "")),
                            ([self.gate()], ("--gate", "absent")),
                            ([self.gate(mode="ci")], ("--gate", "probe"))):
            with self.subTest(gates=gates, args=args):
                self.assert_context_error(self.run_gates(gates, *args))
        data = self.fixture.data()
        del data["gates"]
        self.fixture.context("src/CONTEXT.md", data)
        self.assert_context_error(self.fixture.cli("run", "Source"))

    def test_unknown_layer(self):
        self.assert_context_error(self.fixture.cli("run", "Missing"))

    def test_nonzero_child_and_failure_red_lines(self):
        result = self.run_gates([self.gate(command=self.command + ["exit", "7"]),
                                 self.gate("never")], "--path", "src/a.py")
        self.assertEqual(7, result.returncode)
        self.assertNotIn("Source:never", result.stdout)
        self.assertEqual({
            "layer": "Source", "path": "src/a.py", "kind": "gate_failed",
            "detail": "gate=probe exit=7", "red_lines": ["synthetic boundary"],
        }, json.loads(result.stderr))

    def test_signalled_child_is_shell_conventional(self):
        result = self.run_gates([self.gate(command=self.command + ["signal"])])
        self.assertEqual(128 + signal.SIGTERM, result.returncode)
        self.assertEqual("gate=probe exit=-15", json.loads(result.stderr)["detail"])
        self.assertEqual("gate_failed", json.loads(result.stderr)["kind"])

    def test_missing_executable_is_structured(self):
        result = self.run_gates([self.gate(command=["./src/no-such-executable"])])
        self.assertEqual(1, result.returncode)
        self.assertEqual("gate_execution_failed", json.loads(result.stderr)["kind"])
        self.assertEqual(["synthetic boundary"], json.loads(result.stderr)["red_lines"])
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_gates_commands_and_placeholders(self):
        bad_commands = [[], "echo", [""], [1], ["{test_paths}"],
                        self.command + ["{unknown}"], self.command + ["{test_paths"],
                        self.command + ["prefix{test_paths}"], self.command + ["{owned_python_paths}x"]]
        for command in bad_commands:
            with self.subTest(command=command):
                self.assert_context_error(self.run_gates([self.gate(command=command)]))
        for key, value in (("mode", []), ("kind", "magic"), ("id", ""), ("mode", "never")):
            gate = self.gate()
            gate[key] = value
            self.assert_context_error(self.run_gates([gate]))
        self.assert_context_error(self.run_gates([self.gate(), self.gate()]))
        self.assert_context_error(self.run_gates([None]))

    def test_empty_expansions_fail_before_any_selected_gate(self):
        for placeholder in ("{test_paths}", "{owned_python_paths}"):
            with self.subTest(placeholder=placeholder):
                self.assert_context_error(self.run_gates([
                    self.gate("first"), self.gate("empty", command=self.command + ["args", placeholder]),
                ]))

    def test_expansions_are_owned_sorted_python_paths(self):
        self.fixture.root_index([
            {"patterns": ["src/**"], "test_paths": ["tests/source_*.py"], "context": "src/CONTEXT.md"},
            {"patterns": ["other/**"], "context": "other/CONTEXT.md"},
        ])
        self.fixture.leaf(path="other/CONTEXT.md", layer="Other", scope=["other/**"])
        self.fixture.leaf(test_paths=["tests/source_*.py"], gates=[self.gate(
            command=self.command + ["args", "{test_paths}", "--owned", "{owned_python_paths}"])])
        for path in ("src/z.py", "src/notes.txt", "tests/source_b.py", "tests/source_a.py",
                     "other/not_owned.py", "tests/source_no.txt"):
            self.fixture.write(path)
        self.fixture.git("add", "src/z.py", "src/notes.txt", "tests", "other")
        result = self.fixture.cli("run", "Source")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["tests/source_a.py", "tests/source_b.py", "--owned", "src/z.py",
                          "tests/source_a.py", "tests/source_b.py"],
                         json.loads(result.stdout.splitlines()[-1])["args"])

    def test_outside_paths_and_symlinks_prevent_execution(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        outside.write("payload.py", "raise AssertionError('must never execute')")
        (self.fixture.root / "src/escaped.py").symlink_to(outside.root / "payload.py")
        (self.fixture.root / "escaped.py").symlink_to(outside.root / "payload.py")
        for path in ("src/../../outside", str(outside.root / "payload.py"),
                     "src/escaped.py", "escaped.py", "src/a space/../../../outside"):
            with self.subTest(path=path):
                self.assert_context_error(self.run_gates([self.gate()], "--path", path))
                self.assert_context_error(self.run_gates([
                    self.gate("first"),
                    self.gate("escape", command=self.command + ["args", path]),
                ]))
        self.fixture.git("add", "src/escaped.py")
        self.assert_context_error(self.run_gates([
            self.gate(command=self.command + ["args", "{owned_python_paths}"]),
        ]))
        self.assert_context_error(self.run_gates([self.gate(command=["./src/escaped.py"])]))

    def test_inside_absolute_path_is_preserved_in_failure(self):
        path = str(self.fixture.root / "src/a.py")
        result = self.run_gates([self.gate(command=self.command + ["exit", "3"])], "--path", path)
        self.assertEqual(3, result.returncode)
        self.assertEqual(path, json.loads(result.stderr)["path"])

    def test_invalid_unselected_gate_still_rejected(self):
        self.assert_context_error(self.run_gates([
            self.gate("good"), self.gate("bad", "ci", command=[]),
        ], "--gate", "good"))

    def test_bare_parent_is_rejected_before_any_selected_subprocess(self):
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        # Cover both direct commands and expansion that would otherwise spawn
        # discovery Git before noticing the later bare-parent argument.
        for first in (self.gate("first"), self.gate(
                "first", command=self.command + ["args", "{owned_python_paths}"])):
            self.fixture.leaf(gates=[
                first, self.gate("parent", command=[PYTHON, "-I", "-B", ".."]),
            ])
            output = io.StringIO()
            with self.subTest(first=first), mock.patch.object(
                    layer_context.subprocess, "run", side_effect=AssertionError(
                        "preflight invoked a subprocess")) as child, redirect_stdout(output):
                with self.assertRaisesRegex(layer_context.ContextError, "outside repository"):
                    layer_context.command_run(args, self.fixture.root)
                child.assert_not_called()
            self.assertEqual("", output.getvalue())

    def test_bare_parent_cannot_execute_owned_parent_main(self):
        fixture = Fixture(nested=True)
        self.addCleanup(fixture.close)
        parent = fixture.root.parent
        self.assertEqual(pathlib.Path(fixture.temp.name).resolve(), parent)
        sentinel = parent / "__main__.py"
        marker = parent / "parent-executed"
        sentinel.write_text(
            "from pathlib import Path\n"
            "Path(__file__).with_name('parent-executed').write_text('synthetic execution')\n"
            "raise SystemExit(37)\n", encoding="utf-8")
        fixture.root_index()
        fixture.leaf(gates=[
            self.gate("first", command=fixture.probe() + ["args", "first"]),
            self.gate("parent", command=[PYTHON, "-I", "-B", ".."]),
        ])
        result = fixture.cli("run", "Source")
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assert_context_error(result)

    def test_inside_absolute_alias_gate_path_and_argument(self):
        alias_owner = Fixture()
        self.addCleanup(alias_owner.close)
        alias = alias_owner.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        path = str(alias / "src/probe.py")
        result = self.run_gates([self.gate(command=self.command + ["args", path])], "--path", path)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([path], json.loads(result.stdout.splitlines()[-1])["args"])
        result = self.run_gates([self.gate(command=self.command + ["exit", "7"])], "--path", path)
        self.assertEqual(7, result.returncode, result.stderr)
        self.assertEqual(path, json.loads(result.stderr)["path"])

    def test_outside_absolute_alias_stops_all_selected_gates(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        outside.write("payload.py", "raise AssertionError('must never execute')\n")
        alias = outside.root / "outside-alias"
        alias.symlink_to(outside.root, target_is_directory=True)
        self.assert_context_error(self.run_gates([
            self.gate("first"),
            self.gate("outside", command=[PYTHON, "-I", "-B", str(alias / "payload.py")]),
        ]))

    def owned_executable(self, fixture, name):
        """An executable and marker wholly owned by one disposable fixture."""
        marker = fixture.root / (name.replace("/", "-") + "-executed")
        fixture.write(name, "#!/bin/sh --\n"
                      "printf '%s\\n' synthetic > " + shlex.quote(str(marker)) + "\n"
                      "printf '%s\\n' synthetic-executable\n"
                      "printf '%s\\n' \"$@\"\n")
        executable = fixture.root / name
        executable.chmod(0o755)
        return executable, marker

    def test_executable_alias_escape_prevents_all_subprocesses(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        tool, marker = self.owned_executable(outside, "tool")
        inside, inside_marker = self.owned_executable(self.fixture, "src/inside-tool")
        alias = outside.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        chain = outside.root / "alias-chain"
        chain.symlink_to("repo-alias", target_is_directory=True)
        escaped = self.fixture.root / "src/escape-tool"
        escaped.symlink_to(tool)
        file_alias = outside.root / "file-entry"
        file_alias.symlink_to(alias / "src/escape-tool")
        (self.fixture.root / "src/outside-dir").symlink_to(outside.root, target_is_directory=True)
        (outside.root / "reentry").symlink_to(self.fixture.root, target_is_directory=True)
        unsafe_paths = [
            escaped, "/" + str(escaped), alias / "src/escape-tool", chain / "src/escape-tool", file_alias,
            alias / "src/outside-dir/tool", chain / "src/outside-dir/reentry/src/inside-tool",
            str(alias) + "/../" + outside.root.name + "/tool",
        ]
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        for path in unsafe_paths:
            for first_command in (self.command + ["args", "first"],
                                  self.command + ["args", "{owned_python_paths}"]):
                self.fixture.leaf(gates=[
                    self.gate("first", command=first_command),
                    self.gate("unsafe", command=[str(path)]),
                ])
                with self.subTest(path=path, first=first_command), redirect_stdout(io.StringIO()), \
                        mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                            "unsafe executable allowed a subprocess")) as child:
                    with self.assertRaises(layer_context.ContextError):
                        layer_context.command_run(args, self.fixture.root)
                    child.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertFalse(inside_marker.exists())

    def test_executable_alias_cannot_run_fixture_owned_outside_sentinel(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        tool, marker = self.owned_executable(outside, "tool")
        alias = outside.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        (self.fixture.root / "src/tool").symlink_to(tool)
        result = self.run_gates([
            self.gate("first"), self.gate("unsafe", command=[str(alias / "src/tool")]),
        ])
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assert_context_error(result)

    def test_expanded_preflight_rechecks_executable_alias_before_any_gate(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        external, marker = self.owned_executable(outside, "tool")
        self.owned_executable(self.fixture, "src/inside-tool")
        alias = outside.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        entry = self.fixture.root / "src/tool-entry"
        entry.symlink_to("inside-tool")
        self.fixture.write("src/owned.py")
        self.fixture.leaf(gates=[
            self.gate("first"),
            self.gate("expanded", command=[str(alias / "src/tool-entry"), "{owned_python_paths}"]),
        ])

        def discover_paths(root):
            # A deterministic seam between the two preflights, not a claim of
            # protection against arbitrary concurrent filesystem mutations.
            self.assertEqual(self.fixture.root, root)
            entry.unlink()
            entry.symlink_to(external)
            return ["src/owned.py"]

        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        with mock.patch.object(layer_context, "tracked_files", side_effect=discover_paths) as discover, \
                mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                    "expanded preflight allowed a gate subprocess")) as child, \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(layer_context.ContextError):
                layer_context.command_run(args, self.fixture.root)
            discover.assert_called_once_with(self.fixture.root)
            child.assert_not_called()
        self.assertFalse(marker.exists())

    def test_inside_executable_aliases_and_expanded_arguments_succeed(self):
        alias_owner = Fixture()
        self.addCleanup(alias_owner.close)
        tool, marker = self.owned_executable(self.fixture, "src/tool")
        alias = alias_owner.root / "repo-alias"
        alias.symlink_to(self.fixture.root, target_is_directory=True)
        chain = alias_owner.root / "alias-chain"
        chain.symlink_to("repo-alias", target_is_directory=True)
        file_alias = alias_owner.root / "file-entry"
        file_alias.symlink_to(alias / "src/tool")
        (self.fixture.root / "src/internal-tool").symlink_to("tool")
        self.fixture.write("src/owned.py")
        self.fixture.git("add", "src/owned.py")
        for path in (tool, "/" + str(tool), alias / "src/tool", chain / "src/internal-tool", file_alias):
            with self.subTest(path=path):
                result = self.run_gates([self.gate(command=[str(path), "{owned_python_paths}"])])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["synthetic-executable", "src/owned.py"], result.stdout.splitlines()[1:])
                self.assertEqual("synthetic\n", marker.read_text())

    def test_external_installed_executables_remain_allowed_only_at_argv_zero(self):
        installed = Fixture()
        self.addCleanup(installed.close)
        tool, marker = self.owned_executable(installed, "tool")
        alias = installed.root / "tool-alias"
        alias.symlink_to("tool")
        chain = installed.root / "tool-chain"
        chain.symlink_to("tool-alias")
        for path in (tool, alias, chain):
            with self.subTest(path=path):
                result = self.run_gates([self.gate(command=[str(path), "synthetic-argument"])])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["synthetic-executable", "synthetic-argument"],
                                 result.stdout.splitlines()[1:])
                self.assertEqual("synthetic\n", marker.read_text())
                # The installed-tool exception must never apply to argv[1:].
                self.assert_context_error(self.run_gates([
                    self.gate(command=self.command + ["args", str(path)]),
                ]))
        result = self.run_gates([self.gate(command=[str(installed.root / "missing-tool")])])
        self.assertEqual(1, result.returncode)
        self.assertEqual("gate_execution_failed", json.loads(result.stderr)["kind"])

    def test_host_tmp_executable_alias_cannot_escape(self):
        if pathlib.Path("/tmp").resolve() != pathlib.Path("/private/tmp"):
            self.skipTest("host does not expose the macOS /tmp ancestor alias")
        fixture = Fixture(nested=True, directory="/tmp")
        outside = Fixture()
        self.addCleanup(fixture.close)
        self.addCleanup(outside.close)
        fixture.root_index()
        tool, marker = self.owned_executable(outside, "tool")
        fixture.write("src/placeholder")
        (fixture.root / "src/tool").symlink_to(tool)
        alias = pathlib.Path("/tmp") / fixture.root.parent.name / fixture.root.name
        fixture.leaf(gates=[
            self.gate("first", command=fixture.probe() + ["args", "first"]),
            self.gate("unsafe", command=[str(alias / "src/tool")]),
        ])
        result = fixture.cli("run", "Source")
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assert_context_error(result)

    def test_dash_executable_path_matrix_prevents_all_subprocesses(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        tool, marker = self.owned_executable(outside, "tool")
        self.fixture.write("-tools/placeholder")
        self.fixture.write("--tools/placeholder")
        (self.fixture.root / "-tools/escape").symlink_to(tool)
        (self.fixture.root / "--tools/escape").symlink_to(tool)
        (self.fixture.root / "-chain").symlink_to("-tools", target_is_directory=True)
        (self.fixture.root / "-exit").symlink_to(outside.root, target_is_directory=True)
        (outside.root / "reentry").symlink_to(self.fixture.root, target_is_directory=True)
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        for path in ("-tools/escape", "--tools/escape", "-chain/escape", "-exit/tool",
                     "-exit/reentry/src/probe.py", "-tools/../../outside"):
            for first in (self.command + ["args", "first"],
                          self.command + ["args", "{owned_python_paths}"]):
                self.fixture.leaf(gates=[
                    self.gate("first", command=first), self.gate("unsafe", command=[path]),
                ])
                with self.subTest(path=path, first=first), redirect_stdout(io.StringIO()), \
                        mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                            "executable pathname skipped preflight")) as child:
                    with self.assertRaises(layer_context.ContextError):
                        layer_context.command_run(args, self.fixture.root)
                    child.assert_not_called()
        self.assertFalse(marker.exists())

    def test_dash_executable_cannot_run_outside_sentinel(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        tool, marker = self.owned_executable(outside, "tool")
        self.fixture.write("-tools/placeholder")
        (self.fixture.root / "-tools/escape").symlink_to(tool)
        result = self.run_gates([self.gate("first"), self.gate("unsafe", command=["-tools/escape"])])
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assert_context_error(result)

    def test_explicit_positionals_after_separator_are_contained(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        outside.write("payload")
        self.fixture.write("-paths/placeholder")
        (self.fixture.root / "-paths/outside").symlink_to(outside.root / "payload")
        (self.fixture.root / "-bare").symlink_to(outside.root / "payload")
        (self.fixture.root / "-encoded=..").symlink_to(outside.root, target_is_directory=True)
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        for path in ("-paths/outside", "-bare", "--", "-encoded=../payload", "..",
                     str(outside.root / "payload")):
            if path == "--":
                (self.fixture.root / "--").symlink_to(outside.root / "payload")
            self.fixture.leaf(gates=[
                self.gate("first"),
                self.gate("unsafe", command=self.command + ["args", "--", path]),
            ])
            with self.subTest(path=path), redirect_stdout(io.StringIO()), \
                    mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                        "explicit positional path skipped preflight")) as child:
                with self.assertRaises(layer_context.ContextError):
                    layer_context.command_run(args, self.fixture.root)
                child.assert_not_called()
            if path == "--":
                (self.fixture.root / "--").unlink()

    def test_dash_executable_and_positional_are_rechecked_after_expansion(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        external, marker = self.owned_executable(outside, "tool")
        self.owned_executable(self.fixture, "-tools/inside")
        entry = self.fixture.root / "-tools/entry"
        self.fixture.write("src/owned.py")
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        commands = [["-tools/entry", "{owned_python_paths}"],
                    self.command + ["args", "--", "-tools/entry", "{owned_python_paths}"]]
        for command in commands:
            if entry.is_symlink():
                entry.unlink()
            entry.symlink_to("inside")
            self.fixture.leaf(gates=[self.gate("first"), self.gate("expanded", command=command)])

            def discover_paths(root):
                self.assertEqual(self.fixture.root, root)
                entry.unlink()
                entry.symlink_to(external)
                return ["src/owned.py"]

            with self.subTest(command=command), redirect_stdout(io.StringIO()), \
                    mock.patch.object(layer_context, "tracked_files", side_effect=discover_paths) as discover, \
                    mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                        "expanded path skipped preflight")) as child:
                with self.assertRaises(layer_context.ContextError):
                    layer_context.command_run(args, self.fixture.root)
                discover.assert_called_once_with(self.fixture.root)
                child.assert_not_called()
        self.assertFalse(marker.exists())

    def test_dash_paths_valid_options_and_separator_positive_controls(self):
        outside = Fixture()
        self.addCleanup(outside.close)
        outside.write("payload")
        tool, marker = self.owned_executable(self.fixture, "-tools/run")
        self.fixture.write("-paths/inside")
        (self.fixture.root / "-option").symlink_to(outside.root / "payload")
        (self.fixture.root / "--").symlink_to(outside.root / "payload")
        (self.fixture.root / "-encoded=..").symlink_to(outside.root, target_is_directory=True)
        options = ["-v", "--verbose", "-option", "-encoded=../payload", "--value=/synthetic/outside"]
        arguments = options + ["--", "-paths/inside", "src/probe.py", "."]
        for executable in ("-tools/run", "./-tools/run", str(tool)):
            with self.subTest(executable=executable):
                result = self.run_gates([self.gate(command=[executable] + arguments)])
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["synthetic-executable"] + arguments, result.stdout.splitlines()[1:])
                self.assertEqual("synthetic\n", marker.read_text())

    def test_non_utf8_command_rejected_before_any_discovery_or_gate_subprocess(self):
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        malformed = [chr(0xD800), chr(0xDC80), "prefix" + chr(0xDFFF),
                     "--option=" + chr(0xD800)]
        for token in malformed:
            for command in ([token], self.command + ["args", token]):
                self.fixture.leaf(gates=[
                    self.gate("first", command=self.command + ["args", "{owned_python_paths}"]),
                    self.gate("malformed", command=command),
                ])
                with self.subTest(token=ascii(token), command=ascii(command)), \
                        redirect_stdout(io.StringIO()), \
                        mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                            "malformed command allowed a subprocess")) as child:
                    with self.assertRaises(layer_context.ContextError) as raised:
                        layer_context.command_run(args, self.fixture.root)
                    self.assertIn("UTF-8", str(raised.exception))
                    str(raised.exception).encode("utf-8", errors="strict")
                    child.assert_not_called()

    def test_non_utf8_later_gate_is_safe_cli_error_without_earlier_execution(self):
        first, marker = self.owned_executable(self.fixture, "src/first")
        result = self.run_gates([
            self.gate("first", command=[str(first)]),
            self.gate("malformed", command=self.command + ["args", chr(0xD800)]),
        ])
        self.assertFalse(marker.exists(), result.stdout + result.stderr)
        self.assert_context_error(result)
        self.assertIn("UTF-8", json.loads(result.stderr)["detail"])
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("UnicodeEncodeError", result.stderr)

    def test_non_utf8_unselected_command_still_fails_validation(self):
        result = self.run_gates([
            self.gate("good"),
            self.gate("bad", mode="ci", command=self.command + ["args", chr(0xD800)]),
        ], "--gate", "good")
        self.assert_context_error(result)
        self.assertIn("UTF-8", json.loads(result.stderr)["detail"])

    def test_valid_unicode_arguments_and_expanded_paths_are_preserved(self):
        self.fixture.write("src/路径.py")
        self.fixture.git("add", "src/路径.py")
        values = ["café", "路径", "😀", "e\u0301"]
        result = self.run_gates([self.gate(
            command=self.command + ["args"] + values + ["{owned_python_paths}"])])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(values + ["src/路径.py"], json.loads(result.stdout.splitlines()[-1])["args"])
        self.assertIn("😀", result.stdout.splitlines()[0])

    def test_non_utf8_expansion_is_rejected_before_path_access_or_gate_execution(self):
        self.fixture.leaf(gates=[
            self.gate("first"),
            self.gate("expanded", command=self.command + ["args", "{owned_python_paths}"]),
        ])
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        original = layer_context.normalize_path

        def check_valid_path(root, raw, **kwargs):
            # The malformed expansion must be rejected before any filesystem API.
            raw.encode("utf-8", errors="strict")
            return original(root, raw, **kwargs)

        for value in (chr(0xD800), chr(0xDC80)):
            with self.subTest(value=ascii(value)), redirect_stdout(io.StringIO()), \
                    mock.patch.object(layer_context, "tracked_files",
                                      return_value=["src/bad" + value + ".py"]) as discover, \
                    mock.patch.object(layer_context, "normalize_path", side_effect=check_valid_path), \
                    mock.patch.object(layer_context.subprocess, "run", side_effect=AssertionError(
                        "malformed expansion allowed a gate subprocess")) as child:
                with self.assertRaisesRegex(layer_context.ContextError, "UTF-8") as raised:
                    layer_context.command_run(args, self.fixture.root)
                str(raised.exception).encode("utf-8", errors="strict")
                discover.assert_called_once_with(self.fixture.root)
                child.assert_not_called()

    def test_non_utf8_gate_log_label_is_rejected_before_discovery(self):
        self.fixture.leaf(gates=[
            self.gate("first", command=self.command + ["args", "{owned_python_paths}"]),
            self.gate("label" + chr(0xD800), command=self.command + ["args", "safe"]),
        ])
        args = SimpleNamespace(layer="Source", gate=None, mode="local", path=None)
        with redirect_stdout(io.StringIO()), mock.patch.object(
                layer_context.subprocess, "run", side_effect=AssertionError(
                    "malformed log label allowed a subprocess")) as child:
            with self.assertRaisesRegex(layer_context.ContextError, "gate log.*UTF-8") as raised:
                layer_context.command_run(args, self.fixture.root)
            str(raised.exception).encode("utf-8", errors="strict")
            child.assert_not_called()
