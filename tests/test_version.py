from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("envman_version", Path(__file__).parents[1] / "scripts" / "version.py")
assert SPEC is not None and SPEC.loader is not None
version_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version_tool)


class VersionPolicyTests(unittest.TestCase):
    def test_fully_reverted_commit_does_not_contribute_a_bump(self) -> None:
        original = ("a1b2c3d4e5f6", "feat: add temporary behavior", "")
        revert = ("f6e5d4c3b2a1", 'Revert "feat: add temporary behavior"', "This reverts commit a1b2c3d4e5f6.")
        self.assertEqual(version_tool.active_records([revert, original]), [])

    def test_unrelated_commit_remains_active_after_revert(self) -> None:
        original = ("a1b2c3d4e5f6", "fix: retain behavior", "")
        keep = ("b2c3d4e5f6a1", "docs: clarify usage", "")
        revert = ("c3d4e5f6a1b2", 'Revert "fix: retain behavior"', "This reverts commit a1b2c3d4e5f6.")
        self.assertEqual(version_tool.active_records([revert, keep, original]), [keep])


if __name__ == "__main__":
    unittest.main()
