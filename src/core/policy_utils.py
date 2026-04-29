#!/usr/bin/env python3

"""Policy utility functions shared between Gateway and Worker components."""

from datetime import UTC, datetime, timedelta

from src.config.schemas import HealthPolicyConfig
from src.core.constants import ErrorReason


def compute_next_check_time(
    policy: HealthPolicyConfig,
    reason: ErrorReason,
    failing_since: datetime | None = None,
) -> datetime:
    """
    Compute the next check time for a key based on the health policy and error reason.

    Mirrors the logic of ``_calculate_next_check_time()`` in ``KeyProbe`` but is
    usable as a plain function (e.g. from the Gateway's ``_report_key_failure``).

    Args:
        policy: The provider's ``HealthPolicyConfig``.
        reason: The ``ErrorReason`` that caused the key to fail.
        failing_since: When the key started failing (reserved for future use
            in quarantine/amnesty logic). Currently unused.

    Returns:
        The next ``datetime`` at which the key should be re-checked (UTC).

    Mapping (time unit comes from ``HealthPolicyConfig``):

    ================== ========================
    ErrorReason         HealthPolicyConfig field
    ================== ========================
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
    ================== ========================
    """
    _ = failing_since  # reserved for future quarantine/amnesty logic
    now = datetime.now(UTC)

    # Quota
    if reason == ErrorReason.NO_QUOTA:
        return now + timedelta(hours=policy.on_no_quota_hr)

    # Rate limit
    if reason == ErrorReason.RATE_LIMITED:
        return now + timedelta(hours=policy.on_rate_limit_hr)

    # Fatal key errors
    if reason == ErrorReason.INVALID_KEY:
        return now + timedelta(days=policy.on_invalid_key_days)

    if reason == ErrorReason.NO_ACCESS:
        return now + timedelta(days=policy.on_no_access_days)

    # Short-term recoverable server errors
    if reason in (
        ErrorReason.SERVER_ERROR,
        ErrorReason.TIMEOUT,
        ErrorReason.NETWORK_ERROR,
    ):
        return now + timedelta(minutes=policy.on_server_error_min)

    # Overloaded
    if reason == ErrorReason.OVERLOADED:
        return now + timedelta(minutes=policy.on_overload_min)

    # UNKNOWN, BAD_REQUEST, and everything else
    return now + timedelta(hours=policy.on_other_error_hr)
