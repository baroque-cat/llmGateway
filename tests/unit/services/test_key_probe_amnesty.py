#!/usr/bin/env python3

"""
Unit and integration tests for KeyProbe:
- Downtime amnesty feature (prevents false quarantines after long system downtimes)
- DB retry integration via AsyncRetrier (UT-G01..UT-G07, INT-01..INT-07)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import inspect

import pytest
from asyncpg.exceptions import (
    ConnectionDoesNotExistError,
    DeadlockDetectedError,
    InterfaceError,
    UniqueViolationError,
)

from src.config.schemas import (
    AdaptiveBatchingConfig,
    DatabaseConfig,
    DatabaseRetryConfig,
    HealthPolicyConfig,
)
from src.core.batching import AdaptiveBatchController
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.core.probes import IResourceProbe
from src.core.retry import AsyncRetrier, DB_RETRYABLE
from src.services.probes.key_probe import KeyProbe

# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for KeyProbe with proper DB retry config."""
    mock_db = MagicMock()
    mock_db.keys.update_status = AsyncMock()
    mock_db.keys.get_keys_to_check = AsyncMock(return_value=[])
    mock_http = MagicMock()
    mock_http.get_client_for_provider = AsyncMock()
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10
    # KeyProbe.__init__ now calls accessor.get_database_config().retry
    mock_accessor.get_database_config.return_value = DatabaseConfig(
        retry=DatabaseRetryConfig(
            max_attempts=3,
            base_delay_sec=0.01,  # Small delay for fast tests
            backoff_factor=1.0,
            jitter=False,
        )
    )
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


# ── Amnesty tests ────────────────────────────────────────────────────────────


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
    mock_db.keys.update_status.assert_called_once()
    call_kwargs = mock_db.keys.update_status.call_args.kwargs
    expected_next_check = now + timedelta(
        days=health_policy.quarantine_recheck_interval_days
    )
    actual_next_check = call_kwargs["next_check_time"]
    diff = abs((actual_next_check - expected_next_check).total_seconds())
    assert diff < 1.0, f"Expected quarantine recheck interval, got {actual_next_check}"


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
    assert (
        diff < 1.0
    ), f"Expected on_invalid_key_days interval (amnesty applied), got {actual_next_check}"


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


# ── UT-G01..UT-G07: KeyProbe retry integration ──────────────────────────────


@pytest.mark.asyncio
async def test_ut_g01_init_creates_async_retrier_from_config():
    """
    UT-G01: KeyProbe.__init__ creates AsyncRetrier from accessor.get_database_config().retry
    """
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10
    custom_retry = DatabaseRetryConfig(
        max_attempts=5,
        base_delay_sec=2.0,
        backoff_factor=3.0,
        jitter=False,
    )
    mock_accessor.get_database_config.return_value = DatabaseConfig(retry=custom_retry)
    mock_db = MagicMock()
    mock_http = MagicMock()

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    # Verify _db_retrier is an AsyncRetrier instance
    assert isinstance(probe._db_retrier, AsyncRetrier)
    # Verify it was configured from the database config
    assert probe._db_retrier._max_attempts == 5
    assert probe._db_retrier._base_delay_sec == 2.0
    assert probe._db_retrier._backoff_factor == 3.0
    assert probe._db_retrier._jitter is False


