#!/usr/bin/env python3

"""
Tests for Anthropic provider core functionality.

This module tests the core functionality of the Anthropic provider implementation,
including header construction, request parsing, and error mapping.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import RequestDetails
from src.providers.impl.anthropic import AnthropicProvider


class TestAnthropicProvider:
    """Test suite for Anthropic provider core functionality."""

    def create_mock_provider(self, error_config=None):
        """Helper to create a mock AnthropicProvider with given error parsing configuration."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)

        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])

        mock_config.error_parsing = error_config

        # Set up other required config fields
        mock_config.provider_type = "anthropic"
        mock_config.api_base_url = "https://api.anthropic.com/v1"
        mock_config.default_model = "claude-3-opus-20240229"
        mock_config.models = {}
        mock_config.access_control = MagicMock()
        mock_config.access_control.gateway_access_token = "test_token"
        mock_config.health_policy = MagicMock()
        mock_config.proxy_config = MagicMock()
        mock_config.proxy_config.mode = "none"
        mock_config.timeouts = MagicMock()
        mock_config.timeouts.total = 30.0
        mock_config.timeouts.connect = 10.0
        mock_config.timeouts.read = 30.0
        mock_config.timeouts.write = 30.0
        mock_config.worker_health_policy = MagicMock()

        # Create provider instance
        provider = AnthropicProvider("test_provider", mock_config)
        return provider

    # Test 1: Provider instantiation
    def test_provider_instantiation(self):
        """Test that AnthropicProvider creates an object implementing IProvider with all abstract methods overridden."""
        provider = self.create_mock_provider()

        # Verify it's an instance of AnthropicProvider
        assert isinstance(provider, AnthropicProvider)

        # Verify it implements IProvider abstract methods (should not raise NotImplementedError)
        # Check that each abstract method exists and is callable
        assert hasattr(provider, "_get_headers")
        assert hasattr(provider, "parse_request_details")
        assert hasattr(provider, "_map_status_code_to_reason")
        assert hasattr(provider, "_parse_proxy_error")
        assert hasattr(provider, "check")
        assert hasattr(provider, "inspect")
        assert hasattr(provider, "proxy_request")

        # Verify they are callable (not the abstract stub)
        # By creating the provider, we already know they're implemented

        # Also verify provider has required attributes
        assert provider.name == "test_provider"
        assert provider.config is not None

    # Test 2: _get_headers — required auth headers
    def test_get_headers_valid_token(self):
        """Test _get_headers returns correct headers with valid token."""
        provider = self.create_mock_provider()
        token = "test-token-123"

        headers = provider._get_headers(token)

        assert headers is not None
        assert headers["x-api-key"] == token
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["content-type"] == "application/json"

    # Test 3: _get_headers — empty/invalid token
    def test_get_headers_empty_token(self):
        """Test _get_headers returns None with empty token."""
        provider = self.create_mock_provider()

        headers = provider._get_headers("")
        assert headers is None

        headers = provider._get_headers(None)
        assert headers is None

    # Test 4: _prepare_proxy_headers — beta header pass-through
    def test_prepare_proxy_headers_beta_header_preserved(self):
        """Test that anthropic-beta header is preserved in final headers."""
        provider = self.create_mock_provider()
        token = "test-token"
        incoming_headers = {
            "Host": "example.com",
            "Authorization": "Bearer client-token",
            "Content-Type": "application/json",
            "Content-Length": "123",
            "anthropic-beta": "computer-use-2024-10-22",
            "X-Custom-Header": "value",
        }

        proxy_headers = provider._prepare_proxy_headers(token, incoming_headers)

        # Required auth headers present
        assert "x-api-key" in proxy_headers
        assert proxy_headers["x-api-key"] == token
        assert "anthropic-version" in proxy_headers
        assert "content-type" in proxy_headers

        # Beta header preserved (lowercased)
        assert "anthropic-beta" in proxy_headers
        assert proxy_headers["anthropic-beta"] == "computer-use-2024-10-22"

        # Hop-by-hop headers removed
        assert "host" not in proxy_headers
        assert "authorization" not in proxy_headers
        assert "content-length" not in proxy_headers

        # Other custom headers preserved
        assert "x-custom-header" in proxy_headers
        assert proxy_headers["x-custom-header"] == "value"

    # Test 5: _prepare_proxy_headers — no beta headers
    def test_prepare_proxy_headers_no_beta_headers(self):
        """Test proxy headers when incoming headers lack anthropic-beta."""
        provider = self.create_mock_provider()
        token = "test-token"
        incoming_headers = {
            "Host": "example.com",
            "Authorization": "Bearer client-token",
            "Content-Type": "application/json",
        }

        proxy_headers = provider._prepare_proxy_headers(token, incoming_headers)

        # Required auth headers present
        assert "x-api-key" in proxy_headers
        assert proxy_headers["x-api-key"] == token
        assert "anthropic-version" in proxy_headers
        assert "content-type" in proxy_headers

        # No beta header
        assert "anthropic-beta" not in proxy_headers

        # Hop-by-hop headers removed
        assert "host" not in proxy_headers
        assert "authorization" not in proxy_headers

    # Test 6: parse_request_details — standard Messages API request
    @pytest.mark.asyncio
    async def test_parse_request_details_standard_request(self):
        """Test parse_request_details extracts model name from valid request."""
        provider = self.create_mock_provider()

        content = b'{"model": "claude-3-opus-20240229", "messages": [{"role": "user", "content": "Hello"}]}'
        path = "/v1/messages"

        result = await provider.parse_request_details(path, content)

        assert isinstance(result, RequestDetails)
        assert result.model_name == "claude-3-opus-20240229"

    # Test 7: parse_request_details — empty request body
    @pytest.mark.asyncio
    async def test_parse_request_details_empty_body(self):
        """Test parse_request_details raises ValueError for empty body."""
        provider = self.create_mock_provider()

        with pytest.raises(ValueError, match="Request body is empty"):
            await provider.parse_request_details("/v1/messages", b"")

    # Test 8: parse_request_details — invalid JSON
    @pytest.mark.asyncio
    async def test_parse_request_details_invalid_json(self):
        """Test parse_request_details raises ValueError for invalid JSON."""
        provider = self.create_mock_provider()

        with pytest.raises(ValueError, match="Failed to parse request body as JSON"):
            await provider.parse_request_details("/v1/messages", b"not json")

    # Test 9: parse_request_details — missing model key
    @pytest.mark.asyncio
    async def test_parse_request_details_missing_model(self):
        """Test parse_request_details raises ValueError when model field is missing."""
        provider = self.create_mock_provider()

        content = b'{"messages": [{"role": "user", "content": "Hello"}]}'

        with pytest.raises(ValueError, match="missing a valid 'model' string field"):
            await provider.parse_request_details("/v1/messages", content)

    # Test 10: _map_status_code_to_reason — 401 → INVALID_KEY
    def test_map_status_code_to_reason_401(self):
        """Test 401 maps to INVALID_KEY."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(401)
        assert reason == ErrorReason.INVALID_KEY

    # Test 11: _map_status_code_to_reason — 402 → NO_QUOTA
    def test_map_status_code_to_reason_402(self):
        """Test 402 maps to NO_QUOTA."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(402)
        assert reason == ErrorReason.NO_QUOTA

    # Test 12: _map_status_code_to_reason — 403 → NO_ACCESS
    def test_map_status_code_to_reason_403(self):
        """Test 403 maps to NO_ACCESS."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(403)
        assert reason == ErrorReason.NO_ACCESS

    # Test 13: _map_status_code_to_reason — 413 → BAD_REQUEST
    def test_map_status_code_to_reason_413(self):
        """Test 413 maps to BAD_REQUEST."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(413)
        assert reason == ErrorReason.BAD_REQUEST

    # Test for 404 → NO_MODEL
    def test_map_status_code_to_reason_404(self):
        """Test 404 maps to NO_MODEL."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(404)
        assert reason == ErrorReason.NO_MODEL

    # Test 14: _map_status_code_to_reason — 429 → RATE_LIMITED
    def test_map_status_code_to_reason_429(self):
        """Test 429 maps to RATE_LIMITED."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(429)
        assert reason == ErrorReason.RATE_LIMITED

    # Test 15: _map_status_code_to_reason — 529 → OVERLOADED
    def test_map_status_code_to_reason_529(self):
        """Test 529 maps to OVERLOADED."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(529)
        assert reason == ErrorReason.OVERLOADED

    # Test 16: _map_status_code_to_reason — other 4xx → BAD_REQUEST
    def test_map_status_code_to_reason_other_4xx(self):
        """Test other 4xx statuses map to BAD_REQUEST."""
        provider = self.create_mock_provider()

        # Test various 4xx codes not specifically mapped (excluding 404 which maps to NO_MODEL)
        test_codes = [405, 422, 418, 499]
        for code in test_codes:
            reason = provider._map_status_code_to_reason(code)
            assert (
                reason == ErrorReason.BAD_REQUEST
            ), f"Status {code} should map to BAD_REQUEST"

    # Test 17: _map_status_code_to_reason — 5xx → SERVER_ERROR
    def test_map_status_code_to_reason_5xx(self):
        """Test 5xx statuses map to SERVER_ERROR."""
        provider = self.create_mock_provider()

        # Test 500 maps to SERVER_ERROR
        reason = provider._map_status_code_to_reason(500)
        assert reason == ErrorReason.SERVER_ERROR

        # Special cases
        reason = provider._map_status_code_to_reason(504)
        assert reason == ErrorReason.TIMEOUT

        reason = provider._map_status_code_to_reason(529)
        assert reason == ErrorReason.OVERLOADED

        # Test other 5xx codes (excluding special cases)
        test_codes = [501, 502, 503, 599]
        for code in test_codes:
            reason = provider._map_status_code_to_reason(code)
            assert (
                reason == ErrorReason.SERVER_ERROR
            ), f"Status {code} should map to SERVER_ERROR"

    # Additional test: verify that 400 maps to BAD_REQUEST
    def test_map_status_code_to_reason_400(self):
        """Test 400 maps to BAD_REQUEST."""
        provider = self.create_mock_provider()

        reason = provider._map_status_code_to_reason(400)
        assert reason == ErrorReason.BAD_REQUEST

    # Additional test: verify that unknown status codes map to UNKNOWN
    def test_map_status_code_to_reason_unknown(self):
        """Test unknown status codes map to UNKNOWN."""
        provider = self.create_mock_provider()

        # Test 1xx, 2xx, 3xx codes
        test_codes = [100, 200, 201, 301, 302, 304]
        for code in test_codes:
            reason = provider._map_status_code_to_reason(code)
            assert reason == ErrorReason.UNKNOWN, f"Status {code} should map to UNKNOWN"

    # --- ANT-1 through ANT-4: check() method integration with _refine_error_reason ---

    @pytest.mark.asyncio
    async def test_check_calls_refine_error_reason_on_error(self):
        """ANT-1: AnthropicProvider.check() calls _refine_error_reason() on HTTP error."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=True, rules=[])
        )
        provider.config.models = {
            "claude-3-opus-20240229": ModelInfo(
                endpoint_suffix="/v1/messages",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = '{"error": {"type": "authentication_error"}}'

        httpx_error = httpx.HTTPStatusError(
            "401 Unauthorized", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(
            provider, "_refine_error_reason", new=AsyncMock()
        ) as mock_refine:
            mock_refine.return_value = ErrorReason.INVALID_KEY

            result = await provider.check(
                mock_client, "test_token", model="claude-3-opus-20240229"
            )

            # Verify _refine_error_reason was called
            mock_refine.assert_called_once()
            call_args = mock_refine.call_args
            # First positional arg is the response object
            assert call_args[0][0] is mock_response
            # Second positional arg is default_reason from _map_status_code_to_reason(401) = INVALID_KEY
            assert call_args[0][1] == ErrorReason.INVALID_KEY
            # body_bytes keyword arg contains encoded response text
            assert "body_bytes" in call_args[1]
            assert (
                call_args[1]["body_bytes"]
                == b'{"error": {"type": "authentication_error"}}'
            )

    @pytest.mark.asyncio
    async def test_check_refine_401_to_no_quota_via_error_parsing(self):
        """ANT-2: check() with 401 + error_parsing rule → refined reason (NO_QUOTA)."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=401,
                        error_path="error.type",
                        match_pattern="insufficient_quota|billing_inactive",
                        map_to="no_quota",
                        priority=10,
                    )
                ],
            )
        )
        provider.config.models = {
            "claude-3-opus-20240229": ModelInfo(
                endpoint_suffix="/v1/messages",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = (
            '{"error": {"type": "insufficient_quota", "message": "No quota remaining"}}'
        )

        httpx_error = httpx.HTTPStatusError(
            "401 Unauthorized", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_check_fallback_when_error_parsing_disabled(self):
        """ANT-3: check() with error_parsing.enabled=False → default_reason."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        provider.config.models = {
            "claude-3-opus-20240229": ModelInfo(
                endpoint_suffix="/v1/messages",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request("GET", "https://api.anthropic.com/v1/models")
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = '{"error": {"type": "authentication_error"}}'

        httpx_error = httpx.HTTPStatusError(
            "401 Unauthorized", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert not result.available
        # When error_parsing is disabled, default_reason for 401 is INVALID_KEY
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 401

    def test_check_does_not_call_check_fast_fail(self):
        """ANT-4: check() doesn't call _check_fast_fail() — method has been removed."""
        provider = self.create_mock_provider()
        # _check_fast_fail method should not exist on the provider
        assert not hasattr(provider, "_check_fast_fail")
