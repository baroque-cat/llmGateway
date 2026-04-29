#!/usr/bin/env python3

"""
Tests for Anthropic provider proxy request functionality.

This module tests the AnthropicProvider's inspect and proxy_request methods,
including handling of both streaming and non-streaming content.
"""

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    GatewayPolicyConfig,
    ModelInfo,
    ProviderConfig,
)
from src.core.models import CheckResult
from src.providers.impl.anthropic import AnthropicProvider


class TestAnthropicProxy:
    """Test suite for Anthropic provider proxy_request and inspect methods."""

    def create_mock_provider(
        self, models: dict[str, ModelInfo] | None = None
    ) -> AnthropicProvider:
        """Helper to create a mock AnthropicProvider with given configuration."""
        from unittest.mock import MagicMock

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.error_parsing = ErrorParsingConfig(enabled=False, rules=[])
        mock_config.gateway_policy.debug_mode = "none"
        mock_config.provider_type = "anthropic"
        mock_config.api_base_url = "https://api.anthropic.com"
        mock_config.default_model = "claude-3-opus-20240229"
        if models is None:
            models = {
                "claude-3-opus-20240229": MagicMock(spec=ModelInfo),
                "claude-3-sonnet-20240229": MagicMock(spec=ModelInfo),
                "claude-3-haiku-20240307": MagicMock(spec=ModelInfo),
            }
        mock_config.models = models
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
        mock_config.timeouts.pool = 5.0

        provider = AnthropicProvider("test_anthropic", mock_config)
        return provider

    @pytest.mark.asyncio
    async def test_inspect_returns_model_list_from_config(self):
        """Test that inspect returns a list of keys from self.config.models."""
        provider = self.create_mock_provider()
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        token = "test_token"

        models = await provider.inspect(mock_client, token)

        assert isinstance(models, list)
        assert len(models) == 3
        assert set(models) == {
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
        }
        # Verify no HTTP call was made
        mock_client.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_proxy_request_bytes_content_non_streaming(self):
        """Test proxy_request with bytes content (non-streaming)."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        # Mock _send_proxy_request to capture request and return success
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token_123"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "v1/messages"
        query_params = ""
        content = b'{"model": "claude-3-opus", "messages": []}'

        # Call proxy_request
        _response, _check_result = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify _send_proxy_request was called with the correct request
        assert provider._send_proxy_request.called
        call_args = provider._send_proxy_request.call_args
        assert call_args[0][0] == mock_client
        assert call_args[0][1] == mock_request

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert call_kwargs["url"] == "https://api.anthropic.com/v1/messages"
        # Check headers include x-api-key and anthropic-version
        assert "x-api-key" in call_kwargs["headers"]
        assert call_kwargs["headers"]["x-api-key"] == token
        assert "anthropic-version" in call_kwargs["headers"]
        assert call_kwargs["headers"]["anthropic-version"] == "2023-06-01"
        assert call_kwargs["content"] == content  # bytes content passed as content
        assert "data" not in call_kwargs

    @pytest.mark.asyncio
    async def test_proxy_request_async_generator_content_streaming(self):
        """Test proxy_request with AsyncGenerator content (streaming)."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        # Mock _send_proxy_request to capture request and return success
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token_456"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "v1/messages"
        query_params = ""

        # Create a simple async generator
        async def async_generator() -> AsyncGenerator[bytes]:
            yield b'{"model": "claude-3-sonnet", "messages": []}'
            yield b'{"stream": true}'

        content = async_generator()

        # Call proxy_request
        _response, _check_result = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify _send_proxy_request was called with the correct request
        assert provider._send_proxy_request.called
        call_args = provider._send_proxy_request.call_args
        assert call_args[0][0] == mock_client
        assert call_args[0][1] == mock_request

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert call_kwargs["url"] == "https://api.anthropic.com/v1/messages"
        assert "x-api-key" in call_kwargs["headers"]
        assert call_kwargs["headers"]["x-api-key"] == token
        # AsyncIterable should be passed as content parameter
        assert call_kwargs["content"] == content
        assert "data" not in call_kwargs

    @pytest.mark.asyncio
    async def test_proxy_request_correct_url_formation(self):
        """Test proxy_request forms correct upstream URL with query parameters."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token"
        method = "POST"
        headers = {}
        path = "v1/messages"
        query_params = "stream=true&max_tokens=100"
        content = b'{"model": "claude-3-haiku"}'

        # Call proxy_request
        await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify URL formation
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        expected_url = (
            "https://api.anthropic.com/v1/messages?stream=true&max_tokens=100"
        )
        assert call_kwargs["url"] == expected_url

    @pytest.mark.asyncio
    async def test_proxy_request_correct_url_without_query_params(self):
        """Test proxy_request forms correct upstream URL without query parameters."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token"
        method = "POST"
        headers = {}
        path = "v1/messages"
        query_params = ""
        content = b'{"model": "claude-3-haiku"}'

        # Call proxy_request
        await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify URL formation
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        expected_url = "https://api.anthropic.com/v1/messages"
        assert call_kwargs["url"] == expected_url

    @pytest.mark.asyncio
    async def test_proxy_request_correct_url_with_path_leading_slash(self):
        """Test proxy_request handles path with leading slash."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token"
        method = "POST"
        headers = {}
        path = "/v1/messages"
        query_params = ""
        content = b'{"model": "claude-3-haiku"}'

        # Call proxy_request
        await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify URL formation (should strip leading slash)
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        expected_url = "https://api.anthropic.com/v1/messages"
        assert call_kwargs["url"] == expected_url

    @pytest.mark.asyncio
    async def test_proxy_request_prepares_headers_correctly(self):
        """Test proxy_request prepares headers with x-api-key and removes incoming auth headers."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        # Mock build_request to capture arguments
        build_request_calls = []

        def mock_build_request(**kwargs: Any) -> Any:
            build_request_calls.append(kwargs)
            return mock_request

        mock_client.build_request = mock_build_request
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, CheckResult.success(status_code=200))
        )

        token = "test_token_789"
        method = "POST"
        headers = {
            "Authorization": "Bearer client_token",
            "Host": "example.com",
            "Content-Type": "application/json",
            "X-Custom-Header": "value",
        }
        path = "v1/messages"
        query_params = ""
        content = b'{"model": "claude-3-opus"}'

        # Call proxy_request
        await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify headers
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        proxy_headers = call_kwargs["headers"]

        # Should include x-api-key and anthropic-version
        assert proxy_headers["x-api-key"] == token
        assert proxy_headers["anthropic-version"] == "2023-06-01"
        # Should remove incoming auth headers
        assert "authorization" not in proxy_headers
        assert "host" not in proxy_headers
        # Should preserve other headers (lowercased)
        assert "x-custom-header" in proxy_headers
        assert proxy_headers["x-custom-header"] == "value"
        # Should have content-type from provider headers (application/json)
        assert proxy_headers["content-type"] == "application/json"
