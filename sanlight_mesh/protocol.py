"""Pure SANlight and Bluetooth Mesh access-PDU helpers.

This module has no D-Bus dependency and is safe to import in preflight checks.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import (
    PRIMARY_APP_INDEX,
    SANLIGHT_COMPANY_ID,
    SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
    SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_STATUS_OPCODE,
    SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
    SANLIGHT_GET_DAYLIGHT_CONFIGURATION_STATUS_OPCODE,
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


MAX_DAYLIGHT_VALUES = 96


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
    """Build the ordinary MaxBrightness write; 0 remains intentionally forbidden."""
    return _vendor_opcode(SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE) + bytes(
        (validate_max_brightness(percent),)
    )


def build_blackout_pdu() -> bytes:
    """Build the explicit 0% (off) command used only by blackout workflows."""
    return _vendor_opcode(SANLIGHT_SET_MAX_BRIGHTNESS_OPCODE) + b"\x00"


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


def validate_reported_max_brightness(percent: int) -> int:
    """Validate a value reported by a dimmer.

    Reading and writing intentionally have different policies: 0 is a legitimate
    reported off state, while the ordinary ``set-max`` command remains restricted
    to 20..100. Values 1..19 are retained for diagnostics instead of being hidden.
    """
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise ValueError("reported max brightness must be an integer")
    if not 0 <= percent <= 100:
        raise ValueError("reported max brightness must be between 0 and 100")
    return percent


def get_max_brightness_status_value(data: bytes) -> int:
    """Decode the one-byte GetMaxBrightness status value, including 0% off."""

    parameters = get_max_brightness_status_parameters(data)
    if len(parameters) != 1:
        raise ValueError(
            "SANlight GetMaxBrightness Status must contain exactly one value byte"
        )
    return validate_reported_max_brightness(parameters[0])


@dataclass(frozen=True)
class LiveStatus:
    """Decoded read-only SANlight lamp time and effective brightness status.

    ``brightness_percent_estimate`` is an empirical interpretation of the
    vendor value. The raw value remains authoritative until the scale has been
    validated across additional hardware and firmware versions.
    """

    lamp_time_ms: int
    brightness_raw: int

    def __post_init__(self) -> None:
        if isinstance(self.lamp_time_ms, bool) or not isinstance(
            self.lamp_time_ms, int
        ):
            raise ValueError("lamp time milliseconds must be an integer")
        if not 0 <= self.lamp_time_ms <= 0xFFFFFFFF:
            raise ValueError("lamp time milliseconds must fit in uint32")
        if isinstance(self.brightness_raw, bool) or not isinstance(
            self.brightness_raw, int
        ):
            raise ValueError("live brightness raw value must be an integer")
        if not 0 <= self.brightness_raw <= 0xFFFF:
            raise ValueError("live brightness raw value must fit in uint16")

    @property
    def lamp_clock(self) -> str:
        return format_milliseconds_as_clock(self.lamp_time_ms)

    @property
    def brightness_percent_estimate(self) -> float:
        return self.brightness_raw / 10.0


def decode_uptime_brightness_status_parameters(parameters: bytes) -> LiveStatus:
    if len(parameters) != 6:
        raise ValueError(
            "SANlight GetUptimeAndBrightness Status must contain exactly "
            "six parameter bytes"
        )
    return LiveStatus(
        lamp_time_ms=int.from_bytes(parameters[:4], "little"),
        brightness_raw=int.from_bytes(parameters[4:6], "little"),
    )


def get_uptime_brightness_status_value(data: bytes) -> LiveStatus:
    return decode_uptime_brightness_status_parameters(
        get_uptime_brightness_status_parameters(data)
    )


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


def build_get_daylight_configuration_pdu() -> bytes:
    """Build the read-only GetDaylightConfiguration request (vendor opcode 0x03)."""

    return _vendor_opcode(SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE)


def build_get_combined_daylight_data_pdu() -> bytes:
    """Build the read-only GetCombinedDaylightData request (vendor opcode 0x0E)."""

    return _vendor_opcode(SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE)


def is_get_daylight_configuration_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_GET_DAYLIGHT_CONFIGURATION_STATUS_OPCODE
    )


def is_get_combined_daylight_data_status(data: bytes) -> bool:
    return len(data) >= 3 and data[:3] == _vendor_opcode(
        SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_STATUS_OPCODE
    )


def is_daylight_status(data: bytes) -> bool:
    return is_get_daylight_configuration_status(
        data
    ) or is_get_combined_daylight_data_status(data)


def _format_daylight_minute(value: int) -> str:
    if value == 1_440:
        return "24:00"
    return f"{value // 60:02d}:{value % 60:02d}"


@dataclass(frozen=True)
class DaylightValue:
    """One currently assumed SANlight daylight curve value.

    The field widths are based on the protocol evidence available before the
    first v0.4.0 hardware probe: uint16 little-endian minutes followed by one
    uint8 brightness percentage. Raw status bytes remain available alongside
    parsed values so this assumption can be corrected without losing evidence.
    """

    time_in_minutes: int
    brightness: int

    def __post_init__(self) -> None:
        if isinstance(self.time_in_minutes, bool) or not isinstance(
            self.time_in_minutes, int
        ):
            raise ValueError("daylight time must be an integer")
        if not 0 <= self.time_in_minutes <= 1_440:
            raise ValueError("daylight time must be between 0 and 1440 minutes")
        if isinstance(self.brightness, bool) or not isinstance(self.brightness, int):
            raise ValueError("daylight brightness must be an integer")
        if not 0 <= self.brightness <= 100:
            raise ValueError("daylight brightness must be between 0 and 100")

    def to_document(self) -> dict[str, object]:
        return {
            "timeInMinutes": self.time_in_minutes,
            "time": _format_daylight_minute(self.time_in_minutes),
            "brightness": self.brightness,
        }


@dataclass(frozen=True)
class DaylightConfiguration:
    configuration_id: int
    name: str
    values: tuple[DaylightValue, ...]

    def __post_init__(self) -> None:
        if isinstance(self.configuration_id, bool) or not isinstance(
            self.configuration_id, int
        ):
            raise ValueError("daylight configuration id must be an integer")
        if not 0 <= self.configuration_id <= 0xFFFFFFFF:
            raise ValueError("daylight configuration id must fit in uint32")
        if not isinstance(self.name, str):
            raise ValueError("daylight configuration name must be a string")
        if len(self.values) > MAX_DAYLIGHT_VALUES:
            raise ValueError(
                f"daylight configuration exceeds {MAX_DAYLIGHT_VALUES} values"
            )
        previous = -1
        for value in self.values:
            if value.time_in_minutes < previous:
                raise ValueError("daylight values must be ordered by time")
            previous = value.time_in_minutes

    def to_document(self) -> dict[str, object]:
        return {
            "id": self.configuration_id,
            "name": self.name,
            "valueCount": len(self.values),
            "values": [value.to_document() for value in self.values],
        }


@dataclass(frozen=True)
class DaylightStatus:
    """A raw and, when possible, parsed daylight status response."""

    request_opcode: int
    status_opcode: int
    raw_pdu: bytes
    configuration: DaylightConfiguration | None = None
    parser_layout: str | None = None
    lamp_time_ms: int | None = None
    live_brightness_raw: int | None = None
    max_brightness: int | None = None
    parse_error: str | None = None

    @property
    def parsed(self) -> bool:
        return self.configuration is not None

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "requestOpcode": self.request_opcode,
            "requestOpcodeHex": f"0x{self.request_opcode:02X}",
            "statusOpcode": self.status_opcode,
            "statusOpcodeHex": f"0x{self.status_opcode:02X}",
            "rawPduHex": self.raw_pdu.hex(),
            "rawParametersHex": self.raw_pdu[3:].hex(),
            "parsed": self.parsed,
        }
        if self.parser_layout is not None:
            document["parserLayout"] = self.parser_layout
        if self.configuration is not None:
            document["configuration"] = self.configuration.to_document()
        if self.lamp_time_ms is not None and self.live_brightness_raw is not None:
            live = LiveStatus(self.lamp_time_ms, self.live_brightness_raw)
            combined_status: dict[str, object] = {
                "lampTimeMs": live.lamp_time_ms,
                "lampClock": live.lamp_clock,
                "liveBrightnessRaw": live.brightness_raw,
                "liveBrightnessPercentEstimate": live.brightness_percent_estimate,
            }
            if self.max_brightness is not None:
                combined_status["maxBrightness"] = validate_reported_max_brightness(
                    self.max_brightness
                )
            document["combinedStatus"] = combined_status
        if self.parse_error is not None:
            document["parseError"] = self.parse_error
        return document


def _decode_daylight_configuration_at(
    parameters: bytes,
    *,
    offset: int,
    allowed_trailing_lengths: tuple[int, ...],
) -> tuple[DaylightConfiguration, int]:
    """Decode the currently evidenced daylight layout at ``offset``.

    Working wire hypothesis:

    - uint32 little-endian configuration id
    - uint8 value count
    - repeated uint16 little-endian minute + uint8 brightness
    - UTF-8 profile name terminated by NUL

    The caller controls which exact trailing lengths are accepted. Unknown
    layouts are intentionally rejected and retained as raw data by the public
    decoder instead of being guessed into a false configuration.
    """

    if offset < 0 or offset > len(parameters):
        raise ValueError("invalid daylight payload offset")
    available = len(parameters) - offset
    if available < 6:
        raise ValueError("daylight payload is too short for id, count and name")

    configuration_id = int.from_bytes(parameters[offset : offset + 4], "little")
    count = parameters[offset + 4]
    if count > MAX_DAYLIGHT_VALUES:
        raise ValueError(
            f"daylight value count {count} exceeds {MAX_DAYLIGHT_VALUES}"
        )

    values_start = offset + 5
    values_end = values_start + count * 3
    if values_end >= len(parameters):
        raise ValueError("daylight payload is truncated before the profile name")

    values: list[DaylightValue] = []
    previous = -1
    for index in range(count):
        item_offset = values_start + index * 3
        minute = int.from_bytes(parameters[item_offset : item_offset + 2], "little")
        brightness = parameters[item_offset + 2]
        value = DaylightValue(minute, brightness)
        if value.time_in_minutes < previous:
            raise ValueError("daylight values are not ordered by time")
        previous = value.time_in_minutes
        values.append(value)

    name_end = parameters.find(b"\x00", values_end)
    if name_end < 0:
        raise ValueError("daylight profile name is not NUL-terminated")
    try:
        name = parameters[values_end:name_end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("daylight profile name is not valid UTF-8") from exc
    if any(ord(character) < 0x20 for character in name):
        raise ValueError("daylight profile name contains a control character")

    consumed = name_end + 1
    trailing_length = len(parameters) - consumed
    if trailing_length not in allowed_trailing_lengths:
        expected = ", ".join(str(value) for value in allowed_trailing_lengths)
        raise ValueError(
            "daylight payload has an unsupported trailing length "
            f"of {trailing_length} bytes; expected {expected}"
        )

    return DaylightConfiguration(configuration_id, name, tuple(values)), consumed


def decode_daylight_status_pdu(
    data: bytes,
    *,
    request_opcode: int,
) -> DaylightStatus:
    """Decode 0x04 or 0x0F while retaining authoritative raw bytes.

    Parsing failure is represented in the returned object instead of raising.
    A wrong opcode or impossible request opcode remains a programming error and
    raises ``ValueError``.
    """

    if request_opcode not in (
        SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE,
        SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE,
    ):
        raise ValueError("unsupported daylight request opcode")
    if is_get_daylight_configuration_status(data):
        status_opcode = SANLIGHT_GET_DAYLIGHT_CONFIGURATION_STATUS_OPCODE
    elif is_get_combined_daylight_data_status(data):
        status_opcode = SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_STATUS_OPCODE
    else:
        raise ValueError("not a SANlight daylight status PDU")

    expected_status_opcode = {
        SANLIGHT_GET_DAYLIGHT_CONFIGURATION_OPCODE: (
            SANLIGHT_GET_DAYLIGHT_CONFIGURATION_STATUS_OPCODE
        ),
        SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_OPCODE: (
            SANLIGHT_GET_COMBINED_DAYLIGHT_DATA_STATUS_OPCODE
        ),
    }[request_opcode]
    if status_opcode != expected_status_opcode:
        raise ValueError(
            "daylight status opcode does not match the active request "
            f"(request=0x{request_opcode:02X}, status=0x{status_opcode:02X})"
        )

    parameters = data[3:]
    errors: list[str] = []

    if status_opcode == SANLIGHT_GET_DAYLIGHT_CONFIGURATION_STATUS_OPCODE:
        try:
            configuration, _ = _decode_daylight_configuration_at(
                parameters,
                offset=0,
                allowed_trailing_lengths=(0,),
            )
            return DaylightStatus(
                request_opcode=request_opcode,
                status_opcode=status_opcode,
                raw_pdu=data,
                configuration=configuration,
                parser_layout="configuration-v1",
            )
        except ValueError as exc:
            errors.append(str(exc))
    else:
        # Hardware capture on SANlight EVO firmware 4 confirms that 0x0F uses
        # a seven-byte prefix: the existing six-byte live status followed by
        # the current MaxBrightness byte, then the same configuration object
        # returned by 0x04. Unknown variants remain raw-only and trigger the
        # existing safe fallback to 0x03.
        try:
            if len(parameters) < 7:
                raise ValueError(
                    "combined daylight payload is too short for live status and "
                    "MaxBrightness"
                )
            live = decode_uptime_brightness_status_parameters(parameters[:6])
            max_brightness = validate_reported_max_brightness(parameters[6])
            configuration, _ = _decode_daylight_configuration_at(
                parameters,
                offset=7,
                allowed_trailing_lengths=(0,),
            )
            return DaylightStatus(
                request_opcode=request_opcode,
                status_opcode=status_opcode,
                raw_pdu=data,
                configuration=configuration,
                parser_layout="combined-live-max-prefix-v1",
                lamp_time_ms=live.lamp_time_ms,
                live_brightness_raw=live.brightness_raw,
                max_brightness=max_brightness,
            )
        except ValueError as exc:
            errors.append(str(exc))

    return DaylightStatus(
        request_opcode=request_opcode,
        status_opcode=status_opcode,
        raw_pdu=data,
        parse_error="; ".join(errors),
    )


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
