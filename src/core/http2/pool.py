"""Capacity-aware HTTP/2 connection pool (httpcore-level).

Subclasses httpcore's ``AsyncConnectionPool`` to implement the full
PR #1088 mechanics:

* **connection_request_count** — tracks how many requests are assigned
  to each connection, preventing over-assignment beyond stream capacity.
* **on_capacity_update callback** — fired by H2 connections when
  ``SETTINGS_MAX_CONCURRENT_STREAMS`` changes, triggering immediate
  reassignment of queued requests.
* **max_concurrent_requests() query** — asks each connection for its
  stream capacity; falls back to ``1`` for HTTP/1.1 connections.

This is the low-level pool component.  It is wrapped by
:class:`src.core.http2.transport.CapacityAwareHttp2Transport`
(an ``httpx.AsyncHTTPTransport`` subclass) for httpx integration.
"""

from __future__ import annotations

import logging
import ssl
import typing

from httpcore._async.connection_pool import AsyncConnectionPool
from httpcore._async.http11 import AsyncHTTP11Connection
from httpcore._async.interfaces import AsyncConnectionInterface
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkBackend
from httpcore._models import Origin

from src.core.http2.connection import CapacityAwareHTTPConnection
from src.core.http2.h2_connection import FixedHTTP2Connection

logger = logging.getLogger("httpcore.connection")


