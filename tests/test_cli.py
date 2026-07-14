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

    def test_get_max_command_is_registered_and_unicast_only(self):
        args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "get-max", "0002"]
        )
        self.assertEqual(args.command, "get-max")
        self.assertEqual(args.destination, 0x0002)

        code, stdout, stderr = self.run_cli("get-max", "C000")
        self.assertEqual(code, 2)
        self.assertIn("unicast", stderr)
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

    def test_show_sender_state_command_is_registered(self):
        args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "show-sender-state"]
        )
        self.assertEqual(args.command, "show-sender-state")

    def test_recovery_requires_explicit_confirmation_before_system_access(self):
        code, stdout, stderr = self.run_cli(
            "recover-sequence", "--minimum", "0x100000"
        )
        self.assertEqual(code, 2)
        self.assertIn("--confirm-replay-recovery", stderr)
        self.assertNotIn("systemctl", stderr)

    def test_recovery_rejects_non_24_bit_value_in_parser(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "--cdb",
                    str(FIXTURE),
                    "recover-sequence",
                    "--minimum",
                    str((1 << 64) - 5),
                    "--confirm-replay-recovery",
                ]
            )
        self.assertIn("invalid parse_sequence_target value", stderr.getvalue())

    def test_blackout_requires_confirmation_before_dbus(self):
        code, stdout, stderr = self.run_cli("blackout", "0002")
        self.assertEqual(code, 2)
        self.assertIn("--confirm-blackout", stderr)
        self.assertNotIn("D-Bus", stderr)

    def test_blackout_accepts_all_and_rejects_group(self):
        args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "blackout", "all", "--confirm-blackout"]
        )
        self.assertIsNone(args.destination)
        code, stdout, stderr = self.run_cli(
            "blackout", "C000", "--confirm-blackout"
        )
        self.assertEqual(code, 2)
        self.assertIn("unicast", stderr)

    def test_restore_requires_confirmation_before_snapshot_access(self):
        code, stdout, stderr = self.run_cli("restore-blackout", "latest")
        self.assertEqual(code, 2)
        self.assertIn("--confirm-restore", stderr)
        self.assertNotIn("D-Bus", stderr)

    def test_set_max_keeps_zero_forbidden_while_blackout_is_separate(self):
        set_args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "set-max", "0002", "20"]
        )
        blackout_args = build_parser().parse_args(
            ["--cdb", str(FIXTURE), "blackout", "0002", "--confirm-blackout"]
        )
        self.assertEqual(set_args.command, "set-max")
        self.assertEqual(blackout_args.command, "blackout")
        self.assertFalse(set_args.allow_fast_control)


    def test_help_formats_with_percent_signs(self):
        parser = build_parser()
        self.assertIn("blackout", parser.format_help())
        blackout_parser = next(
            action for action in parser._actions if action.dest == "command"
        ).choices["blackout"]
        self.assertIn("0%", blackout_parser.format_help())



if __name__ == "__main__":
    unittest.main()
