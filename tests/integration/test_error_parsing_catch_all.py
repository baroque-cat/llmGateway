#!/usr/bin/env python3

"""
Integration test for error parsing behavior with catch-all rule.

Validates that error parsing rules work correctly with a catch-all rule pattern,
including transparent error forwarding on the last retry attempt and no-op
discard on intermediate attempts when the body has already been read.

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
   Client receives original upstream response (not synthetic 503).
B. Catch-all rule matches (different 400 error) -> maps to server_error.
   Client receives original upstream response (not synthetic 503).
C. Ensure no httpx.StreamClosed crash when retry.enabled = true (partial streaming mode).
D. Catch-all error_parsing rule + retry: on last attempt client gets original
   upstream response (not synthetic 503).
E. Error_parsing on intermediate attempt: body_bytes provided by proxy_request,
   discard() is a no-op (body already read by error parsing).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
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


def create_provider_config_with_catch_all_rule() -> ProviderConfig:
    """Create a provider config with specific catch-all error parsing rules."""
    retry_policy = RetryPolicyConfig(
        enabled=True,
        on_key_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
        on_server_error=RetryOnErrorConfig(attempts=2, backoff_sec=0.1),
    )
    config = ProviderConfig(provider_type="openai_like")
    config.models = {"gpt-4": ModelInfo()}
    config.gateway_policy = GatewayPolicyConfig(retry=retry_policy)

    # Error parsing configuration with specific rule and catch-all rule
    # error_parsing now lives on ProviderConfig (not gateway_policy)
    config.error_parsing = ErrorParsingConfig(
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
    Client receives the original upstream 400 response, not a synthetic 503.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

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

    # proxy_request returns 3-tuple: (response, check_result, body_bytes)
    # body_bytes is populated because error parsing read the body
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.INVALID_KEY,
                "Access denied",
                0.5,
                400,
            ),
            error_body,
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        # Should not raise StreamClosed because body was read (error parsing enabled).
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)
        # Transparent error forwarding: client gets original upstream status code
        assert response.status_code == 400
        # Transparent error forwarding: client gets original upstream body
        assert response.body == error_body


@pytest.mark.asyncio
async def test_catch_all_rule_catch_all_match():
    """
    Scenario B: Specific rule does NOT match, catch-all rule matches -> maps to server_error.
    Client receives the original upstream 400 response, not a synthetic 503.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

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

    # proxy_request returns 3-tuple: (response, check_result, body_bytes)
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.SERVER_ERROR,
                "Some other 400 error",
                0.5,
                400,
            ),
            error_body,
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)
        # Transparent error forwarding: client gets original upstream status code
        assert response.status_code == 400
        # Transparent error forwarding: client gets original upstream body
        assert response.body == error_body


