"""Tests for KeyProbe._update_resource_status() with transport failures.

Verifies that:
- transport_class is set → transport_failure=True
- guard is DOWN and result is not ok → transport_failure=True
- normal provider error with guard UP → transport_failure=False
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config.schemas import DatabaseConfig, DatabaseRetryConfig, HealthPolicyConfig
from src.core.constants import ErrorReason, TransportFailureClass
from src.core.models import CheckResult
from src.services.key_probe import KeyProbe
from tests._canonical import CanonicalConfig


@pytest.fixture
def mock_dependencies():
    """Create mocked dependencies for KeyProbe with proper DB retry config."""
    mock_db = MagicMock()
    mock_db.keys.update_status = AsyncMock()
    mock_http = MagicMock()
    mock_http.get_client_for_provider = AsyncMock()
    mock_accessor = MagicMock()
    mock_accessor.get_keeper_concurrency.return_value = 10
    mock_accessor.get_database_config.return_value = DatabaseConfig(
        retry=DatabaseRetryConfig(
            max_attempts=3,
            base_delay_sec=0.1,
            backoff_factor=2.0,
            jitter=False,
        )
    )
    mock_accessor.get_provider.return_value = MagicMock()
    mock_accessor.get_health_policy.return_value = HealthPolicyConfig()
    return mock_accessor, mock_db, mock_http


@pytest.fixture
def key_probe(mock_dependencies):
    """Create a KeyProbe with mocked dependencies."""
    mock_accessor, mock_db, mock_http = mock_dependencies
    probe = KeyProbe(mock_accessor, mock_db, mock_http)
    return probe, mock_accessor, mock_db


@pytest.mark.asyncio
async def test_update_resource_status_transport_class_sets_transport_failure(
    key_probe,
):
    """result.transport_class is not None → transport_failure=True."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 123,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.fail(
        ErrorReason.NETWORK_ERROR,
        "Connection timeout",
        transport_class=TransportFailureClass.CONNECT_TIMEOUT,
    )

    await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=True
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is True


@pytest.mark.asyncio
async def test_update_resource_status_guard_down_sets_transport_failure(
    key_probe,
):
    """guard is DOWN and result is not ok → transport_failure=True."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 456,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid API key")

    # Mock guard as DOWN and enforcing
    mock_guard = MagicMock()
    mock_guard.enforcing = True
    mock_guard.is_down.return_value = True

    with patch("src.services.key_probe.get_network_guard", return_value=mock_guard):
        await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=True
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is True


@pytest.mark.asyncio
async def test_update_resource_status_normal_error_guard_up_no_transport_failure(
    key_probe,
):
    """normal provider error with guard UP → transport_failure=False."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 789,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid API key")

    # Mock guard as UP
    mock_guard = MagicMock()
    mock_guard.enforcing = True
    mock_guard.is_down.return_value = False

    with patch("src.services.key_probe.get_network_guard", return_value=mock_guard):
        await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=False
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is False


@pytest.mark.asyncio
async def test_update_resource_status_success_no_transport_failure(
    key_probe,
):
    """success result → transport_failure=False regardless of guard state."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 101,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.success()

    # Mock guard as DOWN
    mock_guard = MagicMock()
    mock_guard.enforcing = True
    mock_guard.is_down.return_value = True

    with patch("src.services.key_probe.get_network_guard", return_value=mock_guard):
        await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=False
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is False


@pytest.mark.asyncio
async def test_update_resource_status_guard_not_enforcing_no_transport_failure(
    key_probe,
):
    """guard in log mode (not enforcing) → transport_failure=False for normal errors."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 202,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.fail(ErrorReason.RATE_LIMITED, "Rate limited")

    # Mock guard as DOWN but not enforcing (log mode)
    mock_guard = MagicMock()
    mock_guard.enforcing = False
    mock_guard.is_down.return_value = True

    with patch("src.services.key_probe.get_network_guard", return_value=mock_guard):
        await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=False
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is False


@pytest.mark.asyncio
async def test_update_resource_status_no_guard_no_transport_failure(
    key_probe,
):
    """no guard installed → transport_failure=False for normal errors."""
    probe, mock_accessor, mock_db = key_probe
    resource = {
        "key_id": 303,
        "model_name": CanonicalConfig.from_example_files().canonical_model_names[0],
        "provider_name": "openai",
        "failing_since": None,
        "next_check_time": datetime.now(UTC),
    }
    result = CheckResult.fail(ErrorReason.INVALID_KEY, "Invalid API key")

    # Mock no guard
    with patch("src.services.key_probe.get_network_guard", return_value=None):
        await probe._update_resource_status(resource, result)

    # Verify update_status was called with transport_failure=False
    mock_db.keys.update_status.assert_awaited_once()
    call_kwargs = mock_db.keys.update_status.call_args[1]
    assert call_kwargs["transport_failure"] is False
