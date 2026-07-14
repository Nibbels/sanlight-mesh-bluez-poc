import tempfile
import unittest
from pathlib import Path

from sanlight_mesh.locking import LockError, exclusive_runtime_lock


class LockingTest(unittest.TestCase):
    def test_second_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "runtime.lock"
            with exclusive_runtime_lock(path):
                with self.assertRaises(LockError):
                    with exclusive_runtime_lock(path):
                        pass
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
