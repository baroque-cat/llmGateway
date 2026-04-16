#!/usr/bin/env python3

"""
Tests for Anthropic provider core functionality.

This module tests the core functionality of the Anthropic provider implementation,
including header construction, request parsing, and error mapping.
"""

from unittest.mock import MagicMock

import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    GatewayPolicyConfig,
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

        mock_config.gateway_policy.error_parsing = error_config

        # Set up other required config fields
        mock_config.provider_type = "anthropic"
        mock_config.keys_path = "/test/keys"
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
        mock_config.worker_health_policy.fast_status_mapping = {}

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
