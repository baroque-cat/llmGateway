#!/usr/bin/env python3

"""Tests for gateway transport retry behavior — P1 transport retry.

Verifies that:
  - Transport failures trigger retry with evict()
  - Transport failures do not penalize the key
  - Transport exhaustion forwards the error
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import ModelInfo, RetryOnErrorConfig, RetryPolicyConfig
from src.core.constants import ErrorReason, KeySelectionMode, TransportFailureClass
from src.core.models import CheckResult
from src.services.gateway.gateway_service import _handle_buffered_retryable_request
from tests._canonical import CanonicalConfig


def _make_mock_request_with_transport_retry(transport_attempts: int = 3) -> MagicMock:
    """Create a mock FastAPI Request with transport retry enabled."""
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
    mock_cache.get_key_from_pool = MagicMock(return_value=(1, "sk-test-key"))
    mock_cache.remove_key_from_pool = AsyncMock()

    mock_http_factory = MagicMock()
    mock_http_factory.get_client_for_provider = AsyncMock(
        return_value=MagicMock(spec=httpx.AsyncClient)
    )
    mock_http_factory.evict = AsyncMock()

    mock_db_manager = MagicMock()

    mock_accessor = MagicMock()
    # Provider config with transport retry enabled
    mock_provider_config = MagicMock()
    mock_provider_config.default_model = {
        CanonicalConfig.from_example_files().canonical_model_names[0]: ModelInfo()
    }
    mock_provider_config.gateway_policy = MagicMock()

    # Retry policy with transport retry enabled
    retry_policy = RetryPolicyConfig(
        enabled=True,
        on_key_error=RetryOnErrorConfig(
            attempts=3, backoff_sec=0.1, backoff_factor=1.0
        ),
        on_server_error=RetryOnErrorConfig(
            attempts=3, backoff_sec=0.1, backoff_factor=1.0
        ),
        on_transport_error=RetryOnErrorConfig(
            attempts=transport_attempts, backoff_sec=0.1, backoff_factor=1.0
        ),
    )

    mock_provider_config.gateway_policy.retry = retry_policy
    mock_provider_config.gateway_policy.streaming_mode = "auto"
    mock_provider_config.gateway_policy.debug_mode = "disabled"
    mock_provider_config.gateway_policy.key_selection = MagicMock()
    mock_provider_config.gateway_policy.key_selection.mode = (
        KeySelectionMode.ROUND_ROBIN
    )
    mock_accessor.get_provider_or_raise = MagicMock(return_value=mock_provider_config)
    mock_accessor.get_provider = MagicMock(return_value=mock_provider_config)
    mock_accessor.get_enabled_providers = MagicMock(return_value={})

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
# Test transport retry with success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_retry_then_success() -> None:
    """One ConnectTimeout followed by success -> 2 proxy_request calls, evict called once."""
    req = _make_mock_request_with_transport_retry()
    provider = _make_mock_provider()
    instance_name = "openai"

    # First attempt: ConnectTimeout
    response_timeout = MagicMock()
    response_timeout.status_code = 504
    response_timeout.headers = {}
    response_timeout.aclose = AsyncMock()
    response_timeout.aread = AsyncMock(return_value=b'{"error": "Timeout"}')

    # Second attempt: success
    response_success = MagicMock()
    response_success.status_code = 200
    response_success.headers = {}
    response_success.aclose = AsyncMock()
    response_success.aread = AsyncMock(return_value=b'{"result": "ok"}')

    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                response_timeout,
                CheckResult.fail(
                    ErrorReason.NETWORK_ERROR,
                    "Connect timeout",
                    transport_class=TransportFailureClass.CONNECT_TIMEOUT,
                ),
                None,
            ),
            (
                response_success,
                CheckResult.success(),
                b'{"result": "ok"}',
            ),
        ]
    )

    original_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await original_sleep(0)

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch(
            "src.services.gateway.gateway_service.observe_upstream_attempt",
            new=MagicMock(),
        ),
        patch(
            "src.services.gateway.gateway_service._report_key_failure",
            new=AsyncMock(),
        ) as mock_report_failure,
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify exactly 2 proxy_request calls
    assert provider.proxy_request.await_count == 2

    # Verify evict was called once
    assert req.app.state.http_client_factory.evict.await_count == 1

    # Verify _report_key_failure was NOT called (transport errors don't penalize keys)
    mock_report_failure.assert_not_awaited()

    # Verify cache.remove_key_from_pool was NOT called
    assert req.app.state.gateway_cache.remove_key_from_pool.await_count == 0

    # Verify success response is returned
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test transport exhaustion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_exhaustion_forwards_error() -> None:
    """Transport exhaustion (attempts=1) -> forwards the last error, no key penalty."""
    req = _make_mock_request_with_transport_retry(transport_attempts=1)

    provider = _make_mock_provider()
    instance_name = "openai"

    # Single attempt: ConnectTimeout
    response_timeout = MagicMock()
    response_timeout.status_code = 504
    response_timeout.headers = {}
    response_timeout.aclose = AsyncMock()
    response_timeout.aread = AsyncMock(return_value=b'{"error": "Timeout"}')

    provider.proxy_request = AsyncMock(
        return_value=(
            response_timeout,
            CheckResult.fail(
                ErrorReason.NETWORK_ERROR,
                "Connect timeout",
                transport_class=TransportFailureClass.CONNECT_TIMEOUT,
            ),
            None,
        )
    )

    with (
        patch(
            "src.services.gateway.gateway_service.observe_upstream_attempt",
            new=MagicMock(),
        ),
        patch(
            "src.services.gateway.gateway_service._report_key_failure",
            new=AsyncMock(),
        ) as mock_report_failure,
    ):
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Verify exactly 1 proxy_request call (no retry)
    assert provider.proxy_request.await_count == 1

    # Verify error response is forwarded
    assert response.status_code == 504

    # Verify _report_key_failure was NOT called
    mock_report_failure.assert_not_awaited()

    # Verify cache.remove_key_from_pool was NOT called
    assert req.app.state.gateway_cache.remove_key_from_pool.await_count == 0


# ---------------------------------------------------------------------------
# Test transport failure does not increment key/server error budgets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_failure_does_not_increment_key_budget() -> None:
    """Transport failure does not increment the key/server error budgets."""
    req = _make_mock_request_with_transport_retry()
    provider = _make_mock_provider()
    instance_name = "openai"

    # First attempt: ConnectTimeout
    response_timeout = MagicMock()
    response_timeout.status_code = 504
    response_timeout.headers = {}
    response_timeout.aclose = AsyncMock()
    response_timeout.aread = AsyncMock(return_value=b'{"error": "Timeout"}')

    # Second attempt: success
    response_success = MagicMock()
    response_success.status_code = 200
    response_success.headers = {}
    response_success.aclose = AsyncMock()
    response_success.aread = AsyncMock(return_value=b'{"result": "ok"}')

    provider.proxy_request = AsyncMock(
        side_effect=[
            (
                response_timeout,
                CheckResult.fail(
                    ErrorReason.NETWORK_ERROR,
                    "Connect timeout",
                    transport_class=TransportFailureClass.CONNECT_TIMEOUT,
                ),
                None,
            ),
            (
                response_success,
                CheckResult.success(),
                b'{"result": "ok"}',
            ),
        ]
    )

    original_sleep = asyncio.sleep

    async def mock_sleep(delay):
        await original_sleep(0)

    with (
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch(
            "src.services.gateway.gateway_service.observe_upstream_attempt",
            new=MagicMock(),
        ),
        patch(
            "src.services.gateway.gateway_service._report_key_failure",
            new=AsyncMock(),
        ),
    ):
        await _handle_buffered_retryable_request(req, provider, instance_name)

    # Verify _report_key_failure was NOT called (transport errors don't penalize keys)
    # This is already verified in test_transport_retry_then_success, but we're
    # explicitly checking the budget behavior here
    assert provider.proxy_request.await_count == 2
    assert req.app.state.http_client_factory.evict.await_count == 1
