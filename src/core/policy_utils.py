#!/usr/bin/env python3

"""Policy utility functions shared between Gateway and Worker components."""

from datetime import UTC, datetime, timedelta

from src.core.constants import ErrorReason


def compute_next_check_time(
    reason: ErrorReason,
    *,
    on_no_quota_hr: int,
    on_rate_limit_hr: int,
    on_invalid_key_days: int,
    on_no_access_days: int,
    on_server_error_min: int,
    on_overload_min: int,
    on_other_error_hr: int,
) -> datetime:
    """
    Compute the next check time for a key based on health policy intervals.

    The function accepts plain values instead of a ``HealthPolicyConfig`` object,
    keeping this core utility free of any config-layer dependency.

    Args:
        reason: The ``ErrorReason`` that caused the key to fail.
        on_no_quota_hr: Delay in hours for ``NO_QUOTA`` errors.
        on_rate_limit_hr: Delay in hours for ``RATE_LIMITED`` errors.
        on_invalid_key_days: Delay in days for ``INVALID_KEY`` errors.
        on_no_access_days: Delay in days for ``NO_ACCESS`` errors.
        on_server_error_min: Delay in minutes for ``SERVER_ERROR``, ``TIMEOUT``,
            and ``NETWORK_ERROR``.
        on_overload_min: Delay in minutes for ``OVERLOADED`` errors.
        on_other_error_hr: Delay in hours for ``UNKNOWN``, ``BAD_REQUEST``,
            and all other unrecognised errors.

    Returns:
        The next ``datetime`` at which the key should be re-checked (UTC).

    Mapping:

    ================== ======================
    ErrorReason         Parameter used
    ================== ======================
    NO_QUOTA           ``on_no_quota_hr``
    RATE_LIMITED       ``on_rate_limit_hr``
    INVALID_KEY        ``on_invalid_key_days``
    NO_ACCESS          ``on_no_access_days``
    SERVER_ERROR       ``on_server_error_min``
    TIMEOUT            ``on_server_error_min``
    NETWORK_ERROR      ``on_server_error_min``
    OVERLOADED         ``on_overload_min``
    UNKNOWN            ``on_other_error_hr``
    BAD_REQUEST        ``on_other_error_hr``
    * (everything else) ``on_other_error_hr``
    ================== ======================
    """
    now = datetime.now(UTC)

    # Quota
    if reason == ErrorReason.NO_QUOTA:
        return now + timedelta(hours=on_no_quota_hr)

    # Rate limit
    if reason == ErrorReason.RATE_LIMITED:
        return now + timedelta(hours=on_rate_limit_hr)

    # Fatal key errors
    if reason == ErrorReason.INVALID_KEY:
        return now + timedelta(days=on_invalid_key_days)

    if reason == ErrorReason.NO_ACCESS:
        return now + timedelta(days=on_no_access_days)

    # Short-term recoverable server errors
    if reason in (
        ErrorReason.SERVER_ERROR,
        ErrorReason.TIMEOUT,
        ErrorReason.NETWORK_ERROR,
    ):
        return now + timedelta(minutes=on_server_error_min)

    # Overloaded
    if reason == ErrorReason.OVERLOADED:
        return now + timedelta(minutes=on_overload_min)

    # UNKNOWN, BAD_REQUEST, and everything else
    return now + timedelta(hours=on_other_error_hr)
