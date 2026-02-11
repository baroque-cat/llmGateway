"""
Unit tests for the StreamMonitor class in gateway_service.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.core.constants import ALL_MODELS_MARKER, ErrorReason
from src.core.models import CheckResult
from src.services.gateway_service import StreamMonitor


class TestStreamMonitor:
    """Tests for the StreamMonitor class."""

    @pytest.fixture
    def mock_httpx_response(self):
        """Provide a mocked httpx.Response."""
        response = AsyncMock(spec=httpx.Response)
        response.status_code = 200
        response.reason_phrase = "OK"
        response.headers = {"content-type": "application/json"}
        response.aclose = AsyncMock()
        return response

    @pytest.fixture
    def mock_logger(self):
        """Mock the module logger."""
        with patch("src.services.gateway_service.logger") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_stream_monitor_success(self, mock_httpx_response, mock_logger):
        """Test streaming success with valid check result."""

        # Simulate a streaming response with two chunks
        async def chunk_iterator():
            yield b"chunk1"
            yield b"chunk2"

        mock_httpx_response.aiter_bytes.return_value = chunk_iterator()
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )
        # Collect chunks
        chunks = []
        async for chunk in monitor:
            chunks.append(chunk)
        assert chunks == [b"chunk1", b"chunk2"]
        # Verify final logging
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "GATEWAY_ACCESS" in log_message
        assert "127.0.0.1" in log_message
        assert "POST /v1/chat/completions" in log_message
        assert "openai:gpt-4" in log_message
        assert "200 OK -> VALID" in log_message
        # Ensure upstream response is closed
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_monitor_error(self, mock_httpx_response, mock_logger):
        """Test streaming with key error (INVALID_KEY)."""

        async def chunk_iterator():
            yield b"error chunk"

        mock_httpx_response.aiter_bytes.return_value = chunk_iterator()
        mock_httpx_response.status_code = 401
        mock_httpx_response.reason_phrase = "Unauthorized"
        check_result = CheckResult.fail(ErrorReason.INVALID_KEY)
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="192.168.1.1",
            request_method="POST",
            request_path="/v1/completions",
            provider_name="openai",
            model_name="gpt-3.5-turbo",
            check_result=check_result,
        )
        chunks = []
        async for chunk in monitor:
            chunks.append(chunk)
        assert chunks == [b"error chunk"]
        # Verify logging includes error status
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "INVALID_KEY" in log_message
        assert "401 Unauthorized" in log_message
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_monitor_exception_during_stream(
        self, mock_httpx_response, mock_logger
    ):
        """Test that exceptions during streaming are logged and re-raised."""

        async def chunk_iterator():
            yield b"first"
            raise RuntimeError("Stream broken")

        mock_httpx_response.aiter_bytes.return_value = chunk_iterator()
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="10.0.0.1",
            request_method="GET",
            request_path="/v1/models",
            provider_name="openai",
            model_name="gpt-4",
            check_result=None,
        )
        with pytest.raises(RuntimeError, match="Stream broken"):
            async for _ in monitor:
                pass
        # Error should be logged
        mock_logger.error.assert_called_once()
        assert "Error during streaming" in mock_logger.error.call_args[0][0]
        # Final logging should still happen (since start_time is set)
        mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_monitor_format_model_name_shared(self):
        """Test that ALL_MODELS_MARKER is formatted as 'shared'."""
        monitor = StreamMonitor(
            upstream_response=AsyncMock(spec=httpx.Response),
            client_ip="",
            request_method="",
            request_path="",
            provider_name="test",
            model_name=ALL_MODELS_MARKER,
            check_result=None,
        )
        formatted = monitor._format_model_name()
        assert formatted == "shared"

    @pytest.mark.asyncio
    async def test_stream_monitor_format_model_name_normal(self):
        """Test that normal model names are unchanged."""
        monitor = StreamMonitor(
            upstream_response=AsyncMock(spec=httpx.Response),
            client_ip="",
            request_method="",
            request_path="",
            provider_name="test",
            model_name="gpt-4",
            check_result=None,
        )
        formatted = monitor._format_model_name()
        assert formatted == "gpt-4"

    @pytest.mark.asyncio
    async def test_stream_monitor_internal_status_valid(self):
        """Test internal status determination for successful check."""
        monitor = StreamMonitor(
            upstream_response=Mock(status_code=200, reason_phrase="OK"),
            client_ip="",
            request_method="",
            request_path="",
            provider_name="",
            model_name="",
            check_result=CheckResult.success(),
        )
        assert monitor._get_internal_status() == "VALID"

    @pytest.mark.asyncio
    async def test_stream_monitor_internal_status_error_reason(self):
        """Test internal status uses error reason when check fails."""
        monitor = StreamMonitor(
            upstream_response=Mock(status_code=200, reason_phrase="OK"),
            client_ip="",
            request_method="",
            request_path="",
            provider_name="",
            model_name="",
            check_result=CheckResult.fail(ErrorReason.RATE_LIMITED),
        )
        assert monitor._get_internal_status() == "RATE_LIMITED"

    @pytest.mark.asyncio
    async def test_stream_monitor_internal_status_unknown(self):
        """Test internal status defaults to UNKNOWN when no check result and non-200."""
        monitor = StreamMonitor(
            upstream_response=Mock(
                status_code=500, reason_phrase="Internal Server Error"
            ),
            client_ip="",
            request_method="",
            request_path="",
            provider_name="",
            model_name="",
            check_result=None,
        )
        assert monitor._get_internal_status() == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_stream_monitor_iterator_initialized_once(self, mock_httpx_response):
        """Test that stream iterator is initialized once to avoid StreamConsumed error."""
        # Create a mock for aiter_bytes that tracks calls
        mock_aiter_bytes = Mock()
        call_count = 0

        async def chunk_iterator():
            yield b"chunk1"
            yield b"chunk2"
            yield b"chunk3"

        def side_effect():
            nonlocal call_count
            call_count += 1
            return chunk_iterator()

        mock_aiter_bytes.side_effect = side_effect
        mock_httpx_response.aiter_bytes = mock_aiter_bytes

        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )
        # Verify aiter_bytes called exactly once during initialization
        assert call_count == 1
        # Consume the stream
        chunks = []
        async for chunk in monitor:
            chunks.append(chunk)
        assert chunks == [b"chunk1", b"chunk2", b"chunk3"]
        # Ensure aiter_bytes not called again (still once)
        assert call_count == 1
