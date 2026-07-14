"""Pure policy helpers for robust SetMaxBrightness confirmation handling."""
from __future__ import annotations

from collections.abc import Collection

SET_MAX_STATUS_TIMEOUT_SECONDS = 4
SET_MAX_RETRY_DELAY_SECONDS = 1
SET_MAX_UNICAST_MAX_ATTEMPTS = 2
SET_MAX_GROUP_MAX_ATTEMPTS = 1
SET_MAX_UNCONFIRMED_EXIT_CODE = 3


def max_attempts_for_destination(
    destination: int,
    node_addresses: Collection[int],
) -> int:
    """Return the safe attempt count for a validated destination.

    A repeated unicast SetMaxBrightness with the same value is idempotent and is
    retried once when the acknowledgement is lost. Group writes are transmitted
    only once because a response from one member cannot prove group-wide state.
    """

    return (
        SET_MAX_UNICAST_MAX_ATTEMPTS
        if destination in node_addresses
        else SET_MAX_GROUP_MAX_ATTEMPTS
    )


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
    """Return why a SetMaxBrightness status is unrelated, or ``None``.

    This prevents a delayed or unrelated vendor status from being mistaken for
    confirmation of the current write transaction.
    """

    if key_index != expected_app_index:
        return (
            f"unexpected AppKey index {key_index}; expected {expected_app_index}"
        )

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
