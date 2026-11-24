#!/usr/bin/env python3

"""
Tests for retry.enabled=false behavior — UT-REN01.

Verifies that when retry.enabled=false, the gateway makes exactly one upstream
attempt and does not retry on server errors.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from src.config.schemas import ModelInfo, RetryOnErrorConfig, RetryPolicyConfig
from src.core.constants import ErrorReason, KeySelectionMode
from src.core.models import CheckResult
from src.services.gateway.gateway_service import _handle_buffered_retryable_request
from tests._canonical import CanonicalConfig


def _make_mock_request_with_retry_disabled() -> MagicMock:
    """Create a mock FastAPI Request with retry.enabled=false."""
    request = MagicMock()
    request.method = "POST"
    request.url = MagicMock()
    request.url.path = "/v1/chat/completions"
    request.url.query = ""
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    canonical_model = CanonicalConfig.from_example_files().canonical_model_names[0]
    request.body = AsyncMock(
        return_value=f'{{"model": "{canonical_model}", "messages": []}}'.encode()
    )

    # Build app.state with all required dependencies
    mock_cache = MagicMock()
    mock_cache.get_key_from_pool = Mock(return_value=(1, "sk-test-key"))
    mock_cache.remove_key_from_pool = AsyncMock()

    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(
        return_value=MagicMock(spec=httpx.AsyncClient)
    )

    mock_db_manager = MagicMock()

    mock_accessor = MagicMock()
    # Provider config with retry.enabled=false
    mock_provider_config = MagicMock()
    mock_provider_config.default_model = {
        CanonicalConfig.from_example_files().canonical_model_names[0]: ModelInfo()
    }
    mock_provider_config.gateway_policy = MagicMock()

    # Retry policy with enabled=false but with actual integer attempts (will be zeroed)
    retry_policy = RetryPolicyConfig(
        enabled=False,  # KEY: retry disabled
        on_key_error=RetryOnErrorConfig(
            attempts=3, backoff_sec=0.1, backoff_factor=1.0
        ),
        on_server_error=RetryOnErrorConfig(
            attempts=3, backoff_sec=0.1, backoff_factor=1.0
        ),
        on_transport_error=RetryOnErrorConfig(
            attempts=3, backoff_sec=0.1, backoff_factor=1.0
        ),
    )

    mock_provider_config.gateway_policy.retry = retry_policy
    mock_provider_config.gateway_policy.streaming_mode = "auto"
    mock_provider_config.gateway_policy.debug_mode = "disabled"
    mock_provider_config.gateway_policy.key_selection = MagicMock()
    mock_provider_config.gateway_policy.key_selection.mode = (
        KeySelectionMode.ROUND_ROBIN
    )
    mock_accessor.get_provider_or_raise = Mock(return_value=mock_provider_config)
    mock_accessor.get_provider = Mock(return_value=mock_provider_config)
    mock_accessor.get_enabled_providers = Mock(return_value={})

    request.app = MagicMock()
    request.app.state.gateway_cache = mock_cache
    request.app.state.http_client_factory = mock_http_factory
    request.app.state.db_manager = mock_db_manager
    request.app.state.accessor = mock_accessor
    request.app.state.debug_mode_map = {"openai": "disabled"}
    request.app.state.full_stream_instances = set()

    return request


def _make_mock_provider() -> AsyncMock:
    """Create a mock IProvider."""
    provider = AsyncMock()
    provider.proxy_request = AsyncMock()
    provider.parse_request_details = AsyncMock(return_value=MagicMock())
    provider.name = "openai"
    return provider


# ---------------------------------------------------------------------------
# UT-REN01 — retry.enabled=false makes exactly one upstream attempt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_disabled_makes_exactly_one_attempt() -> None:
    """UT-REN01: When retry.enabled=false, exactly one upstream attempt is made.

    Even when the first attempt returns a server error (5xx), no retry occurs.
    """
    req = _make_mock_request_with_retry_disabled()
    provider = _make_mock_provider()
    instance_name = "openai"

    # First attempt: server error (503)
    response_503 = MagicMock()
    response_503.status_code = 503
    response_503.headers = {}
    response_503.aclose = AsyncMock()
    response_503.aread = AsyncMock(return_value=b'{"error": "Service unavailable"}')

    provider.proxy_request = AsyncMock(
        return_value=(
            response_503,
            CheckResult.fail(ErrorReason.SERVER_ERROR, "Service unavailable"),
            None,
        )
    )

    with patch(
        "src.services.gateway.gateway_service.observe_upstream_attempt",
        new=MagicMock(),
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify exactly one call to proxy_request (no retries)
    assert provider.proxy_request.await_count == 1

    # Verify the error response is forwarded
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_retry_disabled_does_not_retry_on_timeout() -> None:
    """UT-REN01: When retry.enabled=false, timeout errors are not retried."""
    req = _make_mock_request_with_retry_disabled()
    provider = _make_mock_provider()
    instance_name = "openai"

    # First attempt: timeout error
    response_timeout = MagicMock()
    response_timeout.status_code = 504
    response_timeout.headers = {}
    response_timeout.aclose = AsyncMock()
    response_timeout.aread = AsyncMock(return_value=b'{"error": "Timeout"}')

    provider.proxy_request = AsyncMock(
        return_value=(
            response_timeout,
            CheckResult.fail(ErrorReason.TIMEOUT, "Timeout"),
            None,
        )
    )

    with patch(
        "src.services.gateway.gateway_service.observe_upstream_attempt",
        new=MagicMock(),
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify exactly one call to proxy_request (no retries)
    assert provider.proxy_request.await_count == 1

    # Verify the timeout response is forwarded
    assert response.status_code == 504
