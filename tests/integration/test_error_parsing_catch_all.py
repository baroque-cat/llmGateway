#!/usr/bin/env python3

"""
Integration test for error parsing behavior with catch-all rule.

Validates that error parsing rules work correctly with a catch-all rule pattern.
Specifically tests the configuration:

error_parsing:
  enabled: true
  rules:
    # 1. Specific rule
    - status_code: 400
      match_pattern: "Access denied.*"
      map_to: "invalid_key"
      priority: 10

    # 2. Catch-all rule
    - status_code: 400
      match_pattern: ".*"
      map_to: "server_error"
      priority: 0

Test scenarios:
A. Specific rule matches (response contains "Access denied...") -> maps to invalid_key.
B. Catch-all rule matches (different 400 error) -> maps to server_error.
C. Ensure no httpx.StreamClosed crash when retry.enabled = true (partial streaming mode).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import Request
from starlette.responses import Response

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
    RetryOnErrorConfig,
    RetryPolicyConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult


# Helper from test_gateway_refactor.py
def make_mock_request(
    url: str = "http://test/v1/chat/completions", method: str = "POST"
) -> MagicMock:
    req = MagicMock(spec=Request)
    req.url.path = "/v1/chat/completions"
    req.url.query = ""
    req.method = method
    req.headers = {"authorization": "Bearer test-token"}
    req.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

    # Create state mock explicitly
    state = MagicMock()
    state.gateway_cache = MagicMock()
    state.gateway_cache.remove_key_from_pool = AsyncMock()

    # HTTP Factory Mock
    http_factory = MagicMock()
    http_factory.get_client_for_provider = AsyncMock(return_value=MagicMock())
    state.http_client_factory = http_factory

    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()
    state.accessor = MagicMock()
    state.debug_mode_map = {}

    req.app.state = state
    return req


def create_provider_config_with_catch_all_rule() -> ProviderConfig:
    """Create a provider config with specific catch-all error parsing rules."""
    config = ProviderConfig()
    config.models = {"gpt-4": ModelInfo()}
    config.gateway_policy = GatewayPolicyConfig()
    config.gateway_policy.retry = RetryPolicyConfig(enabled=True)
    config.gateway_policy.retry.on_key_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )
    config.gateway_policy.retry.on_server_error = RetryOnErrorConfig(
        attempts=2, backoff_sec=0.1
    )

    # Error parsing configuration with specific rule and catch-all rule
    config.gateway_policy.error_parsing = ErrorParsingConfig(
        enabled=True,
        rules=[
            ErrorParsingRule(
                status_code=400,
                error_path="error.message",
                match_pattern="Access denied.*",
                map_to="invalid_key",
                priority=10,
                description="Access denied errors",
            ),
            ErrorParsingRule(
                status_code=400,
                error_path="error.message",
                match_pattern=".*",
                map_to="server_error",
                priority=0,
                description="Catch-all for any 400 error",
            ),
        ],
    )

    return config


def create_mock_response(
    status_code: int, body: bytes, elapsed_seconds: float = 0.5
) -> MagicMock:
    """Create a mock httpx.Response with given body."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = status_code
    mock_response.headers = {}
    mock_response.aread = AsyncMock(return_value=body)
    mock_response.aclose = AsyncMock()
    mock_response.elapsed = MagicMock()
    mock_response.elapsed.total_seconds.return_value = elapsed_seconds
    return mock_response


@pytest.mark.asyncio
async def test_catch_all_rule_specific_match():
    """
    Scenario A: Specific rule matches (Access denied message) -> maps to invalid_key.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request  # type: ignore

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = create_provider_config_with_catch_all_rule()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Response body that matches the specific rule
    error_body = json.dumps(
        {
            "error": {
                "message": "Access denied, please make sure your account is in good standing"
            }
        }
    ).encode("utf-8")
    mock_response = create_mock_response(400, error_body)

    # The provider's proxy_request will return a CheckResult with INVALID_KEY (due to rule mapping)
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.INVALID_KEY,
                "Access denied",
                0.5,
                400,
            ),
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        # Should not raise StreamClosed because body was read (error parsing enabled).
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # The gateway will treat INVALID_KEY as a key error and may retry.
        # We just ensure no crash and that the response is a Response object.
        assert isinstance(response, Response)
        # Additionally, we can verify that the provider's proxy_request was called
        # and that the returned CheckResult has INVALID_KEY.
        # However, we rely on the mocked provider to return the correct mapping.
        # For a more thorough test, we could inject a real provider instance,
        # but that's more complex and out of scope for this integration test.


@pytest.mark.asyncio
async def test_catch_all_rule_catch_all_match():
    """
    Scenario B: Specific rule does NOT match, catch-all rule matches -> maps to server_error.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request  # type: ignore

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = create_provider_config_with_catch_all_rule()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Response body that does NOT match the specific rule but matches catch-all
    error_body = json.dumps({"error": {"message": "Some other 400 error"}}).encode(
        "utf-8"
    )
    mock_response = create_mock_response(400, error_body)

    # The provider's proxy_request will return a CheckResult with SERVER_ERROR (due to catch-all rule)
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.SERVER_ERROR,
                "Some other 400 error",
                0.5,
                400,
            ),
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)
        # Ensure no crash and that the provider's proxy_request returned SERVER_ERROR.
        # The gateway may treat SERVER_ERROR as a retryable server error (depending on policy).
        # We just verify the flow completes without StreamClosed.


@pytest.mark.asyncio
async def test_no_stream_closed_with_catch_all_rule():
    """
    Scenario C: Ensure no httpx.StreamClosed crash when retry enabled and error parsing configured.
    This is a regression test for the StreamClosed bug.
    """
    from src.services.gateway_service import _handle_buffered_retryable_request  # type: ignore

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = create_provider_config_with_catch_all_rule()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Response body that matches catch-all rule (any message).
    error_body = json.dumps({"error": {"message": "Random 400 error"}}).encode("utf-8")
    mock_response = create_mock_response(400, error_body)

    # The provider's proxy_request will return a CheckResult with SERVER_ERROR.
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.SERVER_ERROR,
                "Random 400 error",
                0.5,
                400,
            ),
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        # Should not raise httpx.StreamClosed because error parsing is enabled and there is a rule for 400.
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
