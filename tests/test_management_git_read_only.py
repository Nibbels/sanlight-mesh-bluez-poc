from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/sanlight-gateway"


class ManagementGitReadOnlyTest(unittest.TestCase):
    def test_all_management_git_reads_disable_optional_locks(self) -> None:
        helper = HELPER.read_text(encoding="utf-8")

        self.assertIn("git_read_only()", helper)
        self.assertIn('GIT_OPTIONAL_LOCKS=0 git -C "$REPO_DIR" "$@"', helper)
        self.assertIn("git_read_only branch --show-current", helper)
        self.assertEqual(helper.count("git_read_only status --short"), 2)
        self.assertIn("git_read_only log -1 --oneline", helper)
        self.assertNotIn('git -C "$REPO_DIR" status --short', helper)

    def test_optional_lock_setting_prevents_status_index_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "config", "user.name", "Test"],
                check=True,
            )
            tracked = repository / "tracked.txt"
            tracked.write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(repository), "commit", "-qm", "initial"], check=True)

            index = repository / ".git" / "index"
            before = index.stat().st_mtime_ns
            tracked.write_text("changed\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repository), "status", "--short"],
                check=True,
                env={"GIT_OPTIONAL_LOCKS": "0"},
                capture_output=True,
                text=True,
            )
            after = index.stat().st_mtime_ns

            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
