#!/usr/bin/env python3

"""
Tests for OpenAI-like provider error parsing integration.

This module tests the integration of error parsing functionality
in the OpenAILikeProvider class, ensuring that error parsing rules
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
    ModelInfo,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.providers.impl.openai_like import OpenAILikeProvider


class TestOpenAILikeErrorParsing:
    """Test suite for OpenAI-like provider error parsing integration."""

    def create_mock_provider(self, error_config=None):
        """Helper to create a mock OpenAILikeProvider with given error parsing configuration."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)

        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])

        mock_config.error_parsing = error_config

        # Set up other required config fields
        mock_config.provider_type = "openai"
        mock_config.api_base_url = "https://api.openai.com/v1"
        mock_config.default_model = "gpt-4"
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
        provider = OpenAILikeProvider("test_provider", mock_config)
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
            {"error": {"message": "Invalid request", "type": "invalid_request_error"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should map to BAD_REQUEST by default (no error parsing)
        assert isinstance(result, CheckResult)
        assert not result.available
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
                        error_path="error.type",
                        match_pattern="Arrearage|BillingHardLimit",
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

        # Mock aread to return Qwen "Arrearage" error
        error_body = json.dumps(
            {"error": {"type": "Arrearage", "message": "Payment overdue"}}
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
                        error_path="error.type",
                        match_pattern="Arrearage",
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

        # Mock aread to return different error type
        error_body = json.dumps(
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid request format",
                }
            }
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        result = await provider._parse_proxy_error(mock_response, error_body)

        # Should fall back to default mapping (BAD_REQUEST)
        assert isinstance(result, CheckResult)
        assert not result.available
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
                        error_path="error.code",
                        match_pattern="insufficient_quota",
                        map_to="no_quota",
                        priority=5,
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
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
                    "type": "Arrearage",
                    "code": "insufficient_quota",
                    "message": "Multiple error indicators",
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
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                    ),
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit",
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
            {"error": {"code": "rate_limit", "message": "Rate limit exceeded"}}
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
                        error_path="error.type",
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

        # Should use default mapping (BAD_REQUEST)
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
                        error_path="error.type",
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

        # Should use default mapping (BAD_REQUEST)
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
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                    )
                ],
            )
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        error_body = json.dumps({"error": {"type": "Arrearage"}}).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        # Patch _refine_error_reason to verify it's called with body_bytes
        with patch.object(provider, "_refine_error_reason", AsyncMock()) as mock_refine:
            mock_refine.return_value = ErrorReason.INVALID_KEY

            await provider._parse_proxy_error(mock_response, error_body)

            # Verify _refine_error_reason was called with body_bytes
            mock_refine.assert_called_once()
            call_args = mock_refine.call_args
            assert call_args[1]["body_bytes"] == error_body
            assert call_args[1]["default_reason"] == ErrorReason.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_check_method_400_behavior(self):
        """
        Test that check() calls _refine_error_reason() on HTTP 400 errors.

        When error_parsing is disabled, check() returns the default reason
        (INVALID_KEY for 400). When enabled with a matching rule, it returns
        the refined reason from error_parsing.
        """
        # Case 1: error_parsing disabled → default reason (INVALID_KEY for 400)
        provider_disabled = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        provider_disabled.config.models = {
            "gpt-4": ModelInfo(
                endpoint_suffix="/chat/completions",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider_disabled.config.timeouts.pool = 35.0

        mock_request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions"
        )
        mock_response_400 = MagicMock(spec=httpx.Response)
        mock_response_400.status_code = 400
        mock_response_400.elapsed = MagicMock()
        mock_response_400.elapsed.total_seconds.return_value = 0.5
        mock_response_400.text = '{"error": {"message": "Bad request"}}'

        httpx_error_400 = httpx.HTTPStatusError(
            "400 Bad Request", request=mock_request, response=mock_response_400
        )
        mock_response_400.raise_for_status = MagicMock(side_effect=httpx_error_400)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response_400)

        result = await provider_disabled.check(mock_client, "test_token", model="gpt-4")

        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 400

        # Case 2: error_parsing enabled with matching rule → refined reason
        provider_enabled = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="no_quota",
                        priority=10,
                    )
                ],
            )
        )
        provider_enabled.config.models = {
            "gpt-4": ModelInfo(
                endpoint_suffix="/chat/completions",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider_enabled.config.timeouts.pool = 35.0

        mock_response_arrearage = MagicMock(spec=httpx.Response)
        mock_response_arrearage.status_code = 400
        mock_response_arrearage.elapsed = MagicMock()
        mock_response_arrearage.elapsed.total_seconds.return_value = 0.5
        mock_response_arrearage.text = (
            '{"error": {"type": "Arrearage", "message": "Payment overdue"}}'
        )

        httpx_error_arrearage = httpx.HTTPStatusError(
            "400 Bad Request",
            request=mock_request,
            response=mock_response_arrearage,
        )
        mock_response_arrearage.raise_for_status = MagicMock(
            side_effect=httpx_error_arrearage
        )

        mock_client2 = AsyncMock(spec=httpx.AsyncClient)
        mock_client2.post = AsyncMock(return_value=mock_response_arrearage)

        result = await provider_enabled.check(mock_client2, "test_token", model="gpt-4")

        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_calls_refine_error_reason_on_400(self):
        """OAI-1: OpenAILikeProvider.check() calls _refine_error_reason() on HTTP 400."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=True, rules=[])
        )
        provider.config.models = {
            "gpt-4": ModelInfo(
                endpoint_suffix="/chat/completions",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions"
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = '{"error": {"message": "Bad request"}}'

        httpx_error = httpx.HTTPStatusError(
            "400 Bad Request", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(
            provider, "_refine_error_reason", new=AsyncMock()
        ) as mock_refine:
            mock_refine.return_value = ErrorReason.INVALID_KEY

            result = await provider.check(mock_client, "test_token", model="gpt-4")

            # Verify _refine_error_reason was called
            mock_refine.assert_called_once()
            call_args = mock_refine.call_args
            # First positional arg is the response object
            assert call_args[0][0] is mock_response
            # Second positional arg is default_reason (INVALID_KEY for 400 in check())
            assert call_args[0][1] == ErrorReason.INVALID_KEY
            # body_bytes keyword arg contains encoded response text
            assert "body_bytes" in call_args[1]
            assert (
                call_args[1]["body_bytes"] == b'{"error": {"message": "Bad request"}}'
            )

    @pytest.mark.asyncio
    async def test_check_refine_400_to_no_quota_via_error_parsing(self):
        """OAI-2: check() with 400 + Arrearage rule → NO_QUOTA instead of INVALID_KEY."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage|BillingHardLimit",
                        map_to="no_quota",
                        priority=10,
                    )
                ],
            )
        )
        provider.config.models = {
            "gpt-4": ModelInfo(
                endpoint_suffix="/chat/completions",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions"
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = (
            '{"error": {"type": "Arrearage", "message": "Payment overdue"}}'
        )

        httpx_error = httpx.HTTPStatusError(
            "400 Bad Request", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await provider.check(mock_client, "test_token", model="gpt-4")

        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_fallback_when_error_parsing_disabled(self):
        """OAI-3: check() with error_parsing.enabled=False → default_reason (INVALID_KEY for 400)."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        provider.config.models = {
            "gpt-4": ModelInfo(
                endpoint_suffix="/chat/completions",
                test_payload={"messages": [{"role": "user", "content": "hi"}]},
            )
        }
        provider.config.timeouts.pool = 35.0

        mock_request = httpx.Request(
            "POST", "https://api.openai.com/v1/chat/completions"
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_response.text = '{"error": {"message": "Bad request"}}'

        httpx_error = httpx.HTTPStatusError(
            "400 Bad Request", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=httpx_error)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(return_value=mock_response)

        result = await provider.check(mock_client, "test_token", model="gpt-4")

        assert not result.available
        # When error_parsing is disabled, default_reason for 400 in check() is INVALID_KEY
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 400

    def test_check_does_not_call_check_fast_fail(self):
        """OAI-4: check() doesn't call _check_fast_fail() — method has been removed."""
        provider = self.create_mock_provider()
        # _check_fast_fail method should not exist on the provider
        assert not hasattr(provider, "_check_fast_fail")

    def test_map_status_code_to_reason_4xx_errors(self):
        """
        Test that _map_status_code_to_reason correctly maps various 4xx errors to BAD_REQUEST.
        This includes 404 (Not Found) and 422 (Unprocessable Entity).
        """
        provider = self.create_mock_provider()

        # Test 404 Not Found
        assert provider._map_status_code_to_reason(404) == ErrorReason.BAD_REQUEST

        # Test 422 Unprocessable Entity
        assert provider._map_status_code_to_reason(422) == ErrorReason.BAD_REQUEST

        # Test other 4xx codes
        assert provider._map_status_code_to_reason(405) == ErrorReason.BAD_REQUEST
        assert provider._map_status_code_to_reason(406) == ErrorReason.BAD_REQUEST
        assert provider._map_status_code_to_reason(409) == ErrorReason.BAD_REQUEST

        # Ensure existing mappings are preserved
        assert provider._map_status_code_to_reason(400) == ErrorReason.BAD_REQUEST
        assert provider._map_status_code_to_reason(401) == ErrorReason.INVALID_KEY
        assert provider._map_status_code_to_reason(403) == ErrorReason.INVALID_KEY
        assert provider._map_status_code_to_reason(402) == ErrorReason.NO_QUOTA
        assert provider._map_status_code_to_reason(429) == ErrorReason.RATE_LIMITED


class TestOpenAILikeProxyRequest:
    """Test suite for OpenAI-like provider proxy_request with streaming data."""

    def create_mock_provider(self):
        """Helper to create a mock OpenAILikeProvider with minimal configuration."""
        from unittest.mock import MagicMock

        from src.config.schemas import (
            ErrorParsingConfig,
            ProviderConfig,
        )

        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.error_parsing = ErrorParsingConfig(enabled=False, rules=[])
        mock_config.provider_type = "openai"
        mock_config.api_base_url = "https://api.openai.com/v1"
        mock_config.default_model = "gpt-4"
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

        from src.providers.impl.openai_like import OpenAILikeProvider

        provider = OpenAILikeProvider("test_provider", mock_config)
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
        path = "chat/completions"
        query_params = ""
        content = b'{"model": "gpt-4", "messages": []}'

        # Call proxy_request
        response, check_result, body_bytes = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert call_kwargs["url"] == "https://api.openai.com/v1/chat/completions"
        assert "authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["authorization"] == f"Bearer {token}"
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
        path = "chat/completions"
        query_params = ""

        # Create a simple async iterable
        async def async_iterable():
            yield b'{"model": "gpt-4", "messages": []}'
            yield b'{"stream": true}'

        content = async_iterable()

        # Call proxy_request
        response, check_result, body_bytes = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify build_request was called with correct parameters
        assert len(build_request_calls) == 1
        call_kwargs = build_request_calls[0]
        assert call_kwargs["method"] == method
        assert call_kwargs["url"] == "https://api.openai.com/v1/chat/completions"
        assert "authorization" in call_kwargs["headers"]
        assert call_kwargs["headers"]["authorization"] == f"Bearer {token}"
        # AsyncIterable should be passed as content parameter
        assert call_kwargs["content"] == content
        assert "data" not in call_kwargs

    @pytest.mark.asyncio
    async def test_openai_like_proxy_request_returns_three_element_tuple(self):
        """Test proxy_request() returns (response, check_result, body_bytes) — third element pass-through from _send_proxy_request()."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        mock_client.build_request = MagicMock(return_value=mock_request)

        expected_check_result = CheckResult.success(status_code=200)
        expected_body_bytes = b"upstream response body"

        # Mock _send_proxy_request to return a 3-element tuple
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, expected_check_result, expected_body_bytes)
        )

        token = "test_token"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "chat/completions"
        query_params = ""
        content = b'{"model": "gpt-4", "messages": []}'

        result = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify proxy_request returns a 3-element tuple
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0] is mock_response
        assert result[1] is expected_check_result
        assert result[2] is expected_body_bytes

    @pytest.mark.asyncio
    async def test_proxy_request_passes_body_bytes_none_when_no_debug(self):
        """Test _send_proxy_request() returns body_bytes=None → proxy_request() passes through None."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.is_success = True

        mock_client.build_request = MagicMock(return_value=mock_request)

        expected_check_result = CheckResult.success(status_code=200)

        # Mock _send_proxy_request to return body_bytes=None (no debug mode)
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, expected_check_result, None)
        )

        token = "test_token"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "chat/completions"
        query_params = ""
        content = b'{"model": "gpt-4", "messages": []}'

        _response, _check_result, body_bytes = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify third element is None when no debug mode
        assert body_bytes is None

    @pytest.mark.asyncio
    async def test_proxy_request_passes_body_bytes_when_debug_mode(self):
        """Test _send_proxy_request() returns body_bytes=b"..." → proxy_request() passes through bytes."""
        provider = self.create_mock_provider()
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.is_success = False

        mock_client.build_request = MagicMock(return_value=mock_request)

        expected_check_result = CheckResult(
            available=False,
            error_reason=ErrorReason.BAD_REQUEST,
            status_code=400,
            response_time=0.5,
        )
        expected_body_bytes = b'{"error": {"message": "Bad request"}}'

        # Mock _send_proxy_request to return body_bytes with actual bytes (debug mode)
        provider._send_proxy_request = AsyncMock(
            return_value=(mock_response, expected_check_result, expected_body_bytes)
        )

        token = "test_token"
        method = "POST"
        headers = {"Content-Type": "application/json"}
        path = "chat/completions"
        query_params = ""
        content = b'{"model": "gpt-4", "messages": []}'

        _response, _check_result, body_bytes = await provider.proxy_request(
            mock_client, token, method, headers, path, query_params, content
        )

        # Verify third element contains the body bytes from debug mode
        assert body_bytes is not None
        assert isinstance(body_bytes, bytes)
        assert body_bytes == expected_body_bytes
