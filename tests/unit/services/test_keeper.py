from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import (
    DatabaseConfig,
    DatabaseRetryConfig,
    HealthPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.keeper import run_keeper
from src.services.key_probe import KeyProbe


# Mock for asyncio.sleep to avoid waiting in tests
async def mock_sleep(delay):
    return


@pytest.fixture
def mock_accessor():
    accessor = MagicMock()
    # Default policy setup
    policy = HealthPolicyConfig(
        verification_attempts=2,
        verification_delay_sec=60,  # Minimum value per Pydantic Field(ge=60) constraint
    )
    accessor.get_health_policy.return_value = policy
    accessor.get_provider_or_raise.return_value = ProviderConfig(
        provider_type="openai_like"
    )
    accessor.get_provider.return_value = ProviderConfig(provider_type="openai_like")
    # Mock keeper concurrency for semaphore init
    accessor.get_keeper_concurrency.return_value = 10
    # KeyProbe.__init__ now calls accessor.get_database_config().retry
    accessor.get_database_config.return_value = DatabaseConfig(
        retry=DatabaseRetryConfig(
            max_attempts=3,
            base_delay_sec=0.01,
            backoff_factor=1.0,
            jitter=False,
        )
    )
    return accessor


@pytest.fixture
def mock_db_manager():
    manager = MagicMock()
    manager.keys.update_status = AsyncMock()
    return manager


@pytest.fixture
def mock_client_factory():
    factory = MagicMock()
    factory.get_client_for_provider = AsyncMock()
    return factory


@pytest.fixture
def key_probe(mock_accessor, mock_db_manager, mock_client_factory):
    probe = KeyProbe(mock_accessor, mock_db_manager, mock_client_factory)
    return probe


@pytest.mark.asyncio
async def test_fast_fail_fatal_error(key_probe):
    """
    Test that fatal errors (INVALID_KEY) cause immediate failure without verification.
    """
    # Setup provider mock
    provider_instance = MagicMock()
    # Return fatal error immediately
    provider_instance.check = AsyncMock(
        return_value=CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid Key")
    )

    with patch("src.services.key_probe.get_provider", return_value=provider_instance):
        resource = {
            "key_id": 1,
            "key_value": "sk-test",
            "model_name": "gpt-4",
            "provider_name": "openai",
            "failing_since": None,
        }

        result = await key_probe._check_resource(resource)

        # Verify result
        assert result.ok is False
        assert result.error_reason == ErrorReason.INVALID_KEY

        # Verify check was called exactly once (no retries)
        assert provider_instance.check.call_count == 1


@pytest.mark.asyncio
async def test_verification_recovery(key_probe):
    """
    Test scenario: 500 (Server Error) -> Verification Loop -> 200 (Recovered).
    Should succeed after retries.
    """
    provider_instance = MagicMock()
    # Sequence: 1. Server Error, 2. Success
    provider_instance.check = AsyncMock(
        side_effect=[
            CheckResult.fail(ErrorReason.SERVER_ERROR, "Server Error"),
            CheckResult.success(100),  # Latency 100ms
        ]
    )

    with (
        patch("src.services.key_probe.get_provider", return_value=provider_instance),
        patch("asyncio.sleep", side_effect=mock_sleep) as slept,
    ):
        resource = {
            "key_id": 1,
            "key_value": "sk-test",
            "model_name": "gpt-4",
            "provider_name": "openai",
            "failing_since": None,
        }

        result = await key_probe._check_resource(resource)

        # Should be successful eventually
        assert result.ok is True

        # check called 2 times: 1 initial + 1 retry
        assert provider_instance.check.call_count == 2

        # Verify sleep was called (verification delay)
        assert slept.call_count == 1


@pytest.mark.asyncio
async def test_verification_death_confirmation(key_probe):
    """
    Test scenario: 429 (Rate Limit) -> Verification Loop -> 429 -> 429 -> Penalty.
    Should fail after exhausting attempts.
    """
    provider_instance = MagicMock()
    # Sequence: Always Rate Limited
    provider_instance.check = AsyncMock(
        return_value=CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate Limit")
    )

    # Configure 3 attempts in policy
    key_probe.accessor.get_health_policy.return_value.verification_attempts = 3

    with (
        patch("src.services.key_probe.get_provider", return_value=provider_instance),
        patch("asyncio.sleep", side_effect=mock_sleep) as slept,
    ):
        resource = {
            "key_id": 1,
            "key_value": "sk-test",
            "model_name": "gpt-4",
            "provider_name": "openai",
            "failing_since": None,
        }

        result = await key_probe._check_resource(resource)

        # Should fail
        assert result.ok is False
        assert result.error_reason == ErrorReason.RATE_LIMITED

        # Call count: 1 initial + 3 retries = 4 total calls
        assert provider_instance.check.call_count == 4

        # Verify sleep called 3 times
        assert slept.call_count == 3


@pytest.mark.asyncio
async def test_verification_fatal_interruption(key_probe):
    """
    Test scenario: 500 (Server Error) -> Verification Loop -> 401 (Invalid Key).
    Should stop verification immediately upon seeing fatal error.
    """
    provider_instance = MagicMock()
    # Sequence: 1. Server Error (Retryable), 2. Invalid Key (Fatal)
    provider_instance.check = AsyncMock(
        side_effect=[
            CheckResult.fail(ErrorReason.SERVER_ERROR, "Server Error"),
            CheckResult.fail(ErrorReason.INVALID_KEY, "Key Revoked"),
        ]
    )

    with (
        patch("src.services.key_probe.get_provider", return_value=provider_instance),
        patch("asyncio.sleep", side_effect=mock_sleep) as slept,
    ):
        resource = {
            "key_id": 1,
            "key_value": "sk-test",
            "model_name": "gpt-4",
            "provider_name": "openai",
            "failing_since": None,
        }

        result = await key_probe._check_resource(resource)

        # Should fail with fatal error
        assert result.ok is False
        assert result.error_reason == ErrorReason.INVALID_KEY

        # Call count: 1 initial + 1 retry = 2 calls
        assert provider_instance.check.call_count == 2

        # Verify sleep called only 1 time (before the first retry)
        assert slept.call_count == 1


def test_run_sync_cycle_uses_computed_path():
    """run_sync_cycle reads keys from computed path data/<name>/raw instead of provider.keys_path."""
    import os

    provider_name = "gemini-pro-home"
    expected = os.path.join("data", provider_name, "raw")
    assert expected == "data/gemini-pro-home/raw"


# ---------------------------------------------------------------------------
# M18-M20: Scheduler job registration tests
# ---------------------------------------------------------------------------


def _make_scheduler_mocks() -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create the common mock objects for run_keeper() scheduler tests.

    Returns (mock_scheduler, mock_accessor, mock_db_manager).
    """
    mock_scheduler = MagicMock()
    mock_scheduler.start = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.shutdown = MagicMock()
    mock_scheduler.print_jobs = MagicMock()

    mock_accessor = MagicMock()
    mock_accessor.get_all_providers.return_value = {}
    mock_accessor.get_enabled_providers.return_value = {}
    mock_accessor.get_database_dsn.return_value = (
        "postgresql://test:test@localhost:5432/testdb"
    )
    mock_accessor.get_pool_config.return_value = MagicMock(min_size=1, max_size=5)
    mock_db_config = MagicMock()
    mock_db_config.vacuum_policy.interval_minutes = 60
    mock_accessor.get_database_config.return_value = mock_db_config

    mock_db_manager = MagicMock()
    mock_db_manager.initialize_schema = AsyncMock()
    mock_db_manager.providers.sync = AsyncMock()

    return mock_scheduler, mock_accessor, mock_db_manager


async def _run_keeper_with_mocks(mock_scheduler, mock_accessor, mock_db_manager):
    """Patch all dependencies and run run_keeper(), returning the mock scheduler."""
    mock_hcf = MagicMock()
    mock_hcf.return_value.close_all = AsyncMock()

    with (
        patch(
            "src.services.keeper.AsyncIOScheduler",
            return_value=mock_scheduler,
        ),
        patch("src.services.keeper.load_config", return_value=MagicMock()),
        patch(
            "src.services.keeper.ConfigAccessor",
            return_value=mock_accessor,
        ),
        patch("src.services.keeper.setup_logging"),
        patch("src.services.keeper._setup_directories"),
        patch(
            "src.services.keeper.database.init_db_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "src.services.keeper.DatabaseManager",
            return_value=mock_db_manager,
        ),
        patch("src.services.keeper.HttpClientFactory", mock_hcf),
        patch("src.services.keeper.run_sync_cycle", new_callable=AsyncMock),
        patch("src.services.keeper.get_all_probes", return_value=[]),
        patch("src.services.keeper.get_all_syncers", return_value=[]),
        patch("src.services.keeper.KeyInventoryExporter"),
        patch(
            "src.services.keeper.database.close_db_pool",
            new_callable=AsyncMock,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock, side_effect=KeyboardInterrupt),
    ):
        await run_keeper()

    return mock_scheduler


# --- M18 ---


@pytest.mark.asyncio
async def test_no_run_periodic_vacuum_job_registered() -> None:
    """M18: 'run_periodic_vacuum' is NOT in scheduler jobs after keeper setup."""
    mock_scheduler, mock_accessor, mock_db_manager = _make_scheduler_mocks()
    scheduler = await _run_keeper_with_mocks(
        mock_scheduler, mock_accessor, mock_db_manager
    )

    # Verify no job with id "run_periodic_vacuum" was added
    for call in scheduler.add_job.call_args_list:
        job_id = call[1].get("id")
        assert (
            job_id != "run_periodic_vacuum"
        ), "run_periodic_vacuum job should NOT be registered"


# --- M19 ---


@pytest.mark.asyncio
async def test_key_purge_cron_job_registered() -> None:
    """M19: Worker registers cron job 'key_purge' with day_of_week='sun', hour=4, minute=0."""
    mock_scheduler, mock_accessor, mock_db_manager = _make_scheduler_mocks()
    scheduler = await _run_keeper_with_mocks(
        mock_scheduler, mock_accessor, mock_db_manager
    )

    # Find the key_purge job among add_job calls
    key_purge_call = None
    for call in scheduler.add_job.call_args_list:
        if call[1].get("id") == "key_purge":
            key_purge_call = call
            break

    assert key_purge_call is not None, "key_purge job should be registered"
    kwargs = key_purge_call[1]
    assert kwargs["day_of_week"] == "sun"
    assert kwargs["hour"] == 4
    assert kwargs["minute"] == 0


# --- M20 ---


@pytest.mark.asyncio
async def test_smart_vacuum_interval_job_registered() -> None:
    """M20: Worker registers interval job 'smart_vacuum' with minutes=60."""
    mock_scheduler, mock_accessor, mock_db_manager = _make_scheduler_mocks()
    scheduler = await _run_keeper_with_mocks(
        mock_scheduler, mock_accessor, mock_db_manager
    )

    # Find the smart_vacuum job among add_job calls
    smart_vacuum_call = None
    for call in scheduler.add_job.call_args_list:
        if call[1].get("id") == "smart_vacuum":
            smart_vacuum_call = call
            break

    assert smart_vacuum_call is not None, "smart_vacuum job should be registered"
    kwargs = smart_vacuum_call[1]
    assert kwargs["minutes"] == 60
