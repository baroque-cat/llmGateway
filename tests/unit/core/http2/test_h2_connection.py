"""Unit tests for FixedHTTP2Connection in src.core.http2.h2_connection."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import h2.connection
import h2.events
import h2.settings
import pytest
from httpcore._async.http2 import HTTPConnectionState
from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._exceptions import ReadTimeout
from httpcore._models import Origin, Response

from src.core.http2.connection import CapacityAwareHTTPConnection
from src.core.http2.h2_connection import FixedHTTP2Connection
from src.core.http2.semaphore import NonBlockingSemaphore
from tests._canonical import CanonicalConfig


class TestFixedHTTP2Connection:
    """Tests for FixedHTTP2Connection."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_conn(
        max_streams: int = 100,
        sent_init: bool = True,
        max_streams_cap: int | None = None,
        stream_read: float | None = None,
        read_timeout: float = 120.0,
    ) -> FixedHTTP2Connection:
        """Create a FixedHTTP2Connection with common mocks set up.

        Args:
            max_streams: Initial value for ``_max_streams`` and the
                ``local_settings.max_concurrent_streams`` mock.
            sent_init: Whether ``_sent_connection_init`` is True.
            max_streams_cap: Value for ``_max_streams_cap`` (the per-provider
                cap). ``None`` means no cap (default behavior).
            stream_read: Per-stream timeout value.  Not stored on the
                connection itself — used by new tests to construct mock
                requests with the correct ``request.extensions`` dict.
            read_timeout: Read timeout value.  Not stored on the connection
                itself — used by new tests to construct mock requests with
                the correct ``request.extensions`` dict.
        """
        # Bypass __init__ to avoid calling super().__init__ which needs real backends
        conn = object.__new__(FixedHTTP2Connection)
        conn._origin = MagicMock()  # type: ignore[reportPrivateUsage]
        conn._network_stream = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._keepalive_expiry = None  # type: ignore[reportPrivateUsage]
        conn._on_capacity_update = None  # type: ignore[reportPrivateUsage]
        conn._closed_streams = set()  # type: ignore[reportPrivateUsage]
        conn._max_streams_cap = max_streams_cap  # type: ignore[reportPrivateUsage]
        conn._events = {}  # type: ignore[reportPrivateUsage]
        conn._max_streams = max_streams  # type: ignore[reportPrivateUsage]
        conn._max_streams_semaphore = NonBlockingSemaphore(  # type: ignore[reportPrivateUsage]
            max_streams
        )
        conn._max_streams = max_streams  # type: ignore[reportPrivateUsage]
        conn._sent_connection_init = sent_init  # type: ignore[reportPrivateUsage]
        conn._state = HTTPConnectionState.ACTIVE  # type: ignore[reportPrivateUsage]
        conn._state_lock = asyncio.Lock()  # type: ignore[reportPrivateUsage]
        conn._init_lock = asyncio.Lock()  # type: ignore[reportPrivateUsage]
        conn._read_lock = asyncio.Lock()  # type: ignore[reportPrivateUsage]
        conn._connection_terminated = None  # type: ignore[reportPrivateUsage]
        conn._used_all_stream_ids = False  # type: ignore[reportPrivateUsage]
        conn._request_count = 0  # type: ignore[reportPrivateUsage]
        conn._expire_at = None  # type: ignore[reportPrivateUsage]
        conn._connection_error = False  # type: ignore[reportPrivateUsage]

        # Mock h2_state
        mock_h2_state = MagicMock()
        mock_h2_state.state_machine.state = h2.connection.ConnectionState.CLIENT_OPEN
        mock_h2_state.local_settings = MagicMock()
        mock_h2_state.local_settings.max_concurrent_streams = max_streams
        conn._h2_state = mock_h2_state  # type: ignore[reportPrivateUsage]

        # Mock handle_async_request to avoid running the real one
        conn._send_connection_init = AsyncMock()  # type: ignore[reportPrivateUsage]

        # Allow handle_async_request to pass the origin check
        conn.can_handle_request = MagicMock(return_value=True)

        return conn

    # ------------------------------------------------------------------
    # _response_closed tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_response_closed_normal_clean_stream(self) -> None:
        """Stream in _closed_streams: no reset_stream called, semaphore released."""
        conn = self._make_conn()
        stream_id = 5
        conn._events[stream_id] = []  # type: ignore[reportPrivateUsage]
        conn._closed_streams.add(stream_id)  # type: ignore[reportPrivateUsage]

        await conn._response_closed(stream_id)  # type: ignore[reportPrivateUsage]

        # Check _closed_streams was purged
        assert stream_id not in conn._closed_streams  # type: ignore[reportPrivateUsage]
        # Check event was deleted
        assert stream_id not in conn._events  # type: ignore[reportPrivateUsage]
        # reset_stream should NOT have been called
        conn._h2_state.reset_stream.assert_not_called()  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_response_closed_cancelled_stream_reset(self) -> None:
        """Cancelled stream (not in _closed_streams): reset_stream called.

        This test also covers the MODIFIED requirement: the outer
        ``except BaseException`` → ``_response_closed`` path handles
        ``ReadTimeout`` (raised by the inner ``except TimeoutError``
        handler) identically to ``CancelledError`` — both are
        ``BaseException`` subclasses that bypass ``except Exception``.
        The existing assertions verify the cleanup path (reset_stream +
        semaphore release + event deletion).
        """
        conn = self._make_conn()
        stream_id = 7
        conn._events[stream_id] = []  # type: ignore[reportPrivateUsage]

        # stream_id is NOT in _closed_streams
        await conn._response_closed(stream_id)  # type: ignore[reportPrivateUsage]

        # reset_stream should have been called
        conn._h2_state.reset_stream.assert_called_once_with(stream_id)  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_response_closed_conditional_release(self) -> None:
        """Semaphore release only when len(self._events) <= self._max_streams."""
        conn = self._make_conn(max_streams=100)
        stream_id = 9
        conn._events[stream_id] = []  # type: ignore[reportPrivateUsage]

        # Put a lot of events to test the condition
        conn._events = {i: [] for i in range(200)}  # type: ignore[reportPrivateUsage]
        conn._events[stream_id] = []  # type: ignore[reportPrivateUsage]
        conn._closed_streams.add(stream_id)  # type: ignore[reportPrivateUsage]

        sem_initial = conn._max_streams_semaphore  # type: ignore[reportPrivateUsage]

        with patch.object(
            sem_initial, "release", new_callable=AsyncMock
        ) as mock_release:
            await conn._response_closed(stream_id)  # type: ignore[reportPrivateUsage]
            mock_release.assert_not_called()

    @pytest.mark.asyncio
    async def test_response_closed_reset_closes_connection(self) -> None:
        """Connection closes when stream was reset and no events remain in ACTIVE state."""
        conn = self._make_conn(max_streams=100)
        stream_id = 11
        conn._events = {stream_id: []}  # type: ignore[reportPrivateUsage]
        conn._state = HTTPConnectionState.ACTIVE  # type: ignore[reportPrivateUsage]

        with patch.object(conn, "aclose", new_callable=AsyncMock) as mock_aclose:
            await conn._response_closed(stream_id)  # type: ignore[reportPrivateUsage]
            mock_aclose.assert_called_once()

    # ------------------------------------------------------------------
    # _receive_events tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_receive_events_tracks_closed_stream(self) -> None:
        """StreamEnded/StreamReset events add to _closed_streams."""
        conn = self._make_conn()
        conn._read_lock = asyncio.Lock()  # type: ignore[reportPrivateUsage]

        stream_ended = MagicMock(spec=h2.events.StreamEnded)
        stream_ended.stream_id = 15
        stream_reset = MagicMock(spec=h2.events.StreamReset)
        stream_reset.stream_id = 17

        # Return these events from _read_incoming_data
        conn._read_incoming_data = AsyncMock(  # type: ignore[reportPrivateUsage]
            return_value=[stream_ended, stream_reset]
        )
        conn._write_outgoing_data = AsyncMock()  # type: ignore[reportPrivateUsage]

        # We need _events to have entries for the stream_ids
        conn._events[15] = []  # type: ignore[reportPrivateUsage]
        conn._events[17] = []  # type: ignore[reportPrivateUsage]

        request = MagicMock()
        await conn._receive_events(request)  # type: ignore[reportPrivateUsage]

        assert 15 in conn._closed_streams  # type: ignore[reportPrivateUsage]
        assert 17 in conn._closed_streams  # type: ignore[reportPrivateUsage]

    # ------------------------------------------------------------------
    # is_available tests
    # ------------------------------------------------------------------

    def test_is_available_returns_false_when_full(self) -> None:
        """is_available() returns False when all stream slots are filled."""
        conn = self._make_conn(max_streams=100)
        conn._events = {i: [] for i in range(100)}  # type: ignore[reportPrivateUsage]

        assert conn.is_available() is False

    def test_is_available_returns_true_when_room(self) -> None:
        """is_available() returns True when stream slots are available."""
        conn = self._make_conn(max_streams=100)
        conn._events = {i: [] for i in range(50)}  # type: ignore[reportPrivateUsage]

        assert conn.is_available() is True

    # ------------------------------------------------------------------
    # _receive_remote_settings_change tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_settings_change_calls_on_capacity_update(self) -> None:
        """SETTINGS change calls _on_capacity_update() callback."""
        conn = self._make_conn(max_streams=100)
        # Force _max_streams below the new value so the change is detected
        conn._max_streams = 50  # type: ignore[reportPrivateUsage]
        mock_callback = AsyncMock()
        conn._on_capacity_update = mock_callback  # type: ignore[reportPrivateUsage]

        # Also bump local_settings so min(new_value, local_max) > _max_streams
        conn._h2_state.local_settings.max_concurrent_streams = 200  # type: ignore[reportPrivateUsage]

        event = MagicMock(spec=h2.events.RemoteSettingsChanged)
        event.changed_settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: MagicMock(
                new_value=100,  # min(100, 200) = 100, which is != 50
            )
        }

        await conn._receive_remote_settings_change(event)  # type: ignore[reportPrivateUsage]

        mock_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_settings_change_no_callback_no_error(self) -> None:
        """No callback configured — no error (None check)."""
        conn = self._make_conn(max_streams=100)
        conn._on_capacity_update = None  # type: ignore[reportPrivateUsage]

        event = MagicMock(spec=h2.events.RemoteSettingsChanged)
        event.changed_settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: MagicMock(
                new_value=50,  # Decrease from 100 to 50
            )
        }

        # Should not raise
        await conn._receive_remote_settings_change(event)  # type: ignore[reportPrivateUsage]

    # ------------------------------------------------------------------
    # max_concurrent_requests tests
    # ------------------------------------------------------------------

    def test_max_concurrent_requests_initialized(self) -> None:
        """Returns _max_streams after _sent_connection_init is True."""
        conn = self._make_conn(max_streams=100, sent_init=True)
        assert conn.max_concurrent_requests() == 100

    def test_max_concurrent_requests_not_initialized(self) -> None:
        """Returns 1 before _sent_connection_init."""
        conn = self._make_conn(max_streams=100, sent_init=False)
        assert conn.max_concurrent_requests() == 1

    # ------------------------------------------------------------------
    # max_concurrent_streams_cap tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cap_lower_than_server_advertised(self) -> None:
        """Cap lower than server-advertised value caps effective max streams.

        When ``max_concurrent_streams_cap=3`` and the server advertises
        ``MAX_CONCURRENT_STREAMS=100``, the effective max concurrent streams
        is capped to 3, not 100.
        """
        conn = self._make_conn(max_streams=100, max_streams_cap=3)
        # Start below the target so the SETTINGS change is detected.
        conn._max_streams = 1  # type: ignore[reportPrivateUsage]
        # Local settings allow 100; server advertises 100.
        conn._h2_state.local_settings.max_concurrent_streams = 100  # type: ignore[reportPrivateUsage]

        event = MagicMock(spec=h2.events.RemoteSettingsChanged)
        event.changed_settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: MagicMock(
                new_value=100,
            )
        }

        await conn._receive_remote_settings_change(event)  # type: ignore[reportPrivateUsage]

        # min(server=100, local=100, cap=3) = 3
        assert conn._max_streams == 3  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_cap_higher_than_server_advertised(self) -> None:
        """Cap higher than server-advertised value does not exceed server limit.

        When ``max_concurrent_streams_cap=200`` and the server advertises
        ``MAX_CONCURRENT_STREAMS=100``, the effective max concurrent streams
        is 100 (the server's limit), not 200 — the cap cannot raise the
        limit beyond what the server offers.
        """
        conn = self._make_conn(max_streams=100, max_streams_cap=200)
        # Start below the target so the SETTINGS change is detected.
        conn._max_streams = 50  # type: ignore[reportPrivateUsage]
        # Local settings allow 100; server advertises 100.
        conn._h2_state.local_settings.max_concurrent_streams = 100  # type: ignore[reportPrivateUsage]

        event = MagicMock(spec=h2.events.RemoteSettingsChanged)
        event.changed_settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: MagicMock(
                new_value=100,
            )
        }

        await conn._receive_remote_settings_change(event)  # type: ignore[reportPrivateUsage]

        # min(server=100, local=100, cap=200) = 100
        assert conn._max_streams == 100  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_cap_none_uses_server_advertised(self) -> None:
        """No cap (None) uses the server-advertised value unchanged.

        When ``max_concurrent_streams_cap`` is ``None`` (the default), the
        effective max concurrent streams equals the server-advertised value
        — the pre-cap behavior is preserved.
        """
        conn = self._make_conn(max_streams=100, max_streams_cap=None)
        # Start below the target so the SETTINGS change is detected.
        conn._max_streams = 50  # type: ignore[reportPrivateUsage]
        # Local settings allow 100; server advertises 100.
        conn._h2_state.local_settings.max_concurrent_streams = 100  # type: ignore[reportPrivateUsage]

        event = MagicMock(spec=h2.events.RemoteSettingsChanged)
        event.changed_settings = {
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: MagicMock(
                new_value=100,
            )
        }

        await conn._receive_remote_settings_change(event)  # type: ignore[reportPrivateUsage]

        # No cap applied: min(server=100, local=100) = 100
        assert conn._max_streams == 100  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_cap_not_applied_to_h1(self) -> None:
        """H1 connections are unaffected by max_concurrent_streams_cap.

        When ALPN negotiates HTTP/1.1 (not h2), an ``AsyncHTTP11Connection``
        is created without the cap parameter.  The cap has no effect on H1
        providers because H1 has no concept of concurrent streams.
        """
        origin = Origin(b"https", b"example.com", 443)

        conn = CapacityAwareHTTPConnection(
            origin=origin,
            http1=True,
            http2=True,
            max_concurrent_streams_cap=3,
            retries=0,
        )

        # Mock _connect to return a stream WITHOUT h2 ALPN negotiation.
        mock_stream = MagicMock()
        mock_ssl_object = MagicMock()
        mock_ssl_object.selected_alpn_protocol.return_value = "http/1.1"
        mock_stream.get_extra_info.return_value = mock_ssl_object
        conn._connect = AsyncMock(return_value=mock_stream)  # type: ignore[reportPrivateUsage]

        mock_req = MagicMock()
        mock_req.url.origin = origin
        conn.can_handle_request = MagicMock(return_value=True)

        with patch.object(
            AsyncHTTP11Connection,
            "handle_async_request",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            await conn.handle_async_request(mock_req)

        inner = conn._connection  # type: ignore[reportPrivateUsage]
        assert isinstance(inner, AsyncHTTP11Connection)
        # H1 connections have no _max_streams_cap attribute — cap is H2-only.
        assert not hasattr(inner, "_max_streams_cap")


class TestPerStreamTimeout:
    """Tests for the per-stream timeout in ``handle_async_request``.

    Verifies that ``stream_read`` (or the fallback ``read`` timeout) is
    enforced via ``asyncio.wait_for`` around ``_receive_response``, that
    RST_STREAM is sent before semaphore release, and that the send phases
    are NOT wrapped by the timeout.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_request(
        stream_read: float | None = None,
        read_timeout: float | None = None,
    ) -> MagicMock:
        """Create a mock Request with the correct ``extensions`` dict.

        Args:
            stream_read: Per-stream timeout for ``extensions["stream_read"]``.
            read_timeout: Read timeout for ``extensions["timeout"]["read"]``.

        Returns:
            A MagicMock request whose ``extensions`` is a real dict so
            ``request.extensions.get(...)`` behaves correctly.
        """
        request = MagicMock()
        request.url.origin = MagicMock()
        extensions: dict[str, object] = {"stream_read": stream_read}
        if read_timeout is not None:
            extensions["timeout"] = {"read": read_timeout}
        request.extensions = extensions
        return request

    @staticmethod
    def _setup_conn_for_handle(conn: FixedHTTP2Connection) -> int:
        """Configure a conn from ``_make_conn`` for ``handle_async_request``.

        Sets up ``get_next_available_stream_id`` and no-op send mocks.

        Returns:
            The stream ID that ``get_next_available_stream_id`` will return.
        """
        stream_id = 1
        conn._h2_state.get_next_available_stream_id = MagicMock(  # type: ignore[reportPrivateUsage]
            return_value=stream_id
        )
        conn._send_request_headers = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._send_request_body = AsyncMock()  # type: ignore[reportPrivateUsage]
        return stream_id

    @staticmethod
    async def _hang_forever(
        **kwargs: object,
    ) -> tuple[int, list[tuple[bytes, bytes]]]:
        """Mock ``_receive_response`` that hangs beyond any deadline."""
        await asyncio.sleep(10)
        return (200, [])

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_per_stream_timeout_fires_releases_semaphore_and_survives(
        self,
    ) -> None:
        """Per-stream timeout fires, releases semaphore, connection survives.

        When ``stream_read`` deadline is exceeded, ``ReadTimeout`` is
        raised, RST_STREAM is sent, the semaphore slot is released, and
        a second stream on the same connection continues unaffected.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        stream_id = self._setup_conn_for_handle(conn)
        conn._write_outgoing_data = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        # Second stream to prove the connection survives
        other_stream = 3
        conn._events[other_stream] = []  # type: ignore[reportPrivateUsage]

        request = self._make_request(stream_read=0.05)

        with pytest.raises(ReadTimeout):
            await conn.handle_async_request(request)

        # RST_STREAM was sent
        conn._h2_state.reset_stream.assert_called_with(  # type: ignore[reportPrivateUsage]
            stream_id
        )
        # Outgoing data was flushed
        conn._write_outgoing_data.assert_called_once()  # type: ignore[reportPrivateUsage]
        # Semaphore released — _response_closed ran and deleted the stream
        assert stream_id not in conn._events  # type: ignore[reportPrivateUsage]
        # Second stream unaffected
        assert other_stream in conn._events  # type: ignore[reportPrivateUsage]
        assert conn._state != HTTPConnectionState.CLOSED  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_per_stream_timeout_does_not_fire_for_fast_response(
        self,
    ) -> None:
        """Fast response does not trigger the per-stream timeout.

        When ``_receive_response`` returns immediately, the
        ``stream_read`` deadline is not reached and a ``Response`` is
        returned normally.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)

        status = 200
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            return_value=(status, headers)
        )

        request = self._make_request(stream_read=0.05)

        result = await conn.handle_async_request(request)

        assert isinstance(result, Response)
        assert result.status == status

    @pytest.mark.asyncio
    async def test_stream_read_takes_priority_over_read(self) -> None:
        """``stream_read`` takes priority over the ``read`` timeout.

        When both ``stream_read`` and ``timeout.read`` are set, the
        smaller ``stream_read`` value is used, proving priority over
        the larger ``read`` value.
        """
        cfg = CanonicalConfig.from_example_files()
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)
        conn._write_outgoing_data = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        # stream_read=0.05 takes priority over read=cfg.timeout_read (120.0)
        request = self._make_request(stream_read=0.05, read_timeout=cfg.timeout_read)

        start = time.monotonic()
        with pytest.raises(ReadTimeout):
            await conn.handle_async_request(request)
        elapsed = time.monotonic() - start

        # Should fire after ~0.05 s, not 120 s
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_stream_read_none_no_per_stream_timeout(self) -> None:
        """``stream_read=None`` disables the per-stream timeout.

        When ``stream_read`` is ``None``, ``_receive_response`` is called
        directly without ``asyncio.wait_for`` wrapping.  The socket-level
        ``read`` timeout remains as the backstop — preserving the original
        behavior where active streams keep the socket busy and a starved
        stream does NOT time out at the event-loop level.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)

        status = 200
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            return_value=(status, headers)
        )

        # stream_read=None, read=0.001 (very small) — if the code fell back
        # to using read as the asyncio.wait_for timeout, this would raise
        # ReadTimeout.  Instead, no per-stream timeout is applied.
        request = self._make_request(stream_read=None, read_timeout=0.001)

        result = await conn.handle_async_request(request)

        assert isinstance(result, Response)
        assert result.status == status
        # _receive_response was called directly (not through asyncio.wait_for)
        conn._receive_response.assert_called_once()  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_rst_stream_sent_before_semaphore_release(self) -> None:
        """RST_STREAM sent before semaphore release; cleanup runs even if write fails.

        Verifies that ``reset_stream`` and ``_write_outgoing_data`` are
        called in the inner ``except TimeoutError`` handler before the
        outer ``except BaseException`` → ``_response_closed`` path.  The
        inner handler converts ``TimeoutError`` to ``ReadTimeout``.  Also
        verifies that even if ``_write_outgoing_data`` raises,
        ``_response_closed`` still runs and releases the semaphore.
        """
        # --- Scenario A: Normal call order ---
        conn = TestFixedHTTP2Connection._make_conn()
        stream_id = self._setup_conn_for_handle(conn)

        call_order: list[str] = []

        conn._h2_state.reset_stream = MagicMock(  # type: ignore[reportPrivateUsage]
            side_effect=lambda sid: call_order.append("reset_stream")
        )

        async def _track_write(*args: object, **kwargs: object) -> None:
            call_order.append("write_outgoing_data")

        conn._write_outgoing_data = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=_track_write
        )
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        original_closed = conn._response_closed  # type: ignore[reportPrivateUsage]

        async def _track_closed(stream_id: int) -> None:
            call_order.append("response_closed")
            await original_closed(stream_id=stream_id)

        conn._response_closed = _track_closed  # type: ignore[reportPrivateUsage]

        request = self._make_request(stream_read=0.05)

        with pytest.raises(ReadTimeout):
            await conn.handle_async_request(request)

        # reset_stream and write_outgoing_data called before response_closed
        assert call_order[0] == "reset_stream"
        assert call_order[1] == "write_outgoing_data"
        assert call_order[2] == "response_closed"
        # Semaphore released
        assert stream_id not in conn._events  # type: ignore[reportPrivateUsage]

        # --- Scenario B: _write_outgoing_data raises ---
        conn2 = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn2)
        conn2._write_outgoing_data = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=RuntimeError("write failed")
        )
        conn2._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        request2 = self._make_request(stream_read=0.05)

        # RuntimeError from _write_outgoing_data is caught by except BaseException
        with pytest.raises(RuntimeError, match="write failed"):
            await conn2.handle_async_request(request2)

        # _response_closed still ran — semaphore released
        assert stream_id not in conn2._events  # type: ignore[reportPrivateUsage]

    @pytest.mark.asyncio
    async def test_send_request_phases_not_wrapped_by_wait_for(self) -> None:
        """Send phases are not wrapped by ``asyncio.wait_for``.

        ``_send_request_headers`` and ``_send_request_body`` are outside
        the ``asyncio.wait_for`` wrapper.  Even if
        ``_send_request_headers`` sleeps longer than the ``stream_read``
        deadline, no ``TimeoutError`` fires during the send phase.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)

        async def _slow_send(**kwargs: object) -> None:
            await asyncio.sleep(0.2)

        conn._send_request_headers = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=_slow_send
        )

        status = 200
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            return_value=(status, headers)
        )

        # stream_read=0.05 — if send phases were wrapped, this would timeout
        request = self._make_request(stream_read=0.05)

        result = await conn.handle_async_request(request)

        assert isinstance(result, Response)
        assert result.status == status

    # ------------------------------------------------------------------
    # Per-stream timeout logging tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_per_stream_timeout_emits_info_log_with_stream_id_and_stream_read(
        self,
    ) -> None:
        """Per-stream timeout emits an INFO log with stream_id and stream_read.

        Verifies that the inner ``except TimeoutError`` handler logs at
        INFO level before sending RST_STREAM and raising ``ReadTimeout``.
        The log message must contain ``stream_id`` and ``stream_read``
        values, and must be emitted before ``reset_stream``.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        stream_id = self._setup_conn_for_handle(conn)
        conn._write_outgoing_data = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        request = self._make_request(stream_read=0.05)

        call_order: list[str] = []

        with patch("src.core.http2.h2_connection.logger") as mock_logger:

            def _track_info(*args: object, **kwargs: object) -> None:
                call_order.append("info_log")

            mock_logger.info.side_effect = _track_info

            conn._h2_state.reset_stream = MagicMock(  # type: ignore[reportPrivateUsage]
                side_effect=lambda sid: call_order.append("reset_stream")
            )

            with pytest.raises(ReadTimeout):
                await conn.handle_async_request(request)

        # Exactly one INFO log
        mock_logger.info.assert_called_once()

        # Log message contains expected substrings
        log_message: str = mock_logger.info.call_args[0][0]
        assert "Per-stream response timeout" in log_message
        assert f"stream_id={stream_id}" in log_message
        assert "stream_read=" in log_message
        # stream_read=0.05 formatted as :.0f gives "0"
        assert "stream_read=0s" in log_message

        # No ERROR or WARNING logs — confirming INFO level
        mock_logger.error.assert_not_called()
        mock_logger.warning.assert_not_called()

        # Log emitted before reset_stream (RST_STREAM + raise sequence)
        assert call_order[0] == "info_log"
        assert call_order[1] == "reset_stream"

    @pytest.mark.asyncio
    async def test_no_per_stream_timeout_log_when_stream_read_is_none(
        self,
    ) -> None:
        """No per-stream timeout log when stream_read is None.

        When ``stream_read`` is ``None``, the ``asyncio.wait_for`` block
        is never entered, so no per-stream timeout log is emitted.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)

        status = 200
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            return_value=(status, headers)
        )

        request = self._make_request(stream_read=None)

        with patch("src.core.http2.h2_connection.logger") as mock_logger:
            result = await conn.handle_async_request(request)

        assert isinstance(result, Response)
        assert result.status == status
        # No per-stream timeout log was emitted
        mock_logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_stream_timeout_log_emitted_exactly_once(
        self,
    ) -> None:
        """Per-stream timeout INFO log fires exactly once, not duplicated.

        Under sustained stream starvation, the INFO log fires once per
        timed-out stream.  The outer ``except BaseException`` →
        ``_response_closed`` cleanup path does NOT emit a duplicate log.
        """
        conn = TestFixedHTTP2Connection._make_conn()
        self._setup_conn_for_handle(conn)
        conn._write_outgoing_data = AsyncMock()  # type: ignore[reportPrivateUsage]
        conn._receive_response = AsyncMock(  # type: ignore[reportPrivateUsage]
            side_effect=self._hang_forever
        )

        request = self._make_request(stream_read=0.05)

        with (
            patch("src.core.http2.h2_connection.logger") as mock_logger,
            pytest.raises(ReadTimeout),
        ):
            await conn.handle_async_request(request)

        # Log fires exactly once — not duplicated by outer cleanup path
        assert mock_logger.info.call_count == 1
