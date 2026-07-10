"""
Unit tests for the StreamMonitor class in gateway_service.

Covers the ``finally``-based cleanup contract introduced by the
``fix-stream-leaks`` change:

* ``StopAsyncIteration`` (normal completion) — ``finally`` runs
  ``_finalize_logging()`` which logs the GATEWAY_ACCESS line and calls
  ``upstream_response.aclose()``.
* ``httpx.ReadError`` (upstream disconnect) — ``finally`` still runs
  ``_finalize_logging()`` after the ``GatewayStreamError`` is raised.
* ``CancelledError`` / ``GeneratorExit`` (``BaseException`` subclasses) —
  bypass all ``except`` clauses; ``finally`` guarantees cleanup.
* ``_finalize_logging()`` is idempotent (``_finalized`` guard) and
  swallows ``aclose()`` failures so the original exception propagates.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from src.core.constants import ALL_MODELS_MARKER, ErrorReason
from src.core.models import CheckResult
from src.services.gateway.gateway_service import GatewayStreamError, StreamMonitor


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
        with patch("src.services.gateway.gateway_service.logger") as mock:
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
        # Verify final logging — exactly-once guarantee under the new ``finally``
        # block.  Both ``except StopAsyncIteration`` and ``finally`` reach
        # ``_finalize_logging()``, but the ``_finalized`` guard ensures the
        # GATEWAY_ACCESS log and ``aclose()`` are invoked exactly once.
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "GATEWAY_ACCESS" in log_message
        assert "127.0.0.1" in log_message
        assert "POST /v1/chat/completions" in log_message
        assert "openai:gpt-4" in log_message
        assert "200 OK -> VALID" in log_message
        # Ensure upstream response is closed — exactly-once guarantee via the
        # ``_finalized`` guard in ``_finalize_logging()``.
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
        # Design Decision 3: the ``except Exception`` block was removed from
        # ``__anext__``.  The old ``logger.error("Error during streaming")``
        # call no longer exists, so we must NOT assert on ``logger.error``.
        # The ``finally`` block now guarantees ``_finalize_logging()`` +
        # ``aclose()`` on unexpected exceptions.
        mock_logger.info.assert_called_once()
        mock_httpx_response.aclose.assert_called_once()

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

    @pytest.mark.asyncio
    async def test_stream_monitor_read_error_raises_gateway_stream_error(
        self, mock_httpx_response, mock_logger
    ):
        """
        6.8 + 6.6: httpx.ReadError during streaming → StreamMonitor catches it,
        raises GatewayStreamError with provider/model context, logs WARNING
        with provider_name and model_name, and calls _finalize_logging().
        """

        async def chunk_iterator():
            yield b"partial_data"
            raise httpx.ReadError("Connection lost")

        mock_httpx_response.aiter_bytes.return_value = chunk_iterator()
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="10.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )

        with pytest.raises(GatewayStreamError) as exc_info:
            async for _ in monitor:
                pass

        # Verify GatewayStreamError attributes (6.8)
        assert exc_info.value.provider_name == "openai"
        assert exc_info.value.model_name == "gpt-4"
        assert exc_info.value.error_reason == ErrorReason.STREAM_DISCONNECT

        # 6.6: WARNING log contains provider_name and model_name
        mock_logger.warning.assert_called_once()
        log_message = mock_logger.warning.call_args[0][0]
        assert "openai" in log_message
        assert "gpt-4" in log_message

        # 6.8: _finalize_logging was called (GATEWAY_ACCESS info log)
        mock_logger.info.assert_called_once()

        # Verify upstream response was closed — idempotency guarantee under
        # the new ``finally`` block.  Both ``except httpx.ReadError`` and
        # ``finally`` reach ``_finalize_logging()``, but the ``_finalized``
        # guard ensures ``aclose()`` is invoked exactly once.
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_format_model_name_all_models_marker(self, mock_logger):
        """Verify ALL_MODELS_MARKER is formatted as 'shared' in log output."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.reason_phrase = "OK"
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aclose = AsyncMock()

        async def chunk_iterator():
            yield b"chunk1"

        mock_response.aiter_bytes.return_value = chunk_iterator()

        monitor = StreamMonitor(
            upstream_response=mock_response,
            client_ip="10.0.0.5",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="test-provider",
            model_name=ALL_MODELS_MARKER,
            check_result=CheckResult.success(),
        )

        # Verify _format_model_name directly
        formatted = monitor._format_model_name()
        assert formatted == "shared"

        # Consume the stream to trigger _finalize_logging
        async for _ in monitor:
            pass

        # Verify log output uses "shared" (not the raw marker)
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "test-provider:shared" in log_message
        assert ALL_MODELS_MARKER not in log_message


