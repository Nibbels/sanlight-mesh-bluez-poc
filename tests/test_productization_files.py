from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductizationFilesTest(unittest.TestCase):
    def test_shell_scripts_parse(self) -> None:
        for relative in (
            "scripts/install-gateway.sh",
            "scripts/sanlight-gateway",
            "scripts/release-archive.sh",
        ):
            subprocess.run(
                ["bash", "-n", str(ROOT / relative)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_current_repository_urls(self) -> None:
        candidates = [
            *ROOT.glob("*.md"),
            *ROOT.glob("docs/*.md"),
            *ROOT.glob("schemas/*.json"),
            ROOT / "systemd/sanlight-mqtt-gateway.service.example",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in candidates)
        self.assertNotIn("github.com/Nibbels/sanlight-mesh-bluez-poc", combined)
        self.assertIn("sanlight-mesh-mqtt-gateway", combined)
        self.assertIn("ioBroker.sanlightmesh", combined)

    def test_schema_ids_and_json(self) -> None:
        schemas = sorted((ROOT / "schemas").glob("*-v1.schema.json"))
        self.assertGreaterEqual(len(schemas), 5)
        for path in schemas:
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn("Nibbels/sanlight-mesh-mqtt-gateway", document["$id"])
            self.assertNotIn("sanlight-mesh-bluez-poc", document["$id"])

    def test_installation_safety_is_documented_and_enforced(self) -> None:
        installer = (ROOT / "scripts/install-gateway.sh").read_text(encoding="utf-8")
        self.assertNotIn("set-max", installer)
        self.assertNotIn("set-time", installer)
        self.assertNotIn("blackout", installer)
        self.assertIn("--check", installer)
        self.assertIn("temporary.replace(path)", installer)

    def test_management_restart_preserves_arguments(self) -> None:
        helper = (ROOT / "scripts/sanlight-gateway").read_text(encoding="utf-8")
        self.assertIn('args+=(--config "$CONFIG_PATH")', helper)
        self.assertIn('exec sudo -- "$0" "${args[@]}" restart', helper)
        self.assertNotIn('${CONFIG_PATH:+--config "$CONFIG_PATH"}', helper)

    def test_release_archive_excludes_runtime_material(self) -> None:
        release = (ROOT / "scripts/release-archive.sh").read_text(encoding="utf-8")
        self.assertIn("':(exclude)private'", release)
        self.assertIn("SANlightMesh", release)
        self.assertIn("mqtt-password", release)
        self.assertIn("sanlight-gateway-diagnostics", release)

    def test_private_material_not_bundled(self) -> None:
        forbidden_names = {"SANlightMesh.json", "mqtt-password.txt"}
        for path in ROOT.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.name, forbidden_names)
                self.assertNotIn(".state", path.parts)


if __name__ == "__main__":
    unittest.main()
