from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import HealthPolicyConfig, ProviderConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.probes.key_probe import KeyProbe


# Mock for asyncio.sleep to avoid waiting in tests
async def mock_sleep(delay):
    return


@pytest.fixture
def mock_accessor():
    accessor = MagicMock()
    # Default policy setup
    policy = HealthPolicyConfig(
        verification_attempts=2,
        verification_delay_sec=10,  # Short delay for tests, though logic uses it as is
    )
    accessor.get_health_policy.return_value = policy
    accessor.get_provider_or_raise.return_value = ProviderConfig()
    accessor.get_provider.return_value = ProviderConfig()
    # Mock worker concurrency for semaphore init
    accessor.get_worker_concurrency.return_value = 10
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

    with patch(
        "src.services.probes.key_probe.get_provider", return_value=provider_instance
    ):
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

    with patch(
        "src.services.probes.key_probe.get_provider", return_value=provider_instance
    ):
        with patch("asyncio.sleep", side_effect=mock_sleep) as slept:
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

    with patch(
        "src.services.probes.key_probe.get_provider", return_value=provider_instance
    ):
        with patch("asyncio.sleep", side_effect=mock_sleep) as slept:
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

    with patch(
        "src.services.probes.key_probe.get_provider", return_value=provider_instance
    ):
        with patch("asyncio.sleep", side_effect=mock_sleep) as slept:
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
