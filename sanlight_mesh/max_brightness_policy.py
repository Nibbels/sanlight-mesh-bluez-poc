"""Pure policy helpers for MaxBrightness writes and readback verification."""
from __future__ import annotations

from collections.abc import Collection

SET_MAX_STATUS_TIMEOUT_SECONDS = 4
SET_MAX_RETRY_DELAY_SECONDS = 1
SET_MAX_UNICAST_MAX_ATTEMPTS = 2
SET_MAX_GROUP_MAX_ATTEMPTS = 1

GET_MAX_STATUS_TIMEOUT_SECONDS = 4
GET_MAX_RETRY_DELAY_SECONDS = 1
GET_MAX_MAX_ATTEMPTS = 2

MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE = 3
MAX_BRIGHTNESS_MISMATCH_EXIT_CODE = 4


def max_attempts_for_destination(
    destination: int,
    node_addresses: Collection[int],
) -> int:
    """Return the safe SetMaxBrightness attempt count for a destination.

    A repeated unicast write of the same value is idempotent and may be retried
    once when the acknowledgement is lost. A group write is transmitted only
    once because one member's response cannot establish group-wide state.
    """

    return (
        SET_MAX_UNICAST_MAX_ATTEMPTS
        if destination in node_addresses
        else SET_MAX_GROUP_MAX_ATTEMPTS
    )


def _common_vendor_status_rejection_reason(
    *,
    source: int,
    key_index: int,
    response_destination: int | None,
    expected_app_index: int,
    sender_unicast: int,
) -> str | None:
    if key_index != expected_app_index:
        return f"unexpected AppKey index {key_index}; expected {expected_app_index}"

    if response_destination != sender_unicast:
        actual = (
            "unknown"
            if response_destination is None
            else f"0x{response_destination:04X}"
        )
        return (
            f"unexpected response destination {actual}; "
            f"expected sender 0x{sender_unicast:04X}"
        )

    return None


def unicast_status_rejection_reason(
    *,
    source: int,
    key_index: int,
    response_destination: int | None,
    requested_destination: int,
    expected_app_index: int,
    sender_unicast: int,
    node_addresses: Collection[int],
) -> str | None:
    """Return why a unicast vendor status is unrelated, or ``None``."""

    common_reason = _common_vendor_status_rejection_reason(
        source=source,
        key_index=key_index,
        response_destination=response_destination,
        expected_app_index=expected_app_index,
        sender_unicast=sender_unicast,
    )
    if common_reason is not None:
        return common_reason

    if requested_destination not in node_addresses:
        return "requested destination is not a known SANlight lamp node"

    if source != requested_destination:
        return (
            f"unexpected source 0x{source:04X}; "
            f"expected node 0x{requested_destination:04X}"
        )

    return None


def set_max_status_rejection_reason(
    *,
    source: int,
    key_index: int,
    response_destination: int | None,
    requested_destination: int,
    expected_app_index: int,
    sender_unicast: int,
    node_addresses: Collection[int],
    group_addresses: Collection[int],
) -> str | None:
    """Return why a SetMaxBrightness status is unrelated, or ``None``."""

    common_reason = _common_vendor_status_rejection_reason(
        source=source,
        key_index=key_index,
        response_destination=response_destination,
        expected_app_index=expected_app_index,
        sender_unicast=sender_unicast,
    )
    if common_reason is not None:
        return common_reason

    if requested_destination in node_addresses:
        if source != requested_destination:
            return (
                f"unexpected source 0x{source:04X}; "
                f"expected node 0x{requested_destination:04X}"
            )
        return None

    if requested_destination in group_addresses:
        if source not in node_addresses:
            return f"source 0x{source:04X} is not a known SANlight lamp node"
        return None

    return "requested destination is not a known node or group"
