"""
Monkey-patches for httpcore HTTP/2 bugs.

Fixes two upstream httpcore bugs:

Bug #1 — Stream Desync (encode/httpcore#1022):
    _response_closed releases the semaphore but h2's internal state
    still considers the stream open, causing 'Max outbound streams'
    errors after asyncio task cancellation.

Bug #2 — Connection Growth (encode/httpcore#1088 / issue #248):
    httpx connection pool does not open new TCP connections when
    existing HTTP/2 connections reach their stream limit, because
    the pool's is_available() check is unaware of H2 stream capacity.

Remove this module once both fixes are merged upstream into httpcore.
"""

from __future__ import annotations

import logging
from typing import Any

import httpcore
from packaging.version import Version

logger = logging.getLogger(__name__)

PATCH_TARGET_VERSION = "1.0.9"

# Independent patch guards.
_stream_desync_patched = False
_connection_growth_patched = False


# ---------------------------------------------------------------------------
# Bug #1: Stream Desync (httpcore#1022)
# ---------------------------------------------------------------------------


def _make_patched_response_closed(
    async_original: Any,
    sync_original: Any,
) -> tuple[Any, Any]:
    """Return (async_patched, sync_patched) wrappers for _response_closed.

    Each wrapper checks whether the stream is still open in h2's
    internal state and explicitly resets it before releasing the
    semaphore.  This keeps httpcore's semaphore count and h2's
    stream count in sync when a task is cancelled between the
    end_stream() call and the actual frame transmission.
    """

    async def _patched_async(self: Any, stream_id: int) -> None:
        # When a task is cancelled, the stream may still be open in h2's
        # state even though httpcore's semaphore will be released.
        # We must explicitly close the stream in h2's state to keep
        # httpcore's semaphore count and h2's stream count in sync.
        #
        # If the stream object does not exist (cancelled before
        # send_headers), h2 never counted it — no cleanup needed.
        stream = self._h2_state.streams.get(stream_id)
        if stream is not None and not stream.closed:
            # Stream object exists and is open — safe to reset.
            self._h2_state.reset_stream(stream_id)
        await async_original(self, stream_id)

    def _patched_sync(self: Any, stream_id: int) -> None:
        stream = self._h2_state.streams.get(stream_id)
        if stream is not None and not stream.closed:
            self._h2_state.reset_stream(stream_id)
        sync_original(self, stream_id)

    return _patched_async, _patched_sync


