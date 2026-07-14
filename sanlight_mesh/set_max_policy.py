"""Backward-compatible imports for MaxBrightness policy helpers."""

from .max_brightness_policy import (  # noqa: F401
    GET_MAX_MAX_ATTEMPTS,
    GET_MAX_RETRY_DELAY_SECONDS,
    GET_MAX_STATUS_TIMEOUT_SECONDS,
    MAX_BRIGHTNESS_MISMATCH_EXIT_CODE,
    MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE,
    SET_MAX_GROUP_MAX_ATTEMPTS,
    SET_MAX_RETRY_DELAY_SECONDS,
    SET_MAX_STATUS_TIMEOUT_SECONDS,
    SET_MAX_UNICAST_MAX_ATTEMPTS,
    max_attempts_for_destination,
    set_max_status_rejection_reason,
    unicast_status_rejection_reason,
)

# Historical name retained for callers of the v6 patch.
SET_MAX_UNCONFIRMED_EXIT_CODE = MAX_BRIGHTNESS_UNCONFIRMED_EXIT_CODE
