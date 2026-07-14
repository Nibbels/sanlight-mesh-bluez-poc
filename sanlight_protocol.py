#!/usr/bin/env python3
"""Pure protocol/CDB helpers for the SANlight BlueZ Mesh PoC."""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SANLIGHT_COMPANY_ID = 0x0A8B
SANLIGHT_MODEL_ID = 0x0001
SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE = 0x06
SANLIGHT_SET_MAX_BRIGHTNESS_STATUS_OPCODE = 0x07
SANLIGHT_GET_MAX_BRIGHTNESS_OPCODE = 0x08
SANLIGHT_GET_MAX_BRIGHTNESS_STATUS_OPCODE = 0x09
SANLIGHT_GET_UPTIME_BRIGHTNESS_OPCODE = 0x0C
SANLIGHT_GET_UPTIME_BRIGHTNESS_STATUS_OPCODE = 0x0D
SANLIGHT_SET_UPTIME_OPCODE = 0x0A
SANLIGHT_SET_UPTIME_STATUS_OPCODE = 0x0B
PRIMARY_NET_INDEX = 0
PRIMARY_APP_INDEX = 0


class CdbError(ValueError):
    """Raised when the SANlight CDB is missing or internally inconsistent."""


@dataclass(frozen=True)
class ProvisionerIdentity:
    name: str
    uuid: uuid.UUID
    device_key: bytes
    unicast: int
    allocated_unicast_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class MeshMaterial:
    mesh_uuid: uuid.UUID
    net_index: int
    net_key: bytes
    app_index: int
    app_key: bytes
    provisioner: ProvisionerIdentity
    groups: dict[int, str]
    node_names: dict[int, str]
    sanlight_nodes: dict[int, str]
    cdb_iv_index: int | None


