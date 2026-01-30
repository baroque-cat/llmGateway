#!/usr/bin/env python3

"""
Edge case tests for error parsing functionality.

This module tests extreme scenarios, performance, and unusual conditions
that might not be covered in regular tests.
"""

import json
import time
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from src.providers.impl.openai_like import OpenAILikeProvider
from src.config.schemas import ProviderConfig, GatewayPolicyConfig, ErrorParsingConfig, ErrorParsingRule
from src.core.enums import ErrorReason
from src.core.models import CheckResult


class TestErrorParsingEdgeCases:
    """Test suite for edge case error parsing scenarios."""
    
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
    
    @pytest.mark.asyncio
    async def test_large_response_body(self):
        """
        Test error parsing with a very large response body (10MB+).
        
        Ensures that large response bodies don't cause memory issues
        or timeouts during error parsing.
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
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Create a large JSON response (10MB)
        large_payload = {
            "error": {
                "code": "insufficient_quota",
                "message": "You have insufficient quota",
                "details": "x" * 10 * 1024 * 1024  # 10MB of details
            }
        }
        error_body = json.dumps(large_payload).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        # Should still parse successfully
        result = await provider._parse_proxy_error(mock_response)
        
        assert isinstance(result, CheckResult)
        assert not result.available
        assert result.error_reason == ErrorReason.NO_QUOTA
        assert result.status_code == 400
    
    @pytest.mark.asyncio
    async def test_concurrent_rule_matching(self):
        """
        Test that error parsing works correctly with many concurrent rules.
        
        Simulates a configuration with many rules (50+) to ensure
        performance is acceptable and priority sorting works.
        """
        # Create many rules with different priorities and patterns
        rules = []
        for i in range(50):
            rules.append(
                ErrorParsingRule(
                    status_code=400,
                    error_path=f"error.code_{i}",
                    match_pattern=f"pattern_{i}",
                    map_to="bad_request",
                    priority=i
                )
            )
        
        # Add one high-priority rule that should match
        rules.append(
            ErrorParsingRule(
                status_code=400,
                error_path="error.code",
                match_pattern="target_pattern",
                map_to="invalid_key",
                priority=100
            )
        )
        
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=rules
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        error_body = json.dumps({
            "error": {
                "code": "target_pattern",
                "message": "Target error"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        # Start timing
        start_time = time.time()
        result = await provider._parse_proxy_error(mock_response)
        end_time = time.time()
        
        # Should match the high-priority rule
        assert result.error_reason == ErrorReason.INVALID_KEY
        
        # Should complete in reasonable time (under 100ms)
        elapsed = end_time - start_time
        assert elapsed < 0.1, f"Rule matching took {elapsed:.3f}s, expected < 0.1s"
    
    @pytest.mark.asyncio
    async def test_deeply_nested_json_path(self):
        """
        Test error parsing with deeply nested JSON paths.
        
        Ensures the path extraction can handle complex nested structures.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="deeply.nested.structure.error.code",
                        match_pattern="deep_error",
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        error_body = json.dumps({
            "deeply": {
                "nested": {
                    "structure": {
                        "error": {
                            "code": "deep_error",
                            "message": "Deep nested error"
                        }
                    }
                }
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        result = await provider._parse_proxy_error(mock_response)
        
        assert result.error_reason == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_malformed_content_type(self):
        """
        Test error parsing with malformed or unexpected content types.
        
        Ensures error parsing works even when content-type headers
        are missing, malformed, or non-JSON.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="quota_exceeded",
                        map_to="no_quota"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Valid JSON but with non-JSON content type
        error_body = json.dumps({
            "error": {
                "code": "quota_exceeded",
                "message": "Quota exceeded"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        # Test various content types
        content_types = [
            None,  # No content-type header
            "text/plain",
            "application/xml",
            "binary/octet-stream",
            "text/html",
        ]
        
        for content_type in content_types:
            if content_type:
                mock_response.headers = {"content-type": content_type}
            else:
                mock_response.headers = {}
            
            result = await provider._parse_proxy_error(mock_response)
            
            # Should still parse the JSON regardless of content-type
            assert result.error_reason == ErrorReason.NO_QUOTA
    
    @pytest.mark.asyncio
    async def test_invalid_regex_pattern(self):
        """
        Test error parsing with invalid regex patterns in rules.
        
        Ensures the system gracefully handles regex compilation errors
        and falls back to default error reason.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern="[invalid-regex",  # Invalid regex
                        map_to="invalid_key",
                        priority=10
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="valid_pattern",
                        map_to="no_quota",
                        priority=5
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        error_body = json.dumps({
            "error": {
                "code": "valid_pattern",
                "message": "Valid error"
            }
        }).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=error_body)
        
        # Should skip the invalid regex rule and match the valid one
        result = await provider._parse_proxy_error(mock_response)
        
        assert result.error_reason == ErrorReason.NO_QUOTA
    
    @pytest.mark.asyncio
    async def test_memory_efficiency(self):
        """
        Test that error parsing doesn't create memory leaks with repeated calls.
        
        Simulates many error parsing calls to ensure memory usage is stable.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="test_error",
                        map_to="bad_request"
                    )
                ]
            )
        )
        
        # Run parsing many times
        for i in range(100):
            mock_response = AsyncMock(spec=httpx.Response)
            mock_response.status_code = 400
            mock_response.elapsed = MagicMock()
            mock_response.elapsed.total_seconds.return_value = 0.5
            
            error_body = json.dumps({
                "error": {
                    "code": "test_error",
                    "message": f"Error iteration {i}"
                }
            }).encode('utf-8')
            mock_response.aread = AsyncMock(return_value=error_body)
            
            result = await provider._parse_proxy_error(mock_response)
            
            assert result.error_reason == ErrorReason.BAD_REQUEST
            assert result.status_code == 400
    
    @pytest.mark.asyncio
    async def test_mixed_status_code_rules(self):
        """
        Test error parsing with rules for multiple different status codes.
        
        Ensures rules are properly filtered by status code.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="bad_request_error",
                        map_to="bad_request"
                    ),
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit_error",
                        map_to="rate_limited"
                    ),
                    ErrorParsingRule(
                        status_code=500,
                        error_path="error.code",
                        match_pattern="server_error",
                        map_to="server_error"
                    )
                ]
            )
        )
        
        # Test each status code
        test_cases = [
            (400, "bad_request_error", ErrorReason.BAD_REQUEST),
            (429, "rate_limit_error", ErrorReason.RATE_LIMITED),
            (500, "server_error", ErrorReason.SERVER_ERROR),
        ]
        
        for status_code, error_code, expected_reason in test_cases:
            mock_response = AsyncMock(spec=httpx.Response)
            mock_response.status_code = status_code
            mock_response.elapsed = MagicMock()
            mock_response.elapsed.total_seconds.return_value = 0.5
            
            error_body = json.dumps({
                "error": {
                    "code": error_code,
                    "message": f"{error_code} message"
                }
            }).encode('utf-8')
            mock_response.aread = AsyncMock(return_value=error_body)
            
            result = await provider._parse_proxy_error(mock_response)
            
            assert result.error_reason == expected_reason, \
                f"Status {status_code} with code {error_code} should map to {expected_reason}, got {result.error_reason}"
    
    @pytest.mark.asyncio
    async def test_error_parsing_with_empty_response_body(self):
        """
        Test error parsing when response body is empty or None.
        
        Ensures graceful handling of empty responses.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern=".*",
                        map_to="bad_request"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Test empty body cases
        test_bodies = [
            b"",      # Empty bytes
            b"null",  # JSON null
            b"{}",    # Empty object
        ]
        
        for body in test_bodies:
            mock_response.aread = AsyncMock(return_value=body)
            result = await provider._parse_proxy_error(mock_response)
            
            # Should fall back to default mapping (BAD_REQUEST for 400)
            assert result.error_reason == ErrorReason.BAD_REQUEST
            assert result.status_code == 400
    
    @pytest.mark.asyncio
    async def test_unicode_and_special_characters(self):
        """
        Test error parsing with Unicode and special characters in error messages.
        
        Ensures proper handling of non-ASCII characters in error paths and patterns.
        """
        provider = self.create_mock_openai_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern="逾期|überzogen|過払い",  # Multilingual patterns
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.elapsed = MagicMock()
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        # Test each Unicode pattern
        test_messages = [
            "您的账户已逾期",           # Chinese
            "Ihr Konto ist überzogen",  # German
            "お支払いが過払いです",       # Japanese
        ]
        
        for message in test_messages:
            error_body = json.dumps({
                "error": {
                    "message": message,
                    "code": "payment_issue"
                }
            }).encode('utf-8')
            mock_response.aread = AsyncMock(return_value=error_body)
            
            result = await provider._parse_proxy_error(mock_response)
            
            # Should match the Unicode pattern
            assert result.error_reason == ErrorReason.INVALID_KEY