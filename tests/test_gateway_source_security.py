import unittest
from pathlib import Path


class GatewaySourceSecurityTest(unittest.TestCase):
    def test_executor_never_uses_shell_true(self):
        source = (Path(__file__).resolve().parents[1] / "sanlight_mesh" / "gateway_executor.py").read_text(encoding="utf-8")
        self.assertNotIn("shell=True", source)
        self.assertIn("stdin=subprocess.DEVNULL", source)


    def test_results_are_persisted_before_publish(self):
        source = (Path(__file__).resolve().parents[1] / "sanlight_mesh" / "gateway_service.py").read_text(encoding="utf-8")
        method = source.split("def _publish_and_remember", 1)[1].split("def ", 1)[0]
        self.assertLess(method.index("remember_result"), method.index("publish_result"))

    def test_mqtt_never_accepts_arbitrary_snapshot_path(self):
        source = (Path(__file__).resolve().parents[1] / "sanlight_mesh" / "gateway_protocol.py").read_text(encoding="utf-8")
        self.assertIn("accepts only target='latest'", source)

    def test_command_topics_are_non_retained_and_will_is_retained(self):
        transport = (Path(__file__).resolve().parents[1] / "sanlight_mesh" / "mqtt_transport.py").read_text(encoding="utf-8")
        service = (Path(__file__).resolve().parents[1] / "sanlight_mesh" / "gateway_service.py").read_text(encoding="utf-8")
        self.assertIn("retain=True", transport)
        self.assertIn("retained commands are rejected", service)