def _hex_key(value: str, name: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise CdbError(f"{name} is not valid hexadecimal data") from exc
    if len(raw) != 16:
        raise CdbError(f"{name} must be exactly 16 bytes, got {len(raw)}")
    return raw


def _address(value: str, name: str) -> int:
    try:
        parsed = int(value, 16)
    except (TypeError, ValueError) as exc:
        raise CdbError(f"{name} is not a valid hexadecimal address") from exc
    if not 0 <= parsed <= 0xFFFF:
        raise CdbError(f"{name} is outside the uint16 address range")
    return parsed


def _unique_key(records: list[dict[str, Any]], index: int, label: str) -> bytes:
    matches = [record for record in records if int(record.get("index", -1)) == index]
    if not matches:
        raise CdbError(f"No {label} with index {index} found")
    values = {_hex_key(str(record["key"]), f"{label} {index}") for record in matches}
    if len(values) != 1:
        raise CdbError(f"Conflicting duplicate {label} entries for index {index}")
    return next(iter(values))


def _allocated_unicast_ranges(cdb: dict[str, Any], provisioner_name: str) -> tuple[tuple[int, int], ...]:
    records = [
        item
        for item in cdb.get("provisioners", [])
        if item.get("provisionerName") == provisioner_name
    ]
    if not records:
        return ()
    if len(records) != 1:
        raise CdbError(
            f"Expected at most one provisioner allocation record for {provisioner_name!r}, "
            f"found {len(records)}"
        )

    ranges: list[tuple[int, int]] = []
    for index, record in enumerate(records[0].get("allocatedUnicastRange", [])):
        low = _address(
            str(record["lowAddress"]),
            f"{provisioner_name} allocatedUnicastRange[{index}].lowAddress",
        )
        high = _address(
            str(record["highAddress"]),
            f"{provisioner_name} allocatedUnicastRange[{index}].highAddress",
        )
        if low > high or high > 0x7FFF:
            raise CdbError(
                f"Invalid unicast allocation range 0x{low:04X}..0x{high:04X} "
                f"for {provisioner_name}"
            )
        ranges.append((low, high))
    return tuple(ranges)


def _node_has_sanlight_vendor_model(node: dict[str, Any]) -> bool:
    if str(node.get("cid", "")).upper() != f"{SANLIGHT_COMPANY_ID:04X}":
        return False
    wanted_model = f"{SANLIGHT_COMPANY_ID:04X}{SANLIGHT_MODEL_ID:04X}"
    for element in node.get("elements", []):
        for model in element.get("models", []):
            if str(model.get("modelId", "")).upper() == wanted_model:
                return True
    return False


def load_mesh_material(cdb_path: Path, app_id: int) -> MeshMaterial:
    try:
        cdb = json.loads(cdb_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CdbError(f"CDB file not found: {cdb_path}") from exc
    except json.JSONDecodeError as exc:
        raise CdbError(f"CDB is not valid JSON: {exc}") from exc

    try:
        mesh_uuid = uuid.UUID(str(cdb["meshUUID"]))
    except (KeyError, ValueError) as exc:
        raise CdbError("CDB does not contain a valid meshUUID") from exc

    net_key = _unique_key(cdb.get("netKeys", []), PRIMARY_NET_INDEX, "NetKey")
    app_key = _unique_key(cdb.get("appKeys", []), PRIMARY_APP_INDEX, "AppKey")

    wanted_name = "nRF Mesh Provisioner" if app_id == 0 else f"SANlight Provisioner {app_id}"
    provisioner_nodes = [
        node for node in cdb.get("nodes", []) if node.get("name") == wanted_name
    ]
    if len(provisioner_nodes) != 1:
        raise CdbError(
            f"Expected exactly one node named {wanted_name!r}, found {len(provisioner_nodes)}"
        )

    node = provisioner_nodes[0]
    try:
        identity = ProvisionerIdentity(
            name=wanted_name,
            uuid=uuid.UUID(str(node["UUID"])),
            device_key=_hex_key(str(node["deviceKey"]), f"{wanted_name} deviceKey"),
            unicast=_address(str(node["unicastAddress"]), f"{wanted_name} unicastAddress"),
            allocated_unicast_ranges=_allocated_unicast_ranges(cdb, wanted_name),
        )
    except KeyError as exc:
        raise CdbError(f"Provisioner node {wanted_name!r} is incomplete: {exc}") from exc

    groups = {
        _address(str(group["address"]), f"group {group.get('name', '?')} address"):
        str(group.get("name", "unnamed"))
        for group in cdb.get("groups", [])
    }
    node_names = {
        _address(str(n["unicastAddress"]), f"node {n.get('name', '?')} unicastAddress"):
        str(n.get("name", "unnamed"))
        for n in cdb.get("nodes", [])
        if "unicastAddress" in n
    }
    sanlight_nodes = {
        _address(str(n["unicastAddress"]), f"SANlight node {n.get('name', '?')} unicastAddress"):
        str(n.get("name", "unnamed"))
        for n in cdb.get("nodes", [])
        if "unicastAddress" in n and _node_has_sanlight_vendor_model(n)
    }

    cdb_iv_index: int | None = None
    if "ivIndex" in cdb:
        raw_iv = cdb["ivIndex"]
        try:
            cdb_iv_index = int(raw_iv, 16) if isinstance(raw_iv, str) else int(raw_iv)
        except (TypeError, ValueError) as exc:
            raise CdbError("CDB ivIndex is not an integer/hex value") from exc
        if not 0 <= cdb_iv_index <= 0xFFFFFFFF:
            raise CdbError("CDB ivIndex is outside the uint32 range")

    return MeshMaterial(
        mesh_uuid=mesh_uuid,
        net_index=PRIMARY_NET_INDEX,
        net_key=net_key,
        app_index=PRIMARY_APP_INDEX,
        app_key=app_key,
        provisioner=identity,
        groups=groups,
        node_names=node_names,
        sanlight_nodes=sanlight_nodes,
        cdb_iv_index=cdb_iv_index,
    )


def choose_gateway_unicast(material: MeshMaterial) -> int:
    """Choose the first unused unicast after the provisioner in its CDB allocation."""
    occupied = set(material.node_names)
    provisioner_address = material.provisioner.unicast

    if material.provisioner.allocated_unicast_ranges:
        ranges = material.provisioner.allocated_unicast_ranges
    else:
        # Legacy/minimal test CDB fallback. Real SANlight exports contain allocation ranges.
        start = provisioner_address + 1
        ranges = ((start, min(start + 0x03FF, 0x7FFF)),)

    for low, high in ranges:
        for candidate in range(max(low, provisioner_address + 1), high + 1):
            if candidate not in occupied:
                return candidate

    raise CdbError(
        f"No unused unicast address remains after 0x{provisioner_address:04X} "
        f"inside {material.provisioner.name!r}'s allocated range"
    )


def validate_destination(material: MeshMaterial, destination: int) -> str:
    if destination == 0xFFFF:
        raise ValueError("0xFFFF/all-nodes is intentionally rejected by this PoC")
    if destination in material.groups:
        return f"group {material.groups[destination]!r}"
    if destination in material.node_names:
        return f"node {material.node_names[destination]!r}"
    raise ValueError(
        f"0x{destination:04X} is not a group or node address present in the CDB"
    )


def parse_destination(value: str) -> int:
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) != 4:
        raise ValueError("destination must contain exactly four hexadecimal digits")
    try:
        return int(text, 16)
    except ValueError as exc:
        raise ValueError("destination is not hexadecimal") from exc


def validate_max_brightness(percent: int) -> int:
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise ValueError("max brightness must be an integer")
    if percent < 20 or percent > 100:
        raise ValueError("max brightness must be between 20 and 100 inclusive")
    return percent


def build_set_max_brightness_pdu(percent: int) -> bytes:
    percent = validate_max_brightness(percent)
    # Vendor opcode 0x06 encodes as 0xC6, followed by Company ID 0x0A8B LE.
    return bytes((0xC0 | SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE, 0x8B, 0x0A, percent))


def build_get_max_brightness_pdu() -> bytes:
    # Vendor opcode 0x08 encodes as 0xC8, followed by Company ID 0x0A8B LE.
    return bytes((0xC0 | SANLIGHT_GET_MAX_BRIGHTNESS_OPCODE, 0x8B, 0x0A))


def is_get_max_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == bytes(
        (0xC0 | SANLIGHT_GET_MAX_BRIGHTNESS_STATUS_OPCODE, 0x8B, 0x0A)
    )


def get_max_brightness_status_parameters(data: bytes) -> bytes:
    if not is_get_max_brightness_status(data):
        raise ValueError("not a SANlight GetMaxBrightness Status PDU")
    return data[3:]


def build_get_uptime_brightness_pdu() -> bytes:
    # Vendor opcode 0x0C encodes as 0xCC, followed by Company ID 0x0A8B LE.
    return bytes((0xC0 | SANLIGHT_GET_UPTIME_BRIGHTNESS_OPCODE, 0x8B, 0x0A))


def validate_uptime_milliseconds(milliseconds: int) -> int:
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int):
        raise ValueError("uptime milliseconds must be an integer")
    if milliseconds < 0 or milliseconds > 0xFFFFFFFF:
        raise ValueError("uptime milliseconds must be between 0 and 4294967295 inclusive")
    return milliseconds


