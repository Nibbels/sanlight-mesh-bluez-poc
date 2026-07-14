"""Secure, non-secret blackout restore snapshots.

The snapshot deliberately contains only CDB identity metadata, node addresses,
labels, and previously reported MaxBrightness percentages. It never contains
NetKey, AppKey, DeviceKey, or BlueZ state tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import UUID

from .state import StateError, read_state, write_state

BLACKOUT_SNAPSHOT_SCHEMA = 1
BLACKOUT_SNAPSHOT_ROLE = "sanlight-blackout-restore-snapshot"


@dataclass(frozen=True)
class BlackoutEntry:
    address: int
    name: str
    percent: int


@dataclass(frozen=True)
class BlackoutSnapshot:
    path: Path
    mesh_uuid: UUID
    sender_uuid: UUID
    sender_unicast: int
    created_at: str
    entries: tuple[BlackoutEntry, ...]
    restored_at: str | None = None


def _utc_timestamp(now: datetime | None = None) -> tuple[datetime, str]:
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    text = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    return timestamp, text


def _validate_reported_restore_percent(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateError("Blackout snapshot percentage must be an integer")
    if value == 0 or 20 <= value <= 100:
        return value
    raise StateError(
        "Blackout snapshot percentage must be 0 (off) or between 20 and 100"
    )


def _parse_uuid(value: Any, label: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise StateError(f"Blackout snapshot contains no valid {label}") from exc


def _parse_unicast(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0x7FFF:
        raise StateError(f"Blackout snapshot contains no valid {label}")
    return value


def _parse_optional_timestamp(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise StateError(f"Blackout snapshot contains an invalid {label}")
    return value


def create_blackout_snapshot(
    *,
    state_dir: Path,
    mesh_uuid: UUID,
    sender_uuid: UUID,
    sender_unicast: int,
    entries: Iterable[BlackoutEntry],
    now: datetime | None = None,
) -> BlackoutSnapshot:
    normalized = tuple(sorted(entries, key=lambda entry: entry.address))
    if not normalized:
        raise StateError("Cannot create an empty blackout snapshot")

    seen: set[int] = set()
    serialized_entries: list[dict[str, Any]] = []
    for entry in normalized:
        address = _parse_unicast(entry.address, "node address")
        if address in seen:
            raise StateError("Blackout snapshot contains a duplicate node address")
        seen.add(address)
        percent = _validate_reported_restore_percent(entry.percent)
        serialized_entries.append(
            {
                "address": address,
                "name": str(entry.name),
                "percent": percent,
            }
        )

    timestamp, created_at = _utc_timestamp(now)
    filename_stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    path = state_dir / f"blackout-{filename_stamp}.json"
    suffix = 1
    while path.exists():
        path = state_dir / f"blackout-{filename_stamp}-{suffix}.json"
        suffix += 1

    payload = {
        "schema": BLACKOUT_SNAPSHOT_SCHEMA,
        "role": BLACKOUT_SNAPSHOT_ROLE,
        "meshUUID": str(mesh_uuid),
        "senderProvisionerUUID": str(sender_uuid),
        "senderUnicast": _parse_unicast(sender_unicast, "sender unicast"),
        "createdAt": created_at,
        "entries": serialized_entries,
    }
    write_state(path, payload)
    return BlackoutSnapshot(
        path=path,
        mesh_uuid=mesh_uuid,
        sender_uuid=sender_uuid,
        sender_unicast=sender_unicast,
        created_at=created_at,
        entries=normalized,
    )


def load_blackout_snapshot(
    path: Path,
    *,
    expected_mesh_uuid: UUID,
    expected_sender_uuid: UUID,
    expected_sender_unicast: int,
    known_nodes: Mapping[int, str],
) -> BlackoutSnapshot:
    state = read_state(path)
    if state is None:
        raise StateError(f"Blackout snapshot does not exist: {path}")
    if state.get("schema") != BLACKOUT_SNAPSHOT_SCHEMA:
        raise StateError("Blackout snapshot schema is unsupported")
    if state.get("role") != BLACKOUT_SNAPSHOT_ROLE:
        raise StateError("File is not a SANlight blackout restore snapshot")

    mesh_uuid = _parse_uuid(state.get("meshUUID"), "mesh UUID")
    sender_uuid = _parse_uuid(
        state.get("senderProvisionerUUID"), "sender provisioner UUID"
    )
    sender_unicast = _parse_unicast(state.get("senderUnicast"), "sender unicast")

    if mesh_uuid != expected_mesh_uuid:
        raise StateError("Blackout snapshot belongs to a different Mesh")
    if sender_uuid != expected_sender_uuid or sender_unicast != expected_sender_unicast:
        raise StateError("Blackout snapshot belongs to a different sender identity")

    raw_entries = state.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise StateError("Blackout snapshot contains no restore entries")

    entries: list[BlackoutEntry] = []
    seen: set[int] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise StateError("Blackout snapshot entry must be a JSON object")
        address = _parse_unicast(raw.get("address"), "node address")
        if address in seen:
            raise StateError("Blackout snapshot contains a duplicate node address")
        if address not in known_nodes:
            raise StateError("Blackout snapshot contains a node absent from the current CDB")
        seen.add(address)
        percent = _validate_reported_restore_percent(raw.get("percent"))
        entries.append(
            BlackoutEntry(
                address=address,
                name=str(raw.get("name") or known_nodes[address]),
                percent=percent,
            )
        )

    created_at = state.get("createdAt")
    if not isinstance(created_at, str) or not created_at:
        raise StateError("Blackout snapshot contains no creation timestamp")
    restored_at = _parse_optional_timestamp(state.get("restoredAt"), "restore timestamp")

    return BlackoutSnapshot(
        path=path,
        mesh_uuid=mesh_uuid,
        sender_uuid=sender_uuid,
        sender_unicast=sender_unicast,
        created_at=created_at,
        entries=tuple(entries),
        restored_at=restored_at,
    )


def mark_blackout_snapshot_restored(
    path: Path, *, now: datetime | None = None
) -> str:
    state = read_state(path)
    if state is None:
        raise StateError(f"Blackout snapshot does not exist: {path}")
    if state.get("schema") != BLACKOUT_SNAPSHOT_SCHEMA:
        raise StateError("Blackout snapshot schema is unsupported")
    if state.get("role") != BLACKOUT_SNAPSHOT_ROLE:
        raise StateError("File is not a SANlight blackout restore snapshot")

    _, restored_at = _utc_timestamp(now)
    state["restoredAt"] = restored_at
    write_state(path, state)
    return restored_at


def _is_active_blackout_snapshot(path: Path) -> bool:
    state = read_state(path)
    if not (
        state is not None
        and state.get("schema") == BLACKOUT_SNAPSHOT_SCHEMA
        and state.get("role") == BLACKOUT_SNAPSHOT_ROLE
        and state.get("restoredAt") is None
    ):
        return False

    # v8 snapshots included nodes that were already off. Such snapshots are
    # ambiguous as undo steps and can unexpectedly restore 0%. New snapshots
    # contain only nodes actually changed by the blackout, so a zero entry is
    # selected only through an explicit path, never through "latest".
    raw_entries = state.get("entries")
    return bool(
        isinstance(raw_entries, list)
        and raw_entries
        and all(
            isinstance(entry, dict)
            and isinstance(entry.get("percent"), int)
            and not isinstance(entry.get("percent"), bool)
            and entry.get("percent") != 0
            for entry in raw_entries
        )
    )


def resolve_blackout_snapshot_path(value: str, state_dir: Path) -> Path:
    if value.strip().lower() != "latest":
        return Path(value).expanduser().resolve()

    candidates = sorted(
        state_dir.glob("blackout-*.json"),
        key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name),
        reverse=True,
    )
    for candidate in candidates:
        if _is_active_blackout_snapshot(candidate):
            return candidate.resolve()
    raise StateError(
        f"No active unambiguous blackout snapshot found in {state_dir}"
    )
