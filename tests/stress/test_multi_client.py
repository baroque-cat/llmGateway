"""Stress test: two independent httpx clients connect to the same server
and maintain separate connection pools.

Verifies that concurrent clients do not interfere with each other and that
the server correctly reports connections from multiple sources.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_two_clients_independent_connections(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert two clients each open independent connections to the same server.

    Each of two clients sends 10 concurrent requests to a server with high
    stream limit and 2s delay.  Both client batches run in parallel, and all
    20 requests must succeed with independent connection pools.
    """
    server = await http2_server_factory(
        max_concurrent_streams=100, response_delay_ms=2000
    )
    limits = httpx.Limits(
        max_connections=5,
        max_keepalive_connections=5,
    )
    timeout = httpx.Timeout(30.0, pool=30.0)

    async def _send_batch(
        client: httpx.AsyncClient, url: str, count: int
    ) -> list[object]:
        tasks = [client.get(url) for _ in range(count)]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    async with (
        httpx.AsyncClient(
            http2=True, verify=False, limits=limits, timeout=timeout
        ) as client_a,
        httpx.AsyncClient(
            http2=True, verify=False, limits=limits, timeout=timeout
        ) as client_b,
    ):
        # Run both client batches concurrently.
        results_a, results_b = await asyncio.gather(
            _send_batch(client_a, f"{server.url}/test", 10),
            _send_batch(client_b, f"{server.url}/test", 10),
        )

    all_results = results_a + results_b
    success_count = sum(1 for r in all_results if isinstance(r, httpx.Response))

    server_stats = server.stats

    print(
        f"\n[test_multi_client] "
        f"successes={success_count}/20 "
        f"peak_connections={server_stats['peak_connections']}"
    )

    # Two separate clients should result in at least 2 peak connections.
    assert server_stats["peak_connections"] >= 2, (
        f"Expected ≥ 2 peak connections (one per client), "
        f"got {server_stats['peak_connections']}"
    )

    # Upper bound: 2 clients × 5 max connections each = 10.
    assert server_stats["peak_connections"] <= 10, (
        f"Expected ≤ 10 peak connections (2 clients × 5 max), "
        f"got {server_stats['peak_connections']}"
    )

    # All 20 requests should succeed — each client has its own pool.
    assert (
        success_count == 20
    ), f"Expected all 20 requests to succeed, got {success_count}"