def validate_uptime_seconds(seconds: int) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise ValueError("uptime seconds must be an integer")
    if seconds < 0 or seconds > 0xFFFFFFFF // 1000:
        raise ValueError("uptime seconds must be between 0 and 4294967 inclusive")
    return seconds


def build_set_uptime_pdu(milliseconds: int) -> bytes:
    milliseconds = validate_uptime_milliseconds(milliseconds)
    # Vendor opcode 0x0A encodes as 0xCA, followed by Company ID 0x0A8B LE.
    # SANlight interprets the uint32 as milliseconds since the lamp day start.
    return bytes((0xC0 | SANLIGHT_SET_UPTIME_OPCODE, 0x8B, 0x0A)) + milliseconds.to_bytes(4, "little")


def is_set_uptime_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == bytes(
        (0xC0 | SANLIGHT_SET_UPTIME_STATUS_OPCODE, 0x8B, 0x0A)
    )


def set_uptime_status_parameters(data: bytes) -> bytes:
    if not is_set_uptime_status(data):
        raise ValueError("not a SANlight SetUptime Status PDU")
    return data[3:]


def parse_clock_time(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError("time must be HH:MM or HH:MM:SS")
    try:
        hour = int(parts[0], 10)
        minute = int(parts[1], 10)
        second = int(parts[2], 10) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError("time contains a non-integer component") from exc
    if not 0 <= hour <= 23:
        raise ValueError("hour must be 0..23")
    if not 0 <= minute <= 59:
        raise ValueError("minute must be 0..59")
    if not 0 <= second <= 59:
        raise ValueError("second must be 0..59")
    return (hour * 3600 + minute * 60 + second) * 1000


def format_milliseconds_as_clock(milliseconds: int) -> str:
    milliseconds = validate_uptime_milliseconds(milliseconds) % 86400000
    total_seconds = milliseconds // 1000
    ms = milliseconds % 1000
    hour = total_seconds // 3600
    minute = (total_seconds % 3600) // 60
    second = total_seconds % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}"


