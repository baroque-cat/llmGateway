"""Fixed HTTP/2 connection — subclass of httpcore's AsyncHTTP2Connection.

Backports the core fixes from both upstream httpcore PRs:

* **PR #1022 (Stream Desync):** ``_response_closed`` synchronises h2 stream
  state with httpcore's semaphore after asyncio task cancellation.

* **PR #1088 (Connection Growth):** Non-blocking semaphore acquire in
  ``handle_async_request``, capacity-aware ``is_available``, ``_closed_streams``
  tracking, ``max_concurrent_requests``, and ``on_capacity_update`` callback on
  SETTINGS changes.

``handle_async_request`` is copied from httpcore 1.0.9 because
``AsyncSemaphore`` is created *inside* the method's ``_init_lock`` block,
not in ``__init__``.  Without modifying httpcore source, the only way to
replace ``AsyncSemaphore`` with ``NonBlockingSemaphore`` is to override the
entire method.  The single functional change is on the semaphore creation
and acquire lines, clearly marked with comment blocks.

Remove this class when upstream httpcore merges both fixes.
"""

from __future__ import annotations

import logging
import time
import typing

import h2.connection
import h2.events
import h2.exceptions
import h2.settings
from httpcore._async.http2 import (
    AsyncHTTP2Connection,
    HTTP2ConnectionByteStream,
    HTTPConnectionState,
)
from httpcore._exceptions import (
    ConnectionNotAvailable,
    LocalProtocolError,
    RemoteProtocolError,
)
from httpcore._models import Response
from httpcore._synchronization import AsyncShieldCancellation
from httpcore._trace import Trace

from src.core.http2.semaphore import NonBlockingSemaphore

logger = logging.getLogger("httpcore.http2")


