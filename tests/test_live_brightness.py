import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sanlight_mesh.gateway_config import GatewayConfig, MqttConfig
from sanlight_mesh.gateway_executor import CliCommandExecutor, ProcessResult
from sanlight_mesh.gateway_protocol import GatewayCommand
from sanlight_mesh.gateway_store import GatewayStore
from sanlight_mesh.protocol import (
    LiveStatus,
    decode_uptime_brightness_status_parameters,
)


class FakeCliExecutor(CliCommandExecutor):
    def __init__(self, config, node_addresses, results):
        super().__init__(config, node_addresses)
        self.results = list(results)
        self.calls = []

    def _run(self, arguments, timeout=None):
        self.calls.append((list(arguments), timeout))
        return self.results.pop(0)


def make_config(root: Path) -> GatewayConfig:
    (root / "sanlight_canonical_sender_poc.py").write_text("", encoding="utf-8")
    return GatewayConfig(
        config_path=root / "gateway.toml",
        project_root=root,
        gateway_id="test",
        cdb_path=root / "private.json",
        control_app_id=1,
        sender_app_id=2,
        state_dir=root / ".state",
        command_timeout_seconds=45,
        queue_max_size=10,
        dedup_ttl_seconds=3600,
        dedup_max_entries=32,
        coalesce_window_seconds=0,
        state_fresh_seconds=0,
        refresh_on_start=False,
        refresh_interval_seconds=0,
        topic_prefix="sanlightmesh/v1",
        mqtt=MqttConfig("broker", 1883, "client", None, None, 60, 1, False, None),
    )


class LiveBrightnessProtocolTest(unittest.TestCase):
    def test_decodes_observed_six_byte_status(self):
        parameters = (61_265_168).to_bytes(4, "little") + (461).to_bytes(2, "little")

        status = decode_uptime_brightness_status_parameters(parameters)

        self.assertEqual(status.lamp_time_ms, 61_265_168)
        self.assertEqual(status.lamp_clock, "17:01:05.168")
        self.assertEqual(status.brightness_raw, 461)
        self.assertEqual(status.brightness_percent_estimate, 46.1)

    def test_rejects_wrong_status_length_and_invalid_manual_values(self):
        with self.assertRaisesRegex(ValueError, "exactly six"):
            decode_uptime_brightness_status_parameters(b"\x00" * 5)
        with self.assertRaisesRegex(ValueError, "uint32"):
            LiveStatus(0x1_0000_0000, 461)
        with self.assertRaisesRegex(ValueError, "uint16"):
            LiveStatus(0, 0x1_0000)


class LiveBrightnessExecutorTest(unittest.TestCase):
    def test_parses_structured_get_live_completion(self):
        result = ProcessResult(
            0,
            "GET-LIVE COMPLETE. Node 0x0003 reports lampTimeMs=61265168 "
            "lampClock=17:01:05.168 liveBrightnessRaw=461 "
            "liveBrightnessPercentEstimate=46.1%.\n",
            "",
        )

        parsed = CliCommandExecutor._parse_get_live(result)

        self.assertIsNotNone(parsed)
        address, status = parsed
        self.assertEqual(address, "0003")
        self.assertEqual(status, LiveStatus(61_265_168, 461))

    def test_rejects_inconsistent_derived_values(self):
        wrong_clock = ProcessResult(
            0,
            "GET-LIVE COMPLETE. Node 0x0003 reports lampTimeMs=61265168 "
            "lampClock=17:01:05.169 liveBrightnessRaw=461 "
            "liveBrightnessPercentEstimate=46.1%.\n",
            "",
        )
        wrong_percent = ProcessResult(
            0,
            "GET-LIVE COMPLETE. Node 0x0003 reports lampTimeMs=61265168 "
            "lampClock=17:01:05.168 liveBrightnessRaw=461 "
            "liveBrightnessPercentEstimate=46.2%.\n",
            "",
        )

        self.assertIsNone(CliCommandExecutor._parse_get_live(wrong_clock))
        self.assertIsNone(CliCommandExecutor._parse_get_live(wrong_percent))

    def test_refresh_reads_max_and_live_status_for_each_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = FakeCliExecutor(
                make_config(Path(tmp)),
                ["0003"],
                [
                    ProcessResult(0, "GET-MAX COMPLETE. Node 0x0003 reports MaxBrightness 68%.\n", ""),
                    ProcessResult(
                        0,
                        "GET-LIVE COMPLETE. Node 0x0003 reports lampTimeMs=61265168 "
                        "lampClock=17:01:05.168 liveBrightnessRaw=461 "
                        "liveBrightnessPercentEstimate=46.1%.\n",
                        "",
                    ),
                ],
            )

            result = executor.refresh("0003")

            self.assertTrue(result.ok)
            self.assertEqual(result.reported, {"0003": 68})
            self.assertEqual(result.live_reported, {"0003": LiveStatus(61_265_168, 461)})
            self.assertEqual(
                [call[0] for call in executor.calls],
                [["get-max", "0003"], ["get-live", "0003"]],
            )

    def test_verified_set_max_remains_successful_when_live_read_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = FakeCliExecutor(
                make_config(Path(tmp)),
                ["0003"],
                [
                    ProcessResult(0, "SET-MAX VERIFIED. Node 0x0003 reports MaxBrightness 50%.\n", ""),
                    ProcessResult(1, "", "ERROR: no live status"),
                ],
            )
            command = GatewayCommand(
                command_id="set-1",
                action="set-max",
                target="0003",
                value=50,
                confirmed=False,
                created_at=datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc),
                expires_at=datetime(2026, 7, 16, 20, 1, tzinfo=timezone.utc),
            )

            result = executor.execute(command)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "verified")
            self.assertEqual(result.reported, {"0003": 50})
            self.assertEqual(result.live_reported, {})
            self.assertIn("liveError", result.details)


class LiveBrightnessStoreTest(unittest.TestCase):
    def test_live_state_survives_reload_and_can_be_invalidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            now = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
            store = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            store.update_node("0003", 68, now=now)
            store.update_live("0003", LiveStatus(61_265_168, 461), now=now)

            reloaded = GatewayStore(path, dedup_ttl_seconds=3600, dedup_max_entries=10)
            state = reloaded.get_node("0003")
            self.assertIsNotNone(state)
            self.assertEqual(state.max_brightness, 68)
            self.assertEqual(state.live_status, LiveStatus(61_265_168, 461))
            self.assertEqual(state.live_verified_at, now)

            reloaded.clear_live("0003")
            cleared = reloaded.get_node("0003")
            self.assertIsNotNone(cleared)
            self.assertEqual(cleared.max_brightness, 68)
            self.assertIsNone(cleared.live_status)
            self.assertIsNone(cleared.live_verified_at)


if __name__ == "__main__":
    unittest.main()
