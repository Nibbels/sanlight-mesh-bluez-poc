"""Versioned MQTT command/result contract for the SANlight edge gateway."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


PROTOCOL_VERSION = 1
MAX_COMMAND_BYTES = 16_384
_COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NODE_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


class GatewayProtocolError(ValueError):
    """Raised for unsafe or malformed MQTT commands."""


@dataclass(frozen=True)
class GatewayCommand:
    command_id: str
    action: str
    target: str
    created_at: datetime
    expires_at: datetime
    value: int | None = None
    confirmed: bool = False

    @property
    def is_write(self) -> bool:
        return self.action in {"set-max", "blackout", "restore-blackout"}

    def expired(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current >= self.expires_at


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise GatewayProtocolError(f"{label} must be an ISO-8601 timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GatewayProtocolError(f"{label} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise GatewayProtocolError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_node(value: Any, *, allow_all: bool) -> str:
    if value == "all" and allow_all:
        return "all"
    if not isinstance(value, str) or not _NODE_RE.fullmatch(value):
        suffix = " or 'all'" if allow_all else ""
        raise GatewayProtocolError(f"target must be a four-digit node address{suffix}")
    parsed = int(value, 16)
    if not 0x0001 <= parsed <= 0x7FFF:
        raise GatewayProtocolError("target must be a unicast node address")
    return f"{parsed:04X}"


def decode_command(payload: bytes, *, now: datetime | None = None) -> GatewayCommand:
    if len(payload) > MAX_COMMAND_BYTES:
        raise GatewayProtocolError(
            f"command payload exceeds the {MAX_COMMAND_BYTES}-byte limit"
        )
    try:
        document = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise GatewayProtocolError("command payload must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise GatewayProtocolError(f"command payload is not valid JSON: {exc.msg}") from exc
    if not isinstance(document, dict):
        raise GatewayProtocolError("command payload must be a JSON object")

    common_keys = {"id", "action", "target", "value", "confirmed", "createdAt", "ttlSeconds"}
    unknown = set(document) - common_keys
    if unknown:
        raise GatewayProtocolError(
            "unknown command field(s): " + ", ".join(sorted(unknown))
        )

    command_id = document.get("id")
    if not isinstance(command_id, str) or not _COMMAND_ID_RE.fullmatch(command_id):
        raise GatewayProtocolError(
            "id must contain 1..128 letters, digits, '.', '_', ':' or '-'"
        )
    action = document.get("action")
    if action not in {"set-max", "refresh", "blackout", "restore-blackout"}:
        raise GatewayProtocolError(
            "action must be set-max, refresh, blackout or restore-blackout"
        )

    created_at = parse_timestamp(document.get("createdAt"), "createdAt")
    ttl = document.get("ttlSeconds")
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 1 <= ttl <= 300:
        raise GatewayProtocolError("ttlSeconds must be an integer between 1 and 300")
    expires_at = created_at + timedelta(seconds=ttl)
    current = now or utc_now()
    if created_at > current + timedelta(seconds=60):
        raise GatewayProtocolError("createdAt is more than 60 seconds in the future")

    value: int | None = None
    confirmed = document.get("confirmed", False)
    if not isinstance(confirmed, bool):
        raise GatewayProtocolError("confirmed must be true or false")

    if action == "set-max":
        target = normalize_node(document.get("target"), allow_all=False)
        raw_value = document.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise GatewayProtocolError("set-max value must be an integer")
        if not 20 <= raw_value <= 100:
            raise GatewayProtocolError("set-max value must be between 20 and 100")
        value = raw_value
        if "confirmed" in document:
            raise GatewayProtocolError("set-max does not accept confirmed")
    elif action == "refresh":
        target = normalize_node(document.get("target", "all"), allow_all=True)
        if "value" in document or "confirmed" in document:
            raise GatewayProtocolError("refresh does not accept value or confirmed")
    elif action == "blackout":
        target = normalize_node(document.get("target"), allow_all=True)
        if not confirmed:
            raise GatewayProtocolError("blackout requires confirmed=true")
        if "value" in document:
            raise GatewayProtocolError("blackout does not accept value")
    else:
        target = document.get("target", "latest")
        if target != "latest":
            raise GatewayProtocolError(
                "restore-blackout currently accepts only target='latest'"
            )
        if not confirmed:
            raise GatewayProtocolError("restore-blackout requires confirmed=true")
        if "value" in document:
            raise GatewayProtocolError("restore-blackout does not accept value")

    return GatewayCommand(
        command_id=command_id,
        action=action,
        target=target,
        value=value,
        confirmed=confirmed,
        created_at=created_at,
        expires_at=expires_at,
    )


def make_result(
    command: GatewayCommand | None,
    *,
    ok: bool,
    status: str,
    message: str,
    command_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "protocolVersion": PROTOCOL_VERSION,
        "id": command.command_id if command is not None else command_id,
        "ok": bool(ok),
        "status": status,
        "message": message,
        "timestamp": isoformat_utc(now or utc_now()),
    }
    if command is not None:
        result.update({"action": command.action, "target": command.target})
        if command.value is not None:
            result["requested"] = command.value
    if details:
        result["details"] = dict(details)
    return result
