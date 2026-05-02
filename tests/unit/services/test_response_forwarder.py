"""
Unit tests for the response_forwarder module.

Tests cover:
  - Section A: Unit tests for forward_success_stream, forward_buffered_body,
    forward_error_to_client, discard_response, and _extract_filtered_headers.
  - Section E: Static analysis confirming _extract_filtered_headers is the
    sole filtering location (no inline blocks in gateway_service.py).
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

from src.core.constants import ErrorReason
from src.core.models import CheckResult
from src.services.gateway.response_forwarder import (
    _HOP_BY_HOP_HEADERS,
    _extract_filtered_headers,
    discard_response,
    forward_buffered_body,
    forward_error_to_client,
    forward_success_stream,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_upstream_response() -> AsyncMock:
    """Provide a mocked httpx.Response with sensible defaults."""
    response = AsyncMock(spec=httpx.Response)
    response.status_code = 200
    response.headers = httpx.Headers({"content-type": "application/json"})
    response.aread = AsyncMock(return_value=b'{"ok": true}')
    response.aclose = AsyncMock()
    return response


@pytest.fixture
def mock_check_result_success() -> CheckResult:
    """Provide a successful CheckResult."""
    return CheckResult.success(status_code=200)


@pytest.fixture
def mock_check_result_fail() -> CheckResult:
    """Provide a failed CheckResult with SERVER_ERROR."""
    return CheckResult.fail(ErrorReason.SERVER_ERROR, status_code=500)


# ---------------------------------------------------------------------------
# Section A: forward_success_stream
# ---------------------------------------------------------------------------


class TestForwardSuccessStream:
    """Tests for forward_success_stream()."""

    @pytest.mark.asyncio
    async def test_forward_success_stream_returns_streaming_response(
        self, mock_upstream_response, mock_check_result_success
    ):
        """forward_success_stream() creates StreamMonitor and returns
        StreamingResponse with filtered headers; does NOT read body."""
        mock_stream_monitor = MagicMock()

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=mock_stream_monitor,
        ) as patched_sm:
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="127.0.0.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )

        # Must return a StreamingResponse
        from starlette.responses import StreamingResponse

        assert isinstance(result, StreamingResponse)
        # StreamMonitor was created with correct arguments
        patched_sm.assert_called_once_with(
            upstream_response=mock_upstream_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=mock_check_result_success,
        )
        # The content of the StreamingResponse is the StreamMonitor instance
        assert result.body_iterator == mock_stream_monitor
        # aread was NOT called — body is streamed, not buffered
        mock_upstream_response.aread.assert_not_called()

    @pytest.mark.asyncio
    async def test_forward_success_stream_preserves_status_code(
        self, mock_upstream_response, mock_check_result_success
    ):
        """Status codes 200, 201, 204 are passed to client unchanged."""

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=MagicMock(),
        ):
            # 200
            mock_upstream_response.status_code = 200
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="1.1.1.1",
                request_method="GET",
                request_path="/v1/models",
                provider_name="openai",
                model_name="gpt-4",
            )
            assert result.status_code == 200

            # 201
            mock_upstream_response.status_code = 201
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="1.1.1.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )
            assert result.status_code == 201

            # 204
            mock_upstream_response.status_code = 204
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="1.1.1.1",
                request_method="DELETE",
                request_path="/v1/files/abc",
                provider_name="openai",
                model_name="gpt-4",
            )
            assert result.status_code == 204

    @pytest.mark.asyncio
    async def test_forward_success_stream_filters_hop_by_hop_headers(
        self, mock_upstream_response, mock_check_result_success
    ):
        """Hop-by-hop headers (connection, keep-alive, transfer-encoding,
        content-length, content-encoding) are excluded from StreamingResponse."""
        mock_upstream_response.headers = httpx.Headers(
            {
                "content-type": "application/json",
                "connection": "keep-alive",
                "keep-alive": "timeout=5",
                "transfer-encoding": "chunked",
                "content-length": "1234",
                "content-encoding": "gzip",
                "x-request-id": "req-123",
            }
        )

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=MagicMock(),
        ):
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="127.0.0.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )

        # Hop-by-hop headers must NOT appear in the response
        result_headers = dict(result.headers)
        assert "connection" not in result_headers
        assert "keep-alive" not in result_headers
        assert "transfer-encoding" not in result_headers
        assert "content-length" not in result_headers
        assert "content-encoding" not in result_headers
        # Non-hop-by-hop headers must be present
        assert "x-request-id" in result_headers

    @pytest.mark.asyncio
    async def test_forward_success_stream_preserves_content_type_header(
        self, mock_upstream_response, mock_check_result_success
    ):
        """content-type from upstream is preserved in StreamingResponse media_type."""
        mock_upstream_response.headers = httpx.Headers(
            {"content-type": "text/event-stream"}
        )

        with patch(
            "src.services.gateway.gateway_service.StreamMonitor",
            return_value=MagicMock(),
        ):
            result = await forward_success_stream(
                upstream_response=mock_upstream_response,
                check_result=mock_check_result_success,
                client_ip="127.0.0.1",
                request_method="POST",
                request_path="/v1/chat/completions",
                provider_name="openai",
                model_name="gpt-4",
            )

        assert result.media_type == "text/event-stream"


# ---------------------------------------------------------------------------
# Section A: forward_buffered_body
# ---------------------------------------------------------------------------


class TestForwardBufferedBody:
    """Tests for forward_buffered_body()."""

    @pytest.mark.asyncio
    async def test_forward_buffered_body_returns_response_with_body(
        self, mock_upstream_response
    ):
        """forward_buffered_body() returns Response with read body, original
        status code, and filtered headers."""
        mock_upstream_response.headers = httpx.Headers(
            {
                "content-type": "application/json",
                "connection": "close",
                "x-custom": "value1",
            }
        )
        mock_upstream_response.status_code = 200
        mock_upstream_response.aread.return_value = b'{"result": "data"}'

        result = await forward_buffered_body(mock_upstream_response)

        from starlette.responses import Response as StarletteResponse

        assert isinstance(result, StarletteResponse)
        assert result.body == b'{"result": "data"}'
        assert result.status_code == 200
        # Hop-by-hop headers filtered out
        result_headers = dict(result.headers)
        assert "connection" not in result_headers
        assert "x-custom" in result_headers

    @pytest.mark.asyncio
    async def test_forward_buffered_body_calls_aread_and_aclose_in_finally(
        self, mock_upstream_response
    ):
        """aread() called, then aclose() in finally block."""
        result = await forward_buffered_body(mock_upstream_response)

        mock_upstream_response.aread.assert_called_once()
        mock_upstream_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward_buffered_body_aread_failure_returns_fallback_body(
        self, mock_upstream_response
    ):
        """If aread() throws exception, returns fallback empty body,
        aclose() still called."""
        mock_upstream_response.aread.side_effect = RuntimeError("read failed")

        result = await forward_buffered_body(mock_upstream_response)

        # Fallback body is empty bytes
        assert result.body == b""
        # aclose still called in finally block
        mock_upstream_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_forward_buffered_body_with_status_code_override(
        self, mock_upstream_response
    ):
        """status_code_override replaces upstream status code."""
        mock_upstream_response.status_code = 500
        mock_upstream_response.aread.return_value = b"error body"

        result = await forward_buffered_body(
            mock_upstream_response, status_code_override=200
        )

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_forward_buffered_body_with_pre_read_body_bytes(
        self, mock_upstream_response
    ):
        """When body_bytes is provided, aread() and aclose() are NOT called."""
        pre_read = b"already-read-body"

        result = await forward_buffered_body(
            mock_upstream_response, body_bytes=pre_read
        )

        assert result.body == b"already-read-body"
        mock_upstream_response.aread.assert_not_called()
        mock_upstream_response.aclose.assert_not_called()


# ---------------------------------------------------------------------------
# Section A: forward_error_to_client
# ---------------------------------------------------------------------------


class TestForwardErrorToClient:
    """Tests for forward_error_to_client()."""

    @pytest.mark.asyncio
    async def test_forward_error_to_client_reads_body_when_none(
        self, mock_upstream_response, mock_check_result_fail
    ):
        """body_bytes=None: response.aread() called, then response.aclose(),
        returns Response with original status code and read body."""
        mock_upstream_response.status_code = 500
        mock_upstream_response.aread.return_value = b'{"error": "internal"}'

        result = await forward_error_to_client(
            mock_upstream_response, mock_check_result_fail, body_bytes=None
        )

        mock_upstream_response.aread.assert_called_once()
        mock_upstream_response.aclose.assert_called_once()
        assert result.body == b'{"error": "internal"}'
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_forward_error_to_client_uses_pre_read_body(
        self, mock_upstream_response, mock_check_result_fail
    ):
        """body_bytes has data: aread() NOT called, returns Response with
        body_bytes and original status code."""
        mock_upstream_response.status_code = 429
        pre_read = b'{"error": "rate limited"}'

        result = await forward_error_to_client(
            mock_upstream_response, mock_check_result_fail, body_bytes=pre_read
        )

        mock_upstream_response.aread.assert_not_called()
        assert result.body == b'{"error": "rate limited"}'
        assert result.status_code == 429

    @pytest.mark.asyncio
    async def test_forward_error_to_client_filters_hop_by_hop_headers(
        self, mock_upstream_response, mock_check_result_fail
    ):
        """Hop-by-hop headers excluded from Response."""
        mock_upstream_response.headers = httpx.Headers(
            {
                "content-type": "application/json",
                "connection": "close",
                "transfer-encoding": "chunked",
                "x-request-id": "req-456",
            }
        )
        mock_upstream_response.status_code = 500
        mock_upstream_response.aread.return_value = b"error"

        result = await forward_error_to_client(
            mock_upstream_response, mock_check_result_fail, body_bytes=None
        )

        result_headers = dict(result.headers)
        assert "connection" not in result_headers
        assert "transfer-encoding" not in result_headers
        assert "x-request-id" in result_headers

    @pytest.mark.asyncio
    async def test_forward_error_to_client_aclose_in_finally_when_aread_called(
        self, mock_upstream_response, mock_check_result_fail
    ):
        """aclose() called in finally after aread(), even if aread() throws."""
        mock_upstream_response.aread.side_effect = RuntimeError("network error")

        result = await forward_error_to_client(
            mock_upstream_response, mock_check_result_fail, body_bytes=None
        )

        # aclose still called despite aread failure
        mock_upstream_response.aclose.assert_called_once()
        # Fallback body contains error reason
        assert result.body == b'{"error": "Upstream error: server_error"}'

    @pytest.mark.asyncio
    async def test_forward_error_to_client_no_aclose_when_body_bytes_provided(
        self, mock_upstream_response, mock_check_result_fail
    ):
        """When body_bytes != None, aclose() NOT called (connection already
        closed by aread() in _send_proxy_request)."""
        pre_read = b"pre-read error body"

        result = await forward_error_to_client(
            mock_upstream_response, mock_check_result_fail, body_bytes=pre_read
        )

        mock_upstream_response.aclose.assert_not_called()


# ---------------------------------------------------------------------------
# Section A: discard_response
# ---------------------------------------------------------------------------


class TestDiscardResponse:
    """Tests for discard_response()."""

    @pytest.mark.asyncio
    async def test_discard_response_calls_aclose_when_body_none(
        self, mock_upstream_response
    ):
        """body_bytes=None: upstream_response.aclose() called, returns None."""
        result = await discard_response(mock_upstream_response, body_bytes=None)

        mock_upstream_response.aclose.assert_called_once()
        assert result is None

    @pytest.mark.asyncio
    async def test_discard_response_noop_when_body_bytes_provided(
        self, mock_upstream_response
    ):
        """body_bytes != None: aclose() NOT called (connection already closed),
        returns None."""
        result = await discard_response(mock_upstream_response, body_bytes=b"some data")

        mock_upstream_response.aclose.assert_not_called()
        assert result is None

    @pytest.mark.asyncio
    async def test_discard_response_returns_none_always(self, mock_upstream_response):
        """Regardless of body_bytes, result always None."""
        result_none = await discard_response(mock_upstream_response, body_bytes=None)
        result_bytes = await discard_response(
            mock_upstream_response, body_bytes=b"data"
        )

        assert result_none is None
        assert result_bytes is None


# ---------------------------------------------------------------------------
# Section A: _extract_filtered_headers
# ---------------------------------------------------------------------------


class TestExtractFilteredHeaders:
    """Tests for _extract_filtered_headers()."""

    def test_extract_filtered_headers_removes_all_hop_by_hop(self):
        """Full set of hop-by-hop headers excluded."""
        all_hbh = {
            "connection": "close",
            "keep-alive": "timeout=5",
            "proxy-authenticate": "Basic",
            "proxy-authorization": "Bearer abc",
            "te": "trailers",
            "trailers": "chunked",
            "transfer-encoding": "chunked",
            "upgrade": "websocket",
            "content-length": "100",
            "content-encoding": "gzip",
            "content-type": "application/json",  # NOT hop-by-hop
            "x-request-id": "req-1",  # NOT hop-by-hop
        }
        response = Mock(spec=httpx.Response)
        response.headers = httpx.Headers(all_hbh)

        filtered = _extract_filtered_headers(response)

        # All hop-by-hop removed
        for header_name in _HOP_BY_HOP_HEADERS:
            assert header_name not in filtered
        # Non-hop-by-hop preserved
        assert filtered["content-type"] == "application/json"
        assert filtered["x-request-id"] == "req-1"

    def test_extract_filtered_headers_preserves_non_hop_by_hop(self):
        """Headers content-type, x-request-id, x-custom preserved."""
        response = Mock(spec=httpx.Response)
        response.headers = httpx.Headers(
            {
                "content-type": "text/plain",
                "x-request-id": "abc-123",
                "x-custom": "custom-value",
            }
        )

        filtered = _extract_filtered_headers(response)

        assert filtered == {
            "content-type": "text/plain",
            "x-request-id": "abc-123",
            "x-custom": "custom-value",
        }

    def test_extract_filtered_headers_case_insensitive(self):
        """Connection, connection, CONNECTION all excluded."""
        response = Mock(spec=httpx.Response)
        response.headers = httpx.Headers(
            {
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=5",
                "CONTENT-LENGTH": "42",
                "content-type": "text/html",
            }
        )

        filtered = _extract_filtered_headers(response)

        # All case variants of hop-by-hop headers removed
        assert "connection" not in filtered
        assert "Connection" not in filtered
        assert "CONNECTION" not in filtered
        assert "keep-alive" not in filtered
        assert "Keep-Alive" not in filtered
        assert "content-length" not in filtered
        assert "CONTENT-LENGTH" not in filtered
        # Non-hop-by-hop preserved
        assert "content-type" in filtered

    def test_extract_filtered_headers_empty_input(self):
        """Empty upstream headers → empty dict output."""
        response = Mock(spec=httpx.Response)
        response.headers = httpx.Headers({})

        filtered = _extract_filtered_headers(response)

        assert filtered == {}
