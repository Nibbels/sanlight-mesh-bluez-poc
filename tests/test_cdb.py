import json
import tempfile
import unittest
from pathlib import Path

from sanlight_mesh.cdb import (
    CdbError,
    load_cdb_node_device_key,
    load_mesh_material,
    safe_summary,
    validate_destination,
    validate_material_pair,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_cdb.json"


class CdbTest(unittest.TestCase):
    def test_load_and_pair(self):
        control = load_mesh_material(FIXTURE, 1)
        sender = load_mesh_material(FIXTURE, 2)
        validate_material_pair(control, sender, 1, 2)
        self.assertEqual(control.provisioner.unicast, 0x2400)
        self.assertEqual(sender.provisioner.unicast, 0x2800)
        self.assertEqual(sorted(control.sanlight_nodes), [0x0002, 0x0003])
        self.assertEqual(control.cdb_iv_index, 0)

    def test_safe_summary_contains_no_key_material(self):
        control = load_mesh_material(FIXTURE, 1)
        sender = load_mesh_material(FIXTURE, 2)
        text = json.dumps(safe_summary(control, sender, 1, 2))
        for fake_key in ("11" * 16, "22" * 16, "33" * 16, "44" * 16):
            self.assertNotIn(fake_key, text)
        self.assertNotIn("deviceKey", text)
        self.assertNotIn("netKey", text)
        self.assertNotIn("appKey", text)

    def test_destinations_are_cdb_bound(self):
        material = load_mesh_material(FIXTURE, 1)
        self.assertIn("node", validate_destination(material, 0x0003))
        self.assertIn("group", validate_destination(material, 0xC000))
        for address in (0xFFFF, 0x1234):
            with self.subTest(address=address), self.assertRaises(ValueError):
                validate_destination(material, address)

    def test_device_key_load_is_exact(self):
        self.assertEqual(load_cdb_node_device_key(FIXTURE, 0x0003), bytes.fromhex("55" * 16))
        with self.assertRaises(CdbError):
            load_cdb_node_device_key(FIXTURE, 0x0004)

    def test_duplicate_unicast_is_rejected(self):
        data = json.loads(FIXTURE.read_text())
        data["nodes"][3]["unicastAddress"] = "0003"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(data))
            with self.assertRaises(CdbError):
                load_mesh_material(path, 1)


if __name__ == "__main__":
    unittest.main()
