"""Stress tests proving the per-provider ``max_concurrent_streams_cap``
prevents the HTTP/2 cascading-freeze anomaly.

The cap forces the connection pool to open additional TCP connections
before the server-advertised ``MAX_CONCURRENT_STREAMS`` limit is reached.
This prevents stream starvation when a provider has a hidden internal
concurrency limit lower than the advertised value.

Scenarios:
    1. ``test_cap_forces_second_connection`` — cap=5 with 6 concurrent
       requests forces the pool to open >= 2 connections; all succeed.
    2. ``test_all_requests_complete_with_cap`` — cap=5 against a server
       with ``internal_concurrency=8`` ensures all 12 requests complete
       without hanging, proving the cap prevents the cascading freeze.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.http2 import CapacityAwareHttp2Transport
from src.core.http2.pool import CapacityAwareHttp2Pool
from tests.stress.ephemeral_api import EphemeralHttp2Server

pytestmark = pytest.mark.slow


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_capped_client(
    cap: int,
    max_connections: int = 10,
    read_timeout: float = 30.0,
    pool_timeout: float = 10.0,
) -> tuple[httpx.AsyncClient, CapacityAwareHttp2Pool]:
    """Create an httpx client with a capacity-capped HTTP/2 transport.

    Args:
        cap: Per-connection ``max_concurrent_streams`` cap applied at the
            client side, overriding the server-advertised value.
        max_connections: Maximum TCP connections the pool may open.
        read_timeout: Per-read timeout in seconds.
        pool_timeout: Pool-acquisition timeout in seconds.

    Returns:
        A tuple of ``(httpx.AsyncClient, CapacityAwareHttp2Pool)`` so the
        caller can inspect the pool's health summary after requests.
    """
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_connections,
        keepalive_expiry=30.0,
    )
    transport = CapacityAwareHttp2Transport(
        verify=False,
        http1=False,
        http2=True,
        limits=limits,
        max_concurrent_streams_cap=cap,
        provider_name="cap-stress",
    )
    pool: CapacityAwareHttp2Pool = transport._pool  # type: ignore[reportPrivateUsage]
    client = httpx.AsyncClient(
        http2=True,
        verify=False,
        transport=transport,
        limits=limits,
        timeout=httpx.Timeout(read_timeout, pool=pool_timeout),
    )
    return client, pool


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_cap_forces_second_connection(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Cap=5 forces the pool to open a second connection for 6 requests.

    The server advertises ``max_concurrent_streams=100`` but has a hidden
    ``internal_concurrency=8``. With ``max_concurrent_streams_cap=5``, the
    client treats each connection as supporting only 5 concurrent streams.
    Sending 6 concurrent requests therefore requires the pool to open
    at least 2 connections — the 6th request cannot fit on the first
    connection's capped capacity.

    A single warm-up request is sent first so the first connection's
    SETTINGS frame is received and the cap (semaphore=5) is active before
    the concurrent burst. Without this, the H2 init race would open one
    connection per request regardless of the cap.

    Asserts:
        - All 6 requests return HTTP 200 (no errors, no hangs).
        - Pool health summary reports ``total_connections >= 2``.
        - Server-side ``total_connections >= 2`` (corroborating).
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=8,
        response_delay_ms=500,
        stream_headers=True,
    )

    client, pool = _make_capped_client(cap=5, max_connections=10)
    try:
        url = f"{server.url}/test"

        # Warm-up: establish the first connection so the server's
        # SETTINGS frame is processed and the cap (semaphore=5) is
        # active before the concurrent burst.
        warmup = await client.get(url)
        assert warmup.status_code == 200

        tasks = [client.get(url) for _ in range(6)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if isinstance(r, httpx.Response))
        health = pool.get_health_summary()
        server_total = server.stats["total_connections"]

        print(
            f"\n[test_cap_forces_second_connection] "
            f"success={success_count}/6 "
            f"pool_total_connections={health['total_connections']} "
            f"server_total_connections={server_total} "
            f"errors={[type(r).__name__ for r in results if isinstance(r, Exception)]}"
        )

        assert success_count == 6, (
            f"Expected all 6 requests to succeed, got {success_count}. "
            f"Errors: {[type(r).__name__ for r in results if isinstance(r, Exception)]}"
        )
        assert health["total_connections"] >= 2, (
            f"Expected pool total_connections >= 2 (cap forces new connection), "
            f"got {health['total_connections']}"
        )
        assert (
            server_total >= 2
        ), f"Expected server total_connections >= 2, got {server_total}"
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_all_requests_complete_with_cap(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Cap=5 prevents cascading freeze: all 12 requests complete in time.

    The server advertises 100 streams but processes only 8 concurrently
    (``internal_concurrency=8``) with ``stream_headers=True``. Without the
    cap, all 12 streams would land on a single connection; the 4 starved
    streams would wait on the server's internal semaphore while active
    streams keep the socket busy — the cascading-freeze condition.

    With ``max_concurrent_streams_cap=5``, the pool distributes requests
    across multiple connections (e.g. 5 + 5 + 2). Since each connection
    carries <= 5 streams (< ``internal_concurrency=8``), no stream is
    ever starved. All requests complete promptly without hanging.

    A single warm-up request is sent first so the first connection's
    SETTINGS frame is received and the cap (semaphore=5) is active before
    the concurrent burst.

    Asserts:
        - All 12 requests return HTTP 200.
        - Total wall-clock time < 15 s (well within the 30 s timeout).
        - No ``ReadTimeout`` or ``PoolTimeout`` errors.
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=8,
        response_delay_ms=1000,
        stream_headers=True,
    )

    client, pool = _make_capped_client(cap=5, max_connections=20)
    try:
        url = f"{server.url}/test"

        # Warm-up: establish the first connection so the server's
        # SETTINGS frame is processed and the cap (semaphore=5) is
        # active before the concurrent burst.
        warmup = await client.get(url)
        assert warmup.status_code == 200

        start = time.monotonic()
        tasks = [client.get(url) for _ in range(12)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.monotonic() - start

        success_count = sum(1 for r in results if isinstance(r, httpx.Response))
        timeout_errors = [
            r
            for r in results
            if isinstance(r, Exception)
            and ("timeout" in type(r).__name__.lower() or "timeout" in str(r).lower())
        ]
        health = pool.get_health_summary()

        print(
            f"\n[test_all_requests_complete_with_cap] "
            f"success={success_count}/12 "
            f"elapsed={elapsed:.2f}s "
            f"pool_total_connections={health['total_connections']} "
            f"server_total_connections={server.stats['total_connections']} "
            f"timeout_errors={len(timeout_errors)}"
        )

        assert success_count == 12, (
            f"Expected all 12 requests to succeed, got {success_count}. "
            f"Errors: {[type(r).__name__ for r in results if isinstance(r, Exception)]}"
        )
        assert not timeout_errors, (
            f"Expected no timeout errors (cap prevents freeze), "
            f"got {len(timeout_errors)}: "
            f"{[type(e).__name__ for e in timeout_errors]}"
        )
        assert (
            elapsed < 15.0
        ), f"Expected completion < 15 s (no freeze), got {elapsed:.2f} s"
    finally:
        await client.aclose()
