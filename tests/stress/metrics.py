"""Metrics collection for connection pool stress tests.

Provides the :class:`ConnectionMetrics` dataclass and :class:`MetricsCollector`
that aggregates connection lifecycle data from three sources:
1. The ephemeral server's internal counters (:attr:`EphemeralHttp2Server.stats`)
2. httpx trace events (connection creation, closure, request lifecycle)
3. OS-level TCP socket inspection (Linux ``/proc/net/tcp``; optional)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from tests.stress.ephemeral_api import EphemeralHttp2Server


@dataclass
class ConnectionMetrics:
    """Aggregated metrics from a single stress test run.

    Fields:
        server_peak_connections: Highest observed active TCP connections (server-side).
        server_peak_streams: Highest observed active H2 streams (server-side).
        server_total_requests: Total requests handled by the server.
        client_connections_created: Connections created (httpx trace).
        client_connections_closed: Connections closed (httpx trace).
        os_tcp_established: ESTABLISHED TCP sockets from OS (``None`` if unavailable).
        local_protocol_errors: Count of ``httpx.LocalProtocolError`` exceptions.
        pool_timeout_errors: Count of ``httpx.PoolTimeout`` exceptions.
        connect_errors: Count of ``httpx.ConnectError`` exceptions.
        read_timeout_errors: Count of ``httpx.ReadTimeout`` exceptions.
        other_errors: Count of any other ``Exception`` types.
        total_duration_sec: Wall-clock duration from :meth:`MetricsCollector.start`
            to :meth:`MetricsCollector.stop`.
        p50_latency_sec: Median request latency (``None`` if no successful requests).
        p99_latency_sec: 99th percentile request latency (``None`` if fewer than
            100 successful requests).
    """

    server_peak_connections: int = 0
    server_peak_streams: int = 0
    server_total_requests: int = 0

    client_connections_created: int = 0
    client_connections_closed: int = 0

    os_tcp_established: int | None = None

    local_protocol_errors: int = 0
    pool_timeout_errors: int = 0
    connect_errors: int = 0
    read_timeout_errors: int = 0
    other_errors: int = 0

    total_duration_sec: float = 0.0
    p50_latency_sec: float | None = None
    p99_latency_sec: float | None = None


class MetricsCollector:
    """Collects connection pool metrics from server counters and httpx trace.

    Attach the :meth:`trace_handler` as an httpx trace extension to capture
    client-side connection lifecycle events. Record exceptions and latencies
    for each request attempt. Call :meth:`stop` to produce aggregated
    :class:`ConnectionMetrics`.

    Args:
        server: The :class:`EphemeralHttp2Server` to read server-side counters from.
        trace_enabled: If ``False``, :meth:`trace_handler` is a no-op.
    """

    def __init__(
        self,
        server: EphemeralHttp2Server,
        trace_enabled: bool = True,
    ) -> None:
        self._server = server
        self._trace_enabled = trace_enabled
        self._trace_events: list[dict[str, object]] = []
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._exceptions: list[Exception] = []
        self._latencies: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trace_handler(self, event: dict[str, object]) -> None:
        """Callback for ``httpx`` trace extensions.

        Pass this as ``extensions={"trace": collector.trace_handler}`` when
        creating an ``httpx.AsyncClient``.

        Args:
            event: httpx trace event dict with keys such as ``"event"``
                (e.g. ``"connection_created"``), ``"connection_id"``, etc.
        """
        if not self._trace_enabled:
            return
        self._trace_events.append(event)

    def start(self) -> None:
        """Record the wall-clock start time."""
        self._start_time = time.monotonic()

    def record_exception(self, exc: Exception) -> None:
        """Record an exception from a single request attempt.

        Args:
            exc: The exception raised by ``httpx``.
        """
        self._exceptions.append(exc)

    def record_latency(self, latency_sec: float) -> None:
        """Record the latency of a single successful request.

        Args:
            latency_sec: Request duration in seconds.
        """
        self._latencies.append(latency_sec)

    def stop(self) -> ConnectionMetrics:
        """Stop collection, aggregate all data, and return :class:`ConnectionMetrics`.

        Returns:
            Aggregated metrics across all sources.
        """
        self._end_time = time.monotonic()
        server_stats = self._server.stats

        # --- httpx trace ---
        connections_created = sum(
            1 for e in self._trace_events if e.get("event") == "connection_created"
        )
        connections_closed = sum(
            1 for e in self._trace_events if e.get("event") == "connection_closed"
        )

        # --- Exception classification (by isinstance, NOT message string) ---
        local_protocol_errors = 0
        pool_timeout_errors = 0
        connect_errors = 0
        read_timeout_errors = 0
        other_errors = 0

        for exc in self._exceptions:
            if isinstance(exc, httpx.LocalProtocolError):
                local_protocol_errors += 1
            elif isinstance(exc, httpx.PoolTimeout):
                pool_timeout_errors += 1
            elif isinstance(exc, httpx.ConnectError):
                connect_errors += 1
            elif isinstance(exc, httpx.ReadTimeout):
                read_timeout_errors += 1
            else:
                other_errors += 1

        # --- Latency percentiles ---
        p50: float | None = None
        p99: float | None = None
        if self._latencies:
            sorted_l = sorted(self._latencies)
            p50 = sorted_l[len(sorted_l) // 2]
            if len(sorted_l) >= 100:
                p99 = sorted_l[int(len(sorted_l) * 0.99)]
            else:
                p99 = sorted_l[-1]

        return ConnectionMetrics(
            server_peak_connections=server_stats["peak_connections"],
            server_peak_streams=server_stats["peak_concurrent_streams"],
            server_total_requests=server_stats["total_requests"],
            client_connections_created=connections_created,
            client_connections_closed=connections_closed,
            os_tcp_established=self._read_os_tcp_stats(),
            local_protocol_errors=local_protocol_errors,
            pool_timeout_errors=pool_timeout_errors,
            connect_errors=connect_errors,
            read_timeout_errors=read_timeout_errors,
            other_errors=other_errors,
            total_duration_sec=self._end_time - self._start_time,
            p50_latency_sec=p50,
            p99_latency_sec=p99,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _read_os_tcp_stats() -> int | None:
        """Read the number of ESTABLISHED TCP sockets from ``/proc/net/tcp``.

        Returns:
            Count of sockets in state ``01`` (ESTABLISHED), or ``None`` on
            non-Linux platforms or if the file is unreadable.
        """
        try:
            with open("/proc/net/tcp") as f:
                lines = f.readlines()
            # Skip header; ESTABLISHED = state "01" in column 4 (0-indexed: 3)
            count = sum(
                1
                for line in lines[1:]
                if line.strip() and len(line.split()) > 3 and line.split()[3] == "01"
            )
            return count
        except (FileNotFoundError, PermissionError, OSError):
            return None
