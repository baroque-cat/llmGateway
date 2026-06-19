"""Capacity-aware HTTP connection wrapper.

Subclasses httpcore's ``AsyncHTTPConnection`` to create
:class:`FixedHTTP2Connection` instead of ``AsyncHTTP2Connection``
when HTTP/2 is negotiated.

Also adds ``max_concurrent_requests()`` — delegates to the underlying
connection's method, or returns ``1`` when no connection is established.
"""

from __future__ import annotations

import logging
import typing

from httpcore._async.connection import AsyncHTTPConnection
from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._models import Response

from src.core.http2.h2_connection import FixedHTTP2Connection

logger = logging.getLogger("httpcore.connection")


class CapacityAwareHTTPConnection(AsyncHTTPConnection):
    """HTTP connection wrapper that creates ``FixedHTTP2Connection`` for H2.

    When HTTP/2 is negotiated (via ALPN or ``http2=True`` with
    ``http1=False``), this class creates a :class:`FixedHTTP2Connection`
    with the ``on_capacity_update`` callback wired through to the pool.
    For HTTP/1.1, the standard ``AsyncHTTP11Connection`` is used.

    ``handle_async_request`` is duplicated from httpcore 1.0.9 because
    the H2 connection class is hardcoded in the parent's method — there
    is no hook to inject a different class.
    """

    def __init__(
        self,
        *args: typing.Any,
        on_capacity_update: typing.Callable[..., typing.Any] | None = None,
        **kwargs: typing.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._on_capacity_update: typing.Callable[..., typing.Any] | None = (
            on_capacity_update
        )

    async def handle_async_request(self, request: typing.Any) -> Response:
        """Handle request, creating ``FixedHTTP2Connection`` for HTTP/2.

        Duplicated from httpcore 1.0.9 (``AsyncHTTPConnection.handle_async_request``)
        with one change: ``AsyncHTTP2Connection`` → ``FixedHTTP2Connection``.
        """
        if not self.can_handle_request(request.url.origin):
            raise RuntimeError(
                f"Attempted to send request to {request.url.origin} "
                f"on connection to {self._origin}"
            )

        try:
            async with self._request_lock:
                if self._connection is None:
                    stream = await self._connect(request)

                    ssl_object = stream.get_extra_info("ssl_object")
                    http2_negotiated = (
                        ssl_object is not None
                        and ssl_object.selected_alpn_protocol() == "h2"
                    )
                    if http2_negotiated or (self._http2 and not self._http1):
                        self._connection = FixedHTTP2Connection(
                            origin=self._origin,
                            stream=stream,
                            keepalive_expiry=self._keepalive_expiry,
                            on_capacity_update=self._on_capacity_update,
                        )
                    else:
                        self._connection = AsyncHTTP11Connection(
                            origin=self._origin,
                            stream=stream,
                            keepalive_expiry=self._keepalive_expiry,
                        )
        except BaseException as exc:
            self._connect_failed = True
            raise exc

        return await self._connection.handle_async_request(request)

    def max_concurrent_requests(self) -> int:
        """Return concurrent request capacity of the underlying connection.

        Returns:
            The result of ``self._connection.max_concurrent_requests()``
            if a connection is established, otherwise ``1``.
        """
        if self._connection is None:
            return 1
        return self._connection.max_concurrent_requests()  # type: ignore[reportUnknownMemberType]
