from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTest(unittest.TestCase):
    def test_version_is_semver_and_documented(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?$")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {version} - ", changelog)

    def test_release_script_uses_version_file_and_read_only_git_status(self) -> None:
        script = (ROOT / "scripts" / "release-archive.sh").read_text(encoding="utf-8")
        self.assertIn("< VERSION", script)
        self.assertIn("GIT_OPTIONAL_LOCKS=0 git status --short", script)
        self.assertRegex(script, re.compile(r"\(exclude\)private"))


if __name__ == "__main__":
    unittest.main()
