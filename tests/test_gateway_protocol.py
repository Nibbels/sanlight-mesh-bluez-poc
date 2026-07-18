import json
import unittest
from datetime import datetime, timedelta, timezone

from sanlight_mesh.gateway_protocol import GatewayProtocolError, decode_command


class GatewayProtocolTest(unittest.TestCase):
    def command(self, **overrides):
        now = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
        value = {
            "id": "cmd-1",
            "action": "set-max",
            "target": "0003",
            "value": 48,
            "createdAt": "2026-07-15T20:00:00Z",
            "ttlSeconds": 30,
        }
        value.update(overrides)
        value = {key: item for key, item in value.items() if item is not None}
        return decode_command(json.dumps(value).encode(), now=now)

    def test_set_max_is_strictly_20_to_100(self):
        self.assertEqual(self.command().value, 48)
        for invalid in (0, 1, 19, 101):
            with self.subTest(invalid=invalid), self.assertRaises(GatewayProtocolError):
                self.command(value=invalid)

    def test_blackout_requires_confirmation(self):
        with self.assertRaises(GatewayProtocolError):
            self.command(action="blackout", value=None)
        command = self.command(
            action="blackout", target="all", confirmed=True, value=None
        )
        self.assertEqual(command.target, "all")

    def test_restore_accepts_only_latest(self):
        command = self.command(
            action="restore-blackout",
            target="latest",
            confirmed=True,
            value=None,
        )
        self.assertEqual(command.target, "latest")
        with self.assertRaises(GatewayProtocolError):
            self.command(
                action="restore-blackout",
                target="/tmp/file",
                confirmed=True,
                value=None,
            )

    def test_expiration_is_derived_from_creation_and_ttl(self):
        command = self.command(ttlSeconds=30)
        self.assertFalse(command.expired(datetime(2026, 7, 15, 20, 0, 29, tzinfo=timezone.utc)))
        self.assertTrue(command.expired(datetime(2026, 7, 15, 20, 0, 30, tzinfo=timezone.utc)))

    def test_payload_size_is_bounded(self):
        with self.assertRaises(GatewayProtocolError):
            decode_command(b"{" + b" " * 20000 + b"}")

    def test_target_normalizes_to_uppercase(self):
        command = self.command(target="00a3")
        self.assertEqual(command.target, "00A3")

    def test_read_daylight_is_read_only_and_accepts_one_or_all(self):
        one = self.command(action="read-daylight", target="0002", value=None)
        all_nodes = self.command(action="read-daylight", target="all", value=None)
        default_all = self.command(action="read-daylight", target=None, value=None)
        self.assertFalse(one.is_write)
        self.assertEqual(one.target, "0002")
        self.assertEqual(all_nodes.target, "all")
        self.assertEqual(default_all.target, "all")

    def test_read_daylight_rejects_write_fields(self):
        for field in (
            {"value": 20},
            {"confirmed": False},
            {"secondsSinceMidnight": 0},
        ):
            with self.subTest(field=field), self.assertRaises(GatewayProtocolError):
                overrides = {
                    "action": "read-daylight",
                    "target": "0002",
                    "value": None,
                }
                overrides.update(field)
                self.command(**overrides)


    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(GatewayProtocolError):
            self.command(shell="rm -rf /")

    def test_set_max_rejects_even_false_confirmation_field(self):
        with self.assertRaises(GatewayProtocolError):
            self.command(confirmed=False)

    def test_future_timestamp_is_rejected(self):
        with self.assertRaises(GatewayProtocolError):
            self.command(createdAt="2026-07-15T20:02:00Z")
