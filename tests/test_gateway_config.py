import os
import tempfile
import unittest
from pathlib import Path

from sanlight_mesh.gateway_config import GatewayConfigError, load_gateway_config


class GatewayConfigTest(unittest.TestCase):
    def write(self, directory: Path, text: str) -> Path:
        path = directory / "gateway.toml"
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        return path

    def base_text(self, cdb: Path) -> str:
        return f'''\n[gateway]\nid = "sanlight-pi"\ncdb = "{cdb}"\n\n[mqtt]\nhost = "192.168.1.10"\n'''

    def test_loads_minimal_private_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cdb = root / "SANlightMesh.json"
            cdb.write_text("{}", encoding="utf-8")
            os.chmod(cdb, 0o600)
            config = load_gateway_config(self.write(root, self.base_text(cdb)))
            self.assertEqual(config.gateway_id, "sanlight-pi")
            self.assertEqual(config.topic_root, "sanlightmesh/v1/sanlight-pi")
            self.assertEqual(config.mqtt.qos, 1)

    def test_rejects_world_readable_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cdb = root / "SANlightMesh.json"
            cdb.write_text("{}", encoding="utf-8")
            os.chmod(cdb, 0o600)
            path = self.write(root, self.base_text(cdb))
            os.chmod(path, 0o644)
            with self.assertRaises(GatewayConfigError):
                load_gateway_config(path)

    def test_password_file_requires_username(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cdb = root / "SANlightMesh.json"
            cdb.write_text("{}", encoding="utf-8")
            os.chmod(cdb, 0o600)
            text = self.base_text(cdb) + 'password_file = "password.txt"\n'
            with self.assertRaises(GatewayConfigError):
                load_gateway_config(self.write(root, text), check_files=False)

    def test_rejects_unsafe_topic_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cdb = root / "SANlightMesh.json"
            text = self.base_text(cdb) + 'topic_prefix = "sanlightmesh/+/v1"\n'
            with self.assertRaises(GatewayConfigError):
                load_gateway_config(self.write(root, text), check_files=False)
