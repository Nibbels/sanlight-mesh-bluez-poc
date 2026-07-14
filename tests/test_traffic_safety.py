import tempfile
import unittest
from pathlib import Path

from sanlight_mesh.traffic_safety import (
    BRIGHTNESS_WRITE_MIN_INTERVAL_SECONDS,
    check_brightness_write_rate,
    record_brightness_write,
)


class TrafficSafetyTest(unittest.TestCase):
    def test_first_write_is_allowed_then_guarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rate.json"
            self.assertTrue(
                check_brightness_write_rate(
                    path, allow_fast_control=False, now=100.0
                ).allowed
            )
            record_brightness_write(
                path, command="set-max", destination="0x0003", now=100.0
            )
            decision = check_brightness_write_rate(
                path, allow_fast_control=False, now=104.0
            )
            self.assertFalse(decision.allowed)
            self.assertAlmostEqual(
                decision.wait_seconds,
                BRIGHTNESS_WRITE_MIN_INTERVAL_SECONDS - 4.0,
            )
            self.assertTrue(
                check_brightness_write_rate(
                    path,
                    allow_fast_control=False,
                    now=100.0 + BRIGHTNESS_WRITE_MIN_INTERVAL_SECONDS,
                ).allowed
            )

    def test_explicit_override_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rate.json"
            record_brightness_write(
                path, command="blackout", destination="all", now=100.0
            )
            self.assertTrue(
                check_brightness_write_rate(
                    path, allow_fast_control=True, now=101.0
                ).allowed
            )


if __name__ == "__main__":
    unittest.main()
