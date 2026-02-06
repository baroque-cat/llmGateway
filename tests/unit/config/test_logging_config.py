from unittest.mock import patch

import pytest

from src.services.gateway_service import _log_debug_info


@pytest.mark.asyncio
async def test_log_debug_info_headers_only():
    """Test that _log_debug_info logs headers only in headers_only mode."""
    with patch("src.services.gateway_service.logger") as mock_logger:
        await _log_debug_info(
            debug_mode="headers_only",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={
                "content-type": "application/json",
                "authorization": "Bearer test",
            },
            request_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}',
            response_status=200,
            response_headers={
                "content-type": "application/json",
                "content-length": "123",
            },
            response_body=b'{"choices": [{"message": {"content": "response"}}]}',
        )

        # Should log request and response info, but not bodies
        assert (
            mock_logger.info.call_count == 4
        )  # request line, request headers, response line, response headers
        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any(
            "Request to test_provider: POST /v1/chat/completions" in call
            for call in call_args
        )
        assert any("Request headers:" in call for call in call_args)
        assert any("Response from test_provider: 200" in call for call in call_args)
        assert any("Response headers:" in call for call in call_args)
        assert not any("Request body:" in call for call in call_args)
        assert not any("Response body:" in call for call in call_args)


@pytest.mark.asyncio
async def test_log_debug_info_full_body():
    """Test that _log_debug_info logs full bodies in full_body mode."""
    with patch("src.services.gateway_service.logger") as mock_logger:
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={
                "content-type": "application/json",
                "authorization": "Bearer test",
            },
            request_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}',
            response_status=200,
            response_headers={
                "content-type": "application/json",
                "content-length": "123",
            },
            response_body=b'{"choices": [{"message": {"content": "response"}}]}',
        )

        # Should log request and response info, including bodies
        assert (
            mock_logger.info.call_count == 6
        )  # request line, request headers, request body, response line, response headers, response body
        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any(
            "Request to test_provider: POST /v1/chat/completions" in call
            for call in call_args
        )
        assert any("Request headers:" in call for call in call_args)
        assert any("Request body:" in call for call in call_args)
        assert any("Response from test_provider: 200" in call for call in call_args)
        assert any("Response headers:" in call for call in call_args)
        assert any("Response body:" in call for call in call_args)


@pytest.mark.asyncio
async def test_log_debug_info_body_truncation():
    """Test that _log_debug_info truncates large bodies."""
    with patch("src.services.gateway_service.logger") as mock_logger:
        large_body = b"x" * 20000  # 20KB, should be truncated to 10KB
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/v1/chat/completions",
            request_headers={"content-type": "application/json"},
            request_body=large_body,
            response_status=200,
            response_headers={"content-type": "application/json"},
            response_body=large_body,
        )

        call_args = [call[0][0] for call in mock_logger.info.call_args_list]
        request_body_calls = [call for call in call_args if "Request body:" in call]
        response_body_calls = [call for call in call_args if "Response body:" in call]

        assert len(request_body_calls) == 1
        assert len(response_body_calls) == 1
        assert b"... (truncated)" in request_body_calls[0].encode()
        assert b"... (truncated)" in response_body_calls[0].encode()
