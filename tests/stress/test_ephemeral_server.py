"""Tests for the EphemeralHttp2Server covering startup, request handling,
shutdown, stream limits, response delays, and metric counter accuracy.

All tests use real httpx HTTP/2 clients (no mocking) against a self-signed
TLS server, exercising the h2 protocol stack end-to-end.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import httpx
import pytest

from tests.stress.ephemeral_api import EphemeralHttp2Server

pytestmark = pytest.mark.slow


# ------------------------------------------------------------------
# Test cases
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_starts_on_random_port() -> None:
    """Server binds to an OS-assigned port and initial counters are zero."""
    server = EphemeralHttp2Server(max_concurrent_streams=100)
    await server.start()
    try:
        assert server.url.startswith("https://127.0.0.1:")
        stats = server.stats
        assert stats["active_connections"] == 0
        assert stats["total_requests"] == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_responds_to_single_request() -> None:
    """A single GET request returns HTTP 200 with the default JSON body."""
    server = EphemeralHttp2Server(max_concurrent_streams=100)
    await server.start()
    try:
        async with httpx.AsyncClient(http2=True, verify=False) as client:
            resp = await client.get(f"{server.url}/test")
            assert resp.status_code == 200
            assert resp.content == b'{"ok":true}'
        assert server.stats["total_requests"] == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_stops_cleanly() -> None:
    """After stopping the server, new connections should fail with a network error."""
    server = EphemeralHttp2Server(max_concurrent_streams=100)
    await server.start()
    url = server.url
    await server.stop()

    with pytest.raises(
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.RemoteProtocolError,
            OSError,
        )
    ):
        async with httpx.AsyncClient(http2=True, verify=False) as client:
            await client.get(f"{url}/test", timeout=httpx.Timeout(2.0))


@pytest.mark.asyncio
async def test_client_observes_stream_limit() -> None:
    """Exceeding the server-advertised max streams on a single connection
    triggers httpx.LocalProtocolError for the rejected streams."""
    server = EphemeralHttp2Server(max_concurrent_streams=5, response_delay_ms=0)
    await server.start()
    try:
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
        timeout = httpx.Timeout(30.0, pool=30.0)

        async with httpx.AsyncClient(
            http2=True,
            verify=False,
            limits=limits,
            timeout=timeout,
        ) as client:
            tasks = [client.get(f"{server.url}/test") for _ in range(20)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        failures = [r for r in results if isinstance(r, Exception)]
        assert (
            len(failures) > 0
        ), "Expected some requests to fail due to stream limit enforcement"
        assert any(isinstance(exc, httpx.LocalProtocolError) for exc in failures), (
            "Expected LocalProtocolError among failures, "
            f"got: {[type(e).__name__ for e in failures]}"
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_response_arrives_after_delay() -> None:
    """A request against a server with response_delay_ms=500 completes after
    at least 0.5 seconds of wall-clock time."""
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=500,
    )
    await server.start()
    try:
        async with httpx.AsyncClient(http2=True, verify=False) as client:
            start = time.monotonic()
            resp = await client.get(f"{server.url}/test")
            elapsed = time.monotonic() - start

        assert resp.status_code == 200
        assert elapsed >= 0.5, f"Expected >= 0.5 s, got {elapsed:.3f} s"
        assert server.stats["total_requests"] == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_metrics_reflect_concurrent_state() -> None:
    """Opening multiple HTTP/2 clients increases active_connections while
    active_streams remains at zero once all requests have completed."""
    server = EphemeralHttp2Server(max_concurrent_streams=100)
    await server.start()
    clients: list[httpx.AsyncClient] = []
    try:
        # Create 3 separate clients; each sends one request to force a
        # distinct TCP connection.
        for _ in range(3):
            client = httpx.AsyncClient(http2=True, verify=False)
            await client.__aenter__()
            await client.get(f"{server.url}/test")
            clients.append(client)

        # Give the server time to register connections and for request
        # tasks spawned by the concurrent handler to finish.  Retry a few
        # times since StreamEnded processing is asynchronous.
        for _ in range(20):
            await asyncio.sleep(0.1)
            if server.stats["active_streams"] == 0:
                break

        stats = server.stats
        assert (
            stats["active_connections"] >= 3
        ), f"Expected >= 3 active connections, got {stats}"
        assert stats["active_streams"] == 0, f"Expected 0 active streams, got {stats}"
    finally:
        for c in clients:
            with contextlib.suppress(Exception):
                await c.__aexit__(None, None, None)
        await server.stop()


@pytest.mark.asyncio
async def test_peak_stream_count_tracked() -> None:
    """The server's peak_concurrent_streams counter reflects the maximum
    number of streams that were active at any given moment.

    Because the server processes requests on a single connection serially,
    we use separate client instances — each with its own TCP connection —
    so that all requests overlap during the response delay."""
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=200,
    )
    await server.start()
    try:

        async def _send_one() -> None:
            async with httpx.AsyncClient(http2=True, verify=False) as client:
                await client.get(f"{server.url}/test")

        tasks = [_send_one() for _ in range(10)]
        await asyncio.gather(*tasks)

        stats = server.stats
        assert (
            stats["peak_concurrent_streams"] >= 10
        ), f"Expected peak_concurrent_streams >= 10, got {stats}"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_total_connection_count_cumulative() -> None:
    """total_connections is cumulative across the server lifetime and never
    decreases even after clients disconnect."""
    server = EphemeralHttp2Server(max_concurrent_streams=100)
    await server.start()
    all_clients: list[httpx.AsyncClient] = []
    try:
        # Phase 1 — open 3 clients, each sends 1 request to force a connection.
        for _ in range(3):
            client = httpx.AsyncClient(http2=True, verify=False)
            await client.__aenter__()
            await client.get(f"{server.url}/test")
            all_clients.append(client)

        # Phase 2 — close the first two clients.
        await all_clients[0].__aexit__(None, None, None)
        await all_clients[1].__aexit__(None, None, None)
        await asyncio.sleep(0.3)

        # Phase 3 — open a fourth client and send a request.
        client4 = httpx.AsyncClient(http2=True, verify=False)
        await client4.__aenter__()
        await client4.get(f"{server.url}/test")
        all_clients.append(client4)

        await asyncio.sleep(0.3)

        stats = server.stats
        assert (
            stats["total_connections"] >= 4
        ), f"Expected total_connections >= 4 (cumulative), got {stats}"
    finally:
        for c in all_clients:
            with contextlib.suppress(Exception):
                await c.__aexit__(None, None, None)
        await server.stop()
