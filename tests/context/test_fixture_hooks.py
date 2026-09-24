"""Real fixture-local hook behavior without commits or external hook installers."""
import os
import pathlib
import shlex
import unittest

from fixture import Fixture


class FixtureHookTests(unittest.TestCase):
    def test_local_hook_runs_without_changing_parent_or_source(self):
        environment_before = dict(os.environ)
        cwd_before = pathlib.Path.cwd()
        source = Fixture()
        self.addCleanup(source.close)
        source.write("sentinel", "source unchanged\n")
        source.git("add", "--", "sentinel")
        source_before = {
            path: (source.root / path).read_bytes()
            for path in ("sentinel", ".git/index", ".git/config", ".git/HEAD")
        }

        # These are synthetic routing inputs, never changes to os.environ or
        # to the source repository's actual configuration.
        polluted = dict(environment_before)
        for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG",
                    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_EXEC_PATH",
                    "GIT_TEMPLATE_DIR", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE"):
            polluted[key] = str(source.root / ".git")
        polluted.update(
            GIT_WORK_TREE=str(source.root),
            GIT_INDEX_FILE=str(source.root / ".git/index"),
            GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.worktree",
            GIT_CONFIG_VALUE_0=str(source.root),
            GIT_CONFIG_PARAMETERS="'core.worktree=" + str(source.root) + "'",
        )
        polluted_before = dict(polluted)
        fixture = Fixture(polluted, nested=True)
        self.addCleanup(fixture.close)
        # nested=True owns this parent too; no shared temp/source parent writes.
        parent_sentinel = fixture.root.parent / "parent-sentinel"
        parent_sentinel.write_text("parent unchanged\n", encoding="utf-8")
        marker = fixture.root / "hook-marker"
        hook = fixture.root / ".git/hooks/post-index-change"
        self.assertFalse(hook.exists())
        self.assertFalse(marker.exists())

        # Git runs this normal hook after writing the index. Only the installed
        # /bin/sh and its builtins execute; the sole output has an owned absolute
        # path, guarded by the expected physical working directory.
        fixture.write(".git/hooks/post-index-change", (
            "#!/bin/sh\n"
            "[ \"$(pwd -P)\" = " + shlex.quote(str(fixture.root)) + " ] || exit 1\n"
            "printf '%s\\n' 'fixture-local-hook' > " + shlex.quote(str(marker)) + "\n"
        ))
        hook.chmod(0o700)
        fixture.write("tracked.txt", "synthetic index entry\n")
        result = fixture.git("add", "--", "tracked.txt")

        self.assertTrue(marker.is_file(), "Fixture.git must honor its fixture-local hook")
        self.assertEqual("fixture-local-hook\n", marker.read_text(encoding="utf-8"))
        self.assertEqual(["/usr/bin/git", "add", "--", "tracked.txt"], result.args)
        self.assertEqual("tracked.txt\n", fixture.git("ls-files").stdout)
        self.assertEqual(str(fixture.root),
                         fixture.git("rev-parse", "--show-toplevel").stdout.strip())
        for path, content in source_before.items():
            with self.subTest(source_path=path):
                self.assertEqual(content, (source.root / path).read_bytes())
        self.assertFalse((source.root / "hook-marker").exists())
        self.assertFalse((source.root / ".git/hooks/post-index-change").exists())
        self.assertFalse((fixture.root.parent / "hook-marker").exists())
        self.assertEqual("parent unchanged\n", parent_sentinel.read_text(encoding="utf-8"))
        self.assertEqual(polluted_before, polluted)
        self.assertEqual(environment_before, dict(os.environ))
        self.assertEqual(cwd_before, pathlib.Path.cwd())