def format_seconds_as_clock(seconds: int) -> str:
    seconds = validate_uptime_seconds(seconds) % 86400
    hour = seconds // 3600
    minute = (seconds % 3600) // 60
    second = seconds % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def is_get_uptime_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == bytes(
        (0xC0 | SANLIGHT_GET_UPTIME_BRIGHTNESS_STATUS_OPCODE, 0x8B, 0x0A)
    )


def get_uptime_brightness_status_parameters(data: bytes) -> bytes:
    if not is_get_uptime_brightness_status(data):
        raise ValueError("not a SANlight GetUptimeAndBrightness Status PDU")
    return data[3:]


def load_cdb_node_device_key(cdb_path: Path, address: int) -> bytes:
    try:
        cdb = json.loads(cdb_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CdbError(f"CDB file not found: {cdb_path}") from exc
    except json.JSONDecodeError as exc:
        raise CdbError(f"CDB is not valid JSON: {exc}") from exc

    matches = [
        node
        for node in cdb.get("nodes", [])
        if "unicastAddress" in node
        and _address(
            str(node["unicastAddress"]),
            f"node {node.get('name', '?')} unicastAddress",
        )
        == address
    ]
    if len(matches) != 1:
        raise CdbError(
            f"Expected exactly one CDB node at 0x{address:04X}, found {len(matches)}"
        )
    node = matches[0]
    if "deviceKey" not in node:
        raise CdbError(f"CDB node at 0x{address:04X} has no deviceKey")
    return _hex_key(
        str(node["deviceKey"]),
        f"node 0x{address:04X} deviceKey",
    )


def build_config_network_transmit_get_pdu() -> bytes:
    # Config Network Transmit Get = 0x8023.
    return bytes.fromhex("8023")


def is_config_network_transmit_status(data: bytes) -> bool:
    return len(data) == 3 and data[:2] == bytes.fromhex("8025")


def decode_config_network_transmit_status(data: bytes) -> tuple[int, int]:
    if not is_config_network_transmit_status(data):
        raise ValueError("not a Config Network Transmit Status PDU")
    encoded = data[2]
    transmissions = (encoded & 0x07) + 1
    interval_ms = ((encoded >> 3) + 1) * 10
    return transmissions, interval_ms


def build_config_default_ttl_set_pdu(ttl: int) -> bytes:
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise ValueError("default TTL must be an integer")
    if ttl == 1 or ttl < 0 or ttl > 0x7F:
        raise ValueError("default TTL must be 0 or between 2 and 127")
    # Config Default TTL Set = 0x800D, followed by one TTL byte.
    return bytes.fromhex("800d") + bytes((ttl,))


def is_config_default_ttl_status(data: bytes) -> bool:
    return len(data) == 3 and data[:2] == bytes.fromhex("800e")


def config_default_ttl_status_value(data: bytes) -> int:
    if not is_config_default_ttl_status(data):
        raise ValueError("not a Config Default TTL Status PDU")
    return data[2]


def build_vendor_model_app_bind_pdu(
    element_address: int,
    app_index: int = PRIMARY_APP_INDEX,
    company_id: int = SANLIGHT_COMPANY_ID,
    model_id: int = SANLIGHT_MODEL_ID,
) -> bytes:
    if not 0 <= element_address <= 0x7FFF:
        raise ValueError("element address must be a unicast address")
    if not 0 <= app_index <= 0x0FFF:
        raise ValueError("AppKey index must fit in 12 bits")
    # Config Model App Bind opcode 0x803D, then vendor bind parameters LE:
    # element address, AppKey index, Company ID, vendor model ID.
    return bytes.fromhex("803d") + struct.pack(
        "<HHHH", element_address, app_index, company_id, model_id
    )


def is_set_max_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == bytes((0xC7, 0x8B, 0x0A))


def redact_material_summary(material: MeshMaterial) -> dict[str, Any]:
    """Return a safe-to-print summary; intentionally excludes all secret keys."""
    return {
        "meshUUID": str(material.mesh_uuid),
        "provisioner": material.provisioner.name,
        "provisionerUUID": str(material.provisioner.uuid),
        "unicast": f"0x{material.provisioner.unicast:04X}",
        "allocatedUnicastRanges": [
            f"0x{low:04X}..0x{high:04X}"
            for low, high in material.provisioner.allocated_unicast_ranges
        ],
        "netIndex": material.net_index,
        "appIndex": material.app_index,
        "ivIndexInCdb": material.cdb_iv_index,
        "groups": {f"0x{k:04X}": v for k, v in sorted(material.groups.items())},
    }
