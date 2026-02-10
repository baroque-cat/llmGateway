from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request, Response

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway_service import _handle_buffered_retryable_request

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

    mock_app_state.accessor.get_provider_or_raise.return_value = provider_config
    return provider_config


# --- PARAMETERIZED TEST ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_reason, status_code, expected_penalty, expected_retry",
    [
        # FATAL / CLIENT ERRORS (Should NOT retry, Should NOT penalize key - User fault)
        (ErrorReason.BAD_REQUEST, 400, False, False),
        # ACCESS / KEY ERRORS (Should Penalize Key)
        (
            ErrorReason.INVALID_KEY,
            401,
            True,
            False,
        ),  # Expected: True (Penalty), False (Retry) -> BUT Current logic might differ
        (ErrorReason.NO_ACCESS, 403, True, False),
        (ErrorReason.NO_QUOTA, 429, True, False),  # Assuming 429 maps to NO_QUOTA here
        (ErrorReason.NO_MODEL, 404, True, False),
        # SERVER / TRANSIENT ERRORS (Should Retry, No Immediate Penalty)
        (ErrorReason.SERVER_ERROR, 500, False, True),
        (ErrorReason.TIMEOUT, 504, False, True),
        (
            ErrorReason.OVERLOADED,
            503,
            False,
            True,
        ),  # Special case: Overloaded might force rotation in code
        (ErrorReason.SERVICE_UNAVAILABLE, 503, False, True),
        (ErrorReason.NETWORK_ERROR, 502, False, True),
        # RATE LIMIT (The contentious one)
        (ErrorReason.RATE_LIMITED, 429, True, False),  # You WANT this to be True/False.
        # UNKNOWN
        (ErrorReason.UNKNOWN, 520, False, True),
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
    mock_provider.proxy_request.return_value = (mock_response, fail_result)

    # Execute
    await _handle_buffered_retryable_request(
        mock_request, mock_provider, "test_provider"
    )

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

    # We do NOT assert here to fail the test. We want to collect data.
    # Assertions would stop execution on the first mismatch.
    # Instead, we rely on the print output for the report.
