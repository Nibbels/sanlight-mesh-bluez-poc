from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from sanlight_mesh.identity_recovery import (
    IdentityRecoveryError,
    IdentitySpec,
    reconcile_identity,
    recover_identity_state,
    resolve_effective_iv,
)
from sanlight_mesh.state import read_state, write_state


class IdentityRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_dir = self.root / ".state"
        self.bluez_root = self.root / "bluez"
        identity_uuid = uuid.UUID("35799b37-d730-44a9-8a5b-d1b7f74ab1dd")
        provisioner = SimpleNamespace(
            uuid=identity_uuid,
            device_key=bytes.fromhex("11" * 16),
            unicast=0x2800,
        )
        material = SimpleNamespace(
            provisioner=provisioner,
            mesh_uuid=uuid.UUID("b7aec9a0-ecf8-4c89-8cc6-420368cd1f70"),
        )
        self.expected = {
            "role": "canonical-sender",
            "meshUUID": str(material.mesh_uuid),
            "senderProvisionerUUID": str(identity_uuid),
            "senderAppId": 2,
            "unicast": 0x2800,
        }
        self.spec = IdentitySpec(
            "Canonical sender",
            material,
            self.state_dir / "canonical-sender.json",
            self.expected,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_node(self, **overrides: object) -> Path:
        path = self.bluez_root / self.spec.bluez_directory_name / "node.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        value: dict[str, object] = {
            "deviceKey": "11" * 16,
            "unicastAddress": "2800",
            "token": "0123456789abcdef",
            "IVindex": 7,
            "sequenceNumber": 123,
        }
        value.update(overrides)
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_recovers_missing_state_and_ignores_appkeys_presence(self) -> None:
        self.write_node(appKeys=[{"index": 0}])
        result = reconcile_identity(
            self.spec, self.bluez_root, require_root_owner=False
        )
        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.iv_index, 7)
        state = read_state(self.spec.state_path)
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["token"], "0123456789abcdef")
        self.assertEqual(state["ivIndex"], 7)
        for key, value in self.expected.items():
            self.assertEqual(state[key], value)

        self.spec.state_path.unlink()
        node = json.loads(
            (self.bluez_root / self.spec.bluez_directory_name / "node.json").read_text()
        )
        node.pop("appKeys")
        (self.bluez_root / self.spec.bluez_directory_name / "node.json").write_text(
            json.dumps(node), encoding="utf-8"
        )
        (self.bluez_root / self.spec.bluez_directory_name / "node.json").chmod(0o600)
        result = reconcile_identity(
            self.spec, self.bluez_root, require_root_owner=False
        )
        self.assertEqual(result.status, "recovered")

    def test_validates_existing_matching_state(self) -> None:
        self.write_node()
        state = dict(self.expected)
        state.update({"token": "0123456789abcdef", "ivIndex": 7})
        write_state(self.spec.state_path, state)
        result = reconcile_identity(
            self.spec, self.bluez_root, require_root_owner=False
        )
        self.assertEqual(result.status, "validated")

    def test_fresh_identity_requires_import(self) -> None:
        result = reconcile_identity(
            self.spec, self.bluez_root, require_root_owner=False
        )
        self.assertEqual(result.status, "fresh-import-required")
        self.assertIsNone(result.iv_index)

    def test_state_without_bluez_database_is_blocked(self) -> None:
        state = dict(self.expected)
        state.update({"token": "0123456789abcdef", "ivIndex": 7})
        write_state(self.spec.state_path, state)
        with self.assertRaisesRegex(IdentityRecoveryError, "automatic re-import"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

    def test_backup_without_live_database_is_blocked(self) -> None:
        backup = self.bluez_root / self.spec.bluez_directory_name / "node.json.bak"
        backup.parent.mkdir(parents=True)
        backup.write_text("{}", encoding="utf-8")
        backup.chmod(0o600)
        with self.assertRaisesRegex(IdentityRecoveryError, "manual recovery"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

    def test_broken_node_symlink_is_not_treated_as_fresh_identity(self) -> None:
        node = self.bluez_root / self.spec.bluez_directory_name / "node.json"
        node.parent.mkdir(parents=True)
        node.symlink_to(node.parent / "missing-target.json")
        with self.assertRaisesRegex(IdentityRecoveryError, "non-symlink"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

    def test_cdb_identity_mismatches_are_blocked(self) -> None:
        self.write_node(deviceKey="22" * 16)
        with self.assertRaisesRegex(IdentityRecoveryError, "deviceKey"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

        self.write_node(unicastAddress="2400")
        with self.assertRaisesRegex(IdentityRecoveryError, "unicastAddress"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

    def test_token_or_iv_mismatch_is_blocked(self) -> None:
        self.write_node()
        state = dict(self.expected)
        state.update({"token": "1111111111111111", "ivIndex": 7})
        write_state(self.spec.state_path, state)
        with self.assertRaisesRegex(IdentityRecoveryError, "token"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)

        state.update({"token": "0123456789abcdef", "ivIndex": 8})
        write_state(self.spec.state_path, state)
        with self.assertRaisesRegex(IdentityRecoveryError, "IV Index"):
            reconcile_identity(self.spec, self.bluez_root, require_root_owner=False)


    def test_read_only_preflight_does_not_write_recoverable_state(self) -> None:
        self.write_node()
        result = reconcile_identity(
            self.spec,
            self.bluez_root,
            require_root_owner=False,
            recover_missing=False,
        )
        self.assertEqual(result.status, "recoverable")
        self.assertFalse(self.spec.state_path.exists())

    def test_cross_identity_iv_mismatch_writes_no_recovered_state(self) -> None:
        mesh_uuid = uuid.UUID("b7aec9a0-ecf8-4c89-8cc6-420368cd1f70")
        control_uuid = uuid.UUID("ac7e77dc-d118-467c-90be-5b283ca295e9")
        sender_uuid = uuid.UUID("35799b37-d730-44a9-8a5b-d1b7f74ab1dd")
        control = SimpleNamespace(
            mesh_uuid=mesh_uuid,
            cdb_iv_index=None,
            provisioner=SimpleNamespace(
                uuid=control_uuid,
                device_key=bytes.fromhex("22" * 16),
                unicast=0x2400,
            ),
        )
        sender = SimpleNamespace(
            mesh_uuid=mesh_uuid,
            cdb_iv_index=None,
            provisioner=SimpleNamespace(
                uuid=sender_uuid,
                device_key=bytes.fromhex("11" * 16),
                unicast=0x2800,
            ),
        )
        for material, iv in ((control, 6), (sender, 7)):
            path = self.bluez_root / material.provisioner.uuid.hex / "node.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "deviceKey": material.provisioner.device_key.hex(),
                        "unicastAddress": f"{material.provisioner.unicast:04x}",
                        "token": "0123456789abcdef",
                        "IVindex": iv,
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)
        with patch(
            "sanlight_mesh.identity_recovery.load_mesh_material",
            side_effect=lambda _path, app_id: control if app_id == 1 else sender,
        ), patch("sanlight_mesh.identity_recovery.validate_material_pair"):
            with self.assertRaisesRegex(IdentityRecoveryError, "mismatch"):
                recover_identity_state(
                    self.root / "unused.json",
                    self.state_dir,
                    self.bluez_root,
                    require_root_owner=False,
                )
        self.assertFalse((self.state_dir / "control-provisioner.json").exists())
        self.assertFalse((self.state_dir / "canonical-sender.json").exists())

    def test_iv_resolution_requires_unanimous_trusted_values(self) -> None:
        self.assertEqual(
            resolve_effective_iv((("explicit", None), ("BlueZ", 7), ("state", 7))),
            7,
        )
        with self.assertRaisesRegex(IdentityRecoveryError, "mismatch"):
            resolve_effective_iv((("explicit", 8), ("BlueZ", 7)))
        with self.assertRaisesRegex(IdentityRecoveryError, "No trusted IV Index"):
            resolve_effective_iv((("explicit", None), ("CDB", None)))


if __name__ == "__main__":
    unittest.main()
