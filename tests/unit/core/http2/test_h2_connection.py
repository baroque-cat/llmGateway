"""Unit tests for FixedHTTP2Connection in src.core.http2.h2_connection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import h2.connection
import h2.events
import h2.settings
import pytest
from httpcore._async.http2 import HTTPConnectionState
from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._models import Origin

from src.core.http2.connection import CapacityAwareHTTPConnection
from src.core.http2.h2_connection import FixedHTTP2Connection
from src.core.http2.semaphore import NonBlockingSemaphore


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
    ) -> FixedHTTP2Connection:
        """Create a FixedHTTP2Connection with common mocks set up.

        Args:
            max_streams: Initial value for ``_max_streams`` and the
                ``local_settings.max_concurrent_streams`` mock.
            sent_init: Whether ``_sent_connection_init`` is True.
            max_streams_cap: Value for ``_max_streams_cap`` (the per-provider
                cap). ``None`` means no cap (default behavior).
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
        """Cancelled stream (not in _closed_streams): reset_stream called."""
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
