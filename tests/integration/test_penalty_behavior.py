import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request, Response

from src.config.schemas import HealthPolicyConfig
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.gateway_service import _handle_buffered_retryable_request

# --- FIXTURES ---


@pytest.fixture
def mock_app_state():
    """Mocks the FastAPI app state with all necessary dependencies."""
    state = MagicMock()

    # Mock Database
    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()

    # Mock Cache
    state.gateway_cache = MagicMock()
    state.gateway_cache.get_key_from_pool.return_value = (1, "sk-test-key")
    state.gateway_cache.remove_key_from_pool = AsyncMock()

    # Mock HTTP Client Factory
    state.http_client_factory = MagicMock()
    # Correct AsyncMock setup for factory
    state.http_client_factory.get_client_for_provider = AsyncMock(
        return_value=MagicMock()
    )

    # Mock Config Accessor
    state.accessor = MagicMock()

    # Setup Debug Mode Map
    state.debug_mode_map = {}

    return state


@pytest.fixture
def mock_request(mock_app_state):
    """Creates a mock FastAPI Request."""
    request = AsyncMock(spec=Request)
    request.app.state = mock_app_state
    request.method = "POST"
    request.url.path = "/v1/chat/completions"
    request.url.query = ""
    request.headers = {"Authorization": "Bearer gateway-token"}
    request.body.return_value = b'{"model": "gpt-4"}'
    return request


@pytest.fixture
def mock_provider():
    """Creates a mock Provider."""
    provider = MagicMock()
    provider.parse_request_details = AsyncMock()
    # Mock details return
    details = MagicMock()
    details.model_name = "gpt-4"
    provider.parse_request_details.return_value = details
    # Ensure proxy_request is AsyncMock
    provider.proxy_request = AsyncMock()
    return provider


def setup_provider_config(mock_app_state):
    """Helper to setup the provider config with retry policies."""
    provider_config = MagicMock()
    provider_config.models = {"gpt-4": MagicMock()}

    # Enable Retry
    provider_config.gateway_policy.retry.enabled = True

    # Configure limits to allow 2 attempts for everything
    provider_config.gateway_policy.retry.on_key_error.attempts = 1
    provider_config.gateway_policy.retry.on_server_error.attempts = 1
    provider_config.gateway_policy.retry.on_server_error.backoff_sec = 0.0

    # Provide a real HealthPolicyConfig so _report_key_failure can compute next_check_time
    provider_config.worker_health_policy = HealthPolicyConfig()

    mock_app_state.accessor.get_provider_or_raise.return_value = provider_config
    return provider_config


# --- PARAMETERIZED TEST ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_reason, status_code, expected_penalty, expected_retry",
    [
        # FATAL / CLIENT ERRORS (Should NOT retry, Should NOT penalize key - User fault)
        (ErrorReason.BAD_REQUEST, 400, False, False),
        # ACCESS / KEY ERRORS (Should Penalize Key, but NOT retry with same key)
        # INVALID_KEY: is_fatal=True → key removed + penalty reported, is_retryable=False → no retry
        (ErrorReason.INVALID_KEY, 401, True, False),
        # NO_ACCESS: is_fatal=True → key removed + penalty reported, is_retryable=False → no retry
        (ErrorReason.NO_ACCESS, 403, True, False),
        # NO_QUOTA: is_fatal=True → key removed + penalty reported, is_retryable=False → no retry
        (ErrorReason.NO_QUOTA, 429, True, False),
        # NO_MODEL: is_fatal=True → key removed + penalty reported, is_retryable=False → no retry
        (ErrorReason.NO_MODEL, 404, True, False),
        # SERVER / TRANSIENT ERRORS (is_retryable=True, but attempts=1 → exhausts immediately, no retry)
        # With on_server_error.attempts=1, the first failure exhausts the budget → penalty + no retry
        (ErrorReason.SERVER_ERROR, 500, True, False),
        (ErrorReason.TIMEOUT, 504, True, False),
        # OVERLOADED: is_retryable=True BUT treated as key fault (not reason.is_retryable() OR OVERLOADED)
        # → immediate key rotation + penalty, no retry
        (ErrorReason.OVERLOADED, 503, True, False),
        (ErrorReason.SERVICE_UNAVAILABLE, 503, True, False),
        (ErrorReason.NETWORK_ERROR, 502, True, False),
        # RATE_LIMITED: is_retryable=True but is_fatal=False, NOT is_client_error
        # → goes to Case 3 (key fault: not is_retryable() OR OVERLOADED is False for RATE_LIMITED)
        # Actually RATE_LIMITED is retryable and NOT in the fatal set, so it goes to Case 4
        # With attempts=1 → exhausts immediately → penalty
        (ErrorReason.RATE_LIMITED, 429, True, False),
        # UNKNOWN: is_client_error=True → abort immediately, no penalty, no retry
        (ErrorReason.UNKNOWN, 520, False, False),
    ],
)
async def test_error_behavior_matrix(
    mock_request,
    mock_provider,
    mock_app_state,
    error_reason,
    status_code,
    expected_penalty,
    expected_retry,
):
    """
    Tests how the gateway handles each ErrorReason.
    Captures:
    1. Was the key removed from pool? (Penalty)
    2. Was the DB updated? (Penalty)
    3. Did it retry? (deduced from logs or mock call counts)
    """
    setup_provider_config(mock_app_state)

    # Setup Mock Response
    mock_response = MagicMock(spec=Response)
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.aread = AsyncMock(
        return_value=f"Error: {error_reason.value}".encode()
    )
    mock_response.aclose = AsyncMock()

    # Setup CheckResult
    fail_result = CheckResult.fail(error_reason, "Test Error", status_code)
    mock_provider.proxy_request.return_value = (mock_response, fail_result, None)

    # Execute
    await _handle_buffered_retryable_request(
        mock_request, mock_provider, "test_provider"
    )
    # Allow fire-and-forget tasks (asyncio.create_task) to complete
    await asyncio.sleep(0)

    # Analysis
    db_updated = mock_app_state.db_manager.keys.update_status.called
    key_removed = mock_app_state.gateway_cache.remove_key_from_pool.called  # noqa: F841

    # Heuristic for retry: if proxy_request called > 1 time
    retry_count = mock_provider.proxy_request.call_count - 1
    did_retry = retry_count > 0

    # Report Result for this case
    print(f"\n[MATRIX] {error_reason.name} ({status_code}):")
    print(f"  - Penalty (DB/Cache): {'YES' if db_updated else 'NO'}")
    print(
        f"  - Retried?          : {'YES' if did_retry else 'NO'} ({retry_count} times)"
    )

    # Assert that behavior matches expectations
    assert db_updated == expected_penalty, (
        f"Expected penalty={'YES' if expected_penalty else 'NO'} for {error_reason.name}, "
        f"but got {'YES' if db_updated else 'NO'}"
    )
    assert did_retry == expected_retry, (
        f"Expected retry={'YES' if expected_retry else 'NO'} for {error_reason.name}, "
        f"but got {'YES' if did_retry else 'NO'}"
    )
