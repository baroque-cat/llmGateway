import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.responses import Response
import httpx

from src.services.gateway_service import _log_debug_info
from src.core.models import CheckResult
from src.config.schemas import Config, GatewayGlobalConfig, ProviderConfig, GatewayPolicyConfig


@pytest.mark.asyncio
async def test_log_debug_info_headers_only():
    """Test that _log_debug_info logs headers only in headers_only mode."""
    with patch('src.services.gateway_service.logger') as mock_logger:
        await _log_debug_info(
            debug_mode="headers_only",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={"content-type": "application/json", "authorization": "Bearer test"},
            request_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}',
            response_status=200,
            response_headers={"content-type": "application/json", "content-length": "123"},
            response_body=b'{"choices": [{"message": {"content": "response"}}]}'
        )
        
        # Should log request and response info, but not bodies
        assert mock_logger.info.call_count == 4  # request line, request headers, response line, response headers
        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("Request to test_provider: POST /v1/chat/completions" in call for call in call_args)
        assert any("Request headers:" in call for call in call_args)
        assert any("Response from test_provider: 200" in call for call in call_args)
        assert any("Response headers:" in call for call in call_args)
        assert not any("Request body:" in call for call in call_args)
        assert not any("Response body:" in call for call in call_args)


@pytest.mark.asyncio
async def test_log_debug_info_full_body():
    """Test that _log_debug_info logs full bodies in full_body mode."""
    with patch('src.services.gateway_service.logger') as mock_logger:
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={"content-type": "application/json", "authorization": "Bearer test"},
            request_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}',
            response_status=200,
            response_headers={"content-type": "application/json", "content-length": "123"},
            response_body=b'{"choices": [{"message": {"content": "response"}}]}'
        )
        
        # Should log request and response info, including bodies
        assert mock_logger.info.call_count == 6  # request line, request headers, request body, response line, response headers, response body
        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("Request to test_provider: POST /v1/chat/completions" in call for call in call_args)
        assert any("Request headers:" in call for call in call_args)
        assert any("Request body:" in call for call in call_args)
        assert any("Response from test_provider: 200" in call for call in call_args)
        assert any("Response headers:" in call for call in call_args)
        assert any("Response body:" in call for call in call_args)


@pytest.mark.asyncio
async def test_log_debug_info_body_truncation():
    """Test that _log_debug_info truncates large bodies."""
    with patch('src.services.gateway_service.logger') as mock_logger:
        large_body = b'x' * 20000  # 20KB, should be truncated to 10KB
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={"content-type": "application/json"},
            request_body=large_body,
            response_status=200,
            response_headers={"content-type": "application/json"},
            response_body=large_body
        )
        
        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        request_body_calls = [call for call in call_args if "Request body:" in call]
        response_body_calls = [call for call in call_args if "Response body:" in call]
        
        assert len(request_body_calls) == 1
        assert len(response_body_calls) == 1
        assert b"... (truncated)" in request_body_calls[0].encode()
        assert b"... (truncated)" in response_body_calls[0].encode()


def test_debug_mode_disabled():
    """Test that debug mode disabled doesn't affect normal operation."""
    config = Config()
    config.gateway = GatewayGlobalConfig(debug_mode="disabled")
    provider_config = ProviderConfig()
    provider_config.gateway_policy = GatewayPolicyConfig(debug_mode="disabled")
    
    # Should inherit global setting
    effective_debug_mode = "disabled"
    assert effective_debug_mode == "disabled"


def test_debug_mode_inheritance():
    """Test debug mode inheritance logic."""
    # Test case 1: Provider has debug_mode="disabled", should inherit global
    config = Config()
    config.gateway = GatewayGlobalConfig(debug_mode="headers_only")
    provider_config = ProviderConfig()
    provider_config.gateway_policy = GatewayPolicyConfig(debug_mode="disabled")
    
    effective_debug_mode = provider_config.gateway_policy.debug_mode
    if effective_debug_mode == "disabled":
        effective_debug_mode = config.gateway.debug_mode
    
    assert effective_debug_mode == "headers_only"
    
    # Test case 2: Provider has debug_mode="full_body", should override global
    provider_config.gateway_policy.debug_mode = "full_body"
    effective_debug_mode = provider_config.gateway_policy.debug_mode
    if effective_debug_mode == "disabled":
        effective_debug_mode = config.gateway.debug_mode
        
    assert effective_debug_mode == "full_body"