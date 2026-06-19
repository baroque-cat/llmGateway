"""Stress test: httpx connection pool opens multiple connections to stay
under the server's per-connection max_concurrent_streams limit.

Verifies that httpx grows the connection pool organically rather than
hitting protocol errors when the server advertises a low stream limit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.stress.metrics import MetricsCollector

pytestmark = pytest.mark.slow


@pytest.mark.xfail(
    reason=(
        "httpx does not open new connections when H2 streams are exhausted "
        "on existing connections.  This test diagnoses the root cause of "
        '"Max outbound streams" errors in production.'
    ),
    strict=True,
)
@pytest.mark.asyncio
async def test_six_connections_for_thirty_requests(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """Assert that 6+ connections are created to handle 30 concurrent requests.

    Server advertises 5 max streams per connection, yet all 30 requests
    succeed because httpx opens additional connections (≥ 6) and distributes
    load across them without protocol errors.
    """
    server = await http2_server_factory(
        max_concurrent_streams=5, response_delay_ms=2000
    )
    collector: MetricsCollector = collector_factory(server)
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

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
        ),
        timeout=httpx.Timeout(60.0, pool=30.0),
    ) as client:
        tasks = [
            client.get(
                f"{server.url}/test",
                extensions={"trace": _trace_adapter},
            )
            for _ in range(30)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Record any exceptions.
    for r in results:
        if isinstance(r, Exception):
            collector.record_exception(r)

    metrics = collector.stop()

    success_count = sum(1 for r in results if isinstance(r, httpx.Response))

    print(
        f"\n[test_connection_growth] "
        f"server_peak_connections={metrics.server_peak_connections} "
        f"server_peak_streams={metrics.server_peak_streams} "
        f"client_connections_created={metrics.client_connections_created}"
    )

    # All 30 requests must succeed.
    assert success_count == 30, f"Expected 30 successes, got {success_count}"

    # With 5 streams per connection, 30 concurrent requests need ≥ 6 connections.
    assert metrics.client_connections_created >= 6, (
        f"Expected ≥ 6 connections created, "
        f"got {metrics.client_connections_created}"
    )

    # No protocol errors when pool grows organically.
    assert (
        metrics.local_protocol_errors == 0
    ), f"Expected 0 local_protocol_errors, got {metrics.local_protocol_errors}"