class TestStreamMonitorGracefulShutdown:
    """Tests for the ``finally``-based cleanup contract in ``StreamMonitor``.

    These tests verify that ``BaseException`` subclasses (``CancelledError``,
    ``GeneratorExit``) which bypass all ``except`` clauses still trigger
    ``_finalize_logging()`` and ``aclose()`` via the ``finally`` block.
    They also cover the idempotency guard (``_finalized``) and the
    ``aclose()`` failure handling inside ``_finalize_logging()``.
    """

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
        with patch("src.services.gateway.gateway_service.logger") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_cancelled_error_triggers_finalize_and_aclose(
        self, mock_httpx_response, mock_logger
    ):
        """CancelledError (BaseException) bypasses except clauses; finally
        guarantees ``_finalize_logging()`` + ``aclose()``.

        The iterator blocks before yielding any chunk so that
        ``_finalize_logging()`` has NOT been called when the task is
        cancelled.  This ensures the ``finally`` block — not a prior
        successful return — is what triggers cleanup.
        """

        async def blocking_iterator():
            # Block forever — no chunks yielded, so _finalize_logging
            # has not been called when CancelledError is thrown.
            await asyncio.Event().wait()
            yield b"chunk1"  # pragma: no cover

        mock_httpx_response.aiter_bytes.return_value = blocking_iterator()
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )

        async def consume():
            async for _ in monitor:
                pass

        task = asyncio.create_task(consume())
        # Let the task start and block inside __anext__.
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The finally block called _finalize_logging() which logs the
        # GATEWAY_ACCESS line and calls aclose() on the upstream response.
        mock_logger.info.assert_called_once()
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_generator_exit_triggers_finalize_and_aclose(
        self, mock_httpx_response, mock_logger
    ):
        """GeneratorExit (BaseException) bypasses except clauses; finally
        guarantees ``_finalize_logging()`` + ``aclose()``.

        Uses a class-based async iterator (not a native async generator)
        that raises ``GeneratorExit`` on the first ``__anext__`` call.  This
        ensures ``GeneratorExit`` is raised inside the ``try`` block of
        ``StreamMonitor.__anext__`` before any chunk is returned, so
        ``_finalize_logging()`` has not been called yet.  The ``finally``
        block is what triggers cleanup.

        Note: ``StreamMonitor`` is not a native async generator, so Python's
        ``aclose()`` machinery does not apply.  We simulate the effect of
        ``GeneratorExit`` being raised inside the ``try`` block.
        """

        class GeneratorExitIterator:
            """Async iterator that raises GeneratorExit on first __anext__."""

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise GeneratorExit("simulated generator exit")

        mock_httpx_response.aiter_bytes.return_value = GeneratorExitIterator()
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )

        with pytest.raises(GeneratorExit):
            await monitor.__anext__()

        # The finally block called _finalize_logging() which logs the
        # GATEWAY_ACCESS line and calls aclose() on the upstream response.
        mock_logger.info.assert_called_once()
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_finalize_is_safe_noop(self, mock_httpx_response, mock_logger):
        """Calling ``_finalize_logging()`` twice is a safe no-op.

        The ``_finalized`` guard ensures the second call returns immediately
        without a second info log or a second ``aclose()``.
        """
        monitor = StreamMonitor(
            upstream_response=mock_httpx_response,
            client_ip="127.0.0.1",
            request_method="POST",
            request_path="/v1/chat/completions",
            provider_name="openai",
            model_name="gpt-4",
            check_result=CheckResult.success(),
        )
        # Set start_time manually so _finalize_logging does not early-return.
        monitor.start_time = asyncio.get_event_loop().time()

        # First call — should log and close.
        await monitor._finalize_logging()
        assert mock_logger.info.call_count == 1
        assert mock_httpx_response.aclose.call_count == 1

        # Second call — should be a no-op (no second log, no second aclose).
        await monitor._finalize_logging()
        mock_logger.info.assert_called_once()
        mock_httpx_response.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_aclose_failure_in_finally_logged_not_raised(
        self, mock_httpx_response, mock_logger
    ):
        """When ``aclose()`` raises inside ``_finalize_logging()``, the
        exception is caught, logged at ERROR with ``exc_info=True``, and
        does NOT propagate to the caller.

        The GATEWAY_ACCESS info log still happens (it is emitted before
        ``aclose()`` is called).
        """
        mock_httpx_response.aclose = AsyncMock(
            side_effect=RuntimeError("aclose failed")
        )

        async def chunk_iterator():
            yield b"chunk1"

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

        # Consume the stream normally — no exception should propagate.
        chunks: list[bytes] = []
        async for chunk in monitor:
            chunks.append(chunk)
        assert chunks == [b"chunk1"]

        # The GATEWAY_ACCESS info log was emitted before aclose() was called.
        mock_logger.info.assert_called_once()

        # The aclose() failure was caught and logged at ERROR with exc_info.
        mock_logger.error.assert_called_once()
        error_args, error_kwargs = mock_logger.error.call_args
        assert "Failed to close upstream response" in error_args[0]
        assert "openai" in error_args[0]
        assert error_kwargs.get("exc_info") is True
