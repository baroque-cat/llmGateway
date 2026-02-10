#!/usr/bin/env python3

"""
Tests for Gemini provider error parsing integration.

This module tests the integration of error parsing functionality
in the GeminiBaseProvider class, ensuring that error parsing rules
are correctly applied during error response processing.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.providers.impl.gemini import GeminiProvider


class TestGeminiErrorParsing:
    """Test suite for Gemini provider error parsing integration."""

    def create_mock_provider(self, error_config=None):
        """Helper to create a mock GeminiBaseProvider with given error parsing configuration."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)

        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])

        mock_config.gateway_policy.error_parsing = error_config

        # Set up other required config fields
        mock_config.provider_type = "gemini"
        mock_config.keys_path = "/test/keys"
        mock_config.api_base_url = "https://generativelanguage.googleapis.com/v1"
        mock_config.default_model = "gemini-pro"
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

        # Create provider instance
        provider = GeminiProvider("test_provider", mock_config)
        return provider

    @pytest.mark.asyncio
    async def test_parse_proxy_error_without_error_parsing(self):
        """Test _parse_proxy_error when error parsing is disabled."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        # Mock aread to return a generic error
        error_body = json.dumps(
            {"error": {"message": "Bad Request", "status": "INVALID_ARGUMENT"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should map to appropriate error reason by default
        assert isinstance(result, CheckResult)
        assert not result.available
        # Gemini maps 400 to BAD_REQUEST by default
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_with_error_parsing_match(self):
        """Test _parse_proxy_error with error parsing rule that matches."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="INVALID_ARGUMENT|PERMISSION_DENIED",
                        map_to="invalid_key",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        # Mock aread to return Gemini error
        error_body = json.dumps(
            {"error": {"message": "API key not valid", "status": "INVALID_ARGUMENT"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should map to INVALID_KEY due to error parsing rule
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_with_error_parsing_no_match(self):
        """Test _parse_proxy_error with error parsing rule that doesn't match."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="INVALID_ARGUMENT",
                        map_to="invalid_key",
                        priority=10,
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        # Mock aread to return different error status
        error_body = json.dumps(
            {"error": {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should fall back to default mapping
        assert isinstance(result, CheckResult)
        assert not result.available
        # Default mapping for 400 is BAD_REQUEST
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_with_multiple_rules_priority(self):
        """Test _parse_proxy_error with multiple rules, respecting priority."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="RESOURCE_EXHAUSTED",
                        map_to="no_quota",
                        priority=5,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern=".*quota.*exceeded.*",
                        map_to="invalid_key",
                        priority=10,  # Higher priority
                    ),
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        # Mock aread to return error that matches both rules
        error_body = json.dumps(
            {
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "message": "Your quota has been exceeded",
                }
            }
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should use higher priority rule (INVALID_KEY)
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_with_different_status_code(self):
        """Test _parse_proxy_error with rules for different status codes."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="INVALID_ARGUMENT",
                        map_to="invalid_key",
                    ),
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.status",
                        match_pattern="RESOURCE_EXHAUSTED",
                        map_to="rate_limited",
                    ),
                ],
            )
        )

        # Test 429 response
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        error_body = json.dumps(
            {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should map to RATE_LIMITED
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.RATE_LIMITED
        assert result.response_time == 0.5
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_parse_proxy_error_empty_response_body(self):
        """Test _parse_proxy_error with empty response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern=".*",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.aread = AsyncMock(return_value=b"")  # Empty body

        result = await provider._parse_proxy_error(mock_response, b"")

        # Should use default mapping
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_invalid_json_body(self):
        """Test _parse_proxy_error with invalid JSON in response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern=".*",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.aread = AsyncMock(return_value=b"Invalid JSON {")

        result = await provider._parse_proxy_error(mock_response, b"Invalid JSON {")

        # Should use default mapping
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_passes_body_bytes(self):
        """Test that _parse_proxy_error passes body_bytes to avoid re-reading."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="INVALID_ARGUMENT",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        error_body = json.dumps({"error": {"status": "INVALID_ARGUMENT"}}).encode(
            "utf-8"
        )
        mock_response.aread = AsyncMock(return_value=error_body)

        # Patch _refine_error_reason to verify it's called with body_bytes
        with patch.object(provider, "_refine_error_reason", AsyncMock()) as mock_refine:
            mock_refine.return_value = ErrorReason.INVALID_KEY

            await provider._parse_proxy_error(mock_response, error_body)

            # Verify _refine_error_reason was called with body_bytes
            mock_refine.assert_called_once()
            call_args = mock_refine.call_args
            assert call_args[1]["body_bytes"] == error_body
            # Default reason depends on _map_error_to_reason implementation

    @pytest.mark.asyncio
    async def test_map_error_to_reason_integration(self):
        """Test integration with _map_error_to_reason method."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )

        # Test that _map_error_to_reason is called as part of error parsing
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.aread = AsyncMock(
            return_value=b'{"error": {"status": "INVALID_ARGUMENT"}}'
        )

        result = await provider._parse_proxy_error(
            mock_response, b'{"error": {"status": "INVALID_ARGUMENT"}}'
        )

        # Verify result is valid CheckResult
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.status_code == 400
        assert result.response_time == 0.5


class TestGeminiProxyRequest:
    """Test suite for Gemini provider proxy_request with streaming data."""

    def create_mock_provider(self):
        """Helper to create a mock GeminiProvider with minimal configuration."""
        from unittest.mock import MagicMock

        from src.config.schemas import (
            ErrorParsingConfig,
            GatewayPolicyConfig,
            ProviderConfig,
        )

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.gateway_policy.error_parsing = ErrorParsingConfig(
            enabled=False, rules=[]
        )
        mock_config.provider_type = "gemini"
        mock_config.keys_path = "/test/keys"
        mock_config.api_base_url = "https://generativelanguage.googleapis.com/v1"
        mock_config.default_model = "gemini-pro"
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

        from src.providers.impl.gemini import GeminiProvider

        provider = GeminiProvider("test_provider", mock_config)
        return provider

    @pytest.mark.asyncio
    async def test_proxy_request_with_bytes_content(self):
        """Test proxy_request with bytes content (non-streaming)."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []
        original_build_request = mock_client.build_request  # noqa: F841

        def mock_build_request(**kwargs):
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        mock_client.send = AsyncMock(return_value=mock_response)

        token = "test_token"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "v1beta/models/gemini-pro:generateContent"
        query_params = ""
        content = b'{"prompt": "Hello"}'

        # Call proxy_request
        response, check_result = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert (
            call_kwargs["url"]
            == "https://generativelanguage.googleapis.com/v1/v1beta/models/gemini-pro:generateContent"
        )
        assert "x-goog-api-key" in call_kwargs["headers"]
        assert call_kwargs["headers"]["x-goog-api-key"] == token
        assert call_kwargs["content"] == content  # bytes content passed as content
        assert "data" not in call_kwargs

    @pytest.mark.asyncio
    async def test_proxy_request_with_async_iterable_content(self):
        """Test proxy_request with AsyncIterable content (streaming)."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []
        original_build_request = mock_client.build_request  # noqa: F841

        def mock_build_request(**kwargs):
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        mock_client.send = AsyncMock(return_value=mock_response)

        token = "test_token"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "v1beta/models/gemini-pro:generateContent"
        query_params = ""

        # Create a simple async iterable
        async def async_iterable():
            yield b'{"prompt": "Hello"}'
            yield b'{"prompt": "World"}'

        content = async_iterable()

        # Call proxy_request
        response, check_result = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert (
            call_kwargs["url"]
            == "https://generativelanguage.googleapis.com/v1/v1beta/models/gemini-pro:generateContent"
        )
        assert "x-goog-api-key" in call_kwargs["headers"]
        assert call_kwargs["headers"]["x-goog-api-key"] == token
        # AsyncIterable should be passed as content parameter
        assert call_kwargs["content"] == content
        assert "data" not in call_kwargs
