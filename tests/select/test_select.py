"""Changed-layer selection: fixture repositories, fail-closed full runs, dependents."""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "select" / "layers.py"
SPEC = importlib.util.spec_from_file_location("shared_ci_select", SCRIPT)
select = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(select)
PIN = "1" * 40
NEW_PIN = "3" * 40

ROOT = """---
layer: _root
support:
  - patterns: ["*.md", "docs/**", ".github/**", ".githooks/**", "scripts/**"]
    reason: support files
---

# Fixture

| Layer | Responsibility | tech-context | depends_on |
|---|---|---|---|
| Domain | types | `src/domain/tech-context.md` | (none) |
| Infra | adapters | `src/infra/tech-context.md` | Domain |
| App | wiring | `src/app/tech-context.md` | Domain, Infra |
| Tools | standalone | `src/tools/tech-context.md` | (none) |
"""


def leaf(layer: str, owns: str, depends: str) -> str:
    return f"---\nlayer: {layer}\nowns: [{owns}]\ndepends_on: [{depends}]\n---\n# {layer}\n"


FILES = {
    "AGENTS.md": f"# AGENTS\n\nFollow `LeePepe/shared-ci@{PIN}/ai/agent-protocol.md`.\n\nOther text.\n",
    "README.md": "# Fixture\n",
    "docs/architecture/tech-context.md": ROOT,
    "src/domain/tech-context.md": leaf("Domain", "src/domain/**", ""),
    "src/domain/model.py": "X = 1\n",
    "src/infra/tech-context.md": leaf("Infra", "src/infra/**", "Domain"),
    "src/infra/db.py": "Y = 1\n",
    "src/app/tech-context.md": leaf("App", "src/app/**", "Domain, Infra"),
    "src/app/main.py": "Z = 1\n",
    "src/tools/tech-context.md": leaf("Tools", "src/tools/**", ""),
    "src/tools/snap.py": "T = 1\n",
    "docs/guide.md": "guide\n",
    ".github/workflows/ci.yml": "name: ci\n",
    "scripts/verify": "#!/bin/sh\necho ok\n",
}


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                "LC_ALL": "C.UTF-8"})
    return env