class CapacityAwareHttp2Pool(AsyncConnectionPool):
    """HTTP/2 connection pool with stream-capacity-aware request routing.

    Overrides ``create_connection`` to produce ``CapacityAwareHTTPConnection``
    instances wired with the capacity-update callback, and overrides
    ``_assign_requests_to_connections`` to track per-connection request
    counts and respect H2 stream limits.
    """

    def __init__(
        self,
        ssl_context: ssl.SSLContext | None = None,
        max_connections: int | None = 10,
        max_keepalive_connections: int | None = None,
        keepalive_expiry: float | None = None,
        http1: bool = True,
        http2: bool = False,
        retries: int = 0,
        local_address: str | None = None,
        uds: str | None = None,
        network_backend: AsyncNetworkBackend | None = None,
        socket_options: typing.Iterable[SOCKET_OPTION] | None = None,
        max_concurrent_streams_cap: int | None = None,
        provider_name: str = "unknown",
    ) -> None:
        super().__init__(
            ssl_context=ssl_context,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry,
            http1=http1,
            http2=http2,
            retries=retries,
            local_address=local_address,
            uds=uds,
            network_backend=network_backend,
            socket_options=socket_options,
        )
        self._max_concurrent_streams_cap: int | None = max_concurrent_streams_cap
        self._provider_name: str = provider_name
        self._connection_ordinal: int = 0

    # ------------------------------------------------------------------
    # create_connection — wire on_capacity_update callback
    # ------------------------------------------------------------------

    def create_connection(self, origin: Origin) -> AsyncConnectionInterface:
        """Create a new connection with the capacity-update callback.

        Overrides the parent to produce ``CapacityAwareHTTPConnection``
        instead of ``AsyncHTTPConnection``, passing ``on_capacity_update``
        through to the H2 layer.

        Note: SOCKS and HTTP proxy paths from the parent are deliberately
        omitted — this project uses httpx-level proxies, not httpcore-level
        proxy connections.
        """
        label = f"{self._provider_name}-conn-{self._connection_ordinal}"
        self._connection_ordinal += 1
        logger.info(f"Creating connection '{label}' for origin {origin}")
        return CapacityAwareHTTPConnection(
            origin=origin,
            ssl_context=self._ssl_context,
            keepalive_expiry=self._keepalive_expiry,
            http1=self._http1,
            http2=self._http2,
            retries=self._retries,
            local_address=self._local_address,
            uds=self._uds,
            network_backend=self._network_backend,
            socket_options=self._socket_options,
            on_capacity_update=self._connection_capacity_updated,
            max_concurrent_streams_cap=self._max_concurrent_streams_cap,
            connection_label=label,
        )

    # ------------------------------------------------------------------
    # _assign_requests_to_connections — capacity-aware routing
    # ------------------------------------------------------------------

    def _assign_requests_to_connections(self) -> list[AsyncConnectionInterface]:
        """Assign queued requests to connections with stream-capacity checks.

        Overrides the parent to add:

        1. ``connection_request_count`` — counts assigned requests per
           connection (prevents over-assignment beyond stream limits).
        2. Capacity check via ``_max_concurrent_requests(conn)`` when
           selecting an available connection.

        The parent's cleanup logic (closed/expired/idle) is preserved.
        """
        closing_connections: list[AsyncConnectionInterface] = []

        # --- parent cleanup logic (condensed) ---
        for connection in list(self._connections):
            if (
                connection.is_closed()
                or connection.has_expired()
                or (
                    connection.is_idle()
                    and len([c for c in self._connections if c.is_idle()])  # noqa: C419
                    > self._max_keepalive_connections
                )
            ):
                self._connections.remove(connection)
                if not connection.is_closed():
                    label = getattr(connection, "_connection_label", "")
                    logger.info(
                        f"Closing connection '{label}' (cleanup: closed/expired/idle)"
                    )
                    closing_connections.append(connection)

        # --- capacity-aware request assignment ---
        queued_requests = [r for r in self._requests if r.is_queued()]

        # Build request count per connection from already-assigned requests.
        connection_request_count: dict[AsyncConnectionInterface, int] = dict.fromkeys(
            self._connections, 0
        )
        for r in self._requests:
            conn = r.connection
            if conn in connection_request_count:
                connection_request_count[conn] += 1

        idle_connections = [c for c in self._connections if c.is_idle()]

        for pool_request in queued_requests:
            origin = pool_request.request.url.origin

            # Select first connection that can handle the origin, is
            # available, AND has capacity for another request.
            available_connection = next(
                (
                    conn
                    for conn in self._connections
                    if conn.can_handle_request(origin)
                    and conn.is_available()
                    and connection_request_count[conn]
                    < self._max_concurrent_requests(conn)
                ),
                None,
            )

            if available_connection is not None:
                pool_request.assign_to_connection(available_connection)
                connection_request_count[available_connection] += 1
            elif len(self._connections) < self._max_connections:
                connection = self.create_connection(origin)
                self._connections.append(connection)
                pool_request.assign_to_connection(connection)
                connection_request_count[connection] = 1
            elif idle_connections:
                connection = idle_connections[0]
                self._connections.remove(connection)
                label = getattr(connection, "_connection_label", "")
                logger.info(
                    f"Evicting idle connection '{label}' to make room for new connection"
                )
                closing_connections.append(connection)
                connection = self.create_connection(origin)
                self._connections.append(connection)
                pool_request.assign_to_connection(connection)
                connection_request_count[connection] = 1

        return closing_connections

    # ------------------------------------------------------------------
    # _connection_capacity_updated — callback handler
    # ------------------------------------------------------------------

    async def _connection_capacity_updated(self) -> None:
        """Handle capacity-update signal from a connection.

        Called when a ``FixedHTTP2Connection`` detects a change in
        ``SETTINGS_MAX_CONCURRENT_STREAMS``.  Re-runs the request
        assignment loop under the thread lock and closes any connections
        removed during reassignment.
        """
        with self._optional_thread_lock:
            closing = self._assign_requests_to_connections()
        await self._close_connections(closing)

    # ------------------------------------------------------------------
    # _max_concurrent_requests — capacity query helper
    # ------------------------------------------------------------------

    def _max_concurrent_requests(self, connection: AsyncConnectionInterface) -> int:
        """Return the max concurrent requests a connection supports.

        Args:
            connection: A connection in the pool.

        Returns:
            The result of ``connection.max_concurrent_requests()`` or
            ``1`` if the connection does not implement the method
            (fallback for HTTP/1.1 and unpatched connections).
        """
        try:
            return int(connection.max_concurrent_requests())  # type: ignore[reportUnknownMemberType]
        except AttributeError:
            return 1

    # ------------------------------------------------------------------
    # get_health_summary — pool health statistics
    # ------------------------------------------------------------------

    def get_health_summary(
        self,
    ) -> dict[str, int | list[dict[str, int | str]]]:
        """Return pool-level health statistics as a dict.

        Returns:
            A dictionary with keys ``total_connections``,
            ``active_connections``, ``idle_connections``,
            ``h2_connections``, ``h1_connections``,
            ``active_h2_streams``, ``max_h2_stream_capacity``,
            ``queued_requests`` — all non-negative integers — and
            ``connections`` — a list of per-connection dicts with
            ``label``, ``state``, ``protocol``, ``active_streams``,
            and ``max_streams``.
        """
        connections = self._connections

        total_connections = len(connections)
        idle_connections = sum(1 for c in connections if c.is_idle())
        active_connections = total_connections - idle_connections

        # Protocol split: inspect the underlying connection type.
        h2_connections = 0
        h1_connections = 0
        active_h2_streams = 0
        max_h2_stream_capacity = 0

        # Count active (assigned) requests per connection.
        streams_per_conn: dict[AsyncConnectionInterface, int] = dict.fromkeys(
            connections, 0
        )
        for r in self._requests:
            conn = r.connection
            if conn is not None and not r.is_queued():
                streams_per_conn[conn] = streams_per_conn.get(conn, 0) + 1

        # Per-connection details for the ``connections`` list.
        connection_details: list[dict[str, int | str]] = []

        for conn in connections:
            # Protocol detection via the inner connection.
            inner = getattr(conn, "_connection", None)
            if isinstance(inner, FixedHTTP2Connection):
                protocol = "h2"
                h2_connections += 1
                active_h2_streams += streams_per_conn.get(conn, 0)
                max_h2_stream_capacity += self._max_concurrent_requests(conn)
            elif isinstance(inner, AsyncHTTP11Connection):
                protocol = "h1"
                h1_connections += 1
            else:
                protocol = "unknown"

            # State detection.
            if conn.is_closed():
                state = "closed"
            elif conn.is_idle():
                state = "idle"
            else:
                state = "active"

            label = getattr(conn, "_connection_label", "")
            connection_details.append(
                {
                    "label": label,
                    "state": state,
                    "protocol": protocol,
                    "active_streams": streams_per_conn.get(conn, 0),
                    "max_streams": self._max_concurrent_requests(conn),
                }
            )

        queued_requests = sum(1 for r in self._requests if r.is_queued())

        return {
            "total_connections": total_connections,
            "active_connections": active_connections,
            "idle_connections": idle_connections,
            "h2_connections": h2_connections,
            "h1_connections": h1_connections,
            "active_h2_streams": active_h2_streams,
            "max_h2_stream_capacity": max_h2_stream_capacity,
            "queued_requests": queued_requests,
            "connections": connection_details,
        }
