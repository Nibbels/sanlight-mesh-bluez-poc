import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sanlight_mesh.sequence_recovery import (
    MESH_SEQUENCE_MAX,
    RECOVERY_TARGET_MAX,
    SequenceRecoveryError,
    advance_node_sequence,
    parse_sequence_target,
    validate_recovery_target,
)


class SequenceRecoveryTest(unittest.TestCase):
    def make_node(self, root: Path, sequence: int = 11, unicast: str = "2800") -> Path:
        node_dir = root / "uuid"
        node_dir.mkdir()
        path = node_dir / "node.json"
        path.write_text(
            json.dumps(
                {
                    "unicastAddress": unicast,
                    "sequenceNumber": sequence,
                    "deviceKey": "DO-NOT-PRINT-TEST-VALUE",
                }
            ),
            encoding="utf-8",
        )
        os.chmod(path, 0o600)
        return path

    def test_target_is_24_bit_and_has_stricter_project_ceiling(self):
        self.assertEqual(validate_recovery_target(0x100000), 0x100000)
        with self.assertRaisesRegex(ValueError, "24-bit"):
            validate_recovery_target(MESH_SEQUENCE_MAX + 1)
        with self.assertRaisesRegex(ValueError, "safety ceiling"):
            validate_recovery_target(RECOVERY_TARGET_MAX + 1)
        with self.assertRaises(ValueError):
            parse_sequence_target(str((1 << 64) - 5))

    def test_advance_is_forward_only_atomic_and_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_node(root)
            backups = root / "backups"
            result = advance_node_sequence(
                path,
                expected_unicast=0x2800,
                minimum=0x100000,
                backup_root=backups,
                timestamp=datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc),
            )
            self.assertTrue(result.changed)
            self.assertEqual(result.previous, 11)
            self.assertEqual(result.current, 0x100000)
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(result.backup_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backups.stat().st_mode & 0o777, 0o700)
            current = json.loads(path.read_text(encoding="utf-8"))
            backup = json.loads(result.backup_path.read_text(encoding="utf-8"))
            self.assertEqual(current["sequenceNumber"], 0x100000)
            self.assertEqual(backup["sequenceNumber"], 11)

    def test_repeating_same_minimum_does_not_increment_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_node(root, sequence=0x100000)
            result = advance_node_sequence(
                path,
                expected_unicast=0x2800,
                minimum=0x100000,
                backup_root=root / "backups",
            )
            self.assertFalse(result.changed)
            self.assertEqual(result.current, 0x100000)
            self.assertIsNone(result.backup_path)

    def test_identity_mismatch_is_rejected_without_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_node(root, unicast="2400")
            backups = root / "backups"
            with self.assertRaisesRegex(SequenceRecoveryError, "identity mismatch"):
                advance_node_sequence(
                    path,
                    expected_unicast=0x2800,
                    minimum=0x100000,
                    backup_root=backups,
                )
            self.assertFalse(backups.exists())


if __name__ == "__main__":
    unittest.main()
