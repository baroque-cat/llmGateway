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
