#!/usr/bin/env python3

"""
Tests for Anthropic provider error handling.

This module tests the error handling functionality in the AnthropicProvider class,
ensuring that error parsing and status code mapping work correctly.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config.schemas import (
    ErrorParsingConfig,
    ErrorParsingRule,
    GatewayPolicyConfig,
    HealthPolicyConfig,
    ProviderConfig,
)
from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.providers.impl.anthropic import AnthropicProvider


class TestAnthropicErrorHandling:
    """Test suite for Anthropic provider error handling."""

    def create_mock_provider(
        self, error_config=None, health_policy=None, gateway_policy=None
    ):
        """Helper to create a mock AnthropicProvider with given configuration."""
        mock_config = MagicMock(spec=ProviderConfig)

        # Setup gateway_policy
        if gateway_policy is None:
            gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.gateway_policy = gateway_policy

        # Setup worker_health_policy
        if health_policy is None:
            health_policy = MagicMock(spec=HealthPolicyConfig)
        mock_config.worker_health_policy = health_policy

        # Setup error parsing config (now at ProviderConfig level)
        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])
        mock_config.error_parsing = error_config

        # Set up other required config fields
        mock_config.provider_type = "anthropic"
        mock_config.api_base_url = "https://api.anthropic.com"
        mock_config.default_model = "claude-3-opus-20240229"
        mock_config.models = {
            "claude-3-opus-20240229": MagicMock(),
            "claude-3-sonnet-20240229": MagicMock(),
        }
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

        # Create provider instance
        provider = AnthropicProvider("test_provider", mock_config)
        return provider

    @pytest.mark.asyncio
    async def test_parse_proxy_error_without_error_parsing(self):
        """Test _parse_proxy_error when error parsing is disabled and content=None."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )

        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5

        # content=None, meaning body was NOT read
        result = await provider._parse_proxy_error(mock_response, content=None)

        # Should map to INVALID_KEY via _map_status_code_to_reason
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.response_time == 0.5
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_parse_proxy_error_with_error_parsing_rules(self):
        """Test _parse_proxy_error when error parsing rules are enabled."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="invalid_api_key",
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

        # Simulate Anthropic error response
        error_body = json.dumps(
            {"error": {"type": "invalid_api_key", "message": "Invalid API key"}}
        ).encode("utf-8")
        mock_response.aread = AsyncMock(return_value=error_body)

        # Patch _refine_error_reason to verify it's called with body_bytes
        with patch.object(provider, "_refine_error_reason", AsyncMock()) as mock_refine:
            mock_refine.return_value = ErrorReason.INVALID_KEY

            result = await provider._parse_proxy_error(mock_response, error_body)

            # Verify _refine_error_reason was called with body_bytes
            mock_refine.assert_called_once()
            call_args = mock_refine.call_args
            assert call_args[1]["body_bytes"] == error_body
            assert call_args[1]["default_reason"] == ErrorReason.BAD_REQUEST

            # Result should be INVALID_KEY
            assert isinstance(result, CheckResult)
            assert not result.available
            assert result.error_reason == ErrorReason.INVALID_KEY
            assert result.response_time == 0.5
            assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_empty_response_body(self):
        """Test _parse_proxy_error with empty response body when error parsing enabled."""
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

        # Should fall back to default mapping (BAD_REQUEST)
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_proxy_error_invalid_json_body(self):
        """Test _parse_proxy_error with invalid JSON in body when error parsing enabled."""
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

        # Should fall back to default mapping (BAD_REQUEST)
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert result.response_time == 0.5
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_check_successful_key_validation(self):
        """Test check method with successful HTTP 200 response."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.3
        mock_response.raise_for_status = MagicMock()

        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert isinstance(result, CheckResult)
        assert result.available
        assert result.error_reason == ErrorReason.UNKNOWN
        assert result.response_time == 0.3
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_check_invalid_key_401(self):
        """Test check method with HTTP 401 (invalid key)."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 401
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_check_rate_limit_429(self):
        """Test check method with HTTP 429 (rate limit)."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.RATE_LIMITED
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_check_quota_exhausted_402(self):
        """Test check method with HTTP 402 (quota exhausted)."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 402
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "402 Payment Required",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client.get = AsyncMock(return_value=mock_response)

        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )

        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 402

    @pytest.mark.asyncio
    async def test_check_network_errors(self):
        """Test check method with network errors (TimeoutException, ConnectError)."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        # Test TimeoutException
        mock_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )
        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.TIMEOUT
        assert result.status_code == 408

        # Test ConnectError
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
        result = await provider.check(
            mock_client, "test_token", model="claude-3-opus-20240229"
        )
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.NETWORK_ERROR
        assert result.status_code == 503

    @pytest.mark.asyncio
    async def test_check_missing_model_parameter(self):
        """Test check method when model parameter is missing."""
        provider = self.create_mock_provider()

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        result = await provider.check(mock_client, "test_token")
        # Should return BAD_REQUEST due to missing model
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.BAD_REQUEST
        assert "Missing 'model' parameter" in result.message
