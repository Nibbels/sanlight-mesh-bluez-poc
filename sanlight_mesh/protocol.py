"""Pure SANlight and Bluetooth Mesh access-PDU helpers.

This module has no D-Bus dependency and is safe to import in preflight checks.
"""
from __future__ import annotations

import struct

from .constants import (
    PRIMARY_APP_INDEX,
    SANLIGHT_COMPANY_ID,
    SANLIGHT_GET_MAX_BRIGHTNESS_OPCODE,
    SANLIGHT_GET_MAX_BRIGHTNESS_STATUS_OPCODE,
    SANLIGHT_GET_UPTIME_BRIGHTNESS_OPCODE,
    SANLIGHT_GET_UPTIME_BRIGHTNESS_STATUS_OPCODE,
    SANLIGHT_MODEL_ID,
    SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE,
    SANLIGHT_SET_MAX_BRIGHTNESS_STATUS_OPCODE,
    SANLIGHT_SET_UPTIME_OPCODE,
    SANLIGHT_SET_UPTIME_STATUS_OPCODE,
)


def _vendor_opcode(opcode: int) -> bytes:
    if not 0 <= opcode <= 0x3F:
        raise ValueError("vendor opcode must fit in six bits")
    return bytes((0xC0 | opcode, SANLIGHT_COMPANY_ID & 0xFF, SANLIGHT_COMPANY_ID >> 8))


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


def parse_destination_or_all(value: str) -> int | None:
    if value.strip().lower() == "all":
        return None
    return parse_destination(value)


def validate_max_brightness(percent: int) -> int:
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise ValueError("max brightness must be an integer")
    if not 20 <= percent <= 100:
        raise ValueError("max brightness must be between 20 and 100 inclusive")
    return percent


def build_set_max_brightness_pdu(percent: int) -> bytes:
    return _vendor_opcode(SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE) + bytes(
        (validate_max_brightness(percent),)
    )


def is_set_max_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_SET_MAX_BRIGHTNESS_STATUS_OPCODE
    )


def build_get_max_brightness_pdu() -> bytes:
    return _vendor_opcode(SANLIGHT_GET_MAX_BRIGHTNESS_OPCODE)


def is_get_max_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_GET_MAX_BRIGHTNESS_STATUS_OPCODE
    )


def get_max_brightness_status_parameters(data: bytes) -> bytes:
    if not is_get_max_brightness_status(data):
        raise ValueError("not a SANlight GetMaxBrightness Status PDU")
    return data[3:]


def build_get_uptime_brightness_pdu() -> bytes:
    return _vendor_opcode(SANLIGHT_GET_UPTIME_BRIGHTNESS_OPCODE)


def is_get_uptime_brightness_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_GET_UPTIME_BRIGHTNESS_STATUS_OPCODE
    )


def get_uptime_brightness_status_parameters(data: bytes) -> bytes:
    if not is_get_uptime_brightness_status(data):
        raise ValueError("not a SANlight GetUptimeAndBrightness Status PDU")
    return data[3:]


def validate_uptime_milliseconds(milliseconds: int) -> int:
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, int):
        raise ValueError("uptime milliseconds must be an integer")
    if not 0 <= milliseconds <= 0xFFFFFFFF:
        raise ValueError(
            "uptime milliseconds must be between 0 and 4294967295 inclusive"
        )
    return milliseconds


def validate_uptime_seconds(seconds: int) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise ValueError("uptime seconds must be an integer")
    if not 0 <= seconds <= 0xFFFFFFFF // 1000:
        raise ValueError("uptime seconds must be between 0 and 4294967 inclusive")
    return seconds


def build_set_uptime_pdu(milliseconds: int) -> bytes:
    value = validate_uptime_milliseconds(milliseconds)
    return _vendor_opcode(SANLIGHT_SET_UPTIME_OPCODE) + value.to_bytes(4, "little")


def is_set_uptime_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_SET_UPTIME_STATUS_OPCODE
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
    value = validate_uptime_milliseconds(milliseconds) % 86_400_000
    total_seconds, ms = divmod(value, 1000)
    hour, remainder = divmod(total_seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}"


def format_seconds_as_clock(seconds: int) -> str:
    value = validate_uptime_seconds(seconds) % 86_400
    hour, remainder = divmod(value, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def build_config_default_ttl_set_pdu(ttl: int) -> bytes:
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise ValueError("default TTL must be an integer")
    if ttl == 1 or not 0 <= ttl <= 0x7F:
        raise ValueError("default TTL must be 0 or between 2 and 127")
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
    return bytes.fromhex("803d") + struct.pack(
        "<HHHH", element_address, app_index, company_id, model_id
    )


def build_config_network_transmit_get_pdu() -> bytes:
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
