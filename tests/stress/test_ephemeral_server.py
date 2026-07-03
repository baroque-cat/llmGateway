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


@pytest.mark.asyncio
async def test_internal_concurrency_none_processes_all_concurrently() -> None:
    """When ``internal_concurrency`` is ``None``, no semaphore caps processing
    and all requests run truly concurrently.

    Sends 10 concurrent GET requests with a 500 ms response delay. If all
    are processed in parallel, total wall-clock time is ~500 ms — not 5 s
    which would indicate serial queueing.
    """
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=500,
    )
    await server.start()
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(
            http2=True, verify=False, timeout=timeout
        ) as client:
            start = time.monotonic()
            tasks = [client.get(f"{server.url}/test") for _ in range(10)]
            responses = await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start

        assert all(r.status_code == 200 for r in responses)
        assert elapsed < 1.5, f"Expected < 1.5 s (concurrent), got {elapsed:.3f} s"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_internal_concurrency_three_limits_active_processing() -> None:
    """An ``internal_concurrency=3`` semaphore serialises request processing
    into batches of three.

    With 10 requests at 1000 ms each and a semaphore of 3, processing
    requires at least 4 batches (~4 s). The server still receives all 10
    streams (``peak_concurrent_streams >= 10``) even though only 3 process
    at once. After completion, ``concurrency_waiters`` returns to 0.
    """
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=1000,
        internal_concurrency=3,
    )
    await server.start()
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(
            http2=True, verify=False, timeout=timeout
        ) as client:
            start = time.monotonic()
            tasks = [client.get(f"{server.url}/test") for _ in range(10)]
            responses = await asyncio.gather(*tasks)
            elapsed = time.monotonic() - start

        assert all(r.status_code == 200 for r in responses)
        assert (
            elapsed >= 3.0
        ), f"Expected >= 3.0 s (semaphore-limited), got {elapsed:.3f} s"
        assert server.stats["peak_concurrent_streams"] >= 10, (
            f"Expected peak_concurrent_streams >= 10, "
            f"got {server.stats['peak_concurrent_streams']}"
        )
        assert server.stats["concurrency_waiters"] == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_internal_concurrency_preserves_advertised_max_streams() -> None:
    """The internal concurrency semaphore does not affect the HTTP/2
    ``SETTINGS_MAX_CONCURRENT_STREAMS`` advertised to the client.

    With ``max_concurrent_streams=100`` and ``internal_concurrency=3``,
    sending 10 concurrent requests (10 > 3 but < 100) should not trigger
    ``httpx.LocalProtocolError`` — the client trusts the advertised
    100-stream limit, and all 10 requests eventually succeed after internal
    queueing.
    """
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=200,
        internal_concurrency=3,
    )
    await server.start()
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(
            http2=True, verify=False, timeout=timeout
        ) as client:
            tasks = [client.get(f"{server.url}/test") for _ in range(10)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        protocol_errors = [
            r for r in results if isinstance(r, httpx.LocalProtocolError)
        ]
        assert (
            not protocol_errors
        ), f"Expected no LocalProtocolError, got: {protocol_errors}"
        responses = [r for r in results if isinstance(r, httpx.Response)]
        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_concurrency_waiters_reflects_blocked_count() -> None:
    """The ``concurrency_waiters`` metric tracks requests blocked on the
    internal semaphore during active processing.

    With 15 concurrent requests, ``internal_concurrency=3``, and a 2000 ms
    response delay, 12 requests should be waiting (15 - 3 processing)
    during the first response window. A background polling loop samples
    the metric every 50 ms and records the peak observed value.
    """
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=2000,
        internal_concurrency=3,
    )
    await server.start()
    try:
        peak_waiters = 0
        stop_polling = asyncio.Event()

        async def _poll_waiters() -> None:
            nonlocal peak_waiters
            while not stop_polling.is_set():
                peak_waiters = max(peak_waiters, server.stats["concurrency_waiters"])
                await asyncio.sleep(0.05)

        poll_task = asyncio.create_task(_poll_waiters())
        try:
            timeout = httpx.Timeout(30.0)
            async with httpx.AsyncClient(
                http2=True, verify=False, timeout=timeout
            ) as client:
                tasks = [client.get(f"{server.url}/test") for _ in range(15)]
                results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            stop_polling.set()
            await poll_task

        assert peak_waiters >= 11, f"Expected peak_waiters >= 11, got {peak_waiters}"
        assert peak_waiters <= 12, f"Expected peak_waiters <= 12, got {peak_waiters}"
        responses = [r for r in results if isinstance(r, httpx.Response)]
        assert len(responses) == 15
        assert all(r.status_code == 200 for r in responses)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_concurrency_waiters_zero_after_batch_completes() -> None:
    """After all requests complete, ``concurrency_waiters`` returns to zero,
    confirming no leaked waiter counts.

    Sends 15 concurrent requests with ``internal_concurrency=3`` and a 500 ms
    response delay. Once all responses are received, the semaphore should
    have no waiters.
    """
    server = EphemeralHttp2Server(
        max_concurrent_streams=100,
        response_delay_ms=500,
        internal_concurrency=3,
    )
    await server.start()
    try:
        timeout = httpx.Timeout(30.0)
        async with httpx.AsyncClient(
            http2=True, verify=False, timeout=timeout
        ) as client:
            tasks = [client.get(f"{server.url}/test") for _ in range(15)]
            responses = await asyncio.gather(*tasks)

        assert all(r.status_code == 200 for r in responses)
        assert server.stats["concurrency_waiters"] == 0
    finally:
        await server.stop()
