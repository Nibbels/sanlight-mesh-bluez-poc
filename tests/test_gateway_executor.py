import tempfile
import unittest
from pathlib import Path

from sanlight_mesh.gateway_config import GatewayConfig, MqttConfig
from sanlight_mesh.gateway_executor import CliCommandExecutor, ProcessResult


class GatewayExecutorTest(unittest.TestCase):
    def config(self, root: Path) -> GatewayConfig:
        entry = root / "sanlight_canonical_sender_poc.py"
        entry.write_text("", encoding="utf-8")
        return GatewayConfig(
            config_path=root / "config.toml",
            project_root=root,
            gateway_id="test",
            cdb_path=root / "private.json",
            control_app_id=1,
            sender_app_id=2,
            state_dir=root / ".state",
            command_timeout_seconds=45,
            queue_max_size=10,
            dedup_ttl_seconds=60,
            dedup_max_entries=16,
            coalesce_window_seconds=2,
            state_fresh_seconds=300,
            refresh_on_start=False,
            refresh_interval_seconds=0,
            topic_prefix="sanlightmesh/v1",
            mqtt=MqttConfig("broker", 1883, "client", None, None, 60, 1, False, None),
        )

    def test_get_max_parser_accepts_zero_and_normal_values(self):
        parse = CliCommandExecutor._parse_get_max
        self.assertEqual(parse(ProcessResult(0, "GET-MAX COMPLETE. Node 0x0003 reports MaxBrightness 0% (off).", "")), ("0003", 0))
        self.assertEqual(parse(ProcessResult(0, "GET-MAX COMPLETE. Node 0x0003 reports MaxBrightness 68%.", "")), ("0003", 68))


    def test_parses_verified_values_from_restore_output(self):
        result = ProcessResult(
            0,
            "Received matching SANlight GetMaxBrightness status from 0x0003: 0% (off).\n"
            "RESTORE-BLACKOUT VERIFIED: 0x0003=68%, 0x0002=48%.",
            "",
        )
        self.assertEqual(
            CliCommandExecutor._parse_reported_values(result),
            {"0003": 68, "0002": 48},
        )

    def test_base_argv_contains_fixed_paths_not_mqtt_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = CliCommandExecutor(self.config(root), ["0002"])
            argv = executor._base_argv()
            self.assertEqual(argv[1], str(root / "sanlight_canonical_sender_poc.py"))
            self.assertNotIn("shell", " ".join(argv).lower())
