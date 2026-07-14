"""Strict, redaction-aware SANlight CDB loading and validation."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    PRIMARY_APP_INDEX,
    PRIMARY_NET_INDEX,
    SANLIGHT_COMPANY_ID,
    SANLIGHT_MODEL_ID,
    TARGET_DEFAULT_TTL,
)


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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CdbError(f"CDB file not found: {path}") from exc
    except OSError as exc:
        raise CdbError(f"Cannot read CDB file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CdbError(f"CDB is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CdbError("CDB root must be a JSON object")
    return value


def _hex_key(value: str, name: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise CdbError(f"{name} is not valid hexadecimal data") from exc
    if len(raw) != 16:
        raise CdbError(f"{name} must be exactly 16 bytes, got {len(raw)}")
    return raw


def _address(value: object, name: str) -> int:
    try:
        parsed = int(str(value), 16)
    except (TypeError, ValueError) as exc:
        raise CdbError(f"{name} is not a valid hexadecimal address") from exc
    if not 0 <= parsed <= 0xFFFF:
        raise CdbError(f"{name} is outside the uint16 address range")
    return parsed


def _unique_key(records: object, index: int, label: str) -> bytes:
    if not isinstance(records, list):
        raise CdbError(f"CDB {label} collection must be an array")
    matches = [
        record
        for record in records
        if isinstance(record, dict) and int(record.get("index", -1)) == index
    ]
    if not matches:
        raise CdbError(f"No {label} with index {index} found")
    try:
        values = {_hex_key(str(record["key"]), f"{label} {index}") for record in matches}
    except KeyError as exc:
        raise CdbError(f"{label} {index} has no key") from exc
    if len(values) != 1:
        raise CdbError(f"Conflicting duplicate {label} entries for index {index}")
    return next(iter(values))


def _allocated_unicast_ranges(
    cdb: dict[str, Any], provisioner_name: str
) -> tuple[tuple[int, int], ...]:
    records = [
        item
        for item in cdb.get("provisioners", [])
        if isinstance(item, dict) and item.get("provisionerName") == provisioner_name
    ]
    if not records:
        return ()
    if len(records) != 1:
        raise CdbError(
            f"Expected at most one provisioner allocation record for "
            f"{provisioner_name!r}, found {len(records)}"
        )
    ranges: list[tuple[int, int]] = []
    for index, record in enumerate(records[0].get("allocatedUnicastRange", [])):
        if not isinstance(record, dict):
            raise CdbError(f"Invalid allocatedUnicastRange[{index}]")
        try:
            low = _address(
                record["lowAddress"],
                f"{provisioner_name} allocatedUnicastRange[{index}].lowAddress",
            )
            high = _address(
                record["highAddress"],
                f"{provisioner_name} allocatedUnicastRange[{index}].highAddress",
            )
        except KeyError as exc:
            raise CdbError(f"Incomplete unicast allocation range: {exc}") from exc
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
        if not isinstance(element, dict):
            continue
        for model in element.get("models", []):
            if isinstance(model, dict) and str(model.get("modelId", "")).upper() == wanted_model:
                return True
    return False


def load_mesh_material(cdb_path: Path, app_id: int) -> MeshMaterial:
    cdb = _load_json(cdb_path)
    try:
        mesh_uuid = uuid.UUID(str(cdb["meshUUID"]))
    except (KeyError, ValueError) as exc:
        raise CdbError("CDB does not contain a valid meshUUID") from exc

    net_key = _unique_key(cdb.get("netKeys", []), PRIMARY_NET_INDEX, "NetKey")
    app_key = _unique_key(cdb.get("appKeys", []), PRIMARY_APP_INDEX, "AppKey")
    wanted_name = "nRF Mesh Provisioner" if app_id == 0 else f"SANlight Provisioner {app_id}"
    nodes = cdb.get("nodes", [])
    if not isinstance(nodes, list):
        raise CdbError("CDB nodes must be an array")
    provisioner_nodes = [
        node for node in nodes if isinstance(node, dict) and node.get("name") == wanted_name
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
            unicast=_address(node["unicastAddress"], f"{wanted_name} unicastAddress"),
            allocated_unicast_ranges=_allocated_unicast_ranges(cdb, wanted_name),
        )
    except KeyError as exc:
        raise CdbError(f"Provisioner node {wanted_name!r} is incomplete: {exc}") from exc
    except ValueError as exc:
        raise CdbError(f"Provisioner node {wanted_name!r} contains invalid UUID data") from exc

    groups: dict[int, str] = {}
    for group in cdb.get("groups", []):
        if not isinstance(group, dict) or "address" not in group:
            raise CdbError("Every CDB group must be an object with an address")
        address = _address(group["address"], f"group {group.get('name', '?')} address")
        if address in groups:
            raise CdbError(f"Duplicate group address 0x{address:04X}")
        groups[address] = str(group.get("name", "unnamed"))

    node_names: dict[int, str] = {}
    sanlight_nodes: dict[int, str] = {}
    for item in nodes:
        if not isinstance(item, dict) or "unicastAddress" not in item:
            continue
        address = _address(item["unicastAddress"], f"node {item.get('name', '?')} unicastAddress")
        if not 0x0001 <= address <= 0x7FFF:
            raise CdbError(f"Node address 0x{address:04X} is not unicast")
        if address in node_names:
            raise CdbError(f"Duplicate node unicast address 0x{address:04X}")
        name = str(item.get("name", "unnamed"))
        node_names[address] = name
        if _node_has_sanlight_vendor_model(item):
            sanlight_nodes[address] = name

    overlap = set(groups).intersection(node_names)
    if overlap:
        address = min(overlap)
        raise CdbError(f"CDB address 0x{address:04X} is both a group and a node")

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


def validate_material_pair(
    control: MeshMaterial,
    sender: MeshMaterial,
    control_app_id: int,
    sender_app_id: int,
) -> None:
    if control_app_id == sender_app_id:
        raise ValueError("control App-ID and sender App-ID must be different")
    if control.mesh_uuid != sender.mesh_uuid:
        raise ValueError("control and sender identities do not belong to the same meshUUID")
    if control.net_index != sender.net_index or control.net_key != sender.net_key:
        raise ValueError("control and sender CDB material disagree on primary NetKey")
    if control.app_index != sender.app_index or control.app_key != sender.app_key:
        raise ValueError("control and sender CDB material disagree on primary AppKey")
    if control.provisioner.unicast == sender.provisioner.unicast:
        raise ValueError("control and sender CDB primary unicast addresses overlap")


def validate_destination(material: MeshMaterial, destination: int) -> str:
    if destination == 0xFFFF:
        raise ValueError("0xFFFF/all-nodes is intentionally rejected by this project")
    if destination in material.groups:
        return f"group {material.groups[destination]!r}"
    if destination in material.node_names:
        return f"node {material.node_names[destination]!r}"
    raise ValueError(
        f"0x{destination:04X} is not a group or node address present in the CDB"
    )


def load_cdb_node_device_key(cdb_path: Path, address: int) -> bytes:
    cdb = _load_json(cdb_path)
    matches = []
    for node in cdb.get("nodes", []):
        if not isinstance(node, dict) or "unicastAddress" not in node:
            continue
        if _address(node["unicastAddress"], f"node {node.get('name', '?')} address") == address:
            matches.append(node)
    if len(matches) != 1:
        raise CdbError(
            f"Expected exactly one CDB node at 0x{address:04X}, found {len(matches)}"
        )
    if "deviceKey" not in matches[0]:
        raise CdbError(f"CDB node at 0x{address:04X} has no deviceKey")
    return _hex_key(str(matches[0]["deviceKey"]), f"node 0x{address:04X} deviceKey")


def safe_summary(
    control: MeshMaterial,
    sender: MeshMaterial,
    control_app_id: int,
    sender_app_id: int,
) -> dict[str, Any]:
    return {
        "meshUUID": str(control.mesh_uuid),
        "control": {
            "appId": control_app_id,
            "name": control.provisioner.name,
            "uuid": str(control.provisioner.uuid),
            "unicast": f"0x{control.provisioner.unicast:04X}",
        },
        "sender": {
            "appId": sender_app_id,
            "name": sender.provisioner.name,
            "uuid": str(sender.provisioner.uuid),
            "unicast": f"0x{sender.provisioner.unicast:04X}",
            "defaultTTLTarget": TARGET_DEFAULT_TTL,
        },
        "netIndex": control.net_index,
        "appIndex": control.app_index,
        "ivIndexInCdb": control.cdb_iv_index,
        "groups": {
            f"0x{address:04X}": name for address, name in sorted(control.groups.items())
        },
        "sanlightNodes": {
            f"0x{address:04X}": name
            for address, name in sorted(control.sanlight_nodes.items())
        },
    }
