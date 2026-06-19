"""Stress test: HTTP/2 stream exhaustion when client exceeds server's
max_concurrent_streams setting on a single connection.

Verifies that httpx correctly surfaces stream-level limits as
LocalProtocolError or PoolTimeout when the server advertises a low
SETTINGS_MAX_CONCURRENT_STREAMS and the client is constrained to a
single connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.stress.metrics import MetricsCollector

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_requests_exceed_stream_limit(
    http2_server_factory: Callable[..., Any],
    collector_factory: Callable[..., Any],
) -> None:
    """Assert that exceeding server's max_concurrent_streams produces errors.

    Uses a server with 5 max streams and a 2s response delay.  A single-connection
    client sends 20 concurrent requests — at most 5 should succeed, and the
    remaining 15+ must fail with httpx.LocalProtocolError or httpx.PoolTimeout.
    """
    server = await http2_server_factory(
        max_concurrent_streams=5, response_delay_ms=2000
    )
    collector: MetricsCollector = collector_factory(server)
    collector.start()

    async with httpx.AsyncClient(
        http2=True,
        verify=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        timeout=httpx.Timeout(30.0, pool=30.0),
    ) as client:
        tasks = [client.get(f"{server.url}/test") for _ in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Classify every result
    successes = 0
    local_protocol_errors = 0
    pool_timeout_errors = 0
    connect_errors = 0
    read_timeout_errors = 0
    other_errors = 0

    for r in results:
        if isinstance(r, httpx.Response):
            successes += 1
        elif isinstance(r, Exception):
            collector.record_exception(r)
            if isinstance(r, httpx.LocalProtocolError):
                local_protocol_errors += 1
            elif isinstance(r, httpx.PoolTimeout):
                pool_timeout_errors += 1
            elif isinstance(r, httpx.ConnectError):
                connect_errors += 1
            elif isinstance(r, httpx.ReadTimeout):
                read_timeout_errors += 1
            else:
                other_errors += 1

    metrics = collector.stop()

    print(
        f"\n[test_stream_exhaustion] "
        f"successes={successes} "
        f"local_protocol_errors={local_protocol_errors} "
        f"pool_timeout_errors={pool_timeout_errors} "
        f"connect_errors={connect_errors} "
        f"read_timeout_errors={read_timeout_errors} "
        f"other_errors={other_errors}"
    )

    # At most 5 requests should succeed (server allows only 5 concurrent streams
    # on a single connection).
    assert successes <= 5, (
        f"Expected ≤ 5 successes on 1 connection with 5 max streams, "
        f"got {successes}"
    )

    # Remaining must be LocalProtocolError or PoolTimeout.
    failed_count = local_protocol_errors + pool_timeout_errors
    assert failed_count >= 15, (
        f"Expected ≥ 15 failures, got {failed_count} "
        f"(local_protocol={local_protocol_errors}, pool_timeout={pool_timeout_errors})"
    )

    # Metrics collector must also record errors.
    assert (
        metrics.local_protocol_errors > 0 or metrics.pool_timeout_errors > 0
    ), f"Expected local_protocol_errors or pool_timeout_errors > 0, got {metrics}"
