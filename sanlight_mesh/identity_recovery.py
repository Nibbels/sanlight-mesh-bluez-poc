"""Recover protected project identity state from validated local BlueZ storage.

This module is intentionally narrow.  It never scans for an identity by optional
BlueZ fields such as ``appKeys``.  The only accepted BlueZ database path is
computed from the provisioner UUID in the private CDB.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cdb import MeshMaterial, load_mesh_material, validate_material_pair
from .state import (
    StateError,
    read_state,
    token_from_state,
    validate_state_identity,
    write_state,
)


class IdentityRecoveryError(RuntimeError):
    """Raised when local identity state cannot be adopted safely."""


@dataclass(frozen=True)
class IdentitySpec:
    label: str
    material: MeshMaterial
    state_path: Path
    expected_state: Mapping[str, Any]

    @property
    def bluez_directory_name(self) -> str:
        return self.material.provisioner.uuid.hex


@dataclass(frozen=True)
class BluezIdentityState:
    token: int
    iv_index: int


@dataclass(frozen=True)
class ReconcileResult:
    label: str
    status: str
    iv_index: int | None


def _parse_uint(value: object, *, bits: int, label: str, base: int = 10) -> int:
    if isinstance(value, bool):
        raise IdentityRecoveryError(f"{label} is not an integer")
    try:
        if isinstance(value, str):
            text = value.strip()
            parsed = int(text, 0 if text.lower().startswith("0x") else base)
        else:
            parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise IdentityRecoveryError(f"{label} is not a valid integer") from exc
    maximum = (1 << bits) - 1
    if not 0 <= parsed <= maximum:
        raise IdentityRecoveryError(f"{label} is outside the uint{bits} range")
    return parsed


def _parse_hex_exact(value: object, *, bytes_length: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise IdentityRecoveryError(f"{label} is not hexadecimal text")
    text = value.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    if len(text) != bytes_length * 2:
        raise IdentityRecoveryError(
            f"{label} must contain exactly {bytes_length} bytes of hexadecimal data"
        )
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise IdentityRecoveryError(f"{label} is not valid hexadecimal data") from exc


def _parse_token(value: object, label: str) -> int:
    raw = _parse_hex_exact(value, bytes_length=8, label=label)
    return int.from_bytes(raw, byteorder="big", signed=False)


def _parse_unicast(value: object, label: str) -> int:
    if not isinstance(value, str):
        raise IdentityRecoveryError(f"{label} is not hexadecimal text")
    text = value.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    return _parse_uint(text, bits=16, label=label, base=16)


def _read_private_bluez_json(path: Path, *, require_root_owner: bool = True) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise IdentityRecoveryError(f"Cannot inspect BlueZ database {path}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise IdentityRecoveryError(f"BlueZ database {path} must be a regular non-symlink file")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise IdentityRecoveryError(
            f"BlueZ database {path} is too broadly accessible (mode {mode:04o})"
        )
    if require_root_owner and info.st_uid != 0:
        raise IdentityRecoveryError(f"BlueZ database {path} is not owned by root")

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentityRecoveryError(f"BlueZ database {path} is not valid JSON") from exc
    except OSError as exc:
        raise IdentityRecoveryError(f"Cannot read BlueZ database {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IdentityRecoveryError(f"BlueZ database {path} must contain a JSON object")
    return value


def _load_bluez_identity(
    spec: IdentitySpec,
    bluez_root: Path,
    *,
    require_root_owner: bool = True,
) -> BluezIdentityState | None:
    node_path = bluez_root / spec.bluez_directory_name / "node.json"
    backup_path = node_path.with_name("node.json.bak")

    # Do not use Path.exists() here: it follows symlinks and would classify a
    # broken node.json symlink as an absent identity, which could permit an
    # unsafe fresh import. lstat() preserves the distinction.
    try:
        node_path.lstat()
        node_present = True
    except FileNotFoundError:
        node_present = False
    except OSError as exc:
        raise IdentityRecoveryError(
            f"Cannot inspect BlueZ database {node_path}: {exc}"
        ) from exc

    if not node_present:
        try:
            backup_path.lstat()
            backup_present = True
        except FileNotFoundError:
            backup_present = False
        except OSError as exc:
            raise IdentityRecoveryError(
                f"Cannot inspect BlueZ backup {backup_path}: {exc}"
            ) from exc
        if backup_present:
            raise IdentityRecoveryError(
                f"{spec.label}: node.json is missing while node.json.bak exists; "
                "manual recovery is required"
            )
        return None

    value = _read_private_bluez_json(node_path, require_root_owner=require_root_owner)
    # appKeys is deliberately not inspected.  It is optional per local identity
    # and is not a safe identity selector.
    device_key = _parse_hex_exact(
        value.get("deviceKey"), bytes_length=16, label=f"{spec.label} deviceKey"
    )
    if device_key != spec.material.provisioner.device_key:
        raise IdentityRecoveryError(
            f"{spec.label}: BlueZ deviceKey does not match the private CDB identity"
        )
    unicast = _parse_unicast(
        value.get("unicastAddress"), f"{spec.label} unicastAddress"
    )
    if unicast != spec.material.provisioner.unicast:
        raise IdentityRecoveryError(
            f"{spec.label}: BlueZ unicastAddress does not match the private CDB identity"
        )
    token = _parse_token(value.get("token"), f"{spec.label} token")
    iv_index = _parse_uint(
        value.get("IVindex"), bits=32, label=f"{spec.label} IVindex"
    )
    return BluezIdentityState(token=token, iv_index=iv_index)


def _state_iv_index(state: Mapping[str, Any], label: str) -> int:
    if "ivIndex" not in state:
        raise IdentityRecoveryError(f"{label} project state has no ivIndex")
    return _parse_uint(state["ivIndex"], bits=32, label=f"{label} project ivIndex")


def reconcile_identity(
    spec: IdentitySpec,
    bluez_root: Path,
    *,
    require_root_owner: bool = True,
    recover_missing: bool = True,
) -> ReconcileResult:
    """Validate/recover one identity without importing or changing BlueZ state."""

    try:
        project_state = read_state(spec.state_path)
    except StateError as exc:
        raise IdentityRecoveryError(str(exc)) from exc
    bluez_state = _load_bluez_identity(
        spec, bluez_root, require_root_owner=require_root_owner
    )

    if project_state is None and bluez_state is None:
        return ReconcileResult(spec.label, "fresh-import-required", None)

    if project_state is not None and bluez_state is None:
        raise IdentityRecoveryError(
            f"{spec.label}: protected project state exists but the matching BlueZ "
            "node.json is absent; automatic re-import is intentionally blocked"
        )

    assert bluez_state is not None
    if project_state is None:
        if not recover_missing:
            return ReconcileResult(spec.label, "recoverable", bluez_state.iv_index)
        recovered = dict(spec.expected_state)
        recovered.update(
            {
                "token": f"{bluez_state.token:016x}",
                "ivIndex": bluez_state.iv_index,
            }
        )
        try:
            write_state(spec.state_path, recovered)
        except StateError as exc:
            raise IdentityRecoveryError(str(exc)) from exc
        return ReconcileResult(spec.label, "recovered", bluez_state.iv_index)

    try:
        validate_state_identity(project_state, spec.expected_state, spec.label)
        project_token = token_from_state(project_state, spec.label)
    except StateError as exc:
        raise IdentityRecoveryError(str(exc)) from exc
    if project_token is None:
        raise IdentityRecoveryError(f"{spec.label} project state has no token")
    if project_token != bluez_state.token:
        raise IdentityRecoveryError(
            f"{spec.label}: protected project token does not match local BlueZ storage"
        )
    project_iv = _state_iv_index(project_state, spec.label)
    if project_iv != bluez_state.iv_index:
        raise IdentityRecoveryError(
            f"{spec.label}: project and BlueZ IV Index values disagree"
        )
    return ReconcileResult(spec.label, "validated", project_iv)


def resolve_effective_iv(candidates: Sequence[tuple[str, int | None]]) -> int:
    present = [(label, value) for label, value in candidates if value is not None]
    if not present:
        raise IdentityRecoveryError(
            "No trusted IV Index is available. Supply --iv-index with an independently "
            "verified current value."
        )
    first_label, first_value = present[0]
    assert first_value is not None
    for label, value in present[1:]:
        if value != first_value:
            raise IdentityRecoveryError(
                f"IV Index mismatch between {first_label} and {label}; no state was changed"
            )
    return first_value


def build_identity_specs(
    control: MeshMaterial,
    sender: MeshMaterial,
    state_dir: Path,
    *,
    control_app_id: int = 1,
    sender_app_id: int = 2,
) -> tuple[IdentitySpec, IdentitySpec]:
    control_expected = {
        "role": "provisioner",
        "meshUUID": str(control.mesh_uuid),
        "provisionerUUID": str(control.provisioner.uuid),
        "unicast": control.provisioner.unicast,
        "appId": control_app_id,
    }
    sender_expected = {
        "role": "canonical-sender",
        "meshUUID": str(control.mesh_uuid),
        "senderProvisionerUUID": str(sender.provisioner.uuid),
        "senderAppId": sender_app_id,
        "unicast": sender.provisioner.unicast,
    }
    return (
        IdentitySpec(
            "Control provisioner",
            control,
            state_dir / "control-provisioner.json",
            control_expected,
        ),
        IdentitySpec(
            "Canonical sender",
            sender,
            state_dir / "canonical-sender.json",
            sender_expected,
        ),
    )


def recover_identity_state(
    cdb_path: Path,
    state_dir: Path,
    bluez_root: Path,
    *,
    explicit_iv_index: int | None = None,
    control_app_id: int = 1,
    sender_app_id: int = 2,
    require_root_owner: bool = True,
) -> tuple[int, tuple[ReconcileResult, ReconcileResult]]:
    control = load_mesh_material(cdb_path, control_app_id)
    sender = load_mesh_material(cdb_path, sender_app_id)
    validate_material_pair(control, sender, control_app_id, sender_app_id)
    specs = build_identity_specs(
        control,
        sender,
        state_dir,
        control_app_id=control_app_id,
        sender_app_id=sender_app_id,
    )
    # First perform a read-only classification for both identities.  This avoids
    # reconstructing either state file before cross-identity/CDB IV agreement is
    # established.
    preflight = tuple(
        reconcile_identity(
            spec,
            bluez_root,
            require_root_owner=require_root_owner,
            recover_missing=False,
        )
        for spec in specs
    )
    effective_iv = resolve_effective_iv(
        (
            ("explicit --iv-index", explicit_iv_index),
            ("CDB control ivIndex", control.cdb_iv_index),
            ("CDB sender ivIndex", sender.cdb_iv_index),
            (preflight[0].label, preflight[0].iv_index),
            (preflight[1].label, preflight[1].iv_index),
        )
    )
    results = tuple(
        reconcile_identity(
            spec, bluez_root, require_root_owner=require_root_owner
        )
        if result.status == "recoverable"
        else result
        for spec, result in zip(specs, preflight)
    )
    return effective_iv, (results[0], results[1])


def _arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or reconstruct protected project identity state from the exact "
            "BlueZ UUID paths declared by the private CDB. Run only while "
            "bluetooth-meshd is stopped."
        )
    )
    parser.add_argument("--cdb", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--bluez-root", type=Path, default=Path("/var/lib/bluetooth/mesh")
    )
    parser.add_argument("--iv-index")
    parser.add_argument("--control-app-id", type=int, default=1)
    parser.add_argument("--sender-app-id", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _arg_parser().parse_args(argv)
    if os.geteuid() != 0:
        print("ERROR: identity recovery must run as root", file=sys.stderr)
        return 1
    try:
        explicit = (
            None
            if args.iv_index in (None, "")
            else _parse_uint(
                args.iv_index,
                bits=32,
                label="explicit --iv-index",
                base=10,
            )
        )
        effective_iv, results = recover_identity_state(
            args.cdb.resolve(),
            args.state_dir.resolve(),
            args.bluez_root.resolve(),
            explicit_iv_index=explicit,
            control_app_id=args.control_app_id,
            sender_app_id=args.sender_app_id,
        )
    except (IdentityRecoveryError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for result in results:
        print(f"{result.label}: {result.status}", file=sys.stderr)
    print(effective_iv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
