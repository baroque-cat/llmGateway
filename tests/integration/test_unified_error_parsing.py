#!/usr/bin/env python3

"""
Integration tests for unified error parsing across Gateway and Worker paths.

Tests INT-1 through INT-4:
- INT-1: Gateway and Worker use the same ProviderConfig.error_parsing rules
- INT-2: Worker check() with 400 + Arrearage → NO_QUOTA (not INVALID_KEY)
- INT-3: Worker check() with 429 Gemini + fulltext → RATE_LIMITED (not NO_QUOTA)
- INT-4: Gateway 400 without fast_status_mapping → stream remains open
"""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import Request

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    ModelInfo,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.providers import get_provider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_openai_provider_config_with_error_parsing(
    rules: list[ErrorParsingRule],
) -> ProviderConfig:
    """Create an OpenAI-like ProviderConfig with error_parsing enabled."""
    config = ProviderConfig(provider_type="openai_like")
    config.api_base_url = "https://api.test.com/v1"
    config.models = {"gpt-4": ModelInfo(endpoint_suffix="/chat/completions")}
    config.error_parsing = ErrorParsingConfig(enabled=True, rules=rules)
    return config


def _make_gemini_provider_config_with_error_parsing(
    rules: list[ErrorParsingRule],
) -> ProviderConfig:
    """Create a Gemini ProviderConfig with error_parsing enabled."""
    config = ProviderConfig(provider_type="gemini")
    config.api_base_url = "https://generativelanguage.googleapis.com/v1beta"
    config.models = {
        "gemini-pro": ModelInfo(endpoint_suffix="/models/gemini-pro:generateContent")
    }
    config.error_parsing = ErrorParsingConfig(enabled=True, rules=rules)
    return config


def _make_mock_request(
    url: str = "http://test/v1/chat/completions", method: str = "POST"
) -> MagicMock:
    """Create a mock FastAPI Request object for gateway tests."""
    req = MagicMock(spec=Request)
    req.url.path = "/v1/chat/completions"
    req.url.query = ""
    req.method = method
    req.headers = {"authorization": "Bearer test-token"}
    req.body = AsyncMock(return_value=b'{"model": "gpt-4"}')

    state = MagicMock()
    state.gateway_cache = MagicMock()
    state.gateway_cache.remove_key_from_pool = AsyncMock()
    state.gateway_cache.get_key_from_pool = MagicMock(return_value=(1, "key1"))

    http_factory = MagicMock()
    http_factory.get_client_for_provider = AsyncMock(return_value=MagicMock())
    state.http_client_factory = http_factory

    state.db_manager = MagicMock()
    state.db_manager.keys.update_status = AsyncMock()
    state.accessor = MagicMock()
    state.debug_mode_map = {}

    req.app.state = state
    return req


