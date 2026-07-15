import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sanlight_mesh.gateway_store import GatewayStore


class GatewayStoreTest(unittest.TestCase):
    def test_dedup_result_and_node_state_survive_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
            store = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            store.remember_result("a", {"ok": True}, now=now)
            store.update_node("0003", 48, now=now)
            reloaded = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            self.assertEqual(reloaded.get_result("a"), {"ok": True})
            self.assertEqual(reloaded.get_node("0003").max_brightness, 48)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


    def test_inflight_marker_is_persistent_and_cleared_by_final_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            store.mark_inflight("write-1", {"action": "set-max", "target": "0003"})
            reloaded = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            self.assertEqual(
                reloaded.get_inflight("write-1")["command"]["target"], "0003"
            )
            reloaded.remember_result("write-1", {"ok": True})
            self.assertIsNone(reloaded.get_inflight("write-1"))

    def test_prunes_expired_and_limits_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
            store = GatewayStore(path, dedup_ttl_seconds=60, dedup_max_entries=2)
            store.remember_result("old", {"ok": True}, now=now - timedelta(seconds=61))
            store.remember_result("new1", {"ok": True}, now=now - timedelta(seconds=1))
            store.remember_result("new2", {"ok": True}, now=now)
            store.prune(now)
            self.assertIsNone(store.get_result("old"))
            self.assertIsNotNone(store.get_result("new1"))
            self.assertIsNotNone(store.get_result("new2"))