def _apply_stream_desync_fix() -> None:
    """Apply the HTTP/2 stream desync fix (Bug #1).

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _stream_desync_patched
    if _stream_desync_patched:
        return

    from httpcore._async.http2 import AsyncHTTP2Connection
    from httpcore._sync.http2 import HTTP2Connection

    async_original = AsyncHTTP2Connection._response_closed  # type: ignore[reportPrivateUsage]
    sync_original = HTTP2Connection._response_closed  # type: ignore[reportPrivateUsage]

    patched_async, patched_sync = _make_patched_response_closed(
        async_original, sync_original
    )

    AsyncHTTP2Connection._response_closed = patched_async  # type: ignore[reportPrivateUsage]
    HTTP2Connection._response_closed = patched_sync  # type: ignore[reportPrivateUsage]

    _stream_desync_patched = True
    logger.info("httpcore HTTP/2 stream desync patch applied (issue #1022).")


# ---------------------------------------------------------------------------
# Bug #2: Connection Growth (httpcore#1088 / issue #248)
# ---------------------------------------------------------------------------


def _add_semaphore_available_property() -> None:
    """Add .available property to httpcore's semaphore classes.

    The property exposes the number of remaining acquire slots.
    Required by the connection-growth fix so the pool can query
    whether an H2 connection has room for another stream.
    """
    from httpcore._synchronization import AsyncSemaphore, Semaphore

    if hasattr(AsyncSemaphore, "available"):
        return  # Already patched.

    def _async_available(self: Any) -> int:
        """Number of slots remaining on this async semaphore."""
        if not getattr(self, "_backend", ""):
            self.setup()
        if self._backend == "asyncio":
            return self._anyio_semaphore.value
        if self._backend == "trio":
            return self._trio_semaphore.value
        return 0

    def _sync_available(self: Any) -> int:
        """Number of slots remaining on this sync semaphore."""
        # threading.Semaphore internal counter (stable CPython implementation).
        return self._semaphore._value

    AsyncSemaphore.available = property(_async_available)  # type: ignore[attr-defined]
    Semaphore.available = property(_sync_available)  # type: ignore[attr-defined]


def _patch_h2_is_available() -> None:
    """Add stream-capacity awareness to H2 is_available().

    Without this, the connection pool considers an H2 connection
    'available' even when all its streams are occupied.  The pool
    then keeps routing requests to the same connection instead of
    opening new TCP connections.

    After the patch, is_available() returns False when there are
    no free H2 streams, signalling the pool to look elsewhere.
    """
    from httpcore._async.http2 import AsyncHTTP2Connection
    from httpcore._sync.http2 import HTTP2Connection

    _async_orig = AsyncHTTP2Connection.is_available
    _sync_orig = HTTP2Connection.is_available

    if getattr(_async_orig, "__httpcore_capacity_aware__", False):
        return  # Already patched.

    def _async_is_available(self: Any) -> bool:
        if not _async_orig(self):
            return False
        sem = getattr(self, "_max_streams_semaphore", None)
        return sem is None or sem.available is None or sem.available > 0

    def _sync_is_available(self: Any) -> bool:
        if not _sync_orig(self):
            return False
        sem = getattr(self, "_max_streams_semaphore", None)
        return sem is None or sem.available is None or sem.available > 0

    _async_is_available.__httpcore_capacity_aware__ = True  # type: ignore[attr-defined]
    AsyncHTTP2Connection.is_available = _async_is_available
    HTTP2Connection.is_available = _sync_is_available


def _patch_h2_nonblocking_semaphore() -> None:
    """Replace blocking semaphore acquire in H2 handle_request.

    Changes line 131 of handle_async_request / handle_request from
    blocking ``semaphore.acquire()`` to a non-blocking check that
    raises ``ConnectionNotAvailable`` when no streams are free.

    This is the core of the PR #1088 fix: without it, requests
    block indefinitely on the semaphore instead of signalling the
    pool to open new connections.
    """
    from httpcore._async.http2 import AsyncHTTP2Connection

    async_orig = AsyncHTTP2Connection.handle_async_request

    if getattr(async_orig, "__httpcore_nonblocking__", False):
        return

    async def _async_handle_request(self: Any, request: Any) -> Any:
        import h2.exceptions as h2_exc
        from httpcore._async.http2 import (
            HTTP2ConnectionByteStream,
            HTTPConnectionState,
        )
        from httpcore._exceptions import (
            ConnectionNotAvailable,
            LocalProtocolError,
            RemoteProtocolError,
        )
        from httpcore._models import Response
        from httpcore._synchronization import AsyncSemaphore, AsyncShieldCancellation
        from httpcore._trace import Trace

        if not self.can_handle_request(request.url.origin):
            raise RuntimeError(
                f"Attempted to send request to {request.url.origin} "
                f"on connection to {self._origin}"
            )

        async with self._state_lock:
            if self._state in (HTTPConnectionState.ACTIVE, HTTPConnectionState.IDLE):
                self._request_count += 1
                self._expire_at = None
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
                self._max_streams = 1

                local_settings_max_streams = (
                    self._h2_state.local_settings.max_concurrent_streams
                )
                self._max_streams_semaphore = AsyncSemaphore(
                    local_settings_max_streams
                )

                for _ in range(local_settings_max_streams - self._max_streams):
                    await self._max_streams_semaphore.acquire()

        # --- PATCH: non-blocking semaphore acquire (Bug #2 fix) ---
        if self._max_streams_semaphore.available <= 0:  # type: ignore[reportAttributeAccessIssue]
            self._request_count -= 1
            raise ConnectionNotAvailable()
        await self._max_streams_semaphore.acquire()

        try:
            stream_id = self._h2_state.get_next_available_stream_id()
            self._events[stream_id] = []
        except h2_exc.NoAvailableStreamIDError as exc:
            self._used_all_stream_ids = True
            self._request_count -= 1
            raise ConnectionNotAvailable() from exc

        try:
            kwargs = {"request": request, "stream_id": stream_id}
            async with Trace("send_request_headers", logger, request, kwargs):
                await self._send_request_headers(
                    request=request, stream_id=stream_id
                )
            async with Trace("send_request_body", logger, request, kwargs):
                await self._send_request_body(
                    request=request, stream_id=stream_id
                )
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
                content=HTTP2ConnectionByteStream(
                    self, request, stream_id=stream_id
                ),
                extensions={
                    "http_version": b"HTTP/2",
                    "network_stream": self._network_stream,
                    "stream_id": stream_id,
                },
            )
        except BaseException as exc:
            with AsyncShieldCancellation():
                kwargs_c = {"stream_id": stream_id}
                async with Trace("response_closed", logger, request, kwargs_c):
                    await self._response_closed(stream_id=stream_id)

            if isinstance(exc, h2_exc.ProtocolError):
                if self._connection_terminated:
                    raise RemoteProtocolError(
                        self._connection_terminated
                    ) from exc
                raise LocalProtocolError(exc) from exc

            raise exc

    _async_handle_request.__httpcore_nonblocking__ = True  # type: ignore[attr-defined]
    AsyncHTTP2Connection.handle_async_request = _async_handle_request

    logger.info("httpcore H2 async handle_request patched (non-blocking semaphore).")


def _apply_connection_growth_fix() -> None:
    """Apply the connection-growth fix (Bug #2).

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _connection_growth_patched
    if _connection_growth_patched:
        return

    _add_semaphore_available_property()
    _patch_h2_is_available()
    _patch_h2_nonblocking_semaphore()

    _connection_growth_patched = True
    logger.info(
        "httpcore HTTP/2 connection-growth patch applied "
        "(issue #1088 / #248)."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_patch() -> None:
    """Apply all httpcore HTTP/2 fixes.

    Must be called before any httpx.AsyncClient is created.
    Safe to call multiple times — subsequent calls are no-ops.
    Idempotent: each sub-patch tracks its own applied state.
    """
    current = Version(httpcore.__version__)

    if current != Version(PATCH_TARGET_VERSION):
        logger.warning(
            "httpcore_patch: expected version %s, got %s. "
            "Patch may not apply correctly.",
            PATCH_TARGET_VERSION,
            current,
        )

    _apply_stream_desync_fix()
    _apply_connection_growth_fix()
