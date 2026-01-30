#!/usr/bin/env python3

"""
Tests for base provider error parsing logic.

This module tests the core error parsing functionality in AIBaseProvider,
including JSON value extraction and error reason refinement based on
configured parsing rules.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, Optional, List, Tuple
import pytest
import httpx

from src.providers.base import AIBaseProvider
from src.config.schemas import ProviderConfig, GatewayPolicyConfig, ErrorParsingConfig, ErrorParsingRule
from src.core.enums import ErrorReason
from src.core.models import CheckResult, RequestDetails


class MockAIBaseProvider(AIBaseProvider):
    """
    Mock implementation of AIBaseProvider for testing.
    
    Implements all abstract methods with minimal functionality.
    """
    
    def _get_headers(self, token: str) -> Optional[Dict[str, str]]:
        return {}
    
    async def _parse_proxy_error(self, response: httpx.Response) -> CheckResult:
        return CheckResult.fail(ErrorReason.UNKNOWN)
    
    async def check(self, client: httpx.AsyncClient, token: str, **kwargs) -> CheckResult:
        return CheckResult.success()
    
    async def inspect(self, client: httpx.AsyncClient, token: str, **kwargs) -> List[str]:
        return []
    
    async def parse_request_details(self, path: str, content: bytes) -> RequestDetails:
        return RequestDetails(model_name="test")
    
    async def proxy_request(
        self, 
        client: httpx.AsyncClient, 
        token: str, 
        method: str, 
        headers: Dict, 
        path: str, 
        query_params: str, 
        content: bytes
    ) -> Tuple[httpx.Response, CheckResult]:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        return mock_response, CheckResult.success()


class TestErrorParsingBase:
    """Test suite for base provider error parsing functionality."""
    
    def create_mock_provider(self, error_config=None):
        """Helper to create a mock provider with given error parsing configuration."""
        mock_config = MagicMock(spec=ProviderConfig)
        mock_config.gateway_policy = MagicMock(spec=GatewayPolicyConfig)
        
        if error_config is None:
            error_config = ErrorParsingConfig(enabled=False, rules=[])
        
        mock_config.gateway_policy.error_parsing = error_config
        
        # Create provider instance using our mock implementation
        provider = MockAIBaseProvider("test_provider", mock_config)
        return provider
    
    # --- Tests for _extract_json_value ---
    
    def test_extract_json_value_simple_path(self):
        """Test extracting values with simple dot-separated paths."""
        provider = self.create_mock_provider()
        
        data = {
            "error": {
                "type": "Arrearage",
                "code": 1001,
                "message": "Payment overdue"
            }
        }
        
        # Test valid paths
        assert provider._extract_json_value(data, "error.type") == "Arrearage"
        assert provider._extract_json_value(data, "error.code") == 1001
        assert provider._extract_json_value(data, "error.message") == "Payment overdue"
        
        # Test non-existent path
        assert provider._extract_json_value(data, "error.nonexistent") is None
        assert provider._extract_json_value(data, "nonexistent.field") is None
        
        # Test empty path
        assert provider._extract_json_value(data, "") is None
    
    def test_extract_json_value_nested_path(self):
        """Test extracting values from deeply nested structures."""
        provider = self.create_mock_provider()
        
        data = {
            "response": {
                "error": {
                    "details": {
                        "type": "billing",
                        "subtype": "hard_limit"
                    }
                }
            }
        }
        
        assert provider._extract_json_value(data, "response.error.details.type") == "billing"
        assert provider._extract_json_value(data, "response.error.details.subtype") == "hard_limit"
        assert provider._extract_json_value(data, "response.error.details") == {"type": "billing", "subtype": "hard_limit"}
        
        # Partial path that exists but leads to non-dict
        data2 = {"a": {"b": "value"}}
        assert provider._extract_json_value(data2, "a.b.c") is None
    
    def test_extract_json_value_non_dict_data(self):
        """Test extraction with non-dictionary data structures."""
        provider = self.create_mock_provider()
        
        # Data is not a dict at some level
        data = {"error": "simple string"}
        assert provider._extract_json_value(data, "error.type") is None
        
        # Data is a list
        data = {"errors": [{"code": 1001}, {"code": 1002}]}
        # Lists are not supported in current implementation
        assert provider._extract_json_value(data, "errors.0.code") is None
        
        # Data is None - method expects Dict[str, Any], but we test edge case
        # We'll skip this test as it's not valid for the method signature
        pass
    
    # --- Tests for _refine_error_reason ---
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_disabled(self):
        """Test that disabled error parsing returns default reason."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(enabled=False, rules=[])
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST
        )
        
        assert result == ErrorReason.BAD_REQUEST
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_no_rules_for_status(self):
        """Test that no matching rules returns default reason."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit",
                        map_to="rate_limited"
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400  # No rule for 400
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST
        )
        
        assert result == ErrorReason.BAD_REQUEST
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_simple_match(self):
        """Test simple rule matching with JSON response."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        # Mock response body
        response_data = {
            "error": {
                "type": "Arrearage",
                "message": "Payment overdue"
            }
        }
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data
        )
        
        assert result == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_priority_ordering(self):
        """Test that higher priority rules win."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="insufficient_quota",
                        map_to="no_quota",
                        priority=5
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10  # Higher priority
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        # Response matches BOTH rules (different paths)
        response_data = {
            "error": {
                "type": "Arrearage",
                "code": "insufficient_quota"
            }
        }
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data
        )
        
        # Should use higher priority rule (invalid_key)
        assert result == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_regex_matching(self):
        """Test regex pattern matching in rules."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.message",
                        match_pattern="quota.*exceeded|limit.*reached",
                        map_to="no_quota",
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        # Test different messages that should match
        test_cases = [
            ("Your quota has been exceeded", ErrorReason.NO_QUOTA),
            ("API limit reached for today", ErrorReason.NO_QUOTA),
            ("Daily limit reached", ErrorReason.NO_QUOTA),
            ("Some other error", ErrorReason.BAD_REQUEST),  # Should not match
        ]
        
        for message, expected in test_cases:
            response_data = {"error": {"message": message}}
            result = await provider._refine_error_reason(
                response=mock_response,
                default_reason=ErrorReason.BAD_REQUEST,
                response_data=response_data
            )
            assert result == expected, f"Failed for message: {message}"
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_case_insensitive(self):
        """Test that regex matching is case-insensitive."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="arrearage",
                        map_to="invalid_key",  # Lowercase pattern
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        # Response has uppercase
        response_data = {"error": {"type": "ARREARAGE"}}
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data
        )
        
        assert result == ErrorReason.INVALID_KEY
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_invalid_map_to_value(self):
        """Test handling of invalid map_to values in rules."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="TestError",
                        map_to="invalid_error_reason",  # Not a valid ErrorReason
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        response_data = {"error": {"type": "TestError"}}
        
        # Patch logger to capture warning
        with patch('src.providers.base.logger') as mock_logger:
            result = await provider._refine_error_reason(
                response=mock_response,
                default_reason=ErrorReason.BAD_REQUEST,
                response_data=response_data
            )
            
            # Should fall back to default reason
            assert result == ErrorReason.BAD_REQUEST
            
            # Should log a warning
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "invalid_error_reason" in warning_msg
            assert "test_provider" in warning_msg
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_body_parsing(self):
        """Test that response body is parsed when not provided."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = AsyncMock()
        mock_response.status_code = 400
        
        # Mock aread() to return JSON body
        body_json = json.dumps({"error": {"type": "Arrearage"}}).encode('utf-8')
        mock_response.aread = AsyncMock(return_value=body_json)
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST
        )
        
        assert result == ErrorReason.INVALID_KEY
        mock_response.aread.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_empty_body(self):
        """Test handling of empty response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern=".*",
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.aread = AsyncMock(return_value=b'')  # Empty body
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST
        )
        
        # Should return default reason when body is empty
        assert result == ErrorReason.BAD_REQUEST
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_invalid_json(self):
        """Test handling of invalid JSON in response body."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern=".*",
                        map_to="invalid_key"
                    )
                ]
            )
        )
        
        mock_response = AsyncMock()
        mock_response.status_code = 400
        mock_response.aread = AsyncMock(return_value=b'Invalid JSON {')
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST
        )
        
        # Should return default reason when JSON is invalid
        assert result == ErrorReason.BAD_REQUEST
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_pre_read_body_bytes(self):
        """Test using pre-read body bytes to avoid re-reading."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key",
                        priority=10
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        # Pre-read body bytes
        body_bytes = json.dumps({"error": {"type": "Arrearage"}}).encode('utf-8')
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            body_bytes=body_bytes
        )
        
        assert result == ErrorReason.INVALID_KEY
        # aread() should not be called when body_bytes is provided
        assert not hasattr(mock_response, 'aread') or not mock_response.aread.called
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_rule_evaluation_error(self):
        """Test handling of errors during rule evaluation."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="[",  # Invalid regex
                        map_to="invalid_key"
                    ),
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.code",
                        match_pattern="valid_pattern",
                        map_to="no_quota"
                    )
                ]
            )
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        response_data = {
            "error": {
                "type": "Arrearage",
                "code": "valid_pattern"
            }
        }
        
        result = await provider._refine_error_reason(
            response=mock_response,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data
        )
        
        # First rule has invalid regex, second rule should match
        assert result == ErrorReason.NO_QUOTA
    
    @pytest.mark.asyncio
    async def test_refine_error_reason_multiple_status_codes(self):
        """Test rules filtering by status code."""
        provider = self.create_mock_provider(
            error_config=ErrorParsingConfig(
                enabled=True,
                rules=[
                    ErrorParsingRule(
                        status_code=400,
                        error_path="error.type",
                        match_pattern="Arrearage",
                        map_to="invalid_key"
                    ),
                    ErrorParsingRule(
                        status_code=429,
                        error_path="error.code",
                        match_pattern="rate_limit",
                        map_to="rate_limited"
                    ),
                    ErrorParsingRule(
                        status_code=500,
                        error_path="error.message",
                        match_pattern="server_error",
                        map_to="server_error"
                    )
                ]
            )
        )
        
        # Test 400 response
        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        response_data_400 = {"error": {"type": "Arrearage"}}
        
        result_400 = await provider._refine_error_reason(
            response=mock_response_400,
            default_reason=ErrorReason.BAD_REQUEST,
            response_data=response_data_400
        )
        assert result_400 == ErrorReason.INVALID_KEY
        
        # Test 429 response
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        response_data_429 = {"error": {"code": "rate_limit"}}
        
        result_429 = await provider._refine_error_reason(
            response=mock_response_429,
            default_reason=ErrorReason.RATE_LIMITED,
            response_data=response_data_429
        )
        assert result_429 == ErrorReason.RATE_LIMITED
        
        # Test 500 response (no matching data, should return default)
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        response_data_500 = {"error": {"message": "different error"}}
        
        result_500 = await provider._refine_error_reason(
            response=mock_response_500,
            default_reason=ErrorReason.SERVER_ERROR,
            response_data=response_data_500
        )
        assert result_500 == ErrorReason.SERVER_ERROR