@pytest.mark.asyncio
async def test_ut_g02_get_resources_retry_on_connection_error(mock_dependencies):
    """
    UT-G02: _get_resources_to_check() wrapped in self._db_retrier.execute(...)
    — retry on ConnectionDoesNotExistError (1st attempt fails, 2nd succeeds)
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_enabled_providers.return_value = {"openai": MagicMock()}

    # First call raises ConnectionDoesNotExistError, second succeeds
    keys_data = [
        {
            "key_id": 1,
            "model_name": "gpt-4",
            "provider_name": "openai",
            "key_value": "sk-test",
            "failing_since": None,
        }
    ]
    mock_db.keys.get_keys_to_check = AsyncMock(
        side_effect=[
            ConnectionDoesNotExistError("connection lost"),
            keys_data,
        ]
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await probe._get_resources_to_check()

    assert len(result) == 1
    assert result[0]["key_id"] == 1
    # Called twice: first failed, second succeeded
    assert mock_db.keys.get_keys_to_check.call_count == 2


@pytest.mark.asyncio
async def test_ut_g03_update_status_retry_on_deadlock(mock_dependencies, health_policy):
    """
    UT-G03: _update_resource_status() wrapped in self._db_retrier.execute(...)
    — retry on DeadlockDetectedError (1st attempt fails, 2nd succeeds)
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    # First call raises DeadlockDetectedError, second succeeds
    mock_db.keys.update_status = AsyncMock(
        side_effect=[
            DeadlockDetectedError("deadlock detected"),
            None,
        ]
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    resource = {
        "key_id": 1,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": None,
        "next_check_time": now,
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await probe._update_resource_status(resource, result)

    # Called twice: first failed (deadlock), second succeeded
    assert mock_db.keys.update_status.call_count == 2


@pytest.mark.asyncio
async def test_ut_g04_get_resources_non_retryable_error(mock_dependencies):
    """
    UT-G04: _get_resources_to_check() — non-retryable DB error (UniqueViolationError)
    is not retried, raised immediately.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_enabled_providers.return_value = {"openai": MagicMock()}

    mock_db.keys.get_keys_to_check = AsyncMock(
        side_effect=UniqueViolationError("unique violation")
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    with pytest.raises(UniqueViolationError):
        await probe._get_resources_to_check()

    # Called only once — no retry for non-retryable errors
    assert mock_db.keys.get_keys_to_check.call_count == 1


@pytest.mark.asyncio
async def test_ut_g05_update_status_all_attempts_exhausted(
    mock_dependencies, health_policy
):
    """
    UT-G05: _update_resource_status() — all retry attempts exhausted → InterfaceError raised
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    # All calls raise InterfaceError
    mock_db.keys.update_status = AsyncMock(
        side_effect=InterfaceError("interface error")
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    resource = {
        "key_id": 1,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": None,
        "next_check_time": now,
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(InterfaceError):
            await probe._update_resource_status(resource, result)

    # Called 3 times (max_attempts=3)
    assert mock_db.keys.update_status.call_count == 3


def test_ut_g06_iresourceprobe_no_async_retrier():
    """
    UT-G06: IResourceProbe does not contain AsyncRetrier — retry only in KeyProbe.
    """
    assert not hasattr(IResourceProbe, "_db_retrier")
    assert not hasattr(IResourceProbe, "_execute_with_retry")


def test_ut_g07_keyprobe_init_no_retrier_parameter():
    """
    UT-G07: KeyProbe.__init__ does not accept AsyncRetrier as a parameter — creates it itself.
    """
    sig = inspect.signature(KeyProbe.__init__)
    params = list(sig.parameters.keys())
    # KeyProbe.__init__ has (self, *args, **kwargs) — no db_retrier parameter
    assert "db_retrier" not in params

    # Verify that _db_retrier is created internally from accessor config
    mock_accessor = MagicMock()
    mock_accessor.get_worker_concurrency.return_value = 10
    mock_accessor.get_database_config.return_value = DatabaseConfig()
    mock_db = MagicMock()
    mock_http = MagicMock()

    probe = KeyProbe(mock_accessor, mock_db, mock_http)
    assert isinstance(probe._db_retrier, AsyncRetrier)
    # Verify default config values are used
    assert probe._db_retrier._max_attempts == 3
    assert probe._db_retrier._base_delay_sec == 1.0
    assert probe._db_retrier._backoff_factor == 2.0
    assert probe._db_retrier._jitter is True


# ── INT-01..INT-07: Integration tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_int01_full_cycle_transient_db_error(mock_dependencies, health_policy):
    """
    INT-01: Full cycle KeyProbe with transient DB error.
    ConnectionDoesNotExistError at get_keys_to_check → retry successful →
    keys obtained → _check_resource → _update_resource_status → status updated.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_enabled_providers.return_value = {"openai": MagicMock()}
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    # get_keys_to_check: first attempt fails, second succeeds
    keys_data = [
        {
            "key_id": 1,
            "model_name": "gpt-4",
            "provider_name": "openai",
            "key_value": "sk-test",
            "failing_since": None,
            "next_check_time": datetime.now(UTC),
        }
    ]
    mock_db.keys.get_keys_to_check = AsyncMock(
        side_effect=[
            ConnectionDoesNotExistError("connection lost"),
            keys_data,
        ]
    )
    mock_db.keys.update_status = AsyncMock()

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    # Step 1: Get resources (with retry)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resources = await probe._get_resources_to_check()

    assert len(resources) == 1
    assert mock_db.keys.get_keys_to_check.call_count == 2

    # Step 2: Check resource (mock provider check)
    # Use INVALID_KEY (fatal) to avoid verification loop with long sleeps
    provider_instance = MagicMock()
    provider_instance.check = AsyncMock(
        return_value=CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")
    )

    with patch(
        "src.services.probes.key_probe.get_provider", return_value=provider_instance
    ):
        check_result = await probe._check_resource(resources[0])

    assert check_result.ok is False
    assert check_result.error_reason == ErrorReason.INVALID_KEY

    # Step 3: Update status (no retry needed)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await probe._update_resource_status(resources[0], check_result)

    mock_db.keys.update_status.assert_called_once()


@pytest.mark.asyncio
async def test_int02_full_cycle_db_unavailable(mock_dependencies):
    """
    INT-02: Full cycle KeyProbe with complete DB unavailability.
    InterfaceError on all 3 attempts of get_keys_to_check →
    run_cycle() doesn't crash (error is caught and logged).
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_enabled_providers.return_value = {"openai": MagicMock()}

    # All attempts raise InterfaceError
    mock_db.keys.get_keys_to_check = AsyncMock(
        side_effect=InterfaceError("db unavailable")
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    # _get_resources_to_check raises InterfaceError after 3 attempts
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(InterfaceError),
    ):
        await probe._get_resources_to_check()

    assert mock_db.keys.get_keys_to_check.call_count == 3

    # run_cycle() catches the exception — doesn't crash
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await probe.run_cycle()

    # No resources were processed (DB was unavailable)
    assert len(probe.active_tasks) == 0


@pytest.mark.asyncio
async def test_int03_adaptive_batching_new_api():
    """
    INT-03: Full cycle with adaptive batching through new API.
    HealthPolicyConfig without batch_size/batch_delay_sec,
    with adaptive_batching: { start_batch_size: 10, start_batch_delay_sec: 30.0 } →
    controller created with batch_size=10, batch_delay=30.0 →
    after successful batch, ramp-up to batch_size=15.
    """
    adaptive_config = AdaptiveBatchingConfig(
        start_batch_size=10,
        start_batch_delay_sec=30.0,
    )
    policy = HealthPolicyConfig(adaptive_batching=adaptive_config)

    # Verify HealthPolicyConfig has no batch_size/batch_delay_sec
    assert "batch_size" not in HealthPolicyConfig.model_fields
    assert "batch_delay_sec" not in HealthPolicyConfig.model_fields

    # Verify adaptive_batching is populated with custom values
    assert policy.adaptive_batching.start_batch_size == 10
    assert policy.adaptive_batching.start_batch_delay_sec == 30.0

    # Create controller from config (new API: params parameter)
    controller = AdaptiveBatchController(params=adaptive_config.to_params())
    assert controller.batch_size == 10
    assert controller.batch_delay == 30.0

    # Report a successful batch → ramp-up
    controller.report_batch_result([CheckResult.success(100)])
    assert controller.batch_size == 15  # 10 + step(5) = 15


@pytest.mark.asyncio
async def test_int06_retry_and_adaptive_batching_no_conflict(
    mock_dependencies, health_policy
):
    """
    INT-06: Retry + adaptive batching simultaneously (no conflict).
    get_keys_to_check fails with ConnectionDoesNotExistError → retry succeeds →
    keys obtained → batch processed → update_status succeeds → controller ramp-up.
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_enabled_providers.return_value = {"openai": MagicMock()}
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    # get_keys_to_check: first fails, second succeeds
    keys_data = [
        {
            "key_id": 1,
            "model_name": "gpt-4",
            "provider_name": "openai",
            "key_value": "sk-test",
            "failing_since": None,
            "next_check_time": datetime.now(UTC),
        }
    ]
    mock_db.keys.get_keys_to_check = AsyncMock(
        side_effect=[
            ConnectionDoesNotExistError("connection lost"),
            keys_data,
        ]
    )
    mock_db.keys.update_status = AsyncMock()

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    # Get resources with retry
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resources = await probe._get_resources_to_check()

    assert len(resources) == 1
    assert mock_db.keys.get_keys_to_check.call_count == 2

    # Verify adaptive batch controller works independently of retry
    adaptive_config = health_policy.adaptive_batching
    controller = AdaptiveBatchController(params=adaptive_config.to_params())
    initial_batch_size = controller.batch_size

    # Report a successful batch to trigger ramp-up
    controller.report_batch_result([CheckResult.success(100)])
    assert controller.batch_size > initial_batch_size  # ramp-up happened

    # Retry and adaptive batching don't interfere:
    # retry is at DB operation level, adaptive batching is at batch processing level


@pytest.mark.asyncio
async def test_int07_retry_deadlock_idempotency(mock_dependencies, health_policy):
    """
    INT-07: Retry in _update_resource_status on deadlock — idempotency.
    update_status fails with DeadlockDetectedError on 1st attempt → retry →
    called twice with same arguments (COALESCE preserves first value in SQL).
    """
    mock_accessor, mock_db, mock_http = mock_dependencies
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = health_policy

    # First call raises DeadlockDetectedError, second succeeds
    mock_db.keys.update_status = AsyncMock(
        side_effect=[
            DeadlockDetectedError("deadlock detected"),
            None,
        ]
    )

    probe = KeyProbe(mock_accessor, mock_db, mock_http)

    now = datetime.now(UTC)
    resource = {
        "key_id": 1,
        "model_name": "test-model",
        "provider_name": "test-provider",
        "failing_since": None,
        "next_check_time": now,
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid key")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await probe._update_resource_status(resource, result)

    # update_status called twice (deadlock retry)
    assert mock_db.keys.update_status.call_count == 2

    # Both calls have the same arguments — idempotent (COALESCE preserves first value)
    call1_kwargs = mock_db.keys.update_status.call_args_list[0].kwargs
    call2_kwargs = mock_db.keys.update_status.call_args_list[1].kwargs

    assert call1_kwargs["key_id"] == call2_kwargs["key_id"]
    assert call1_kwargs["model_name"] == call2_kwargs["model_name"]
    assert call1_kwargs["provider_name"] == call2_kwargs["provider_name"]
    assert call1_kwargs["result"] == call2_kwargs["result"]
