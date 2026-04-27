from unittest.mock import patch

import pytest

from src.core.constants import DebugMode
from src.services.gateway_service import _log_debug_info


@pytest.mark.asyncio
async def test_debug_logging_function():
    """Test that the debug logging function works as expected."""
    with patch("src.services.gateway_service.logger") as mock_logger:
        # Test no_content mode (replaces headers_only; now also logs body)
        _log_debug_info(
            debug_mode="no_content",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"test body",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"test response body",
        )

        # Should log 6 messages: request line, request headers, request body,
        # response line, response headers, response body
        assert mock_logger.info.call_count == 6

        # Reset mock
        mock_logger.info.reset_mock()

        # Test full_body mode
        _log_debug_info(
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
    # Verify NO_CONTENT value
    assert DebugMode.NO_CONTENT.value == "no_content"

    # Verify HEADERS_ONLY does NOT exist (removed in refactor)
    with pytest.raises(AttributeError):
        DebugMode.HEADERS_ONLY


@pytest.mark.asyncio
async def test_log_debug_info_bytes_formatting():
    """
    Test: verify that the fixed implementation logs bytes as decoded strings,
    no_content mode applies redaction, and newlines are collapsed.
    """
    with patch("src.services.gateway_service.logger") as mock_logger:
        # --- full_body mode: basic decoding ---
        _log_debug_info(
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

        # Reset mock for next sub-test
        mock_logger.info.reset_mock()

    # --- no_content mode: body is logged (with redaction applied upstream) ---
    with patch("src.services.gateway_service.logger") as mock_logger:
        _log_debug_info(
            debug_mode="no_content",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"test request body",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"test response body",
        )

        # no_content now also logs body → 6 calls
        assert mock_logger.info.call_count == 6
        calls = mock_logger.info.call_args_list
        request_body_log = calls[2][0][0]
        response_body_log = calls[5][0][0]
        # Body content is still present (redaction happens upstream in _debug_and_respond)
        assert "test request body" in request_body_log
        assert "test response body" in response_body_log

        # Reset mock for next sub-test
        mock_logger.info.reset_mock()

    # --- newline collapse: \n → \\n in body strings ---
    with patch("src.services.gateway_service.logger") as mock_logger:
        _log_debug_info(
            debug_mode="full_body",
            instance_name="test_provider",
            request_method="POST",
            request_path="/test",
            request_headers={"test": "header"},
            request_body=b"line1\nline2\nline3",
            response_status=200,
            response_headers={"test": "response_header"},
            response_body=b"rline1\nrline2",
        )

        calls = mock_logger.info.call_args_list
        request_body_log = calls[2][0][0]
        response_body_log = calls[5][0][0]
        # Newlines should be collapsed to literal \\n
        assert "\\n" in request_body_log
        assert "\n" not in request_body_log  # actual newline should not appear
        assert "\\n" in response_body_log
        assert "\n" not in response_body_log
