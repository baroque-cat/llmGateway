#!/usr/bin/env python3

"""
End-to-end scenario tests for error parsing functionality.

This module tests real-world error parsing scenarios, including
common provider error patterns and the interaction between
gateway and worker components.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from src.providers.impl.openai_like import OpenAILikeProvider
from src.providers.impl.gemini import GeminiProvider
from src.config.schemas import ProviderConfig, GatewayPolicyConfig, ErrorParsingConfig, ErrorParsingRule
from src.core.enums import ErrorReason
from src.core.models import CheckResult


class TestErrorParsingScenarios:
    """Test suite for end-to-end error parsing scenarios."""
    
    def create_mock_openai_provider(self, error_config):
        """Helper to create a mock OpenAILikeProvider."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.gateway_policy.error_parsing = error_config
        
        # Minimal config
        mock_config.provider_type = "openai"
        mock_config.keys_path = "/test/keys"
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
        
        return OpenAILikeProvider("test_openai", mock_config)
    
    def create_mock_gemini_provider(self, error_config):
        """Helper to create a mock GeminiProvider."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        mock_config.gateway_policy.error_parsing = error_config
        
        # Minimal config
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
        
        return GeminiProvider("test_gemini", mock_config)
    
    @pytest.mark.asyncio
    async def test_qwen_arrearage_scenario(self):
        """
        Test Qwen 'Arrearage' error scenario (400 with error.type='Arrearage').
        
        This simulates the real-world case where Qwen returns 400 Bad Request
        with error.type='Arrearage' (payment overdue), which should be mapped
        to INVALID_KEY.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage|BillingHardLimit",
                        map_to="invalid_key",
                        priority=10,
                        description="Payment overdue or billing limit"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Qwen-style error response
        error_body = json.dumps({
            "error": {
                "type": "Arrearage",
                "message": "Your account is in arrears. Please recharge your account.",
                "code": "ARREARAGE"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        result = await provider._parse_proxy_error(mock_response)
        
        # Should map to INVALID_KEY
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 400
        assert "Arrearage" in result.message or result.message == ""
    
    @pytest.mark.asyncio
    async def test_insufficient_quota_scenario(self):
        """
        Test insufficient quota error scenario (400 with error.code='insufficient_quota').
        
        This simulates providers that return quota-related errors with the same
        HTTP status code as other errors.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="insufficient_quota",
                        map_to="no_quota",
                        priority=10,
                        description="Insufficient quota or credits"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # OpenAI-style quota error
        error_body = json.dumps({
            "error": {
                "message": "You have insufficient quota for this operation.",
                "type": "insufficient_quota",
                "code": "insufficient_quota"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        result = await provider._parse_proxy_error(mock_response)
        
        # Should map to NO_QUOTA
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 400
    
    @pytest.mark.asyncio
    async def test_gemini_invalid_argument_scenario(self):
        """
        Test Gemini INVALID_ARGUMENT error scenario.
        
        Gemini returns errors with a 'status' field that can indicate
        authentication issues vs other types of errors.
        """
        provider = self.create_mock_gemini_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.status",
                        match_pattern="INVALID_ARGUMENT|PERMISSION_DENIED",
                        map_to="invalid_key",
                        priority=10,
                        description="Invalid API key or permissions"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Gemini-style authentication error
        error_body = json.dumps({
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        result = await provider._parse_proxy_error(mock_response)
        
        # Should map to INVALID_KEY
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.INVALID_KEY
        assert result.status_code == 400
    
    @pytest.mark.asyncio
    async def test_gateway_vs_worker_behavior(self):
        """
        Test that gateway and worker handle 400 errors differently.
        
        Gateway: Uses error parsing rules to refine error classification.
        Worker: In check() method, treats all 400 errors as INVALID_KEY
                (this is tested separately in unit tests).
        """
        # This test demonstrates the conceptual difference
        # Gateway behavior with error parsing disabled
        provider_disabled = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        
        # Gateway behavior with error parsing enabled
        provider_enabled = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Regular 400 error (not Arrearage)
        error_body = json.dumps({
            "error": {
                "message": "Invalid request format",
                "type": "invalid_request_error"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        # With error parsing disabled, should get BAD_REQUEST
        result_disabled = await provider_disabled._parse_proxy_error(mock_response)
        assert result_disabled.error_reason == ErrorReason.BAD_REQUEST
        
        # With error parsing enabled but no match, should also get BAD_REQUEST
        result_enabled = await provider_enabled._parse_proxy_error(mock_response)
        assert result_enabled.error_reason == ErrorReason.BAD_REQUEST
        
        # Now test with Arrearage error
        arrearage_body = json.dumps({
            "error": {
                "type": "Arrearage",
                "message": "Payment overdue"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=arrearage_body)
        
        result_arrearage = await provider_enabled._parse_proxy_error(mock_response)
        assert result_arrearage.error_reason == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_priority_handling_real_world(self):
        """
        Test priority handling with real-world overlapping rules.
        
        Simulates a scenario where multiple rules could match,
        and higher priority should win.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern=".*quota.*",
                        map_to="no_quota",
                        priority=5,
                        description="Generic quota error"
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="insufficient_quota",
                        map_to="no_quota_specific",
                        priority=15,  # Higher priority
                        description="Specific insufficient quota code"
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=20,  # Highest priority
                        description="Payment overdue"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Error that matches all three rules
        error_body = json.dumps({
            "error": {
                "type": "Arrearage",
                "code": "insufficient_quota",
                "message": "Your quota has been exceeded. Please upgrade your plan."
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        result = await provider._parse_proxy_error(mock_response)
        
        # Should use highest priority rule (INVALID_KEY for Arrearage)
        # Note: map_to="invalid_key" maps to ErrorReason.INVALID_KEY
        assert result.error_reason == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_malformed_error_response(self):
        """
        Test handling of malformed or unexpected error response structures.
        
        Error parsing should gracefully handle missing fields, wrong types,
        and other malformations.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Various malformed responses
        test_cases = [
            b'{}',  # Empty object
            b'{"error": "simple string"}',  # Error as string, not object
            b'{"error": {"message": "test"}}',  # Missing 'type' field
            b'{"error": {"type": 123}}',  # Type is number, not string
            b'{"error": null}',  # Error is null
            b'Not JSON at all',  # Not JSON
        ]
        
        for error_body in test_cases:
            mock_response.aread = AsyncMock(return_value=error_body)
            result = await provider._parse_proxy_error(mock_response)
            
            # Should still return a valid CheckResult
            assert isinstance(result, CheckResult)
            assert not result.available
            assert result.status_code == 400
            # Should fall back to default mapping (BAD_REQUEST)
            assert result.error_reason == ErrorReason.BAD_REQUEST
    
    @pytest.mark.asyncio
    async def test_error_parsing_disabled_fallback(self):
        """
        Test that when error parsing is disabled, the system falls back
        to default HTTP status code mapping.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        
        # Test various status codes using OpenAILikeProvider's default mapping
        test_cases = [
            (400, ErrorReason.BAD_REQUEST),
            (401, ErrorReason.INVALID_KEY),    # OpenAILike maps 401 to INVALID_KEY
            (403, ErrorReason.INVALID_KEY),    # OpenAILike maps 403 to INVALID_KEY
            (429, ErrorReason.RATE_LIMITED),
            (500, ErrorReason.SERVER_ERROR),
            (503, ErrorReason.OVERLOADED),     # OpenAILike maps 503 to OVERLOADED
        ]
        
        for status_code, expected_reason in test_cases:
            mock_response = AsyncMock(spec=httpx.Response)
            mock_response.status_code = status_code
            mock_response.elapsed = MagicMock()
            mock_response.elapsed.total_seconds.return_value = 0.5
            mock_response.aread = AsyncMock(return_value=b'{"error": {"message": "test"}}')
            
            result = await provider._parse_proxy_error(mock_response)
            assert result.error_reason == expected_reason, \
                f"Status {status_code} should map to {expected_reason}, got {result.error_reason}"