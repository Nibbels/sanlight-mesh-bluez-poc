import json
import unittest
from pathlib import Path


class MqttContractTest(unittest.TestCase):
    def test_all_schema_files_are_valid_json(self):
        root = Path(__file__).resolve().parents[1] / "schemas"
        names = {
            "command-v1.schema.json",
            "result-v1.schema.json",
            "node-meta-v1.schema.json",
            "node-state-v1.schema.json",
            "gateway-info-v1.schema.json",
        }
        self.assertEqual({path.name for path in root.glob("*.json")}, names)
        for path in root.glob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_documentation_states_commands_are_not_retained(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "MQTT_API.md").read_text(encoding="utf-8")
        self.assertIn("Command messages must be non-retained", text)
        self.assertIn("retained commands are always rejected", text)

    def test_daylight_read_is_present_in_schemas_and_documentation(self):
        root = Path(__file__).resolve().parents[1]
        command = json.loads(
            (root / "schemas" / "command-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        result = json.loads(
            (root / "schemas" / "result-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        node_state = json.loads(
            (root / "schemas" / "node-state-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        node_meta = json.loads(
            (root / "schemas" / "node-meta-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("read-daylight", command["properties"]["action"]["enum"])
        self.assertIn("read-daylight", result["properties"]["action"]["enum"])
        self.assertIn("daylightConfiguration", node_state["properties"])
        self.assertIn("daylightConfiguration", node_meta["properties"]["readable"]["properties"])

        text = (root / "docs" / "MQTT_API.md").read_text(encoding="utf-8")
        self.assertIn('"action": "read-daylight"', text)
        self.assertIn("rawPduHex", text)
        self.assertIn("never sends the daylight write opcode", text)
