"""Identity scanning uses Git filenames, not the narrower route URL syntax."""
import json
import unittest

from fixture import ContractRepo


class IdentityFilenameTests(unittest.TestCase):
    def test_regular_tracked_filenames_retain_identity_scan_coverage(self):
        for name in ("tab\tname.py", "newline\nname.py", 'double"quote.py',
                     "single'quote.py", "back\\slash.py"):
            with self.subTest(name=name):
                repo = ContractRepo()
                self.addCleanup(repo.close)
                path = "src/core/" + name
                # Synthetic forbidden text stays assembled, never in the source.
                repo.write(path, repr("/User" + "s/example/file") + "\n")
                repo.add()
                self.assertIn(path, repo.git("ls-files", "-z").stdout.split("\0"))
                result = repo.cli("audit")
                findings = [json.loads(line) for line in result.stderr.splitlines()]
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertTrue(any(f["kind"] == "contract_identity" and f["path"] == path + ":1"
                                    for f in findings), findings)
                self.assertFalse(json.loads(result.stdout)["ok"])

                repo.write(path, "VALUE = 1\n")
                result = repo.cli("audit")
                findings = [json.loads(line) for line in result.stderr.splitlines()]
                self.assertFalse(any(f["kind"] == "contract_identity" for f in findings), findings)


if __name__ == "__main__":
    unittest.main()
