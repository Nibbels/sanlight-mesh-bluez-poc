from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-mosquitto-broker.sh"


class MosquittoBrokerScriptTest(unittest.TestCase):
    def test_script_parses_and_help_is_non_destructive(self) -> None:
        subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            check=True,
            capture_output=True,
            text=True,
        )
        completed = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("broker/ioBroker host", completed.stdout)
        self.assertIn("--reset-passwords", completed.stdout)

    def test_broker_requires_authentication(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("allow_anonymous false", script)
        self.assertNotIn("allow_anonymous true", script)
        self.assertIn("anonymous MQTT publication unexpectedly succeeded", script)
        self.assertIn("sanlight-mesh-passwords", script)

    def test_gateway_and_iobroker_have_separate_acl_directions(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("user ${GATEWAY_USER}", script)
        self.assertIn("user ${IOBROKER_USER}", script)
        self.assertIn(
            "topic read sanlightmesh/v1/${GATEWAY_ID}/command",
            script,
        )
        self.assertIn(
            "topic write sanlightmesh/v1/${GATEWAY_ID}/command",
            script,
        )
        self.assertNotIn("topic readwrite #", script)
        self.assertNotIn("topic readwrite sanlightmesh/#", script)

    def test_passwords_are_not_read_or_passed_by_the_wrapper(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("read -r -s", script)
        self.assertNotIn("mosquitto_passwd -b", script)
        self.assertNotIn("mosquitto_pub -P", script)
        self.assertNotIn("mosquitto_sub -P", script)

    def test_documentation_declares_external_broker_first(self) -> None:
        setup = (ROOT / "SETUP.md").read_text(encoding="utf-8")
        integration = (ROOT / "docs/IOBROKER_INTEGRATION.md").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            setup.index("## 1. Prepare the external MQTT broker"),
            setup.index("## 4. Run the complete gateway installer"),
        )
        self.assertIn("install-mosquitto-broker.sh", setup)
        self.assertIn("client/subscriber mode", integration)
        self.assertIn("localhost:1883", integration)


if __name__ == "__main__":
    unittest.main()