class Fixture:
    """A git repo with a base commit on main and a PR branch on top."""

    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="shared-ci-select-")
        self.root = pathlib.Path(self.temp.name).resolve()
        self.env = environment()
        self.git("init", "-q", "-b", "main")
        for path, content in FILES.items():
            self.write(path, content)
        self.commit("base")
        self.base = self.rev()
        self.git("checkout", "-q", "-b", "pr")

    def close(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True, timeout=20).stdout

    def rev(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.rev()

    def change(self, *paths: str) -> str:
        for path in paths:
            existing = self.root / path
            old = existing.read_text(encoding="utf-8") if existing.exists() else ""
            self.write(path, old + "# changed\n")
        return self.commit("change")

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=60)

    def select(self, event: str = "pull_request", *, base: str | None = None, head: str | None = None,
               extra: str = "") -> dict:
        args = ["--event", event, "--base", base if base is not None else self.base,
                "--head", head if head is not None else self.rev()]
        if extra:
            args += ["--force-full-paths", extra]
        result = self.cli(*args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


class SelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Fixture()
        self.addCleanup(self.repo.close)

    def assertFull(self, selection: dict, fragment: str) -> None:
        self.assertTrue(selection["full"], selection)
        self.assertTrue(selection["any_layer"])
        self.assertEqual(["App", "Domain", "Infra", "Tools"], selection["layers"])
        self.assertTrue(any(fragment in trigger for trigger in selection["triggers"]), selection["triggers"])

    # ---- selective ---------------------------------------------------------
    def test_single_layer_leaf_selects_only_that_layer(self):
        self.repo.change("src/app/main.py")
        selection = self.repo.select()
        self.assertEqual((False, True, ["App"], []), (selection["full"], selection["any_layer"],
                                                      selection["layers"], selection["triggers"]))

    def test_single_layer_change_adds_transitive_dependents(self):
        self.repo.change("src/domain/model.py")
        selection = self.repo.select()
        self.assertFalse(selection["full"])
        self.assertEqual(["App", "Domain", "Infra"], selection["layers"])  # Tools is standalone
        self.assertIn("dependents: App, Infra", selection["reason"])

    def test_middle_layer_change_adds_only_its_dependents(self):
        self.repo.change("src/infra/db.py")
        self.assertEqual(["App", "Infra"], self.repo.select()["layers"])

    def test_standalone_layer(self):
        self.repo.change("src/tools/snap.py")
        self.assertEqual(["Tools"], self.repo.select()["layers"])

    def test_merge_base_ignores_new_commits_on_base(self):
        self.repo.change("src/tools/snap.py")
        head = self.repo.rev()
        self.repo.git("checkout", "-q", "main")
        self.repo.change("src/domain/model.py")
        main_tip = self.repo.rev()
        self.repo.git("checkout", "-q", "pr")
        self.assertEqual(["Tools"], self.repo.select(base=main_tip, head=head)["layers"])

    def test_docs_only_selects_no_layer(self):
        self.repo.change("docs/guide.md", "README.md")
        selection = self.repo.select()
        self.assertEqual((False, False, []), (selection["full"], selection["any_layer"], selection["layers"]))
        self.assertIn("only support paths changed", selection["reason"])

    def test_changed_gate_script_selects_its_layer(self):
        text = (self.repo.root / "src/tools/tech-context.md").read_text()
        self.repo.write("src/tools/tech-context.md",
                        text.replace("---\n# ", "gate: {check: \"python3 scripts/tests/check_tools.py\"}\n---\n# ", 1))
        self.repo.write("scripts/tests/check_tools.py", "print(1)\n")
        self.repo.commit("gate")
        self.repo.base = self.repo.rev()
        self.repo.change("scripts/tests/check_tools.py")
        selection = self.repo.select()
        self.assertEqual((False, ["Tools"]), (selection["full"], selection["layers"]))

    def test_agents_prose_change_is_not_a_pin_change(self):
        self.repo.change("AGENTS.md")
        self.assertFalse(self.repo.select()["full"])

    def test_empty_diff_is_defined_contract_and_lint_only(self):
        selection = self.repo.select(head=self.repo.commit("empty"))
        self.assertEqual((False, False, [], []), (selection["full"], selection["any_layer"],
                                                  selection["layers"], selection["changed"]))
        self.assertIn("empty diff", selection["reason"])

    # ---- full runs ---------------------------------------------------------
    def test_unmapped_path_is_full(self):
        self.repo.write("unowned/thing.py", "x\n")
        self.repo.commit("unmapped")
        self.assertFull(self.repo.select(), "unowned/thing.py: unmapped")

    def test_manifest_change_is_full(self):
        for manifest in ("src/app/Package.swift", "src/app/package-lock.json", "requirements.txt"):
            with self.subTest(manifest=manifest):
                repo = Fixture()
                self.addCleanup(repo.close)
                repo.write(manifest, "{}\n")
                repo.commit("manifest")
                self.assertFull(repo.select(), "dependency manifest")

    def test_github_change_is_full(self):
        self.repo.change(".github/workflows/ci.yml")
        self.assertFull(self.repo.select(), ".github/workflows/ci.yml: CI wiring")

    def test_scripts_verify_and_scripts_ci_are_full(self):
        self.repo.change("scripts/verify")
        self.assertFull(self.repo.select(), "scripts/verify: CI wiring")
        self.repo.write("scripts/ci/fetch.sh", "x\n")
        self.repo.commit("ci script")
        self.assertFull(self.repo.select(), "scripts/ci/fetch.sh: CI wiring")

    def test_layer_map_change_is_full(self):
        self.repo.change("src/tools/tech-context.md")
        self.assertFull(self.repo.select(), "layer map")

    def test_shared_ci_pin_change_is_full(self):
        text = (self.repo.root / "AGENTS.md").read_text(encoding="utf-8").replace(PIN, NEW_PIN)
        self.repo.write("AGENTS.md", text)
        self.repo.commit("pin")
        self.assertFull(self.repo.select(), "shared-ci pin changed")

    def test_caller_force_full_pattern(self):
        self.repo.change("docs/guide.md")
        self.assertFull(self.repo.select(extra="docs/guide.md, other/**"), "caller force-full pattern")

    def test_non_pr_events_are_full(self):
        self.repo.change("src/tools/snap.py")
        for event in ("push", "schedule", "workflow_dispatch", "merge_group", ""):
            with self.subTest(event=event):
                self.assertFull(self.repo.select(event), "always runs in full")

    def test_push_to_main_is_full_without_base(self):
        self.assertFull(self.repo.select("push", base=""), "event push always runs in full")

    def test_resolver_error_is_full(self):
        self.repo.write("docs/architecture/tech-context.md", "no frontmatter\n")
        self.repo.commit("break map")
        selection = self.repo.select()
        self.assertTrue(selection["full"] and selection["any_layer"], selection)
        self.assertTrue(any("resolver error" in t for t in selection["triggers"]), selection["triggers"])

    def test_resolver_exception_during_resolve_is_full(self):
        self.repo.change("src/app/main.py")

        class Broken:
            match_pattern = staticmethod(lambda path, pattern: False)

            @staticmethod
            def layer_map(root):
                return {"App": {"dependencies": []}}

            @staticmethod
            def resolve(root, path):
                raise RuntimeError("boom")

        # Unlike CLI fixtures, a direct engine call inherits the test process
        # environment. Git hooks export GIT_DIR for the parent repository.
        with mock.patch.dict(os.environ, self.repo.env, clear=True):
            selection = select.select(self.repo.root, event="pull_request", base=self.repo.base,
                                      head=self.repo.rev(), extra_patterns=[], ctx=Broken())
        self.assertTrue(selection["full"])
        self.assertIn("src/app/main.py", selection["unmapped"])

    def test_git_error_is_full(self):
        self.assertFull(self.repo.select(base="f" * 40), "diff error")

    def test_missing_pr_shas_are_full(self):
        self.assertFull(self.repo.select(base=""), "base/head SHA unavailable")
        self.assertFull(self.repo.select(head="HEAD"), "base/head SHA unavailable")

    def test_not_a_git_repository_is_full(self):
        with tempfile.TemporaryDirectory() as empty:
            result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--event", "pull_request",
                                     "--base", "a" * 40, "--head", "b" * 40], cwd=empty,
                                    env=self.repo.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["full"] and data["any_layer"])

    def test_mixed_docs_and_unmapped_is_full(self):
        self.repo.change("docs/guide.md")
        self.repo.write("stray.txt", "x\n")
        self.repo.commit("stray")
        self.assertFull(self.repo.select(), "stray.txt: unmapped")

    # ---- outputs -----------------------------------------------------------
    def test_github_outputs(self):
        self.repo.change("src/infra/db.py")
        output = self.repo.root.parent / (self.repo.root.name + ".out")
        summary = self.repo.root.parent / (self.repo.root.name + ".md")
        self.addCleanup(lambda: [p.unlink() for p in (output, summary) if p.exists()])
        result = self.repo.cli("--event", "pull_request", "--base", self.repo.base, "--head", self.repo.rev(),
                               "--github-output", str(output), "--step-summary", str(summary))
        self.assertEqual(0, result.returncode, result.stderr)
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        self.assertEqual(("false", "true", '["App","Infra"]', "App Infra"),
                         (values["full"], values["any-layer"], values["layers"], values["layers-space"]))
        record = json.loads(values["selection"])
        self.assertEqual((self.repo.rev(), "changed-only", 1), (record["head"], record["mode"], record["changed_count"]))
        self.assertIn("layer selection: changed-only", summary.read_text())

    def test_disabled_mode_is_full_and_reads_no_diff(self):
        result = self.repo.cli("--mode", "disabled", "--event", "pull_request", "--head", self.repo.rev())
        data = json.loads(result.stdout)
        self.assertEqual(("disabled", True, True, []), (data["mode"], data["full"], data["any_layer"], data["changed"]))

    def test_output_lists_are_capped(self):
        record = select.compact_selection({"changed": ["x"] * 500, "unmapped": [], "triggers": ["t"] * 300,
                                           "full": True})
        self.assertEqual((200, 500, 300), (len(record["changed"]), record["changed_count"], record["triggers_count"]))

    def test_dependents_closure_uses_declared_dependents_too(self):
        layers = {"A": {"dependencies": []}, "B": {"dependencies": [], "dependents": []},
                  "C": {"dependencies": ["B"]}, "D": {"dependencies": [], "dependents": ["A"]}}
        self.assertEqual({"B", "C"}, select.dependents_closure(layers, {"B"}))
        self.assertEqual({"D", "A"}, select.dependents_closure(layers, {"D"}))

    def test_plain_python_invocation_selects(self):
        # The workflows run `python3 scripts/select/layers.py` without -I; the script's
        # directory is then sys.path[0] and must not shadow a stdlib module.
        self.repo.change("src/tools/snap.py")
        result = subprocess.run([sys.executable, str(SCRIPT), "--event", "pull_request", "--base", self.repo.base,
                                 "--head", self.repo.rev()], cwd=self.repo.root, env=self.repo.env,
                                capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
        self.assertEqual((False, ["Tools"], []), (data["full"], data["layers"], data["triggers"]))

    def test_usage_error_exits_2(self):
        self.assertEqual(2, self.repo.cli().returncode)


class TemplateVerifySelectedTests(unittest.TestCase):
    """templates/scripts/verify --selected honours the CI selection and fails closed."""

    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location("shared_ci_repo_fixture", REPO / "tests/repo/fixture.py")
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              check=True).stdout.strip()
        self.repo = fixture.ContractRepo()
        self.addCleanup(self.repo.close)
        # A contract-clean caller pinned to this checkout, with printing gates.
        for path in ("AGENTS.md", ".github/workflows/ci.yml"):
            self.repo.write(path, (self.repo.root / path).read_text().replace(fixture.PIN, head))
        for path, layer in (("src/core/tech-context.md", "Core"), ("src/app/tech-context.md", "App")):
            text = (self.repo.root / path).read_text()
            text = re.sub(r"gate:.*?(?=red_lines:)", f'gate:\n  test: [python3, -c, "print(\'gate-{layer}\')"]\n',
                          text, flags=re.DOTALL)
            self.repo.write(path, text)
        self.repo.write("scripts/verify", (REPO / "templates/scripts/verify").read_text())
        (self.repo.root / "scripts/verify").chmod(0o755)
        self.repo.add()
        self.shared = tempfile.TemporaryDirectory(prefix="shared-ci-pin-")
        self.addCleanup(self.shared.cleanup)
        self.checkout = self.shared.name + "/c"
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(REPO), self.checkout],
                       check=True, capture_output=True, env=self.repo.env)
        subprocess.run(["git", "-C", self.checkout, "checkout", "-q", "--detach", head],
                       check=True, capture_output=True, env=self.repo.env)

    def verify(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = dict(self.repo.env, SHARED_CI=self.checkout, **env)
        return subprocess.run(["bash", "scripts/verify", *args], cwd=self.repo.root, env=environment,
                              capture_output=True, text=True, timeout=120)

    def gates(self, result: subprocess.CompletedProcess) -> list[str]:
        return sorted(line for line in result.stdout.splitlines() if line.startswith("gate-"))

    def test_selected_layers_only(self):
        result = self.verify("--selected", CI_SELECTION_FULL="false", CI_SELECTED_LAYERS="App")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["gate-App"], self.gates(result))

    def test_full_or_missing_selection_runs_every_layer(self):
        for env in ({"CI_SELECTION_FULL": "true", "CI_SELECTED_LAYERS": "App"}, {}, {"CI_SELECTION_FULL": ""}):
            with self.subTest(env=env):
                result = self.verify("--selected", **env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(["gate-App", "gate-Core"], self.gates(result))

    def test_unknown_selected_layer_fails(self):
        result = self.verify("--selected", CI_SELECTION_FULL="false", CI_SELECTED_LAYERS="Ghost")
        self.assertEqual(1, result.returncode)
        self.assertIn("unknown selected layer: Ghost", result.stderr)

if __name__ == "__main__":
    unittest.main()
