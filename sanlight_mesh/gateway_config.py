"""Strict TOML configuration for the optional MQTT edge gateway."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class GatewayConfigError(ValueError):
    """Raised when gateway configuration is missing or unsafe."""


_GATEWAY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_TOPIC_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    client_id: str
    username: str | None
    password_file: Path | None
    keepalive_seconds: int
    qos: int
    tls: bool
    ca_cert: Path | None


@dataclass(frozen=True)
class GatewayConfig:
    config_path: Path
    project_root: Path
    gateway_id: str
    cdb_path: Path
    control_app_id: int
    sender_app_id: int
    state_dir: Path
    command_timeout_seconds: int
    queue_max_size: int
    dedup_ttl_seconds: int
    dedup_max_entries: int
    coalesce_window_seconds: float
    state_fresh_seconds: int
    refresh_on_start: bool
    refresh_interval_seconds: int
    topic_prefix: str
    mqtt: MqttConfig

    @property
    def topic_root(self) -> str:
        return f"{self.topic_prefix}/{self.gateway_id}"

    @property
    def command_topic(self) -> str:
        return f"{self.topic_root}/command"


def _table(root: dict[str, Any], key: str) -> dict[str, Any]:
    value = root.get(key, {})
    if not isinstance(value, dict):
        raise GatewayConfigError(f"[{key}] must be a TOML table")
    return value


def _string(table: dict[str, Any], key: str, *, required: bool = False) -> str | None:
    value = table.get(key)
    if value is None:
        if required:
            raise GatewayConfigError(f"missing required setting {key!r}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise GatewayConfigError(f"{key!r} must be a non-empty string")
    return value.strip()


def _integer(
    table: dict[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GatewayConfigError(f"{key!r} must be an integer")
    if not minimum <= value <= maximum:
        raise GatewayConfigError(
            f"{key!r} must be between {minimum} and {maximum} inclusive"
        )
    return value


def _float(
    table: dict[str, Any], key: str, default: float, minimum: float, maximum: float
) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GatewayConfigError(f"{key!r} must be numeric")
    parsed = float(value)
    if not minimum <= parsed <= maximum:
        raise GatewayConfigError(
            f"{key!r} must be between {minimum} and {maximum} inclusive"
        )
    return parsed


def _boolean(table: dict[str, Any], key: str, default: bool) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise GatewayConfigError(f"{key!r} must be true or false")
    return value


def _resolve_path(value: str, config_path: Path) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = config_path.parent / expanded
    return expanded.resolve()


def _validate_private_file(path: Path, label: str, *, required: bool = True) -> None:
    if not path.exists():
        if required:
            raise GatewayConfigError(f"{label} not found: {path}")
        return
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise GatewayConfigError(f"cannot inspect {label} {path}: {exc}") from exc
    if mode & 0o077:
        raise GatewayConfigError(
            f"{label} {path} is too broadly accessible (mode {mode:04o}); "
            "use chmod 600"
        )


def load_gateway_config(path: Path, *, check_files: bool = True) -> GatewayConfig:
    config_path = path.expanduser().resolve()
    try:
        root = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GatewayConfigError(f"gateway config not found: {config_path}") from exc
    except OSError as exc:
        raise GatewayConfigError(f"cannot read gateway config {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise GatewayConfigError(f"gateway config is not valid TOML: {exc}") from exc
    if not isinstance(root, dict):
        raise GatewayConfigError("gateway config root must be a TOML table")

    gateway = _table(root, "gateway")
    mqtt = _table(root, "mqtt")

    gateway_id = _string(gateway, "id", required=True)
    assert gateway_id is not None
    if not _GATEWAY_ID_RE.fullmatch(gateway_id):
        raise GatewayConfigError(
            "gateway.id must match [a-z0-9][a-z0-9_-]{0,47}"
        )

    project_root_raw = _string(gateway, "project_root")
    project_root = (
        _resolve_path(project_root_raw, config_path)
        if project_root_raw
        else Path(__file__).resolve().parents[1]
    )
    cdb_raw = _string(gateway, "cdb", required=True)
    assert cdb_raw is not None
    cdb_path = _resolve_path(cdb_raw, config_path)
    state_raw = _string(gateway, "state_dir")
    state_dir = (
        _resolve_path(state_raw, config_path)
        if state_raw
        else (project_root / ".state").resolve()
    )

    topic_prefix = _string(mqtt, "topic_prefix") or "sanlightmesh/v1"
    topic_parts = topic_prefix.strip("/").split("/")
    if not topic_parts or any(not _TOPIC_COMPONENT_RE.fullmatch(part) for part in topic_parts):
        raise GatewayConfigError(
            "mqtt.topic_prefix must contain slash-separated alphanumeric, '_' or '-' components"
        )
    topic_prefix = "/".join(topic_parts)

    host = _string(mqtt, "host", required=True)
    assert host is not None
    username = _string(mqtt, "username")
    password_raw = _string(mqtt, "password_file")
    password_file = _resolve_path(password_raw, config_path) if password_raw else None
    if password_file is not None and username is None:
        raise GatewayConfigError("mqtt.password_file requires mqtt.username")

    tls = _boolean(mqtt, "tls", False)
    ca_raw = _string(mqtt, "ca_cert")
    ca_cert = _resolve_path(ca_raw, config_path) if ca_raw else None
    if ca_cert is not None and not tls:
        raise GatewayConfigError("mqtt.ca_cert requires mqtt.tls = true")

    config = GatewayConfig(
        config_path=config_path,
        project_root=project_root,
        gateway_id=gateway_id,
        cdb_path=cdb_path,
        control_app_id=_integer(gateway, "control_app_id", 1, 0, 15),
        sender_app_id=_integer(gateway, "sender_app_id", 2, 0, 15),
        state_dir=state_dir,
        command_timeout_seconds=_integer(
            gateway, "command_timeout_seconds", 45, 10, 300
        ),
        queue_max_size=_integer(gateway, "queue_max_size", 32, 1, 1024),
        dedup_ttl_seconds=_integer(gateway, "dedup_ttl_seconds", 86400, 60, 604800),
        dedup_max_entries=_integer(gateway, "dedup_max_entries", 512, 16, 10000),
        coalesce_window_seconds=_float(
            gateway, "coalesce_window_seconds", 2.0, 0.0, 10.0
        ),
        state_fresh_seconds=_integer(gateway, "state_fresh_seconds", 0, 0, 86400),
        refresh_on_start=_boolean(gateway, "refresh_on_start", True),
        refresh_interval_seconds=_integer(
            gateway, "refresh_interval_seconds", 1800, 0, 86400
        ),
        topic_prefix=topic_prefix,
        mqtt=MqttConfig(
            host=host,
            port=_integer(mqtt, "port", 1883, 1, 65535),
            client_id=_string(mqtt, "client_id")
            or f"sanlightmesh-{gateway_id}",
            username=username,
            password_file=password_file,
            keepalive_seconds=_integer(mqtt, "keepalive_seconds", 60, 10, 3600),
            qos=_integer(mqtt, "qos", 1, 0, 1),
            tls=tls,
            ca_cert=ca_cert,
        ),
    )

    if config.control_app_id == config.sender_app_id:
        raise GatewayConfigError("control_app_id and sender_app_id must differ")
    if check_files:
        _validate_private_file(config.config_path, "gateway config")
        _validate_private_file(config.cdb_path, "SANlight CDB")
        if config.mqtt.password_file is not None:
            _validate_private_file(config.mqtt.password_file, "MQTT password file")
        if config.mqtt.ca_cert is not None and not config.mqtt.ca_cert.is_file():
            raise GatewayConfigError(f"MQTT CA certificate not found: {config.mqtt.ca_cert}")
    return config


def redacted_config_summary(config: GatewayConfig) -> dict[str, Any]:
    """Return a safe configuration summary without passwords or Mesh material."""
    return {
        "gatewayId": config.gateway_id,
        "projectRoot": str(config.project_root),
        "cdbPath": str(config.cdb_path),
        "stateDir": str(config.state_dir),
        "topicRoot": config.topic_root,
        "mqtt": {
            "host": config.mqtt.host,
            "port": config.mqtt.port,
            "clientId": config.mqtt.client_id,
            "usernameConfigured": config.mqtt.username is not None,
            "passwordFileConfigured": config.mqtt.password_file is not None,
            "tls": config.mqtt.tls,
            "qos": config.mqtt.qos,
        },
        "queueMaxSize": config.queue_max_size,
        "coalesceWindowSeconds": config.coalesce_window_seconds,
        "refreshIntervalSeconds": config.refresh_interval_seconds,
    }
