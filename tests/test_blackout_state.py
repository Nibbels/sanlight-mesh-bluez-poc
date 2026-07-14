import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sanlight_mesh.blackout_state import (
    BlackoutEntry,
    create_blackout_snapshot,
    load_blackout_snapshot,
    resolve_blackout_snapshot_path,
)
from sanlight_mesh.state import StateError


class BlackoutStateTest(unittest.TestCase):
    MESH = UUID("11111111-1111-1111-1111-111111111111")
    SENDER = UUID("22222222-2222-2222-2222-222222222222")

    def test_snapshot_is_private_and_round_trips_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / ".state"
            snapshot = create_blackout_snapshot(
                state_dir=state_dir,
                mesh_uuid=self.MESH,
                sender_uuid=self.SENDER,
                sender_unicast=0x2800,
                entries=(
                    BlackoutEntry(0x0002, "Left", 68),
                    BlackoutEntry(0x0003, "Right", 0),
                ),
                now=datetime(2026, 7, 15, 10, 30, tzinfo=timezone.utc),
            )
            self.assertEqual(snapshot.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(snapshot.path.parent.stat().st_mode & 0o777, 0o700)
            loaded = load_blackout_snapshot(
                snapshot.path,
                expected_mesh_uuid=self.MESH,
                expected_sender_uuid=self.SENDER,
                expected_sender_unicast=0x2800,
                known_nodes={0x0002: "Left", 0x0003: "Right"},
            )
            self.assertEqual([entry.percent for entry in loaded.entries], [68, 0])
            self.assertEqual(resolve_blackout_snapshot_path("latest", state_dir), snapshot.path)

    def test_snapshot_rejects_unrestorable_value(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(StateError):
                create_blackout_snapshot(
                    state_dir=Path(directory),
                    mesh_uuid=self.MESH,
                    sender_uuid=self.SENDER,
                    sender_unicast=0x2800,
                    entries=(BlackoutEntry(0x0002, "Left", 19),),
                )

    def test_overbroad_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text("{}", encoding="utf-8")
            os.chmod(path, 0o644)
            with self.assertRaises(StateError):
                load_blackout_snapshot(
                    path,
                    expected_mesh_uuid=self.MESH,
                    expected_sender_uuid=self.SENDER,
                    expected_sender_unicast=0x2800,
                    known_nodes={0x0002: "Left"},
                )


if __name__ == "__main__":
    unittest.main()
