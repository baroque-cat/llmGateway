"""Tests for the MetricsCollector covering trace integration, exception
classification, and optional OS-level TCP metrics.

All tests run against a real EphemeralHttp2Server with real httpx HTTP/2
clients (no mocking).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest

from tests.stress.ephemeral_api import EphemeralHttp2Server
from tests.stress.metrics import ConnectionMetrics, MetricsCollector

pytestmark = pytest.mark.slow


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------


async def _create_server(**kwargs: int) -> EphemeralHttp2Server:
    """Create and start an EphemeralHttp2Server with the given parameters."""
    server = EphemeralHttp2Server(**kwargs)  # type: ignore[arg-type]
    await server.start()
    return server


# ------------------------------------------------------------------
# Test cases
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_captures_connection_creation(
    collector_factory: Callable[..., MetricsCollector],
) -> None:
    """httpx trace events delivered via collector.trace_handler are aggregated
    into client_connections_created >= 1 after a single request.

    httpcore >= 1.0 calls the trace extension as ``trace_extension(name, info)``
    with two positional arguments, while :class:`MetricsCollector` expects a
    single ``dict``.  We bridge the two with a thin adapter that maps httpcore
    event names (e.g. ``"http2.connect_tcp.complete"``) to the dict keys the
    collector recognises (``"connection_created"``).
    """
    server = await _create_server(max_concurrent_streams=100)
    try:
        collector = collector_factory(server)
        collector.start()

        async def _trace_adapter(name: str, info: dict[str, object]) -> None:
            event: dict[str, object] = {**info}
            if "connect_tcp.complete" in name:
                event["event"] = "connection_created"
            elif "close.complete" in name or "close.started" in name:
                event["event"] = "connection_closed"
            else:
                event["event"] = name
            collector.trace_handler(event)

        async with httpx.AsyncClient(http2=True, verify=False) as client:
            resp = await client.get(
                f"{server.url}/test",
                extensions={"trace": _trace_adapter},
            )
            assert resp.status_code == 200

        metrics: ConnectionMetrics = collector.stop()
        assert (
            metrics.client_connections_created >= 1
        ), f"Expected >= 1 client_connections_created, got {metrics}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_error_classification_by_type(
    collector_factory: Callable[..., MetricsCollector],
) -> None:
    """Exceptions collected from concurrent requests are classified by
    isinstance, not message string:

    - httpx.LocalProtocolError → local_protocol_errors
    - httpx.PoolTimeout       → pool_timeout_errors
    """
    server = await _create_server(
        max_concurrent_streams=5,
        response_delay_ms=0,
    )
    try:
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        timeout = httpx.Timeout(30.0, pool=30.0)

        # Send 20 concurrent requests on a single connection — the server's
        # 5-stream limit will cause excess streams to be reset.
        async with httpx.AsyncClient(
            http2=True,
            verify=False,
            limits=limits,
            timeout=timeout,
        ) as client:
            tasks = [client.get(f"{server.url}/test") for _ in range(20)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Record all exceptions into the collector.
        collector = collector_factory(server)
        collector.start()
        for result in results:
            if isinstance(result, Exception):
                collector.record_exception(result)

        metrics: ConnectionMetrics = collector.stop()

        # At least some of the 20 requests should have been refused due to
        # the stream cap, producing LocalProtocolError instances.
        assert (
            metrics.local_protocol_errors > 0
        ), f"Expected local_protocol_errors > 0, got {metrics}"
        # No connection-pool timeout is expected because we are only using a
        # single connection — the failure mode is stream rejection, not pool
        # exhaustion.
        assert (
            metrics.pool_timeout_errors == 0
        ), f"Expected pool_timeout_errors == 0, got {metrics}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_os_tcp_metric_optional(
    collector_factory: Callable[..., MetricsCollector],
) -> None:
    """os_tcp_established is an int on Linux and None on other platforms.
    The property must never raise an exception."""
    server = await _create_server(max_concurrent_streams=100)
    try:
        collector = collector_factory(server)
        collector.start()

        # Make a request so the server connection registers in the OS.
        async with httpx.AsyncClient(http2=True, verify=False) as client:
            await client.get(f"{server.url}/test")

        metrics: ConnectionMetrics = collector.stop()

        assert metrics.os_tcp_established is None or isinstance(
            metrics.os_tcp_established, int
        ), (
            "os_tcp_established must be None or int, "
            f"got {type(metrics.os_tcp_established).__name__}"
        )
    finally:
        await server.stop()
