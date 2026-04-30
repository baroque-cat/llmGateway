#!/usr/bin/env python3

"""
Integration test for the StreamClosed bug (now fixed).

Verifies that:
1. A provider returns a 400 error with a body.
2. The gateway has retry.enabled: true.
3. The error_parsing config either doesn't exist for status 400, or has rules that don't match the response body.
4. The default error mapping for 400 is bad_request (a client error).

After the fix: The base provider does NOT close the HTTP stream for 400 without matching rules,
so the gateway can read the body via aread() and return the original provider error to the client,
instead of a synthetic placeholder like "Upstream error: bad_request".
"""

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


def create_provider_config(
    retry_enabled: bool = True,
    error_parsing_enabled: bool = True,
    error_parsing_rule_for_400: bool = False,
    rule_matches: bool = False,
) -> ProviderConfig:
    """Create a provider config with specific error parsing settings."""
    config = ProviderConfig(provider_type="openai_like")
    config.models = {"gpt-4": ModelInfo()}
    config.gateway_policy = GatewayPolicyConfig()
    if retry_enabled:
        config.gateway_policy.retry = RetryPolicyConfig(
            enabled=True,
            on_key_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
            on_server_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
        )
    else:
        config.gateway_policy.retry = RetryPolicyConfig(enabled=False)

    if error_parsing_enabled:
        rules: list[ErrorParsingRule] = []
        if error_parsing_rule_for_400:
            # Create a rule that either matches or doesn't match the response body
            pattern = "Access denied" if rule_matches else "SomethingElse"
            rules.append(
                ErrorParsingRule(
                    status_code=400,
                    error_path="error.message",
                    match_pattern=pattern,
                    map_to="invalid_key",
                    priority=10,
                )
            )
        config.error_parsing = ErrorParsingConfig(enabled=True, rules=rules)
    else:
        config.error_parsing = ErrorParsingConfig(enabled=False, rules=[])

    return config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_parsing_enabled,error_parsing_rule_for_400",
    [
        (True, False),  # error parsing enabled but no rule for 400
        (False, False),  # error parsing disabled
        (True, True),  # rule exists but does not match (rule_matches=False)
    ],
)
async def test_stream_closed_bug(
    error_parsing_enabled: bool,
    error_parsing_rule_for_400: bool,
):
    """
    Verify that when a provider returns 400 with body, retry enabled,
    and error parsing config does not match, the gateway preserves the
    original error body and returns it to the client (not a synthetic placeholder).

    After the fix in _send_proxy_request: for 400 without matching rules,
    the stream is NOT closed, so aread() succeeds and returns the original body.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    # Setup provider parse_request_details
    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Create provider config with retry enabled and error parsing as parameterized.
    provider_config = create_provider_config(
        retry_enabled=True,
        error_parsing_enabled=error_parsing_enabled,
        error_parsing_rule_for_400=error_parsing_rule_for_400,
        rule_matches=False,  # rule does NOT match response body
    )
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Create a mock response with 400 status and a body.
    # After the fix: for 400 without matching rules, the stream is preserved (not closed),
    # so aread() succeeds and returns the original provider error body.
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.headers = {}
    # Mock aread to return the original provider error body (stream is open after fix)
    provider_error_body = b'{"error":{"message":"provider specific error"}}'
    mock_response.aread = AsyncMock(return_value=provider_error_body)
    mock_response.aclose = AsyncMock()
    # Mock elapsed to avoid RuntimeError
    mock_response.elapsed = MagicMock()
    mock_response.elapsed.total_seconds.return_value = 0.5

    # The provider's proxy_request will return this response along with a CheckResult
    # that indicates BAD_REQUEST (client error).
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.BAD_REQUEST,
                "Bad request",
                0.5,
                400,
            ),
        )
    )

    # Mock asyncio.sleep to avoid actual delays
    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        # After the fix: the stream is open for 400, aread() succeeds,
        # so the handler returns the original provider error body (not a synthetic placeholder).
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)
        # The response should have a status code of 400 (client error)
        assert response.status_code == 400
        # The response body should contain the original provider error message,
        # NOT the synthetic placeholder "Upstream error: bad_request"
        response_body = response.body
        assert b"provider specific error" in response_body
        assert b"Upstream error" not in response_body


@pytest.mark.asyncio
async def test_no_bug_when_error_parsing_rule_matches():
    """
    When error parsing rule matches the response body, the provider reads the body,
    so the stream is not closed. This scenario should work without StreamClosed.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    # Config with rule that matches the response body
    provider_config = create_provider_config(
        retry_enabled=True,
        error_parsing_enabled=True,
        error_parsing_rule_for_400=True,
        rule_matches=True,
    )
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "key1")

    # Create a mock response with body that matches the rule.
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.headers = {}
    # Since the rule matches, the provider will read the body, so aread returns bytes.
    mock_response.aread = AsyncMock(
        return_value=b'{"error": {"message": "Access denied, please make sure your account is in good standing"}}'
    )
    mock_response.aclose = AsyncMock()
    mock_response.elapsed = MagicMock()
    mock_response.elapsed.total_seconds.return_value = 0.5

    # The provider's proxy_request will return a CheckResult with INVALID_KEY (due to rule mapping)
    # but we can still simulate BAD_REQUEST for simplicity.
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
        # Should not raise StreamClosed because body was read.
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        # The gateway will treat INVALID_KEY as a key error (not client error) and may retry.
        # We just ensure no crash.
        assert isinstance(response, Response)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
