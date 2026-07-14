import contextlib
import io
import unittest
from pathlib import Path

from sanlight_mesh.cli import build_parser, main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_cdb.json"


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--cdb", str(FIXTURE), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_inspect_is_offline_and_redacted(self):
        code, stdout, stderr = self.run_cli("inspect")
        self.assertEqual(code, 0, stderr)
        self.assertIn("Local BlueZ state tokens are intentionally not printed", stdout)
        self.assertNotIn("11111111111111111111111111111111", stdout)
        self.assertNotIn("deviceKey", stdout)

    def test_list_nodes_only_suggests_read_only_command(self):
        code, stdout, stderr = self.run_cli("list-nodes")
        self.assertEqual(code, 0, stderr)
        self.assertIn("NODE_ADDRESS", stdout)
        self.assertIn("four-digit unicast value", stdout)
        self.assertIn("get-live 0002", stdout)
        self.assertNotIn("set-max", stdout)
        self.assertNotIn("sync-now", stdout)

    def test_unsafe_brightness_rejected_before_dbus(self):
        for percent in (0, 1, 19, 101):
            with self.subTest(percent=percent):
                code, stdout, stderr = self.run_cli(
                    "set-max", "0003", str(percent)
                )
                self.assertEqual(code, 2)
                self.assertIn("between 20 and 100", stderr)
                self.assertNotIn("D-Bus", stderr)

    def test_group_rejected_for_get_live(self):
        code, stdout, stderr = self.run_cli("get-live", "C000")
        self.assertEqual(code, 2)
        self.assertIn("unicast", stderr)

    def test_group_rejected_for_sender_network_probe(self):
        code, stdout, stderr = self.run_cli("get-net-tx-sender", "C000")
        self.assertEqual(code, 2)
        self.assertIn("unicast", stderr)
        self.assertNotIn("D-Bus", stderr)

    def test_sender_network_probe_command_is_registered(self):
        args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "get-net-tx-sender", "0002"]
        )
        self.assertEqual(args.command, "get-net-tx-sender")
        self.assertEqual(args.destination, 0x0002)


if __name__ == "__main__":
    unittest.main()
