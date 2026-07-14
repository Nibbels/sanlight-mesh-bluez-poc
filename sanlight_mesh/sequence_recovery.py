"""Explicit recovery for a reused BlueZ Mesh sender sequence number.

This module handles the local BlueZ node database only. It never modifies a
SANlight lamp and it never prints node.json contents, keys, or tokens.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

MESH_SEQUENCE_MAX = 0xFFFFFF
# Project policy: sequence recovery must stay below the common 0xC00000 IV
# Update trigger region. This is deliberately stricter than the 24-bit maximum.
RECOVERY_TARGET_MAX = 0xBFFFFF
DEFAULT_MESH_ROOT = Path("/var/lib/bluetooth/mesh")
DEFAULT_BACKUP_ROOT = Path("/root/sanlight-mesh-sequence-backups")
DEFAULT_SERVICE_UNIT = "sanlight-meshd-generic.service"


class SequenceRecoveryError(RuntimeError):
    """Raised when local sequence recovery cannot be performed safely."""


@dataclass(frozen=True)
class RecoveryResult:
    node_path: Path
    previous: int
    current: int
    changed: bool
    backup_path: Path | None


def parse_sequence_target(value: str) -> int:
    """Parse decimal or 0x-prefixed sequence targets for argparse."""
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise ValueError("sequence target must be a decimal or 0x-prefixed integer") from exc
    return validate_recovery_target(parsed)


def validate_recovery_target(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ValueError("sequence recovery target must be at least 1")
    if value > MESH_SEQUENCE_MAX:
        raise ValueError(
            "Bluetooth Mesh sequence numbers are 24-bit; maximum is "
            f"0x{MESH_SEQUENCE_MAX:06X} ({MESH_SEQUENCE_MAX})"
        )
    if value > RECOVERY_TARGET_MAX:
        raise ValueError(
            "sequence recovery target exceeds the project safety ceiling "
            f"0x{RECOVERY_TARGET_MAX:06X}; use a proper IV Update or rebuild "
            "the Mesh instead of consuming the final sequence range"
        )
    return value


def bluez_node_path(mesh_root: Path, provisioner_uuid: UUID) -> Path:
    return mesh_root / provisioner_uuid.hex / "node.json"


def _parse_unicast(value: Any) -> int:
    try:
        return int(str(value).removeprefix("0x"), 16)
    except (TypeError, ValueError) as exc:
        raise SequenceRecoveryError("BlueZ node.json contains an invalid unicastAddress") from exc


def _parse_sequence(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SequenceRecoveryError("BlueZ node.json contains an invalid sequenceNumber") from exc
    if not 0 <= parsed <= MESH_SEQUENCE_MAX:
        raise SequenceRecoveryError(
            "BlueZ node.json sequenceNumber is outside the 24-bit Mesh range"
        )
    return parsed


def _load_node(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SequenceRecoveryError(f"BlueZ sender state not found: {path}") from exc
    except OSError as exc:
        raise SequenceRecoveryError(f"Cannot read BlueZ sender state {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SequenceRecoveryError(f"BlueZ sender state is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SequenceRecoveryError("BlueZ node.json must contain a JSON object")
    return value


def _secure_backup(path: Path, backup_root: Path, timestamp: datetime) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_root, 0o700)
    name = timestamp.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = backup_root / f"{name}-{path.parent.name}-node.json"
    shutil.copy2(path, destination)
    os.chmod(destination, 0o600)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())
    directory_fd = os.open(backup_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return destination


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    original = path.stat()
    temporary: str | None = None
    fd = -1
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=".node.json.", suffix=".tmp", dir=str(path.parent)
        )
        os.fchmod(fd, original.st_mode & 0o777)
        try:
            os.fchown(fd, original.st_uid, original.st_gid)
        except PermissionError:
            # Unit tests may run unprivileged against files already owned by the
            # current user. Real recovery requires root before this function.
            if original.st_uid != os.geteuid():
                raise
        payload = (json.dumps(value, indent=2) + "\n").encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise SequenceRecoveryError(f"Cannot update BlueZ sender state {path}: {exc}") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def advance_node_sequence(
    path: Path,
    expected_unicast: int,
    minimum: int,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    timestamp: datetime | None = None,
) -> RecoveryResult:
    """Advance one stopped BlueZ node to an explicit minimum, never backwards."""
    minimum = validate_recovery_target(minimum)
    node = _load_node(path)
    actual_unicast = _parse_unicast(node.get("unicastAddress"))
    if actual_unicast != expected_unicast:
        raise SequenceRecoveryError(
            f"BlueZ state identity mismatch: expected unicast 0x{expected_unicast:04X}, "
            f"found 0x{actual_unicast:04X}"
        )
    previous = _parse_sequence(node.get("sequenceNumber", 0))
    if previous >= minimum:
        return RecoveryResult(path, previous, previous, False, None)

    backup = _secure_backup(path, backup_root, timestamp or datetime.now(timezone.utc))
    node["sequenceNumber"] = minimum
    _atomic_write_json(path, node)
    return RecoveryResult(path, previous, minimum, True, backup)


def _systemctl(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", *arguments],
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise SequenceRecoveryError("systemctl is unavailable") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown systemctl error").strip()
        raise SequenceRecoveryError(
            f"systemctl {' '.join(arguments)} failed: {detail}"
        ) from exc


def _wait_mesh_ready(timeout_seconds: int = 25) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "busctl",
                    "introspect",
                    "org.bluez.mesh",
                    "/org/bluez/mesh",
                    "org.bluez.mesh.Network1",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise SequenceRecoveryError("busctl is unavailable") from exc
        if result.returncode == 0:
            return
        time.sleep(1)
    raise SequenceRecoveryError(
        "org.bluez.mesh.Network1 was not ready after restarting the Mesh service"
    )


def recover_sender_sequence(
    provisioner_uuid: UUID,
    expected_unicast: int,
    minimum: int,
    mesh_root: Path = DEFAULT_MESH_ROOT,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    service_unit: str = DEFAULT_SERVICE_UNIT,
) -> RecoveryResult:
    """Stop meshd, advance the sender state atomically, and restart meshd."""
    if os.geteuid() != 0:
        raise SequenceRecoveryError("sequence recovery must be run as root via sudo")
    minimum = validate_recovery_target(minimum)
    path = bluez_node_path(mesh_root, provisioner_uuid)
    if not path.is_file():
        raise SequenceRecoveryError(f"BlueZ sender state not found: {path}")

    active = _systemctl("is-active", "--quiet", service_unit, check=False).returncode == 0
    if not active:
        raise SequenceRecoveryError(
            f"{service_unit} is not active; start and validate the service before recovery"
        )

    _systemctl("stop", service_unit)
    try:
        if _systemctl("is-active", "--quiet", service_unit, check=False).returncode == 0:
            raise SequenceRecoveryError(f"{service_unit} did not stop cleanly")
        return advance_node_sequence(
            path,
            expected_unicast=expected_unicast,
            minimum=minimum,
            backup_root=backup_root,
        )
    finally:
        _systemctl("start", service_unit)
        if _systemctl("is-active", "--quiet", service_unit, check=False).returncode != 0:
            raise SequenceRecoveryError(
                f"{service_unit} did not become active after sequence recovery"
            )
        _wait_mesh_ready()
