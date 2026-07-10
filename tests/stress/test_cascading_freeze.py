"""Stress tests reproducing the production HTTP/2 cascading-freeze anomaly.

These tests prove that when a server advertises ``max_concurrent_streams=100``
but has a lower internal concurrency limit, the client-visible capacity is
a lie:

1. **Abrupt freeze** — beyond the internal concurrency threshold, new
   requests are starved (no response at all). The freeze is abrupt, not
   gradual: at N concurrent, all work; at N+1, the N+1th is delayed.

2. **Cascading backlog** — after the initial batch completes, new requests
   also get stuck because the server is still backlogged with queued
   streams from the first batch. The cascade never self-heals as long as
   new requests keep arriving.

3. **Silent timeout** — the socket-level read timeout does NOT fire for
   starved streams when active streams keep the socket busy with drip-fed
   data. This is the core httpcore architectural limitation: the read
   timeout wraps a single ``socket.receive()`` call, not a per-stream
   deadline. As long as ANY data flows on the connection, ALL streams
   are "active" from the timeout's perspective.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.http2 import CapacityAwareHttp2Transport
from tests.stress.ephemeral_api import EphemeralHttp2Server

pytestmark = pytest.mark.slow


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_client(
    read_timeout: float,
    pool_timeout: float = 10.0,
    stream_read: float | None = None,
) -> httpx.AsyncClient:
    """Create an httpx client with a single-connection HTTP/2 transport.

    Args:
        read_timeout: Per-read timeout in seconds (flows to
            ``httpx.Timeout(read=...)`` → httpcore ``anyio.fail_after``).
        pool_timeout: Pool-acquisition timeout in seconds.
        stream_read: Per-stream read deadline in seconds. When set,
            injected into ``request.extensions["stream_read"]`` via a
            request event hook so the custom HTTP/2 transport enforces it
            via ``asyncio.wait_for()`` on ``_receive_response``. When
            ``None``, no per-stream deadline is applied (socket-level
            read timeout only — the pre-fix behaviour).

    Returns:
        An ``httpx.AsyncClient`` with ``max_connections=1`` and the
        capacity-aware HTTP/2 transport.
    """
    limits = httpx.Limits(
        max_connections=1,
        max_keepalive_connections=1,
        keepalive_expiry=30.0,
    )

    event_hooks: dict[str, list[Callable[..., Any]]] = {}
    if stream_read is not None:
        # The event hook fires after request building but before the
        # transport call, so stream_read lands in the httpcore Request
        # extensions that FixedHTTP2Connection.handle_async_request reads.
        async def _inject_stream_read(request: httpx.Request) -> None:
            request.extensions["stream_read"] = stream_read

        event_hooks["request"] = [_inject_stream_read]

    return httpx.AsyncClient(
        http2=True,
        verify=False,
        transport=CapacityAwareHttp2Transport(
            verify=False,
            http1=False,
            http2=True,
            limits=limits,
        ),
        limits=limits,
        timeout=httpx.Timeout(read_timeout, pool=pool_timeout),
        event_hooks=event_hooks,
    )


async def _timed_get(
    client: httpx.AsyncClient,
    url: str,
    latencies: list[float],
) -> httpx.Response | Exception:
    """Send a GET request and record its wall-clock latency.

    Args:
        client: The httpx async client to send the request through.
        url: The full URL to GET.
        latencies: A shared list to which the elapsed time is appended.

    Returns:
        The ``httpx.Response`` on success, or the caught ``Exception``
        on failure.
    """
    start = time.monotonic()
    try:
        resp = await client.get(url)
        latencies.append(time.monotonic() - start)
        return resp
    except Exception as exc:
        latencies.append(time.monotonic() - start)
        return exc


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_abrupt_freeze_at_concurrency_threshold(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert abrupt freeze when exceeding server's internal concurrency.

    The server advertises ``max_concurrent_streams=100`` but processes only
    3 concurrently (``internal_concurrency=3``).  With ``stream_headers=True``,
    active streams receive ``200 OK`` headers immediately; starved streams
    receive nothing until a slot frees.

    Sends 6 concurrent requests through a single-connection transport.
    The first 3 complete at ~2 s (one processing batch); the remaining 3
    complete at ~4 s (second batch after semaphore frees).

    The bimodal latency distribution proves the threshold is **abrupt**:
    at ≤3 concurrent, all requests are fast; at >3, the excess is delayed
    by exactly one batch duration.

    Asserts:
        - ``peak_connections == 1`` (pool trusts advertised 100, never
          opens a second connection).
        - All 6 requests return HTTP 200.
        - Exactly 3 requests have latency ≤ 3.0 s (first batch).
        - Exactly 3 requests have latency > 3.0 s (queued second batch).
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=3,
        response_delay_ms=2000,
        stream_headers=True,
    )

    latencies: list[float] = []
    url = f"{server.url}/test"

    async with _make_client(read_timeout=10.0) as client:
        tasks = [_timed_get(client, url, latencies) for _ in range(6)]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if isinstance(r, httpx.Response))
    fast_count = sum(1 for lat in latencies if lat <= 3.0)
    slow_count = sum(1 for lat in latencies if lat > 3.0)
    peak_connections = server.stats["peak_connections"]

    print(
        f"\n[test_abrupt_freeze] "
        f"peak_connections={peak_connections} "
        f"success={success_count}/6 "
        f"fast(<=3s)={fast_count} slow(>3s)={slow_count} "
        f"latencies={[round(lat, 2) for lat in sorted(latencies)]}"
    )

    assert (
        peak_connections == 1
    ), f"Expected peak_connections == 1, got {peak_connections}"
    assert success_count == 6, f"Expected all 6 to succeed, got {success_count}"
    assert fast_count == 3, f"Expected 3 fast (first batch), got {fast_count}"
    assert slow_count == 3, f"Expected 3 slow (queued), got {slow_count}"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_cascading_backlog_after_initial_batch(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert cascading backlog: new requests get stuck after initial batch.

    The server advertises 100 streams but processes only 3 concurrently
    with a 2 s delay.  6 requests are sent at T=0 (3 active, 3 starved).
    At T=2.5 s (after the first 3 complete), 3 MORE requests are sent.
    These new requests are also starved because the server is still
    processing the 3 queued streams from the first batch.

    This reproduces the production observation: "the stream finishes, the
    bot wants to make another request, and everything is silent."  The
    server's queue never empties because new requests arrive while the
    previous batch's queued streams are still being processed.

    Asserts:
        - After 2.5 s, exactly 3 of the first 6 requests have completed
          (the active batch).
        - All 9 requests eventually succeed.
        - The 3 new requests (sent at T=2.5 s) all have latency > 2.0 s
          (they were queued behind the first batch's starved streams).
        - ``peak_connections == 1`` (single connection throughout).
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=3,
        response_delay_ms=2000,
        stream_headers=True,
    )

    url = f"{server.url}/test"
    latencies_1: list[float] = []
    latencies_2: list[float] = []

    async with _make_client(read_timeout=15.0) as client:
        # T=0: send 6 requests (3 active, 3 starved)
        tasks_1 = [
            asyncio.create_task(_timed_get(client, url, latencies_1)) for _ in range(6)
        ]

        # Wait 2.5 s — first 3 should complete, 3 still pending
        await asyncio.sleep(2.5)
        done_count = sum(1 for t in tasks_1 if t.done())

        # T=2.5s: send 3 NEW requests (server still has 3 queued)
        tasks_2 = [
            asyncio.create_task(_timed_get(client, url, latencies_2)) for _ in range(3)
        ]

        # Wait for all 9 to complete
        all_results = await asyncio.gather(*tasks_1, *tasks_2, return_exceptions=True)

    success_count = sum(1 for r in all_results if isinstance(r, httpx.Response))
    peak_connections = server.stats["peak_connections"]

    print(
        f"\n[test_cascading_backlog] "
        f"peak_connections={peak_connections} "
        f"done_after_2.5s={done_count}/6 "
        f"success={success_count}/9 "
        f"latencies_batch1={[round(lat, 2) for lat in sorted(latencies_1)]} "
        f"latencies_batch2={[round(lat, 2) for lat in sorted(latencies_2)]}"
    )

    assert (
        peak_connections == 1
    ), f"Expected peak_connections == 1, got {peak_connections}"
    assert (
        done_count == 3
    ), f"Expected 3 done after 2.5 s (first batch), got {done_count}"
    assert success_count == 9, f"Expected all 9 to succeed, got {success_count}"
    assert all(lat > 2.0 for lat in latencies_2), (
        f"Expected all 3 new requests to have latency > 2.0 s "
        f"(queued behind first batch), got {latencies_2}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_read_timeout_silence_with_drip_feed(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert read timeout does NOT fire for starved streams with drip-feed.

    **Core proof of the silent-timeout bug.**

    The server advertises 100 streams but processes only 2 concurrently.
    Active streams send headers immediately, then drip-feed body chunks
    every 500 ms (simulating SSE token streaming).  Starved streams get
    nothing — they wait on the server's internal semaphore.

    The client's ``read_timeout=3.0 s`` is **shorter** than the 5 s
    processing delay.  If the timeout were per-stream, starved streams
    would time out after 3 s.  But the timeout is **socket-level**: it
    wraps a single ``socket.receive()`` call.  As long as ANY data
    arrives on the connection (drip-fed chunks for active streams), the
    timer is reset on every read, and starved streams wait indefinitely.

    Expected timeline:

    - T=0:     2 active streams send headers → socket active.
    - T=0.5 s: chunk 1 for active streams → socket active.
    - T=1.0 s: chunk 2 → socket active.
    - ...
    - T=5.0 s: last chunk → active streams complete.
    - T=5.0 s: 2 starved streams start processing → headers sent.
    - T=10.0 s: starved streams complete.

    Maximum socket silence: 500 ms (between chunks) << 3.0 s timeout.
    No ``ReadTimeout`` should fire for any stream.

    Asserts:
        - All 4 requests return HTTP 200 (no ``ReadTimeout``).
        - 2 requests have latency ≤ 6.0 s (active, drip-fed).
        - 2 requests have latency > 6.0 s (starved, waited for active).
        - ``peak_connections == 1``.
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=2,
        response_delay_ms=5000,
        response_body=b'{"ok":true}',
        stream_headers=True,
        chunk_interval_ms=500,
    )

    latencies: list[float] = []
    url = f"{server.url}/test"

    async with _make_client(
        read_timeout=3.0,
        pool_timeout=10.0,
    ) as client:
        tasks = [_timed_get(client, url, latencies) for _ in range(4)]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if isinstance(r, httpx.Response))
    timeout_count = sum(
        1
        for r in results
        if isinstance(r, Exception)
        and ("timeout" in str(r).lower() or "ReadTimeout" in type(r).__name__)
    )
    fast_count = sum(1 for lat in latencies if lat <= 6.0)
    slow_count = sum(1 for lat in latencies if lat > 6.0)
    peak_connections = server.stats["peak_connections"]

    print(
        f"\n[test_read_timeout_silence] "
        f"peak_connections={peak_connections} "
        f"success={success_count}/4 "
        f"timeout_errors={timeout_count} "
        f"fast(<=6s)={fast_count} slow(>6s)={slow_count} "
        f"latencies={[round(lat, 2) for lat in sorted(latencies)]}"
    )

    assert (
        peak_connections == 1
    ), f"Expected peak_connections == 1, got {peak_connections}"
    assert success_count == 4, (
        f"Expected all 4 to succeed (no ReadTimeout), got {success_count}. "
        f"Timeout errors: {timeout_count}"
    )
    assert timeout_count == 0, (
        f"Expected 0 timeout errors, got {timeout_count}. "
        f"This proves the socket-level read timeout does NOT fire for "
        f"starved streams when active streams keep the socket busy."
    )
    assert fast_count == 2, f"Expected 2 fast (active, drip-fed), got {fast_count}"
    assert (
        slow_count == 2
    ), f"Expected 2 slow (starved, waited for active), got {slow_count}"


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_per_stream_timeout_fires_before_total_deadline(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert per-stream timeout fires for starved streams before total deadline.

    Direct counterpart to ``test_read_timeout_silence_with_drip_feed``.

    Same server setup: 100 advertised streams, 2 internal concurrency,
    5 s delay, 500 ms drip-feed chunks. But the client now has
    ``stream_read=3.0`` (shorter than the 5 s delay) and
    ``read_timeout=30.0`` (total deadline that should NOT fire).

    The per-stream timeout wraps ``_receive_response`` (waiting for
    response headers). Active streams receive headers immediately
    (``stream_headers=True``), so their per-stream timeout does NOT fire
    and they complete at ~5 s after the drip-feed body finishes. Starved
    streams block on the server's internal semaphore — no headers arrive,
    and the per-stream timeout fires at ~3 s, producing a
    ``httpx.ReadTimeout`` that surfaces to the caller as a network-level
    failure.

    Asserts:
        - 2 active streams return ``httpx.Response`` (success, ~5 s).
        - 2 starved streams receive ``httpx.ReadTimeout`` at ~3 s.
        - All latencies < 10 s (30 s total deadline does NOT fire).
        - ``peak_connections == 1`` (single connection throughout).
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=2,
        response_delay_ms=5000,
        response_body=b'{"ok":true}',
        stream_headers=True,
        chunk_interval_ms=500,
    )

    latencies: list[float] = []
    url = f"{server.url}/test"

    async with _make_client(
        read_timeout=30.0,
        pool_timeout=10.0,
        stream_read=3.0,
    ) as client:
        tasks = [_timed_get(client, url, latencies) for _ in range(4)]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if isinstance(r, httpx.Response))
    timeout_count = sum(1 for r in results if isinstance(r, httpx.ReadTimeout))
    fast_count = sum(1 for lat in latencies if lat <= 4.0)
    slow_count = sum(1 for lat in latencies if lat > 4.0)
    peak_connections = server.stats["peak_connections"]

    print(
        f"\n[test_per_stream_timeout] "
        f"peak_connections={peak_connections} "
        f"success={success_count}/4 "
        f"timeout_errors={timeout_count} "
        f"fast(<=4s)={fast_count} slow(>4s)={slow_count} "
        f"latencies={[round(lat, 2) for lat in sorted(latencies)]}"
    )

    assert (
        peak_connections == 1
    ), f"Expected peak_connections == 1, got {peak_connections}"
    assert (
        success_count == 2
    ), f"Expected 2 successes (active streams), got {success_count}"
    assert timeout_count == 2, (
        f"Expected 2 ReadTimeouts (starved streams), got {timeout_count}. "
        f"This proves the per-stream timeout DOES fire for starved streams "
        f"when stream_read is set, unlike the socket-level timeout."
    )
    assert fast_count == 2, f"Expected 2 fast (starved, ~3 s timeout), got {fast_count}"
    assert (
        slow_count == 2
    ), f"Expected 2 slow (active, ~5 s drip-feed), got {slow_count}"
    # Total deadline (30 s) did NOT fire — all latencies well under 10 s.
    assert all(lat < 10.0 for lat in latencies), (
        f"Expected all latencies < 10 s (30 s deadline did not fire), "
        f"got {latencies}"
    )


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_total_deadline_fires_when_all_retries_time_out(
    http2_server_factory: Callable[..., Any],
) -> None:
    """Assert total deadline fires when all retry attempts time out.

    Server configured for pure starvation: no drip-feed
    (``stream_headers=False``), long delay (10 s). Client configured with
    ``stream_read=2.0`` and a simulated total deadline of 7.0 s via
    ``asyncio.timeout()``.

    Each request times out at ~2 s (per-stream timeout < 10 s delay). A
    sequential retry loop sends requests until either retries are
    exhausted or the total deadline fires.

    With ``stream_read=2.0`` and ``total=7.0``, approximately 3 per-stream
    timeouts fit within the total window (3 x 2 s = 6 s < 7 s). The 4th
    attempt is interrupted by the total deadline at 7 s.

    Asserts:
        - Multiple per-stream timeouts occur (~2 s each).
        - Each timed-out request has latency <= 3.0 s.
        - Total operation completes within ~9 s (7 s deadline + margin).
        - Either the total deadline fires (``TimeoutError`` from
          ``asyncio.timeout``) or all retries are exhausted.
    """
    server: EphemeralHttp2Server = await http2_server_factory(
        max_concurrent_streams=100,
        internal_concurrency=2,
        response_delay_ms=10000,
        stream_headers=False,
    )

    url = f"{server.url}/test"
    stream_read = 2.0
    total_deadline = 7.0
    max_retries = 5  # More than can fit in 7 s

    latencies: list[float] = []
    timeout_count = 0
    total_fired = False
    start = time.monotonic()

    async with _make_client(
        read_timeout=30.0,
        pool_timeout=10.0,
        stream_read=stream_read,
    ) as client:
        try:
            async with asyncio.timeout(total_deadline):
                for _ in range(max_retries):
                    result = await _timed_get(client, url, latencies)
                    if isinstance(result, httpx.ReadTimeout):
                        timeout_count += 1
                    elif isinstance(result, httpx.Response):
                        break  # Success — stop retrying
        except TimeoutError:
            total_fired = True

    elapsed = time.monotonic() - start

    per_stream_timeout_latencies = [lat for lat in latencies if lat <= 3.0]

    print(
        f"\n[test_total_deadline] "
        f"elapsed={elapsed:.1f}s "
        f"timeout_count={timeout_count} "
        f"total_fired={total_fired} "
        f"latencies={[round(lat, 2) for lat in latencies]}"
    )

    # Multiple per-stream timeouts occurred.
    assert (
        timeout_count >= 2
    ), f"Expected at least 2 per-stream timeouts, got {timeout_count}"
    # Each timed-out request had latency <= 3.0 s (per-stream timeout ~2 s).
    assert len(per_stream_timeout_latencies) >= 2, (
        f"Expected at least 2 timeouts with latency <= 3.0 s, "
        f"got {len(per_stream_timeout_latencies)}, latencies={latencies}"
    )
    # Total operation completed within deadline + margin.
    assert elapsed <= total_deadline + 2.0, (
        f"Expected elapsed <= {total_deadline + 2.0:.1f} s, " f"got {elapsed:.1f} s"
    )
    # Either total deadline fired or all retries timed out.
    assert total_fired or timeout_count == max_retries, (
        f"Expected either total deadline fired or {max_retries} timeouts, "
        f"got total_fired={total_fired}, timeout_count={timeout_count}"
    )