@pytest.mark.asyncio
async def test_no_stream_closed_with_catch_all_rule():
    """
    Scenario C: Ensure no httpx.StreamClosed crash when retry enabled and error parsing configured.
    This is a regression test for the StreamClosed bug.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

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

    # proxy_request returns 3-tuple: (response, check_result, body_bytes)
    provider.proxy_request = AsyncMock(
        return_value=(
            mock_response,
            CheckResult.fail(
                ErrorReason.SERVER_ERROR,
                "Random 400 error",
                0.5,
                400,
            ),
            error_body,
        )
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        # Should not raise httpx.StreamClosed because error parsing is enabled and there is a rule for 400.
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )
        assert isinstance(response, Response)


@pytest.mark.asyncio
async def test_catch_all_rule_with_retry_last_attempt_original_error():
    """
    Scenario D: Catch-all error_parsing rule + retry: on last attempt client gets
    original upstream response (not synthetic 503).

    Flow:
    - Attempt 1: INVALID_KEY (intermediate attempt) → discard, retry with next key
    - Attempt 2: INVALID_KEY (last attempt) → forward original upstream error to client

    The client should receive the original upstream 400 status code and body,
    NOT a synthetic 503 JSON error.
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )

    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = create_provider_config_with_catch_all_rule()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Two different keys for two retry attempts
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
    ]

    # First attempt: INVALID_KEY (intermediate, will be discarded and retried)
    error_body_1 = json.dumps({"error": {"message": "Access denied for key1"}}).encode(
        "utf-8"
    )
    mock_response_1 = create_mock_response(400, error_body_1)

    # Second (last) attempt: INVALID_KEY again (forwarded to client as original error)
    error_body_2 = json.dumps({"error": {"message": "Access denied for key2"}}).encode(
        "utf-8"
    )
    mock_response_2 = create_mock_response(400, error_body_2)

    provider.proxy_request = AsyncMock(
        side_effect=[
            # Attempt 1: intermediate key error → discard, retry
            (
                mock_response_1,
                CheckResult.fail(
                    ErrorReason.INVALID_KEY, "Access denied for key1", 0.5, 400
                ),
                error_body_1,  # body_bytes populated by error parsing
            ),
            # Attempt 2: last key error → forward original upstream error
            (
                mock_response_2,
                CheckResult.fail(
                    ErrorReason.INVALID_KEY, "Access denied for key2", 0.5, 400
                ),
                error_body_2,  # body_bytes populated by error parsing
            ),
        ]
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # Client gets the ORIGINAL upstream response, NOT synthetic 503
    assert response.status_code == 400
    assert response.body == error_body_2
    # Verify it's NOT a synthetic 503 JSON
    assert b"No available API keys" not in response.body


@pytest.mark.asyncio
async def test_error_parsing_intermediate_attempt_discarded():
    """
    Scenario E: Error_parsing on intermediate attempt: body_bytes provided by
    proxy_request (error parsing read the body), discard() is a no-op (body already read).

    When error parsing is enabled and a rule matches the upstream status code,
    proxy_request reads the body via aread() and returns body_bytes populated.
    On an intermediate retry attempt, discard_response() is called with
    body_bytes != None, which means it does NOT call aclose() on the upstream
    response — the stream was already closed by aread(), so discard is a no-op.

    This test verifies:
    1. Directly: discard_response with body_bytes populated → aclose NOT called
    2. Through the full retry flow: intermediate attempt's response.aclose NOT called
    """
    from src.services.gateway.gateway_service import (
        _handle_buffered_retryable_request,  # type: ignore
    )
    from src.services.gateway.response_forwarder import discard_response

    # --- Part 1: Direct test of discard_response no-op ---
    # When body_bytes is populated (error parsing already read the body),
    # discard_response should NOT call aclose on the upstream response.
    mock_resp_direct = MagicMock(spec=httpx.Response)
    mock_resp_direct.aclose = AsyncMock()
    pre_read_body = b'{"error": {"message": "test error"}}'

    await discard_response(mock_resp_direct, pre_read_body)
    # aclose should NOT be called because body_bytes is already populated
    mock_resp_direct.aclose.assert_not_called()

    # Also verify: when body_bytes is None, aclose IS called (the non-no-op path)
    mock_resp_none = MagicMock(spec=httpx.Response)
    mock_resp_none.aclose = AsyncMock()
    await discard_response(mock_resp_none, None)
    mock_resp_none.aclose.assert_called_once()

    # --- Part 2: Integration test through _handle_buffered_retryable_request ---
    req = make_mock_request()
    provider = MagicMock()
    instance_name = "test-provider"

    provider.parse_request_details = AsyncMock()
    provider.parse_request_details.return_value = MagicMock(model_name="gpt-4")

    provider_config = create_provider_config_with_catch_all_rule()
    req.app.state.accessor.get_provider_or_raise.return_value = provider_config

    # Two keys for two retry attempts
    req.app.state.gateway_cache.get_key_from_pool.side_effect = [
        (1, "key1"),
        (2, "key2"),
    ]

    # First attempt: INVALID_KEY with body_bytes populated (error parsing read the body)
    error_body_1 = json.dumps({"error": {"message": "Access denied for key1"}}).encode(
        "utf-8"
    )
    mock_response_1 = create_mock_response(400, error_body_1)

    # Second (last) attempt: INVALID_KEY with body_bytes populated
    error_body_2 = json.dumps({"error": {"message": "Access denied for key2"}}).encode(
        "utf-8"
    )
    mock_response_2 = create_mock_response(400, error_body_2)

    provider.proxy_request = AsyncMock(
        side_effect=[
            # Attempt 1: intermediate key error → discard (no-op since body_bytes populated)
            (
                mock_response_1,
                CheckResult.fail(
                    ErrorReason.INVALID_KEY, "Access denied for key1", 0.5, 400
                ),
                error_body_1,  # body_bytes populated by error parsing
            ),
            # Attempt 2: last key error → forward original upstream error
            (
                mock_response_2,
                CheckResult.fail(
                    ErrorReason.INVALID_KEY, "Access denied for key2", 0.5, 400
                ),
                error_body_2,  # body_bytes populated by error parsing
            ),
        ]
    )

    with patch("asyncio.sleep", side_effect=lambda x: None):  # type: ignore
        response = await _handle_buffered_retryable_request(
            req, provider, instance_name
        )

    # The intermediate attempt's response should NOT have aclose called
    # (discard_response is a no-op when body_bytes is populated)
    mock_response_1.aclose.assert_not_called()

    # The last attempt's response should also NOT have aclose called
    # (forward_error_to_client skips aclose when body_bytes is populated)
    mock_response_2.aclose.assert_not_called()

    # Client gets original upstream response (transparent error forwarding)
    assert isinstance(response, Response)
    assert response.status_code == 400
    assert response.body == error_body_2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