class FixedHTTP2Connection(AsyncHTTP2Connection):
    """HTTP/2 connection with stream-desync and connection-growth fixes.

    Overrides:

    * ``__init__`` — adds ``_on_capacity_update`` and ``_closed_streams``
    * ``_response_closed`` — synchronises h2 state on cancellation
    * ``_receive_events`` — tracks server-closed streams
    * ``_receive_remote_settings_change`` — fires capacity callback
    * ``is_available`` — checks H2 stream capacity
    * ``max_concurrent_requests`` — exposes stream limit
    * ``handle_async_request`` — non-blocking semaphore acquire
      (copied from httpcore 1.0.9; see class docstring for rationale)
    """

    def __init__(
        self,
        origin: typing.Any,
        stream: typing.Any,
        keepalive_expiry: float | None = None,
        on_capacity_update: typing.Callable[..., typing.Any] | None = None,
    ) -> None:
        super().__init__(
            origin=origin,
            stream=stream,
            keepalive_expiry=keepalive_expiry,
        )
        self._on_capacity_update: typing.Callable[..., typing.Any] | None = (
            on_capacity_update
        )
        self._closed_streams: set[int] = set()

    # ------------------------------------------------------------------
    # _response_closed — stream desync fix (PR #1022)
    # ------------------------------------------------------------------

    async def _response_closed(self, stream_id: int) -> None:
        """Release stream resources, synchronising h2 state with the semaphore.

        When a stream is cancelled (not in ``_closed_streams``), we explicitly
        reset it in h2's state to prevent phantom stream accumulation that
        leads to ``NoAvailableStreamIDError``.

        Semaphore release is conditional — only if ``len(self._events)`` is
        within the stream limit, preventing semaphore overflow when the
        server changes ``SETTINGS_MAX_CONCURRENT_STREAMS``.
        """
        stream_was_reset = stream_id not in self._closed_streams

        if stream_was_reset:
            try:
                self._h2_state.reset_stream(stream_id)
            except h2.exceptions.NoSuchStreamError:
                pass
            except h2.exceptions.ProtocolError:
                pass

        # Conditional release — prevent semaphore overflow.
        if len(self._events) <= self._max_streams:
            await self._max_streams_semaphore.release()

        self._closed_streams.discard(stream_id)
        del self._events[stream_id]

        async with self._state_lock:
            if self._connection_terminated and not self._events:
                await self.aclose()
            elif self._state == HTTPConnectionState.ACTIVE and not self._events:
                if stream_was_reset or self._used_all_stream_ids:
                    await self.aclose()
                else:
                    self._state = HTTPConnectionState.IDLE
                    if self._keepalive_expiry is not None:
                        now = time.monotonic()
                        self._expire_at = now + self._keepalive_expiry

    # ------------------------------------------------------------------
    # _receive_events — track server-closed streams
    # ------------------------------------------------------------------

    async def _receive_events(
        self, request: typing.Any, stream_id: int | None = None
    ) -> None:
        """Read network data, tracking which streams the server closes.

        Adds stream IDs from ``StreamEnded`` and ``StreamReset`` events
        to ``_closed_streams`` so that ``_response_closed`` can distinguish
        between cleanly-closed and cancelled streams.
        """
        async with self._read_lock:
            if self._connection_terminated is not None:
                last_stream_id = self._connection_terminated.last_stream_id
                if stream_id and last_stream_id and stream_id > last_stream_id:
                    self._request_count -= 1
                    raise ConnectionNotAvailable()
                raise RemoteProtocolError(self._connection_terminated)

            if stream_id is None or not self._events.get(stream_id):
                events = await self._read_incoming_data(request)
                for event in events:
                    if isinstance(event, h2.events.RemoteSettingsChanged):
                        async with Trace(
                            "receive_remote_settings", logger, request
                        ) as trace:
                            await self._receive_remote_settings_change(event)
                            trace.return_value = event

                    elif isinstance(
                        event,
                        (
                            h2.events.ResponseReceived,
                            h2.events.DataReceived,
                            h2.events.StreamEnded,
                            h2.events.StreamReset,
                        ),
                    ):
                        if event.stream_id in self._events:
                            self._events[event.stream_id].append(event)

                    elif isinstance(event, h2.events.ConnectionTerminated):
                        self._connection_terminated = event

                    # --- TRACK SERVER-CLOSED STREAMS ---
                    if isinstance(
                        event,
                        (h2.events.StreamEnded, h2.events.StreamReset),
                    ):
                        self._closed_streams.add(event.stream_id)

        await self._write_outgoing_data(request)

    # ------------------------------------------------------------------
    # _receive_remote_settings_change — capacity callback
    # ------------------------------------------------------------------

    async def _receive_remote_settings_change(
        self, event: h2.events.RemoteSettingsChanged
    ) -> None:
        """Handle SETTINGS frame from server, firing capacity callback.

        After adjusting the semaphore for a new ``MAX_CONCURRENT_STREAMS``
        value, calls ``_on_capacity_update()`` to inform the connection pool
        that capacity has changed.
        """
        max_concurrent_streams = event.changed_settings.get(
            h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS
        )
        if max_concurrent_streams:
            new_max_streams = min(
                max_concurrent_streams.new_value,
                self._h2_state.local_settings.max_concurrent_streams,
            )
            if new_max_streams and new_max_streams != self._max_streams:
                while new_max_streams > self._max_streams:
                    await self._max_streams_semaphore.release()
                    self._max_streams += 1
                while new_max_streams < self._max_streams:
                    await self._max_streams_semaphore.acquire()
                    self._max_streams -= 1

                if self._on_capacity_update is not None:
                    await self._on_capacity_update()

    # ------------------------------------------------------------------
    # is_available — check H2 stream capacity
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` if this connection can accept a new request.

        Extends the parent check with a stream-capacity check:
        ``len(self._events) < self.max_concurrent_requests()``.
        """
        return (
            self._state != HTTPConnectionState.CLOSED
            and not self._connection_error
            and not self._used_all_stream_ids
            and len(self._events) < self.max_concurrent_requests()
            and self._h2_state.state_machine.state
            != h2.connection.ConnectionState.CLOSED
        )

    # ------------------------------------------------------------------
    # max_concurrent_requests — expose stream limit
    # ------------------------------------------------------------------

    def max_concurrent_requests(self) -> int:
        """Return the number of concurrent streams this connection supports."""
        if self._sent_connection_init:
            return self._max_streams
        return 1

    # ------------------------------------------------------------------
    # handle_async_request — non-blocking semaphore (PR #1088)
    #
    # COPIED from httpcore 1.0.9 (AsyncHTTP2Connection.handle_async_request).
    # The method is duplicated here because AsyncSemaphore is created inside
    # the _init_lock block — there is no hook to inject NonBlockingSemaphore
    # without replacing the entire method.
    #
    # FUNCTIONAL CHANGES from the original:
    #   1. AsyncSemaphore → NonBlockingSemaphore (line marked [CHANGE 1])
    #   2. blocking acquire() → non-blocking acquire_nowait() with state
    #      rollback on failure (lines marked [CHANGE 2])
    #   Everything else is identical to httpcore 1.0.9.
    # ------------------------------------------------------------------

    async def handle_async_request(self, request: typing.Any) -> Response:
        """Handle an HTTP request, using a non-blocking stream-slot semaphore.

        Raises ``ConnectionNotAvailable`` when no H2 stream slots are
        free, signalling the connection pool to route the request elsewhere.
        """
        if not self.can_handle_request(request.url.origin):
            raise RuntimeError(
                f"Attempted to send request to {request.url.origin} on connection "
                f"to {self._origin}"
            )

        async with self._state_lock:
            if self._state in (HTTPConnectionState.ACTIVE, HTTPConnectionState.IDLE):
                self._request_count += 1
                self._expire_at = None
                previous_state = self._state
                previous_expire_at = self._expire_at
                self._state = HTTPConnectionState.ACTIVE
            else:
                raise ConnectionNotAvailable()

        async with self._init_lock:
            if not self._sent_connection_init:
                try:
                    sci_kwargs = {"request": request}
                    async with Trace(
                        "send_connection_init", logger, request, sci_kwargs
                    ):
                        await self._send_connection_init(**sci_kwargs)
                except BaseException as exc:
                    with AsyncShieldCancellation():
                        await self.aclose()
                    raise exc

                self._sent_connection_init = True

                # Initially start with just 1 until the remote server provides
                # its max_concurrent_streams value
                self._max_streams = 1

                local_settings_max_streams = (
                    self._h2_state.local_settings.max_concurrent_streams
                )
                # [CHANGE 1] Use NonBlockingSemaphore instead of AsyncSemaphore.
                self._max_streams_semaphore = NonBlockingSemaphore(
                    local_settings_max_streams
                )

                for _ in range(local_settings_max_streams - self._max_streams):
                    await self._max_streams_semaphore.acquire()

        # [CHANGE 2] Non-blocking semaphore acquire with state rollback.
        # ORIGINAL (httpcore 1.0.9, line 131):
        #     await self._max_streams_semaphore.acquire()
        if not self._max_streams_semaphore.acquire_nowait():
            async with self._state_lock:
                self._request_count -= 1
                if not self._events:
                    self._state = previous_state
                    self._expire_at = previous_expire_at
            raise ConnectionNotAvailable()

        try:
            stream_id = self._h2_state.get_next_available_stream_id()
            self._events[stream_id] = []
        except h2.exceptions.NoAvailableStreamIDError:  # pragma: nocover
            self._used_all_stream_ids = True
            self._request_count -= 1
            raise ConnectionNotAvailable() from None

        try:
            kwargs = {"request": request, "stream_id": stream_id}
            async with Trace("send_request_headers", logger, request, kwargs):
                await self._send_request_headers(request=request, stream_id=stream_id)
            async with Trace("send_request_body", logger, request, kwargs):
                await self._send_request_body(request=request, stream_id=stream_id)
            async with Trace(
                "receive_response_headers", logger, request, kwargs
            ) as trace:
                status, headers = await self._receive_response(
                    request=request, stream_id=stream_id
                )
                trace.return_value = (status, headers)

            return Response(
                status=status,
                headers=headers,
                content=HTTP2ConnectionByteStream(self, request, stream_id=stream_id),
                extensions={
                    "http_version": b"HTTP/2",
                    "network_stream": self._network_stream,
                    "stream_id": stream_id,
                },
            )
        except BaseException as exc:
            with AsyncShieldCancellation():
                kwargs = {"stream_id": stream_id}
                async with Trace("response_closed", logger, request, kwargs):
                    await self._response_closed(stream_id=stream_id)

            if isinstance(exc, h2.exceptions.ProtocolError):
                if self._connection_terminated:  # pragma: nocover
                    raise RemoteProtocolError(self._connection_terminated) from exc
                raise LocalProtocolError(exc) from exc  # pragma: nocover

            raise exc
