from unittest.mock import patch

import pytest

from src.services.gateway_service import _log_debug_info


@pytest.mark.asyncio
async def test_debug_logging_function():
    """Test that the debug logging function works as expected."""
    with patch("src.services.gateway_service.logger") as mock_logger:
        # Test headers_only mode
        await _log_debug_info(
            debug_mode="headers_only",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"test body",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"test response body",
        )

        # Should log 4 messages: request line, request headers, response line, response headers
        assert mock_logger.info.call_count == 4

        # Reset mock
        mock_logger.info.reset_mock()

        # Test full_body mode
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"test body",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"test response body",
        )

        # Should log 6 messages: request line, request headers, request body, response line, response headers, response body
        assert mock_logger.info.call_count == 6


def test_debug_mode_constants():
    """Test that debug mode constants are defined correctly."""
    from src.services.gateway_service import MAX_DEBUG_BODY_SIZE

    assert MAX_DEBUG_BODY_SIZE == 10 * 1024  # 10KB


@pytest.mark.asyncio
async def test_log_debug_info_bytes_formatting():
    """
    Test: verify that the fixed implementation logs bytes as decoded strings.
    This test should pass after refactoring, confirming the bug is fixed.
    """
    with patch("src.services.gateway_service.logger") as mock_logger:
        await _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"test request body",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"test response body",
        )

        # Capture all logged messages
        calls = mock_logger.info.call_args_list
        # We expect 6 logs: request line, request headers, request body, response line, response headers, response body
        assert len(calls) == 6

        # Find the request body log call (third call)
        request_body_log = calls[2][0][0]
        # Find the response body log call (sixth call)
        response_body_log = calls[5][0][0]

        # Assert that the logs contain decoded string representation (fixed behavior)
        assert "test request body" in request_body_log
        assert "test response body" in response_body_log

        # Additional sanity checks: logs should NOT contain b'...' prefix
        assert not request_body_log.startswith("Request body: b'")
        assert not response_body_log.startswith("Response body: b'")
