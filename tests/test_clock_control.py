import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sanlight_mesh.gateway_executor import (
    CliCommandExecutor,
    ProcessResult,
    _circular_clock_difference,
)
from sanlight_mesh.gateway_protocol import GatewayProtocolError, decode_command
from sanlight_mesh.protocol import LiveStatus


NOW = datetime(2026, 7, 17, 18, 0, tzinfo=timezone.utc)


def command(action: str, target: str = "0003", **extra):
    payload = {
        "id": f"{action}-1",
        "action": action,
        "target": target,
        "createdAt": "2026-07-17T18:00:00Z",
        "ttlSeconds": 30,
        **extra,
    }
    return decode_command(json.dumps(payload).encode(), now=NOW)


class ClockProtocolTest(unittest.TestCase):
    def test_sync_clock_accepts_one_or_all_without_value(self):
        self.assertEqual(command("sync-clock").target, "0003")
        self.assertEqual(command("sync-clock", "all").target, "all")
        with self.assertRaises(GatewayProtocolError):
            command("sync-clock", secondsSinceMidnight=1)

    def test_set_clock_requires_strict_integer_seconds(self):
        self.assertEqual(
            command("set-clock", secondsSinceMidnight=86399).seconds_since_midnight,
            86399,
        )
        for invalid in (-1, 86400, 1.5, "1", True):
            with self.subTest(invalid=invalid), self.assertRaises(GatewayProtocolError):
                command("set-clock", secondsSinceMidnight=invalid)

    def test_gateway_info_refresh_has_no_mesh_target(self):
        value = command("refresh-gateway-info", "gateway")
        self.assertEqual(value.target, "gateway")
        self.assertFalse(value.is_write)

    def test_clock_difference_wraps_at_midnight(self):
        self.assertEqual(_circular_clock_difference(10, 86390), 20)
        self.assertEqual(_circular_clock_difference(86390, 10), -20)


class ClockExecutorTest(unittest.TestCase):
    def executor(self):
        value = object.__new__(CliCommandExecutor)
        value.node_addresses = ("0002", "0003")
        return value

    @staticmethod
    def live_output(address: str, seconds: int) -> ProcessResult:
        milliseconds = seconds * 1000
        clock = f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}.000"
        return ProcessResult(
            0,
            f"GET-LIVE COMPLETE. Node 0x{address} reports lampTimeMs={milliseconds} "
            f"lampClock={clock} liveBrightnessRaw=334 "
            "liveBrightnessPercentEstimate=33.4%.\n",
            "",
        )

    def test_set_clock_verifies_readback_and_compensates_all_lamps(self):
        executor = self.executor()
        calls = []
        monotonic_values = iter([100.0, 100.0, 102.0, 103.0, 103.0, 105.0, 107.0])

        def run(arguments, timeout=None):
            calls.append(arguments)
            if arguments[0] == "set-uptime":
                return ProcessResult(0, "SET-UPTIME COMPLETE.", "")
            written = int(calls[-2][2])
            return self.live_output(arguments[1], (written + 2) % 86400)

        executor._run = run
        with patch("sanlight_mesh.gateway_executor.time.monotonic", side_effect=monotonic_values):
            result = executor.execute(
                command("set-clock", "all", secondsSinceMidnight=21600)
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.message, "Requested lamp clocks applied and verified.")
        writes = [item for item in calls if item[0] == "set-uptime"]
        self.assertEqual(writes[0], ["set-uptime", "0002", "21600"])
        self.assertEqual(writes[1], ["set-uptime", "0003", "21603"])
        self.assertEqual(set(result.live_reported), {"0002", "0003"})

    def test_set_clock_reports_partial_success_per_lamp(self):
        executor = self.executor()
        calls = []
        monotonic_values = iter([100.0, 100.0, 100.0, 102.0, 103.0, 103.0])

        def run(arguments, timeout=None):
            calls.append(arguments)
            if arguments[0] == "set-uptime":
                return ProcessResult(0, "SET-UPTIME COMPLETE.", "")
            if arguments[1] == "0002":
                return self.live_output("0002", 21_602)
            return ProcessResult(4, "", "readback timeout")

        executor._run = run
        with patch("sanlight_mesh.gateway_executor.time.monotonic", side_effect=monotonic_values):
            result = executor.execute(
                command("set-clock", "all", secondsSinceMidnight=21_600)
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.details["nodes"]["0002"]["status"], "verified")
        self.assertEqual(result.details["nodes"]["0003"]["status"], "unconfirmed")
        self.assertIn("0002", result.live_reported)
        self.assertNotIn("0003", result.live_reported)


    def test_refresh_message_mentions_clock_and_pluralizes_all_lamps(self):
        executor = self.executor()

        def run(arguments, timeout=None):
            if arguments[0] == "get-max":
                return ProcessResult(
                    0,
                    f"GET-MAX COMPLETE. Node 0x{arguments[1]} reports MaxBrightness 60%.",
                    "",
                )
            return self.live_output(arguments[1], 21_600)

        executor._run = run
        single = executor.execute(command("refresh", "0002"))
        all_lamps = executor.execute(command("refresh", "all"))

        self.assertEqual(
            single.message,
            "MaxBrightness, live lamp output, and lamp clock refreshed and verified.",
        )
        self.assertEqual(
            all_lamps.message,
            "MaxBrightness, live lamp output, and lamp clocks refreshed and verified.",
        )

    def test_sync_clock_message_pluralizes_all_lamps(self):
        executor = self.executor()
        calls = []

        def run(arguments, timeout=None):
            calls.append(arguments)
            if arguments[0] == "set-uptime":
                return ProcessResult(0, "SET-UPTIME COMPLETE.", "")
            written = int(calls[-2][2])
            return self.live_output(arguments[1], written)

        executor._run = run
        with (
            patch(
                "sanlight_mesh.gateway_executor._local_seconds_since_midnight",
                return_value=21_600,
            ),
            patch("sanlight_mesh.gateway_executor.time.monotonic", return_value=100.0),
        ):
            result = executor.execute(command("sync-clock", "all"))

        self.assertTrue(result.ok)
        self.assertEqual(
            result.message,
            "Lamp clocks synchronized with the gateway local clock and verified.",
        )

    def test_refresh_gateway_info_runs_no_subprocess(self):
        executor = self.executor()
        executor._run = lambda *args, **kwargs: self.fail("subprocess must not run")
        result = executor.execute(command("refresh-gateway-info", "gateway"))
        self.assertTrue(result.ok)
        self.assertEqual(result.details["meshMessagesSent"], 0)


if __name__ == "__main__":
    unittest.main()