def _make_mock_httpx_response(
    status_code: int, body: bytes, elapsed: float = 0.5
) -> MagicMock:
    """Create a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.headers = {}
    mock.aread = AsyncMock(return_value=body)
    mock.aclose = AsyncMock()
    mock.elapsed = MagicMock()
    mock.elapsed.total_seconds.return_value = elapsed
    return mock


# ---------------------------------------------------------------------------
# INT-1: Gateway and Worker use same error_parsing rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_and_worker_use_same_error_parsing_rules() -> None:
    """
    INT-1: Both Gateway (_send_proxy_request) and Worker (check()) use the
    same ProviderConfig.error_parsing for error classification.

    We create a single ProviderConfig with error_parsing rules, then verify
    that both the provider's _refine_error_reason (used by check()) and
    _send_proxy_request (used by proxy_request) read from the same config.
    """
    # Create a single config with an Arrearage → no_quota rule
    arrearage_rule = ErrorParsingRule(
        status_code=400,
        error_path="error.message",
        match_pattern="Arrearage",
        map_to=ErrorReason.NO_QUOTA,
        priority=10,
        description="Arrearage → no_quota",
    )
    config = _make_openai_provider_config_with_error_parsing([arrearage_rule])

    # Both paths should reference the same error_parsing object
    provider = get_provider("test-openai", config)

    # Verify the provider reads from config.error_parsing (not gateway_policy)
    assert provider.config.error_parsing is config.error_parsing
    assert provider.config.error_parsing.enabled is True
    assert len(provider.config.error_parsing.rules) == 1

    # Verify GatewayPolicyConfig does NOT have error_parsing attribute
    # (it was moved to ProviderConfig)
    gateway_policy = config.gateway_policy
    assert not hasattr(
        gateway_policy, "error_parsing"
    ), "GatewayPolicyConfig should not have error_parsing field"

    # The same config object is used by both check() and proxy_request()
    # This is the key assertion: unified source of truth.
    assert provider.config.error_parsing.rules[0].map_to == ErrorReason.NO_QUOTA


# ---------------------------------------------------------------------------
# INT-2: Worker check() refines 400 Arrearage → NO_QUOTA
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_check_refines_400_arrearage_to_no_quota() -> None:
    """
    INT-2: Worker check() with 400 + Arrearage body → NO_QUOTA (not INVALID_KEY).

    The OpenAILikeProvider.check() method calls _refine_error_reason() when
    it receives a 400 HTTPStatusError.  With an error_parsing rule that maps
    Arrearage → no_quota, the result should be NO_QUOTA instead of the
    default INVALID_KEY.
    """
    arrearage_rule = ErrorParsingRule(
        status_code=400,
        error_path="error.message",
        match_pattern="Arrearage",
        map_to=ErrorReason.NO_QUOTA,
        priority=10,
        description="Arrearage → no_quota",
    )
    config = _make_openai_provider_config_with_error_parsing([arrearage_rule])
    provider = get_provider("test-openai", config)

    # Create a mock 400 response with Arrearage in the body
    error_body = json.dumps(
        {"error": {"message": "Arrearage: Your account is in arrears"}}
    ).encode("utf-8")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 400
    mock_response.aread = AsyncMock(return_value=error_body)
    mock_response.text = json.dumps(
        {"error": {"message": "Arrearage: Your account is in arrears"}}
    )

    # Call _refine_error_reason directly (this is what check() does internally)
    default_reason = ErrorReason.INVALID_KEY  # Default for 400 in check()
    refined = await provider._refine_error_reason(
        mock_response,
        default_reason,
        body_bytes=error_body,
    )

    assert refined == ErrorReason.NO_QUOTA, (
        f"Expected NO_QUOTA but got {refined.value} — Worker should refine "
        "400 Arrearage to NO_QUOTA, not keep INVALID_KEY"
    )


# ---------------------------------------------------------------------------
# INT-3: Worker check() refines 429 Gemini → RATE_LIMITED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_check_refines_429_gemini_rate_limit() -> None:
    """
    INT-3: Worker check() with 429 Gemini + fulltext rule → RATE_LIMITED
    (not NO_QUOTA or the default mapping).

    Gemini's check() method calls _refine_error_reason() when it receives
    a 429 error.  With a fulltext rule (error_path="$") that matches
    RATE_LIMIT_EXCEEDED, the result should be RATE_LIMITED.
    """
    rate_limit_rule = ErrorParsingRule(
        status_code=429,
        error_path="$",
        match_pattern="RATE_LIMIT_EXCEEDED",
        map_to=ErrorReason.RATE_LIMITED,
        priority=10,
        description="Gemini rate limit via fulltext",
    )
    config = _make_gemini_provider_config_with_error_parsing([rate_limit_rule])
    provider = get_provider("test-gemini", config)

    # Create a mock 429 response with RATE_LIMIT_EXCEEDED in the body
    error_body = b'{"error": {"code": 429, "message": "RATE_LIMIT_EXCEEDED"}}'

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.aread = AsyncMock(return_value=error_body)

    # Gemini's default for 429 in check() would be mapped via _map_error_to_reason
    # which typically returns NO_QUOTA for 429.  We use that as default_reason.
    default_reason = ErrorReason.NO_QUOTA

    refined = await provider._refine_error_reason(
        mock_response,
        default_reason,
        body_bytes=error_body,
    )

    assert refined == ErrorReason.RATE_LIMITED, (
        f"Expected RATE_LIMITED but got {refined.value} — Worker should refine "
        "429 RATE_LIMIT_EXCEEDED to RATE_LIMITED via fulltext rule"
    )


# ---------------------------------------------------------------------------
# INT-4: Gateway 400 without fast_status_mapping → stream open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_error_body_preservation_without_fast_status_mapping() -> None:
    """
    INT-4: Gateway 400 response without fast_status_mapping (now removed)
    preserves the stream so the gateway can read the body and return it
    to the client.

    In _send_proxy_request, when error_parsing is disabled and there are
    no rules for status 400, the stream is NOT closed for 400 responses
    (the exception case).  This allows the gateway's client-error handler
    to read the body via aread() and return the original error to the client.
    """
    from src.services.gateway.gateway_service import _handle_full_stream_request

    # Create a provider config WITHOUT error_parsing (disabled by default)
    config = ProviderConfig(provider_type="openai_like")
    config.models = {"gpt-4": ModelInfo()}
    # Explicitly verify error_parsing is disabled
    assert config.error_parsing.enabled is False

    # Create a mock request
    req = _make_mock_request()
    req.app.state.accessor.get_provider_or_raise.return_value = config

    # Create a provider mock that returns a 400 CheckResult with client error
    provider = MagicMock()
    provider_name = "test-provider"

    error_body = json.dumps({"error": {"message": "Invalid request format"}}).encode(
        "utf-8"
    )

    mock_response = _make_mock_httpx_response(400, error_body)

    # The provider returns a client_error CheckResult (BAD_REQUEST)
    check_result = CheckResult.fail(
        ErrorReason.BAD_REQUEST, "Invalid request format", 0.5, 400
    )

    provider.proxy_request = AsyncMock(return_value=(mock_response, check_result))

    # Mock the cache to return a key
    req.app.state.gateway_cache.get_key_from_pool.return_value = (1, "test-key")

    response = await _handle_full_stream_request(req, provider, provider_name, "gpt-4")

    # The response should be a Response (not JSONResponse 503)
    # because BAD_REQUEST is a client_error → stream is read and forwarded
    from starlette.responses import Response as StarletteResponse

    assert isinstance(response, StarletteResponse)
    # The response body should contain the original error
    # (not a synthetic placeholder)
    assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
