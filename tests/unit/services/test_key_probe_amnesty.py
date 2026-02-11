#!/usr/bin/env python3

"""
Unit tests for the downtime amnesty feature in KeyProbe.
Tests the logic that prevents false quarantines after long system downtimes.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import HealthPolicyConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.probes.key_probe import KeyProbe


@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for KeyProbe."""
    mock_db = MagicMock()
    mock_db.keys.update_status = AsyncMock()
    mock_http = MagicMock()
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10
    return mock_accessor, mock_db, mock_http


@pytest.fixture
def health_policy():
    """Return a HealthPolicyConfig with custom amnesty threshold."""
    return HealthPolicyConfig(
        amnesty_threshold_days=2.0,
        quarantine_after_days=30,
        stop_checking_after_days=90,
        on_invalid_key_days=10,
        on_no_access_days=10,
        on_rate_limit_hr=4,
        on_no_quota_hr=4,
        on_overload_min=60,
        on_server_error_min=30,
        on_other_error_hr=1,
        on_success_hr=24,
    )


@pytest.mark.asyncio
async def test_amnesty_not_applied_small_gap(mock_dependencies, health_policy):
    """
    Scenario A: Gap is small (1 minute). Old failing_since should be respected.
    A key that has been failing for > quarantine_after_days should go to quarantine.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()  # provider exists
    mock_accessor.get_health_policy.return_value = health_policy

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    next_check_time_scheduled = now - timedelta(minutes=1)  # 1 minute late
    failing_since = now - timedelta(
        days=40
    )  # failing for 40 days (> quarantine threshold)

    resource = {
        "key_id": 1,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": failing_since,
        "next_check_time": next_check_time_scheduled,
    }

    # Simulate a failure (e.g., INVALID_KEY)
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    await probe._update_resource_status(resource, result)

    # Amnesty should NOT be applied because gap (1 min) < threshold (2 days)
    # Therefore failing_since remains unchanged, and key should be in quarantine.
    # The next_check_time should be quarantine_recheck_interval_days (default 10 days).
    # However, the default quarantine_recheck_interval_days is 10 (from defaults).
    # Since we didn't set it in health_policy, it will be default 10.
    # Let's verify that update_status was called with appropriate next_check_time.
    # We'll compute expected next_check_time: now + timedelta(days=health_policy.quarantine_recheck_interval_days)
    # But we need to capture the call arguments.
    mock_db.keys.update_status.assert_called_once()
    call_kwargs = mock_db.keys.update_status.call_args.kwargs
    # next_check_time should be roughly now + 10 days (allow small epsilon).
    expected_next_check = now + timedelta(
        days=health_policy.quarantine_recheck_interval_days
    )
    actual_next_check = call_kwargs["next_check_time"]
    diff = abs((actual_next_check - expected_next_check).total_seconds())
    assert diff < 1.0, f"Expected quarantine recheck interval, got {actual_next_check}"
    # Ensure failing_since was not reset (i.e., passed as original? Actually update_status doesn't receive failing_since)
    # The amnesty logic resets failing_since to None only if gap > threshold, which didn't happen.
    # We can verify that logger.info about amnesty was NOT called.
    # We'll need to patch logger, but for simplicity we trust the logic.


@pytest.mark.asyncio
async def test_amnesty_not_applied_short_downtime(mock_dependencies, health_policy):
    """
    Scenario B: Gap is less than amnesty_threshold_days (e.g., 1 day with 2-day threshold).
    Old failing_since should still be respected.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    next_check_time_scheduled = now - timedelta(days=1)  # 1 day late
    failing_since = now - timedelta(days=15)  # failing for 15 days (< quarantine)

    resource = {
        "key_id": 2,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": failing_since,
        "next_check_time": next_check_time_scheduled,
    }

    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    await probe._update_resource_status(resource, result)

    # Amnesty should NOT be applied (gap < threshold)
    # Since failing_since is not None and time_failing < quarantine_after_days,
    # next_check_time should be on_invalid_key_days (10 days).
    mock_db.keys.update_status.assert_called_once()
    call_kwargs = mock_db.keys.update_status.call_args.kwargs
    expected_next_check = now + timedelta(days=health_policy.on_invalid_key_days)
    actual_next_check = call_kwargs["next_check_time"]
    diff = abs((actual_next_check - expected_next_check).total_seconds())
    assert diff < 1.0, f"Expected on_invalid_key_days interval, got {actual_next_check}"


@pytest.mark.asyncio
async def test_amnesty_applied_long_downtime(mock_dependencies, health_policy):
    """
    Scenario C: Gap is greater than amnesty_threshold_days (e.g., 3 days with 2-day threshold).
    The failing_since should be treated as None, so even if the key fails,
    it starts a fresh backoff cycle instead of going to quarantine.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    next_check_time_scheduled = now - timedelta(days=3)  # 3 days late (> threshold)
    failing_since = now - timedelta(days=40)  # failing for 40 days (> quarantine)

    resource = {
        "key_id": 3,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": failing_since,
        "next_check_time": next_check_time_scheduled,
    }

    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    await probe._update_resource_status(resource, result)

    # Amnesty SHOULD be applied (gap > threshold), failing_since reset to None.
    # Therefore the key is treated as fresh failure, not yet in quarantine.
    # next_check_time should be on_invalid_key_days (10 days) instead of quarantine recheck.
    mock_db.keys.update_status.assert_called_once()
    call_kwargs = mock_db.keys.update_status.call_args.kwargs
    expected_next_check = now + timedelta(days=health_policy.on_invalid_key_days)
    actual_next_check = call_kwargs["next_check_time"]
    diff = abs((actual_next_check - expected_next_check).total_seconds())
    assert diff < 1.0, (
        f"Expected on_invalid_key_days interval (amnesty applied), got {actual_next_check}"
    )


@pytest.mark.asyncio
async def test_amnesty_applied_but_key_valid(mock_dependencies, health_policy):
    """
    Scenario D: Gap is large, but the key check is successful.
    The status should become valid and failing_since should be cleared (existing behavior).
    Amnesty doesn't affect this; confirm amnesty doesn't break it.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    next_check_time_scheduled = now - timedelta(days=5)  # 5 days late (> threshold)
    failing_since = now - timedelta(days=40)  # failing for 40 days

    resource = {
        "key_id": 4,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": failing_since,
        "next_check_time": next_check_time_scheduled,
    }

    result = CheckResult.success()  # success

    await probe._update_resource_status(resource, result)

    # Amnesty may be applied but irrelevant because key is valid.
    # The next_check_time should be on_success_hr (24 hours).
    mock_db.keys.update_status.assert_called_once()
    call_kwargs = mock_db.keys.update_status.call_args.kwargs
    expected_next_check = now + timedelta(hours=health_policy.on_success_hr)
    actual_next_check = call_kwargs["next_check_time"]
    diff = abs((actual_next_check - expected_next_check).total_seconds())
    assert diff < 1.0, f"Expected on_success_hr interval, got {actual_next_check}"
    # Result should be ok
    assert call_kwargs["result"].ok is True
